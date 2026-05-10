# openosint/tools/search_username.py

import asyncio
import logging
import shutil
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration & Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Custom Exceptions (Clean Error Handling)
# ---------------------------------------------------------------------------
class OSINTError(Exception):
    """Base exception for all OSINT tool-related errors."""
    pass

class ToolNotFoundError(OSINTError):
    """Raised when the required external binary is missing."""
    pass

class ToolExecutionError(OSINTError):
    """Raised when the external tool fails (e.g., unexpected exit code)."""
    pass

class ToolTimeoutError(OSINTError):
    """Raised when the execution exceeds the allowed time limit."""
    pass

# ---------------------------------------------------------------------------
# Internal Core Logic (Private functions)
# ---------------------------------------------------------------------------
async def _execute_sherlock(username: str, timeout: int) -> str:
    """
    Handles the asynchronous execution of the 'sherlock' binary.
    
    Args:
        username: The target username/alias to search for.
        timeout: Maximum execution time in seconds for the entire process.
        
    Raises:
        ToolNotFoundError: If the binary is not in the system PATH.
        ToolExecutionError: If the process fails to return meaningful output.
        ToolTimeoutError: If the process hangs.
        
    Returns:
        The raw stdout string from the command containing the discovered URLs.
    """
    # Fail Fast: Check if the required binary exists before starting processes
    if not shutil.which("sherlock"):
        raise ToolNotFoundError(
            "The 'sherlock' binary is not installed or not in PATH. "
            "Please run: pip install sherlock-project"
        )

    # Command configuration:
    # --print-found: Excludes negative results to save LLM context window tokens
    # --timeout 3: Limits the connection time for EACH individual site check
    command = ["sherlock", username, "--print-found", "--timeout", "3"]
    
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        # Wait for the entire OSINT operation to complete, bounded by the global timeout
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), 
            timeout=timeout
        )
        
        raw_output = stdout.decode('utf-8').strip()
        
        # Sherlock might return a non-zero exit code if some sites fail, 
        # but we still want the positive hits it managed to collect.
        if not raw_output:
            error_msg = stderr.decode('utf-8').strip()
            raise ToolExecutionError(f"No valid output generated. Details: {error_msg}")
            
        return raw_output
        
    except asyncio.TimeoutError:
        # Prevent zombie processes if the timeout triggers
        try:
            process.kill()
        except ProcessLookupError:
            pass 
        raise ToolTimeoutError(f"Username scan for '{username}' timed out after {timeout} seconds.")

def _parse_output(raw_output: str, username: str) -> str:
    """
    Parses and formats the raw tool output into a clean LLM-friendly string.
    Removes unnecessary terminal artifacts if present.
    """
    if not raw_output:
        return f"Scan completed natively, but no accounts were found for username '{username}'."
    
    # Wrap the output in a structured format for the LLM or CLI user
    return f"OSINT Results for username '{username}':\n\n{raw_output}"

# ---------------------------------------------------------------------------
# Public API (Exposed to MCP Server)
# ---------------------------------------------------------------------------
async def run_username_osint(username: str, timeout_seconds: int = 180) -> str:
    """
    Executes an OSINT scan on a specific username across various platforms.
    This is the main entry point to be wrapped by the MCP server or the CLI.
    
    Args:
        username (str): The target username/alias to investigate.
        timeout_seconds (int): Max execution time. Defaults to 180 (Sherlock is slow).
        
    Returns:
        str: The formatted results or a safe, descriptive error message.
    """
    logger.info(f"Initiating username OSINT workflow for: {username}")
    
    try:
        # 1. Execute the core scanning logic
        raw_data = await _execute_sherlock(username, timeout_seconds)
        
        # 2. Parse & Format the output
        formatted_result = _parse_output(raw_data, username)
        
        logger.info(f"Successfully completed username scan for: {username}")
        return formatted_result
        
    except OSINTError as base_err:
        # Graceful handling of known tool errors
        logger.warning(f"OSINT username scan failed gracefully: {str(base_err)}")
        return f"Error executing username scan: {str(base_err)}"
        
    except Exception as unexpected_err:
        # Catch-all for critical system or memory errors
        logger.exception("A critical unexpected error occurred during username scan.")
        return f"Critical system error during username OSINT scan: {str(unexpected_err)}"

# ---------------------------------------------------------------------------
# Standalone Testing Block
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    async def run_test():
        test_target = "johndoe"
        print(f"[*] Starting local test for username '{test_target}'...\n")
        
        # We use a shorter timeout for local testing to fail fast if there's a problem
        result = await run_username_osint(test_target, timeout_seconds=60)
        
        print("\n[RESULT]")
        print(result)
        
    asyncio.run(run_test())