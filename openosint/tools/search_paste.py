# openosint/tools/search_paste.py
"""
Pastebin dump search module.

Queries the psbdmp.ws public API to find pastes
mentioning a target email address or username.
"""

from __future__ import annotations

import logging

import requests

from openosint.tools.exceptions import OSINTError, ToolExecutionError

logger = logging.getLogger(__name__)

_PSBDMP_URL = "https://psbdmp.ws/api/search/{query}"
_TIMEOUT = 15
_MAX_RESULTS = 10


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _query_psbdmp(query: str) -> list[dict]:
    try:
        response = requests.get(
            _PSBDMP_URL.format(query=query),
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise OSINTError(f"Network error querying psbdmp.ws: {exc}") from exc

    if response.status_code == 404:
        return []
    if response.status_code != 200:
        raise ToolExecutionError(f"psbdmp.ws returned HTTP {response.status_code}.")

    data = response.json()
    return data.get("data", []) if isinstance(data, dict) else []


def _format_output(pastes: list[dict], query: str) -> str:
    if not pastes:
        return f"No pastes found mentioning '{query}'."

    count = len(pastes)
    shown = pastes[:_MAX_RESULTS]
    lines = [f"Found in {count} paste(s) for '{query}':\n"]
    for paste in shown:
        pid = paste.get("id", "unknown")
        date = paste.get("time", "unknown date")
        lines.append(f"[+] https://pastebin.com/{pid} ({date})")
    if count > _MAX_RESULTS:
        lines.append(f"\n... and {count - _MAX_RESULTS} more.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def run_paste_osint(query: str) -> str:
    """
    Search Pastebin dumps for *query* via psbdmp.ws.

    Returns
    -------
    str
        Formatted result string or descriptive error message.
    """
    logger.info("Starting paste search for: %s", query)
    try:
        pastes = _query_psbdmp(query)
        result = _format_output(pastes, query)
        logger.info("Paste search complete for: %s", query)
        return result
    except OSINTError as exc:
        logger.warning("Paste search failed: %s", exc)
        return f"Scan error: {exc}"
    except Exception as exc:
        logger.exception("Unexpected error during paste search.")
        return f"Internal error: {exc}"
