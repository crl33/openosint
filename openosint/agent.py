# openosint/agent.py
"""
OpenOSINT AI Agent.

Implements the agentic loop using either:
  - The Anthropic native tool use API (default, ``provider="anthropic"``).
  - A local Ollama model (``provider="ollama"``).

Both agents share the same ``run()`` interface and return an ``AgentResponse``.
No manual JSON parsing.  The model issues hard stops when it needs a tool,
the real tool executes, the output goes back.  Hallucination in tool results
is structurally impossible.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

import anthropic

from openosint.tools.generate_dorks import run_dork_osint
from openosint.tools.search_breach import run_breach_osint
from openosint.tools.search_domain import run_domain_osint
from openosint.tools.search_email import run_email_osint
from openosint.tools.search_ip import run_ip_osint
from openosint.tools.search_paste import run_paste_osint
from openosint.tools.search_phone import run_phone_osint
from openosint.tools.search_shodan import run_shodan_osint
from openosint.tools.search_username import run_username_osint
from openosint.tools.search_whois import run_whois_osint

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions — Anthropic format
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "search_email",
        "description": (
            "Enumerate online accounts and services associated with an email "
            "address using holehe. Use when the user provides an email to investigate."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "email": {"type": "string", "description": "Target email address."}
            },
            "required": ["email"],
        },
    },
    {
        "name": "search_username",
        "description": (
            "Enumerate social networks and platforms where a username is registered "
            "using sherlock. Never pass a full name with spaces — derive username variations."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "username": {"type": "string", "description": "Target username or alias."}
            },
            "required": ["username"],
        },
    },
    {
        "name": "search_breach",
        "description": (
            "Check if an email address appears in known data breaches via HaveIBeenPwned. "
            "Only call this with a valid email address, never with a name."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "email": {"type": "string", "description": "Target email address."}
            },
            "required": ["email"],
        },
    },
    {
        "name": "search_whois",
        "description": "Retrieve WHOIS registration data for a domain.",
        "input_schema": {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Target domain (e.g. example.com)."}
            },
            "required": ["domain"],
        },
    },
    {
        "name": "search_ip",
        "description": "Retrieve geolocation, ASN, and hostname data for an IP address.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ip": {"type": "string", "description": "Target IP address."}
            },
            "required": ["ip"],
        },
    },
    {
        "name": "search_domain",
        "description": "Enumerate subdomains of a target domain using sublist3r.",
        "input_schema": {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Target domain (e.g. example.com)."}
            },
            "required": ["domain"],
        },
    },
    {
        "name": "generate_dorks",
        "description": (
            "Generate targeted Google dork URLs for any target string. "
            "Always run this first when investigating a full name to discover "
            "real usernames and emails before calling other tools."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Any target: name, email, username, or domain.",
                }
            },
            "required": ["target"],
        },
    },
    {
        "name": "search_paste",
        "description": "Search Pastebin dumps for mentions of an email or username.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Email address or username to search for.",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_phone",
        "description": (
            "Gather carrier, country, and line type data for a phone number. "
            "Use E.164 format."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "phone": {
                    "type": "string",
                    "description": "Target phone number in E.164 format (e.g. +14155552671).",
                }
            },
            "required": ["phone"],
        },
    },
    {
        "name": "search_shodan",
        "description": (
            "Query Shodan for host intelligence or banner searches. "
            "If the query looks like an IP address, performs a host lookup. "
            "Otherwise performs a keyword/service search. Requires SHODAN_API_KEY."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "IP address for host lookup, or a Shodan search query.",
                }
            },
            "required": ["query"],
        },
    },
]

# ---------------------------------------------------------------------------
# Tool executor (shared by both agents)
# ---------------------------------------------------------------------------

_TOOL_MAP: dict[str, Any] = {
    "search_email":    lambda a: run_email_osint(a["email"], timeout_seconds=120),
    "search_username": lambda a: run_username_osint(a["username"], timeout_seconds=180),
    "search_breach":   lambda a: run_breach_osint(a["email"]),
    "search_whois":    lambda a: run_whois_osint(a["domain"]),
    "search_ip":       lambda a: run_ip_osint(a["ip"]),
    "search_domain":   lambda a: run_domain_osint(a["domain"]),
    "generate_dorks":  lambda a: run_dork_osint(a["target"]),
    "search_paste":    lambda a: run_paste_osint(a["query"]),
    "search_phone":    lambda a: run_phone_osint(a["phone"]),
    "search_shodan":   lambda a: run_shodan_osint(a["query"], timeout_seconds=30),
}

SYSTEM_PROMPT = """You are OpenOSINT, an expert OSINT analyst assistant running in a terminal.

INVESTIGATION STRATEGY:
- For a full name target: always start with generate_dorks to discover real identifiers.
- For an email: run search_email and search_breach.
- For a username: run search_username and search_paste.
- For a domain: run search_whois and search_domain.
- For an IP: run search_ip and optionally search_shodan for open ports/vulns.
- For a Shodan query or banners: use search_shodan.
- Chain tools intelligently: use findings from each step to decide the next.
- Never run search_email or search_breach with a full name — only with actual email addresses.
- Never run search_username with spaces in the name.

REPORTING:
After completing the investigation write a structured report:
## Summary
## Online Presence
## Data Breaches (if any)
## Conclusion & Recommendations

CRITICAL RULES:
- NEVER invent, guess, or fabricate information not returned by tools.
- If a tool returns no results, report exactly that.
- Be honest about ambiguity — if multiple people share the name, say so.
- For general questions or chat, respond normally without calling tools."""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ToolCall:
    """Represents a single tool invocation during the agent loop."""
    name: str
    input: dict[str, Any]
    result: str = ""


@dataclass
class AgentResponse:
    """Complete response from one agent turn."""
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    error: str = ""


# ---------------------------------------------------------------------------
# Anthropic agent
# ---------------------------------------------------------------------------

class OpenOSINTAgent:
    """
    Stateful OSINT agent backed by the Anthropic API.

    Maintains conversation history across turns so the model
    can reference previous findings within a session.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-20250514",
    ) -> None:
        self.client = anthropic.Anthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        )
        self.model = model
        self.history: list[dict[str, Any]] = []

    def clear_history(self) -> None:
        """Reset conversation memory."""
        self.history = []

    async def run(
        self,
        prompt: str,
        on_tool_call: Any = None,
    ) -> AgentResponse:
        """
        Execute one agent turn.

        Parameters
        ----------
        prompt:
            User message or OSINT target description.
        on_tool_call:
            Optional async callback invoked before each tool execution.
            Signature: ``async def on_tool_call(name: str, input: dict) -> None``

        Returns
        -------
        AgentResponse
            Final text response and list of tool calls made.
        """
        self.history.append({"role": "user", "content": prompt})

        messages = list(self.history)
        tool_calls_made: list[ToolCall] = []

        try:
            while True:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
                    tools=TOOL_DEFINITIONS,
                    messages=messages,
                )

                if response.stop_reason == "end_turn":
                    text = ""
                    for block in response.content:
                        if hasattr(block, "text"):
                            text = block.text
                            break

                    self.history.append({
                        "role": "assistant",
                        "content": response.content,
                    })
                    return AgentResponse(content=text, tool_calls=tool_calls_made)

                if response.stop_reason == "tool_use":
                    messages.append({
                        "role": "assistant",
                        "content": response.content,
                    })

                    tool_results = []
                    for block in response.content:
                        if block.type != "tool_use":
                            continue

                        tool_name = block.name
                        tool_input = block.input

                        if on_tool_call is not None:
                            await on_tool_call(tool_name, tool_input)

                        if tool_name in _TOOL_MAP:
                            result = await _TOOL_MAP[tool_name](tool_input)
                        else:
                            result = f"Error: unknown tool '{tool_name}'."

                        tc = ToolCall(name=tool_name, input=tool_input, result=result)
                        tool_calls_made.append(tc)
                        logger.info("Tool executed: %s → %d chars", tool_name, len(result))

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })

                    messages.append({"role": "user", "content": tool_results})

                else:
                    break

        except anthropic.AuthenticationError:
            return AgentResponse(
                content="",
                error="Invalid API key. Run 'openosint config' to update it.",
            )
        except anthropic.APIConnectionError:
            return AgentResponse(
                content="",
                error="Cannot reach the Anthropic API. Check your internet connection.",
            )
        except Exception as exc:
            logger.exception("Unexpected error in Anthropic agent loop.")
            return AgentResponse(content="", error=str(exc))

        return AgentResponse(content="", error="Unexpected agent loop exit.")


# ---------------------------------------------------------------------------
# Ollama agent
# ---------------------------------------------------------------------------

def _to_ollama_tools(defs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Anthropic-format tool definitions to Ollama/OpenAI format."""
    out = []
    for d in defs:
        out.append({
            "type": "function",
            "function": {
                "name": d["name"],
                "description": d["description"],
                "parameters": d["input_schema"],
            },
        })
    return out


_OLLAMA_TOOLS = _to_ollama_tools(TOOL_DEFINITIONS)


class OllamaAgent:
    """
    Stateful OSINT agent backed by a local Ollama model.

    Requires the ``ollama`` Python library and a running Ollama daemon.
    No Anthropic API key is needed.

    The agent follows the same tool-use loop as ``OpenOSINTAgent``:
    tool_use → execute real binary → feed real output back → loop until done.
    """

    def __init__(
        self,
        model: str = "llama3.2",
        host: str = "http://localhost:11434",
    ) -> None:
        self.model = model
        self.host = host
        self.history: list[dict[str, Any]] = []

    def clear_history(self) -> None:
        """Reset conversation memory."""
        self.history = []

    async def run(
        self,
        prompt: str,
        on_tool_call: Any = None,
    ) -> AgentResponse:
        """
        Execute one agent turn via Ollama.

        Parameters
        ----------
        prompt:
            User message or OSINT target description.
        on_tool_call:
            Optional async callback — same signature as ``OpenOSINTAgent.run``.

        Returns
        -------
        AgentResponse
            Final text response and list of tool calls made.
        """
        try:
            import ollama  # type: ignore
        except ImportError:
            return AgentResponse(
                content="",
                error=(
                    "'ollama' library is not installed. "
                    "Install it with: pip install ollama"
                ),
            )

        self.history.append({"role": "user", "content": prompt})

        # Prepend system message on every call; system is not stored in history
        messages: list[Any] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *self.history,
        ]
        tool_calls_made: list[ToolCall] = []

        try:
            client = ollama.AsyncClient(host=self.host)

            while True:
                response = await client.chat(
                    model=self.model,
                    messages=messages,
                    tools=_OLLAMA_TOOLS,
                )

                msg = response.message

                if not msg.tool_calls:
                    # Final response — no more tool calls
                    text = msg.content or ""
                    self.history.append({"role": "assistant", "content": text})
                    return AgentResponse(content=text, tool_calls=tool_calls_made)

                # Append assistant turn (with tool_calls) to the local messages list
                assistant_dict: dict[str, Any] = {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            }
                        }
                        for tc in msg.tool_calls
                    ],
                }
                messages.append(assistant_dict)

                for tc in msg.tool_calls:
                    tool_name = tc.function.name
                    tool_input = dict(tc.function.arguments)

                    if on_tool_call is not None:
                        await on_tool_call(tool_name, tool_input)

                    if tool_name in _TOOL_MAP:
                        result = await _TOOL_MAP[tool_name](tool_input)
                    else:
                        result = f"Error: unknown tool '{tool_name}'."

                    tool_calls_made.append(
                        ToolCall(name=tool_name, input=tool_input, result=result)
                    )
                    logger.info(
                        "Ollama tool executed: %s → %d chars", tool_name, len(result)
                    )
                    messages.append({"role": "tool", "content": result})

        except Exception as exc:
            logger.exception("Unexpected error in Ollama agent loop.")
            return AgentResponse(content="", error=str(exc))
