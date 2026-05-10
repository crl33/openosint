# openosint/tools/search_phone.py
"""
Phone number intelligence module.

Wraps the 'phoneinfoga' binary to gather carrier, country,
and line type data for a target phone number.
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

_BINARY = "phoneinfoga"
_DEFAULT_TIMEOUT = 60


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _execute_phoneinfoga(phone: str, timeout: int) -> str:
    """
    Execute phoneinfoga asynchronously against *phone*.

    Raises
    ------
    ToolNotFoundError
        Binary absent from PATH.
    ToolExecutionError
        Process produced no useful output.
    ToolTimeoutError
        Process exceeded *timeout* seconds.
    """
    if not shutil.which(_BINARY):
        raise ToolNotFoundError(
            f"'{_BINARY}' is not installed or not in PATH. "
            "Download from: https://github.com/sundowndev/phoneinfoga/releases"
        )

    command: list[str] = [_BINARY, "scan", "-n", phone]
    process: asyncio.subprocess.Process | None = None

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=float(timeout),
        )
        raw = stdout.decode("utf-8", errors="replace").strip()
        if not raw:
            err = stderr.decode("utf-8", errors="replace").strip()
            raise ToolExecutionError(
                f"phoneinfoga produced no output for '{phone}'. stderr: {err}"
            )
        return raw

    except asyncio.TimeoutError:
        if process is not None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        raise ToolTimeoutError(
            f"phoneinfoga scan of '{phone}' timed out after {timeout}s."
        )


def _format_output(raw: str, phone: str) -> str:
    if not raw:
        return f"No data found for phone number '{phone}'."
    return f"Phone intelligence for '{phone}':\n\n{raw}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def run_phone_osint(phone: str, timeout_seconds: int = _DEFAULT_TIMEOUT) -> str:
    """
    Gather intelligence on *phone* using phoneinfoga.

    The phone number should be in E.164 format (e.g. +14155552671).

    Returns
    -------
    str
        Formatted result string or descriptive error message.
    """
    logger.info("Starting phone scan for: %s", phone)
    try:
        raw = await _execute_phoneinfoga(phone, timeout_seconds)
        result = _format_output(raw, phone)
        logger.info("Phone scan complete for: %s", phone)
        return result
    except OSINTError as exc:
        logger.warning("Phone scan failed: %s", exc)
        return f"Scan error: {exc}"
    except Exception as exc:
        logger.exception("Unexpected error during phone scan.")
        return f"Internal error: {exc}"
