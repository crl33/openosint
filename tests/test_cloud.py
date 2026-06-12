"""
Smoke tests for OpenOSINT Cloud gateway.

Runs against the in-memory DB backend (DATABASE_URL not set).
Tool dispatch is mocked — no real network calls.

Coverage:
  (a) 401 on missing / invalid API key
  (b) 402 when credits are exhausted
  (c) success path decrements credits and returns structured result
  (d) non-allow-listed tool returns 400
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from cloud import db
from cloud.main import create_app

# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_memory_store():
    """Clear in-memory state before each test to prevent cross-test pollution."""
    db._MEMORY_CUSTOMERS.clear()
    db._MEMORY_BY_POLAR_ID.clear()
    db._MEMORY_EVENTS.clear()
    yield


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _seed(api_key: str, credits: int = 10, plan: str = "starter") -> db.Customer:
    """Insert a test customer into the in-memory store."""
    customer = db.Customer(
        api_key=api_key,
        polar_customer_id="polar_test_cust",
        credits=credits,
        plan=plan,
    )
    db._MEMORY_CUSTOMERS[api_key] = customer
    db._MEMORY_BY_POLAR_ID["polar_test_cust"] = api_key
    return customer


# ── (a) authentication ────────────────────────────────────────────────────────


async def test_missing_api_key_returns_401(client):
    resp = await client.post("/v1/enrich", json={"tool": "search_ip", "target": "8.8.8.8"})
    assert resp.status_code == 401


async def test_invalid_api_key_returns_401(client):
    resp = await client.post(
        "/v1/enrich",
        json={"tool": "search_ip", "target": "8.8.8.8"},
        headers={"X-API-Key": "not-a-real-key"},
    )
    assert resp.status_code == 401


# ── (b) credits exhausted ─────────────────────────────────────────────────────


async def test_zero_credits_returns_402(client):
    _seed("key-402", credits=0)
    resp = await client.post(
        "/v1/enrich",
        json={"tool": "search_ip", "target": "8.8.8.8"},
        headers={"X-API-Key": "key-402"},
    )
    assert resp.status_code == 402
    body = resp.json()
    assert "checkout_url" in body["detail"]


# ── (c) success path ──────────────────────────────────────────────────────────


async def test_success_decrements_credits_and_returns_result(client):
    _seed("key-200", credits=5)
    fake_result = {
        "tool": "search_ip",
        "target": "8.8.8.8",
        "timestamp": "2026-01-01T00:00:00+00:00",
        "results": ["[+] IP: 8.8.8.8", "[+] Country: US"],
        "error": None,
    }
    with patch("cloud.tools.dispatch", new=AsyncMock(return_value=fake_result)):
        resp = await client.post(
            "/v1/enrich",
            json={"tool": "search_ip", "target": "8.8.8.8"},
            headers={"X-API-Key": "key-200"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["credits_left"] == 4
    assert body["results"] == ["[+] IP: 8.8.8.8", "[+] Country: US"]
    assert body["error"] is None
    # Confirm the DB was actually mutated
    assert db._MEMORY_CUSTOMERS["key-200"].credits == 4


# ── (d) tool not on allow-list ────────────────────────────────────────────────


async def test_non_allowlisted_tool_returns_400(client):
    _seed("key-400", credits=10)
    resp = await client.post(
        "/v1/enrich",
        json={"tool": "search_shodan", "target": "8.8.8.8"},
        headers={"X-API-Key": "key-400"},
    )
    assert resp.status_code == 400
    # Credits must NOT have been decremented for a rejected tool
    assert db._MEMORY_CUSTOMERS["key-400"].credits == 10


# ── usage endpoint ────────────────────────────────────────────────────────────


async def test_usage_returns_credits_and_plan(client):
    _seed("key-usage", credits=7, plan="pro")
    resp = await client.get("/v1/usage", headers={"X-API-Key": "key-usage"})
    assert resp.status_code == 200
    assert resp.json() == {"plan": "pro", "credits": 7}
