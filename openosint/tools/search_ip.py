# openosint/tools/search_ip.py
"""
IP intelligence module.

Queries ipinfo.io to retrieve geolocation, ASN, hostname,
and organisation data for a target IP address.

Free tier: 50k requests/month, no API key required.
Set IPINFO_TOKEN env var for higher limits.
"""

from __future__ import annotations

import logging
import os

import requests

from openosint.tools.exceptions import OSINTError, ToolExecutionError

logger = logging.getLogger(__name__)

_IPINFO_URL = "https://ipinfo.io/{ip}/json"
_TIMEOUT = 10


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _query_ipinfo(ip: str) -> dict:
    token = os.environ.get("IPINFO_TOKEN", "")
    params = {"token": token} if token else {}

    try:
        response = requests.get(
            _IPINFO_URL.format(ip=ip),
            params=params,
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise OSINTError(f"Network error querying ipinfo.io: {exc}") from exc

    if response.status_code == 429:
        raise OSINTError(
            "ipinfo.io rate limit exceeded. "
            "Set IPINFO_TOKEN for higher limits: https://ipinfo.io/signup"
        )
    if response.status_code != 200:
        raise ToolExecutionError(f"ipinfo.io returned HTTP {response.status_code}.")

    return response.json()


def _format_output(data: dict, ip: str) -> str:
    if "bogon" in data:
        return f"'{ip}' is a bogon/private address — no public data available."

    fields = ["ip", "hostname", "org", "city", "region", "country", "loc", "timezone"]
    lines = [f"IP intelligence for '{ip}':\n"]
    for field in fields:
        val = data.get(field)
        if val:
            lines.append(f"[+] {field.capitalize()}: {val}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def run_ip_osint(ip: str) -> str:
    """
    Retrieve geolocation and ASN data for *ip* via ipinfo.io.

    Returns
    -------
    str
        Formatted result string or descriptive error message.
    """
    logger.info("Starting IP lookup for: %s", ip)
    try:
        data = _query_ipinfo(ip)
        result = _format_output(data, ip)
        logger.info("IP lookup complete for: %s", ip)
        return result
    except OSINTError as exc:
        logger.warning("IP lookup failed: %s", exc)
        return f"Scan error: {exc}"
    except Exception as exc:
        logger.exception("Unexpected error during IP lookup.")
        return f"Internal error: {exc}"
