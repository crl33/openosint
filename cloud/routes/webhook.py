"""POST /v1/polar/webhook — handle Polar.sh webhook events."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from cloud import db, polar
from cloud.config import BENEFIT_PLAN_MAP, PLAN_CREDITS, POLAR_WEBHOOK_SECRET, SUBSCRIPTION_PLAN_MAP

logger = logging.getLogger(__name__)

router = APIRouter()


# ── event handlers ────────────────────────────────────────────────────────────

async def _handle_benefit_grant(data: dict) -> None:
    """
    Handle benefit_grant.created and benefit_grant.updated.

    Extracts the Polar-generated license key and upserts the customer.
    The license key IS the customer's X-API-Key — Polar mints it on purchase
    and shows it in the customer portal automatically.

    benefit_grant.created fires only AFTER payment is confirmed, so we never
    credit an uncaptured order.

    ⚠️  Verify the exact key field path by sending a test event from
        Polar dashboard → Developer → Webhooks → Send test event
        and inspecting the benefit_grant payload.
    """
    customer_id = data.get("customer_id", "")
    benefit_id  = data.get("benefit_id", "")
    properties  = data.get("properties") or {}

    # Try both known field paths; verify correct one against live payload.
    license_field = properties.get("license_key")
    if isinstance(license_field, dict):
        api_key = license_field.get("key", "")
    elif isinstance(license_field, str):
        api_key = license_field
    else:
        api_key = properties.get("display_key", "")

    if not api_key:
        logger.error(
            "benefit_grant payload missing license key — "
            "customer_id=%s benefit_id=%s properties_keys=%s",
            customer_id,
            benefit_id,
            list(properties.keys()),
        )
        return

    plan    = BENEFIT_PLAN_MAP.get(benefit_id, "payg")
    credits = PLAN_CREDITS.get(plan, PLAN_CREDITS["payg"])

    await db.upsert_customer(
        api_key=api_key,
        polar_customer_id=customer_id,
        plan=plan,
        credits=credits,
    )
    logger.info(
        "Customer upserted from benefit_grant: plan=%s credits=%d", plan, credits
    )


async def _handle_benefit_revoke(data: dict) -> None:
    """Zero credits when a license key benefit is revoked."""
    customer_id = data.get("customer_id", "")
    if customer_id:
        await db.zero_credits_by_polar_id(customer_id)
        logger.info(
            "Credits zeroed for polar_customer_id=%s (benefit revoked)", customer_id
        )


async def _handle_subscription_update(data: dict) -> None:
    """
    Refill credits when a subscription renews.

    Polar fires subscription.updated when the subscription's billing period
    advances.  We gate on status == "active" and derive the plan from the
    product ID mapping in config.

    ⚠️  Verify the renewal event name and that product.id is present in the
        subscription.updated payload via Polar dashboard → Send test event.
    """
    if data.get("status") != "active":
        return

    customer_id = data.get("customer_id", "")
    product     = data.get("product") or {}
    product_id  = product.get("id", "")
    plan        = SUBSCRIPTION_PLAN_MAP.get(product_id, "")

    if not plan:
        logger.warning(
            "subscription.updated: unknown product_id=%s — "
            "set POLAR_PRODUCT_ID_STARTER / POLAR_PRODUCT_ID_PRO env vars",
            product_id,
        )
        return

    credits = PLAN_CREDITS.get(plan, 0)
    if customer_id and credits:
        await db.refill_credits_by_polar_id(customer_id, credits)
        logger.info(
            "Credits refilled: polar_customer_id=%s plan=%s credits=%d",
            customer_id,
            plan,
            credits,
        )


# ── dispatch table ────────────────────────────────────────────────────────────

_HANDLERS = {
    polar.EVT_BENEFIT_GRANT_CREATED: _handle_benefit_grant,
    polar.EVT_BENEFIT_GRANT_UPDATED: _handle_benefit_grant,
    polar.EVT_BENEFIT_GRANT_REVOKED: _handle_benefit_revoke,
    polar.EVT_SUBSCRIPTION_UPDATED:  _handle_subscription_update,
}


# ── route ─────────────────────────────────────────────────────────────────────

@router.post("/polar/webhook")
async def polar_webhook(request: Request) -> JSONResponse:
    body = await request.body()

    msg_id        = request.headers.get("webhook-id", "")
    msg_timestamp = request.headers.get("webhook-timestamp", "")
    msg_signature = request.headers.get("webhook-signature", "")

    if not polar.verify_webhook_signature(
        body, msg_id, msg_timestamp, msg_signature, POLAR_WEBHOOK_SECRET
    ):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload    = json.loads(body)
    event_type = payload.get("type", "")
    # Standard Webhooks guarantees webhook-id is unique per message delivery.
    event_id   = msg_id or payload.get("id", "")

    if not event_id:
        logger.error("Webhook delivered with no event ID — cannot guarantee idempotency")
        return JSONResponse({"status": "error", "detail": "missing event id"}, status_code=400)

    if await db.is_event_processed(event_id):
        logger.info("Duplicate webhook (event_id=%s) — no-op", event_id)
        return JSONResponse({"status": "already_processed"})

    handler = _HANDLERS.get(event_type)
    if handler:
        await handler(payload.get("data") or {})
    else:
        logger.info("Unhandled Polar event type: %s", event_type)

    await db.mark_event_processed(event_id)
    return JSONResponse({"status": "ok"})
