"""POST /v1/enrich — run an OSINT tool against a target."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from cloud import db, polar, tools
from cloud.auth import get_customer
from cloud.config import CHECKOUT_URLS, TOOL_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)

router = APIRouter()


class EnrichRequest(BaseModel):
    tool: str
    target: str


class EnrichResponse(BaseModel):
    tool: str
    target: str
    timestamp: str
    results: list[str]
    error: str | None
    credits_left: int


@router.post("/enrich", response_model=EnrichResponse)
async def enrich(
    body: EnrichRequest,
    customer: db.Customer = Depends(get_customer),
) -> EnrichResponse:
    # 400 — tool not in allow-list (checked before any credit deduction)
    if body.tool not in tools.ALLOW_LIST:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Tool '{body.tool}' is not available in v1.  "
                f"Available: {sorted(tools.ALLOW_LIST)}"
            ),
        )

    # 402 — fast pre-check to avoid DB round-trip on obviously empty accounts
    if customer.credits <= 0:
        _raise_402(customer.plan)

    # Atomic decrement — guards against concurrent exhaustion between the
    # pre-check above and this debit.
    new_credits = await db.decrement_credits(customer.api_key)
    if new_credits is None:
        _raise_402(customer.plan)

    # Run the tool under the Heroku-safe timeout
    try:
        result = await asyncio.wait_for(
            tools.dispatch(body.tool, body.target),
            timeout=float(TOOL_TIMEOUT_SECONDS),
        )
    except asyncio.TimeoutError:
        logger.warning("Tool %s timed out (target=%s)", body.tool, body.target)
        raise HTTPException(
            status_code=504,
            detail=f"Tool '{body.tool}' exceeded the {TOOL_TIMEOUT_SECONDS} s timeout",
        )

    # Fire-and-forget Polar usage telemetry — errors are swallowed in polar.py
    if customer.polar_customer_id:
        asyncio.create_task(
            polar.send_usage_event(customer.polar_customer_id, body.tool)
        )

    return EnrichResponse(
        tool=result["tool"],
        target=result["target"],
        timestamp=result["timestamp"],
        results=result["results"],
        error=result["error"],
        credits_left=new_credits,
    )


def _raise_402(plan: str) -> None:
    checkout_url = CHECKOUT_URLS.get(plan) or CHECKOUT_URLS.get("payg", "")
    raise HTTPException(
        status_code=402,
        detail={"message": "No credits remaining.", "checkout_url": checkout_url},
    )
