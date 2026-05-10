# openosint/mcp_server.py
"""
OpenOSINT MCP Server — v2.1.0

Exposes all 9 OSINT tool capabilities to MCP-compliant AI clients
over standard I/O.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool

from openosint.tools.search_email import run_email_osint
from openosint.tools.search_username import run_username_osint
from openosint.tools.search_breach import run_breach_osint
from openosint.tools.search_whois import run_whois_osint
from openosint.tools.search_ip import run_ip_osint
from openosint.tools.search_domain import run_domain_osint
from openosint.tools.generate_dorks import run_dork_osint
from openosint.tools.search_paste import run_paste_osint
from openosint.tools.search_phone import run_phone_osint

logging.basicConfig(level=logging.INFO, format="[MCP] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)
app = Server("openosint")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(name="search_email", description="Enumerate accounts linked to an email using holehe.", inputSchema={"type":"object","properties":{"email":{"type":"string"}},"required":["email"]}),
        Tool(name="search_username", description="Enumerate platforms where a username is registered using sherlock.", inputSchema={"type":"object","properties":{"username":{"type":"string"}},"required":["username"]}),
        Tool(name="search_breach", description="Check if an email appears in data breaches via HaveIBeenPwned. Requires HIBP_API_KEY env var.", inputSchema={"type":"object","properties":{"email":{"type":"string"}},"required":["email"]}),
        Tool(name="search_whois", description="Retrieve WHOIS registration data for a domain.", inputSchema={"type":"object","properties":{"domain":{"type":"string"}},"required":["domain"]}),
        Tool(name="search_ip", description="Retrieve geolocation and ASN data for an IP address via ipinfo.io.", inputSchema={"type":"object","properties":{"ip":{"type":"string"}},"required":["ip"]}),
        Tool(name="search_domain", description="Enumerate subdomains of a target domain using sublist3r.", inputSchema={"type":"object","properties":{"domain":{"type":"string"}},"required":["domain"]}),
        Tool(name="generate_dorks", description="Generate targeted Google dork URLs for any target (name, email, username, domain).", inputSchema={"type":"object","properties":{"target":{"type":"string"}},"required":["target"]}),
        Tool(name="search_paste", description="Search Pastebin dumps for an email or username via psbdmp.ws.", inputSchema={"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}),
        Tool(name="search_phone", description="Gather carrier and geolocation data for a phone number using phoneinfoga. Use E.164 format.", inputSchema={"type":"object","properties":{"phone":{"type":"string"}},"required":["phone"]}),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
    logger.info("Tool: %s | args: %s", name, arguments)
    try:
        handlers = {
            "search_email":    lambda a: run_email_osint(a["email"], timeout_seconds=120),
            "search_username": lambda a: run_username_osint(a["username"], timeout_seconds=180),
            "search_breach":   lambda a: run_breach_osint(a["email"]),
            "search_whois":    lambda a: run_whois_osint(a["domain"]),
            "search_ip":       lambda a: run_ip_osint(a["ip"]),
            "search_domain":   lambda a: run_domain_osint(a["domain"]),
            "generate_dorks":  lambda a: run_dork_osint(a["target"]),
            "search_paste":    lambda a: run_paste_osint(a["query"]),
            "search_phone":    lambda a: run_phone_osint(a["phone"]),
        }
        if name not in handlers:
            raise ValueError(f"Unknown tool: '{name}'")
        result = await handlers[name](arguments)
        return CallToolResult(content=[TextContent(type="text", text=result)], isError=False)
    except (KeyError, ValueError) as exc:
        logger.error("Validation error: %s", exc)
        return CallToolResult(content=[TextContent(type="text", text=str(exc))], isError=True)
    except Exception as exc:
        logger.exception("Unhandled error in tool '%s'.", name)
        return CallToolResult(content=[TextContent(type="text", text=f"Internal error: {exc}")], isError=True)


async def _serve() -> None:
    async with stdio_server() as (r, w):
        await app.run(r, w, app.create_initialization_options())

def main() -> None:
    asyncio.run(_serve())

if __name__ == "__main__":
    main()
