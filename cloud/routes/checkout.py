"""GET /v1/checkout?plan= — return a Polar hosted checkout URL."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from cloud.config import CHECKOUT_URLS, PLAN_CREDITS

router = APIRouter()


class CheckoutResponse(BaseModel):
    plan: str
    credits: int
    url: str


@router.get("/checkout", response_model=CheckoutResponse)
async def checkout(plan: str = "payg") -> CheckoutResponse:
    if plan not in CHECKOUT_URLS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown plan '{plan}'.  Available: {sorted(CHECKOUT_URLS)}",
        )
    url = CHECKOUT_URLS[plan]
    if not url:
        raise HTTPException(
            status_code=503,
            detail=f"Checkout URL for plan '{plan}' is not configured yet.",
        )
    return CheckoutResponse(plan=plan, credits=PLAN_CREDITS[plan], url=url)
