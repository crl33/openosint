# openosint/tools/search_whois.py
"""
WHOIS module.

Queries WHOIS registration data for a target domain
using the python-whois library.
"""

from __future__ import annotations

import logging

from openosint.tools.exceptions import OSINTError, ToolExecutionError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _query_whois(domain: str) -> object:
    try:
        import whois  # type: ignore
    except ImportError as exc:
        raise OSINTError(
            "python-whois is not installed. Run: pip install python-whois"
        ) from exc

    try:
        return whois.whois(domain)
    except Exception as exc:
        raise ToolExecutionError(f"WHOIS query failed for '{domain}': {exc}") from exc


def _format_output(data: object, domain: str) -> str:
    fields = {
        "Domain":       getattr(data, "domain_name", None),
        "Registrar":    getattr(data, "registrar", None),
        "Created":      getattr(data, "creation_date", None),
        "Expires":      getattr(data, "expiration_date", None),
        "Updated":      getattr(data, "updated_date", None),
        "Name Servers": getattr(data, "name_servers", None),
        "Emails":       getattr(data, "emails", None),
        "Org":          getattr(data, "org", None),
        "Country":      getattr(data, "country", None),
    }

    lines = [f"WHOIS results for '{domain}':\n"]
    for key, val in fields.items():
        if not val:
            continue
        if isinstance(val, list):
            val = val[0] if len(val) == 1 else ", ".join(str(v) for v in val[:3])
        lines.append(f"[+] {key}: {val}")

    return "\n".join(lines) if len(lines) > 1 else f"No WHOIS data found for '{domain}'."


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def run_whois_osint(domain: str) -> str:
    """
    Run a WHOIS lookup on *domain*.

    Returns
    -------
    str
        Formatted result string or descriptive error message.
    """
    logger.info("Starting WHOIS lookup for: %s", domain)
    try:
        data = _query_whois(domain)
        result = _format_output(data, domain)
        logger.info("WHOIS lookup complete for: %s", domain)
        return result
    except OSINTError as exc:
        logger.warning("WHOIS lookup failed: %s", exc)
        return f"Scan error: {exc}"
    except Exception as exc:
        logger.exception("Unexpected error during WHOIS lookup.")
        return f"Internal error: {exc}"
