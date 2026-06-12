"""
OpenOSINT Cloud — FastAPI application entry point.

Heroku Procfile:  web: uvicorn cloud.main:app --host 0.0.0.0 --port $PORT
Local dev:        python -m cloud.main
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from cloud import db
from cloud.routes import checkout, enrich, usage, webhook

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    await db.init_pool()
    yield
    await db.close_pool()


def create_app() -> FastAPI:
    app = FastAPI(
        title="OpenOSINT Cloud",
        version="1.0.0",
        description=(
            "Hosted OSINT gateway — pay-as-you-go, no upstream API-key juggling, "
            "AI-chained results.  Billing via Polar.sh."
        ),
        lifespan=_lifespan,
    )
    app.include_router(enrich.router,   prefix="/v1")
    app.include_router(usage.router,    prefix="/v1")
    app.include_router(checkout.router, prefix="/v1")
    app.include_router(webhook.router,  prefix="/v1")
    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("cloud.main:app", host="0.0.0.0", port=port, reload=False)
