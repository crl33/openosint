# openosint/utils.py
"""
Shared utility functions for OpenOSINT tool modules.

run_subprocess() centralises the asyncio subprocess execution pattern
(binary check → create_subprocess_exec → wait_for → kill on timeout)
that all binary-based OSINT tool wrappers share.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from typing import NamedTuple

from openosint.tools.exceptions import ToolNotFoundError, ToolTimeoutError

logger = logging.getLogger(__name__)


class SubprocessResult(NamedTuple):
    """Result of a completed external subprocess call."""

    stdout: str
    stderr: str
    return_code: int


async def run_subprocess(
    binary: str,
    args: list[str],
    timeout_seconds: int,
    install_hint: str = "",
) -> SubprocessResult:
    """
    Execute an external binary asynchronously and return its output.

    Parameters
    ----------
    binary:
        Executable name discoverable via PATH.
    args:
        Arguments forwarded to the binary.
    timeout_seconds:
        Hard wall-clock limit; process is killed on expiry.
    install_hint:
        Short installation message appended to ToolNotFoundError.

    Raises
    ------
    ToolNotFoundError
        When the binary is absent from PATH.
    ToolTimeoutError
        When the process exceeds timeout_seconds.
    """
    if not shutil.which(binary):
        detail = f" {install_hint}" if install_hint else ""
        raise ToolNotFoundError(
            f"'{binary}' is not installed or not in PATH.{detail}"
        )

    process: asyncio.subprocess.Process | None = None
    try:
        process = await asyncio.create_subprocess_exec(
            binary,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        raw_stdout, raw_stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=float(timeout_seconds),
        )
        return SubprocessResult(
            stdout=raw_stdout.decode("utf-8", errors="replace").strip(),
            stderr=raw_stderr.decode("utf-8", errors="replace").strip(),
            return_code=process.returncode or 0,
        )
    except asyncio.TimeoutError:
        _kill_process(process)
        raise ToolTimeoutError(
            f"'{binary}' scan timed out after {timeout_seconds}s."
        )


def _kill_process(process: asyncio.subprocess.Process | None) -> None:
    """Terminate a subprocess, ignoring errors if it already exited."""
    if process is None:
        return
    try:
        process.kill()
    except ProcessLookupError:
        pass
