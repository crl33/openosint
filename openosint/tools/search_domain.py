# openosint/tools/search_domain.py
"""
Domain enumeration module.

Wraps the 'sublist3r' binary to discover subdomains
of a target domain.
"""

from __future__ import annotations

import asyncio
import logging
import shutil

from openosint.tools.exceptions import (
    OSINTError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolTimeoutError,
)

logger = logging.getLogger(__name__)

_BINARY = "sublist3r"
_DEFAULT_TIMEOUT = 120


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _execute_sublist3r(domain: str, timeout: int) -> str:
    """
    Execute sublist3r asynchronously against *domain*.

    Raises
    ------
    ToolNotFoundError
        Binary absent from PATH.
    ToolExecutionError
        Process produced no output.
    ToolTimeoutError
        Process exceeded *timeout* seconds.
    """
    if not shutil.which(_BINARY):
        raise ToolNotFoundError(
            f"'{_BINARY}' is not installed or not in PATH. "
            "Install it with: pip install sublist3r"
        )

    command: list[str] = [_BINARY, "-d", domain, "-n"]
    process: asyncio.subprocess.Process | None = None

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(
            process.communicate(),
            timeout=float(timeout),
        )
        raw = stdout.decode("utf-8", errors="replace").strip()
        if not raw:
            raise ToolExecutionError(
                f"sublist3r produced no output for '{domain}'."
            )
        return raw

    except asyncio.TimeoutError:
        if process is not None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        raise ToolTimeoutError(
            f"sublist3r scan of '{domain}' timed out after {timeout}s."
        )


def _format_output(raw: str, domain: str) -> str:
    lines = [
        line.strip()
        for line in raw.splitlines()
        if line.strip() and domain in line and not line.startswith("[")
    ]
    if not lines:
        return f"No subdomains found for '{domain}'."
    return f"Subdomains found for '{domain}':\n\n" + "\n".join(
        f"[+] {s}" for s in lines
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def run_domain_osint(domain: str, timeout_seconds: int = _DEFAULT_TIMEOUT) -> str:
    """
    Enumerate subdomains of *domain* using sublist3r.

    Returns
    -------
    str
        Formatted result string or descriptive error message.
    """
    logger.info("Starting domain enumeration for: %s", domain)
    try:
        raw = await _execute_sublist3r(domain, timeout_seconds)
        result = _format_output(raw, domain)
        logger.info("Domain enumeration complete for: %s", domain)
        return result
    except OSINTError as exc:
        logger.warning("Domain scan failed: %s", exc)
        return f"Scan error: {exc}"
    except Exception as exc:
        logger.exception("Unexpected error during domain scan.")
        return f"Internal error: {exc}"
