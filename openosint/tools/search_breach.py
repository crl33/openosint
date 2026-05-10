# openosint/tools/search_breach.py
"""
Data breach module.

Queries the HaveIBeenPwned v3 API to check whether an email
address appears in known public data breaches.

Requires a HIBP API key: https://haveibeenpwned.com/API/Key
Set it via the HIBP_API_KEY environment variable.
"""

from __future__ import annotations

import logging
import os

import requests

from openosint.tools.exceptions import OSINTError, ToolExecutionError

logger = logging.getLogger(__name__)

_HIBP_API_URL = "https://haveibeenpwned.com/api/v3/breachedaccount/{email}"
_TIMEOUT = 15


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _query_hibp(email: str) -> list[dict]:
    """
    Query the HIBP v3 API for breaches associated with *email*.

    Raises
    ------
    OSINTError
        On missing API key, HTTP errors, or network failures.
    """
    api_key = os.environ.get("HIBP_API_KEY", "")
    if not api_key:
        raise OSINTError(
            "HIBP_API_KEY environment variable is not set. "
            "Get a key at https://haveibeenpwned.com/API/Key"
        )

    headers = {
        "hibp-api-key": api_key,
        "user-agent": "OpenOSINT/2.1.0",
    }
    url = _HIBP_API_URL.format(email=email)

    try:
        response = requests.get(
            url,
            headers=headers,
            params={"truncateResponse": "false"},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise OSINTError(f"Network error querying HIBP: {exc}") from exc

    if response.status_code == 404:
        return []
    if response.status_code == 401:
        raise OSINTError("Invalid HIBP API key.")
    if response.status_code == 429:
        raise OSINTError("HIBP rate limit exceeded. Wait 1 second and retry.")
    if response.status_code != 200:
        raise ToolExecutionError(f"HIBP returned HTTP {response.status_code}.")

    return response.json()


def _format_output(breaches: list[dict], email: str) -> str:
    if not breaches:
        return f"No breaches found for '{email}'."

    lines = [f"Found in {len(breaches)} breach(es) for '{email}':\n"]
    for b in breaches:
        data_classes = ", ".join(b.get("DataClasses", [])[:4])
        lines.append(
            f"[+] {b['Name']} ({b.get('BreachDate', 'unknown')}) "
            f"— leaked: {data_classes}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def run_breach_osint(email: str) -> str:
    """
    Check whether *email* appears in known data breaches via HIBP.

    Returns
    -------
    str
        Formatted result string or descriptive error message.
    """
    logger.info("Starting breach check for: %s", email)
    try:
        breaches = _query_hibp(email)
        result = _format_output(breaches, email)
        logger.info("Breach check complete for: %s", email)
        return result
    except OSINTError as exc:
        logger.warning("Breach check failed: %s", exc)
        return f"Scan error: {exc}"
    except Exception as exc:
        logger.exception("Unexpected error during breach check.")
        return f"Internal error: {exc}"
