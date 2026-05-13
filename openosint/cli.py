# openosint/cli.py
"""
OpenOSINT command-line interface.

Default behaviour  : launches the interactive REPL (Claude Code style).
Subcommands        : direct tool execution without AI (email, username,
                     shodan, multi).

Usage:
    openosint                                   # interactive REPL
    openosint email target@example.com          # direct, no AI
    openosint username johndoe99                # direct, no AI
    openosint shodan 8.8.8.8                    # Shodan lookup, no AI
    openosint multi targets.txt                 # multi-target (file)
    openosint multi email1,email2,email3        # multi-target (inline)
    openosint --parallel email target@example.com
    openosint --json email target@example.com
    openosint --provider ollama                 # use local Ollama
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from openosint.json_output import format_tool_result, to_json
from openosint.tools.search_breach import run_breach_osint
from openosint.tools.search_email import run_email_osint
from openosint.tools.search_paste import run_paste_osint
from openosint.tools.search_shodan import run_shodan_osint
from openosint.tools.search_username import run_username_osint

_DIVIDER = "=" * 60


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(level=level, format="[%(levelname)s] %(name)s: %(message)s")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openosint",
        description=(
            "OpenOSINT — AI-powered OSINT framework.\n"
            "Run without arguments to start the interactive REPL."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  openosint                                   # interactive AI session\n"
            "  openosint email target@example.com          # direct email scan\n"
            "  openosint username johndoe99                # direct username scan\n"
            "  openosint shodan 8.8.8.8                    # Shodan host lookup\n"
            "  openosint multi targets.txt                 # multi-target from file\n"
            "  openosint multi a@x.com,b@y.com             # multi-target inline\n"
            "  openosint --parallel email target@example.com\n"
            "  openosint --json email target@example.com\n"
            "  openosint --provider ollama                 # use local Ollama\n"
            "  openosint --provider ollama --ollama-model mistral\n"
        ),
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug-level logging.",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        metavar="KEY",
        help="Anthropic API key (overrides ANTHROPIC_API_KEY env var).",
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        help=(
            "Run independent complementary tools concurrently using asyncio.gather(). "
            "For 'email': runs search_email + search_breach in parallel. "
            "For 'username': runs search_username + search_paste in parallel."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output results as structured JSON instead of formatted text.",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default="anthropic",
        choices=["anthropic", "ollama"],
        help="AI provider for the interactive REPL (default: anthropic).",
    )
    parser.add_argument(
        "--ollama-model",
        type=str,
        default="llama3.2",
        metavar="MODEL",
        help="Ollama model name (default: llama3.2).  Used when --provider ollama.",
    )
    parser.add_argument(
        "--ollama-host",
        type=str,
        default="http://localhost:11434",
        metavar="URL",
        help="Ollama server URL (default: http://localhost:11434).",
    )
    parser.add_argument(
        "--no-pdf",
        action="store_true",
        dest="no_pdf",
        help="Disable automatic PDF generation alongside Markdown reports.",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="command")

    # shell — explicit alias for REPL
    subparsers.add_parser(
        "shell",
        help="Start the interactive REPL (default when no command given).",
    )

    # email
    email_cmd = subparsers.add_parser(
        "email",
        help="Direct email scan via holehe (no AI).",
    )
    email_cmd.add_argument("target", type=str, metavar="ADDRESS")
    email_cmd.add_argument(
        "-t", "--timeout",
        type=int,
        default=120,
        metavar="SECONDS",
        help="Maximum execution time (default: 120).",
    )

    # username
    username_cmd = subparsers.add_parser(
        "username",
        help="Direct username scan via sherlock (no AI).",
    )
    username_cmd.add_argument("target", type=str, metavar="USERNAME")
    username_cmd.add_argument(
        "-t", "--timeout",
        type=int,
        default=180,
        metavar="SECONDS",
        help="Maximum execution time (default: 180).",
    )

    # shodan
    shodan_cmd = subparsers.add_parser(
        "shodan",
        help="Shodan host lookup or keyword search (no AI). Requires SHODAN_API_KEY.",
    )
    shodan_cmd.add_argument(
        "query",
        type=str,
        metavar="QUERY",
        help="IP address for host lookup, or any Shodan search query.",
    )
    shodan_cmd.add_argument(
        "-t", "--timeout",
        type=int,
        default=30,
        metavar="SECONDS",
        help="Request timeout (default: 30).",
    )

    # multi
    multi_cmd = subparsers.add_parser(
        "multi",
        help="Investigate multiple targets in parallel (AI-powered).",
    )
    multi_cmd.add_argument(
        "targets",
        type=str,
        metavar="TARGETS",
        help=(
            "Comma-separated list of targets, "
            "or path to a file with one target per line."
        ),
    )

    return parser


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _print_result(result: str) -> None:
    print(_DIVIDER)
    print(" SCAN RESULTS ".center(60, "="))
    print(_DIVIDER)
    print(result)
    print(_DIVIDER)


def _print_result_labeled(label: str, result: str) -> None:
    print(_DIVIDER)
    print(f" {label} ".center(60, "="))
    print(_DIVIDER)
    print(result)
    print(_DIVIDER)


def _emit_json(data: dict | list) -> None:
    print(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# Direct command handlers (no AI)
# ---------------------------------------------------------------------------

async def _handle_email(
    target: str,
    timeout: int,
    parallel: bool = False,
    json_output: bool = False,
) -> None:
    if parallel:
        print(f"[*] Email scan (parallel): {target}", file=sys.stderr)
        email_result, breach_result = await asyncio.gather(
            run_email_osint(email=target, timeout_seconds=timeout),
            run_breach_osint(email=target),
        )
        if json_output:
            _emit_json([
                format_tool_result("search_email", target, email_result),
                format_tool_result("search_breach", target, breach_result),
            ])
        else:
            _print_result_labeled("search_email", email_result)
            _print_result_labeled("search_breach", breach_result)
    else:
        print(f"[*] Email scan: {target}", file=sys.stderr)
        print(f"[*] Timeout: {timeout}s\n", file=sys.stderr)
        result = await run_email_osint(email=target, timeout_seconds=timeout)
        if json_output:
            _emit_json(format_tool_result("search_email", target, result))
        else:
            _print_result(result)


async def _handle_username(
    target: str,
    timeout: int,
    parallel: bool = False,
    json_output: bool = False,
) -> None:
    if parallel:
        print(f"[*] Username scan (parallel): {target}", file=sys.stderr)
        username_result, paste_result = await asyncio.gather(
            run_username_osint(username=target, timeout_seconds=timeout),
            run_paste_osint(query=target),
        )
        if json_output:
            _emit_json([
                format_tool_result("search_username", target, username_result),
                format_tool_result("search_paste", target, paste_result),
            ])
        else:
            _print_result_labeled("search_username", username_result)
            _print_result_labeled("search_paste", paste_result)
    else:
        print(f"[*] Username scan: {target}", file=sys.stderr)
        print(f"[*] Timeout: {timeout}s\n", file=sys.stderr)
        result = await run_username_osint(username=target, timeout_seconds=timeout)
        if json_output:
            _emit_json(format_tool_result("search_username", target, result))
        else:
            _print_result(result)


async def _handle_shodan(
    query: str,
    timeout: int,
    json_output: bool = False,
) -> None:
    print(f"[*] Shodan lookup: {query}", file=sys.stderr)
    result = await run_shodan_osint(query=query, timeout_seconds=timeout)
    if json_output:
        _emit_json(format_tool_result("search_shodan", query, result))
    else:
        _print_result(result)


async def _handle_multi(
    targets_arg: str,
    api_key: str | None = None,
    no_pdf: bool = False,
) -> None:
    from openosint.multi_target import MAX_TARGETS, parse_targets, run_multi_target

    targets = parse_targets(targets_arg)
    if not targets:
        print("[!] No targets found.", file=sys.stderr)
        sys.exit(1)
    if len(targets) > MAX_TARGETS:
        print(
            f"[!] Too many targets ({len(targets)}). Maximum is {MAX_TARGETS}.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"[*] Multi-target investigation: {len(targets)} target(s)", file=sys.stderr)
    summary = await run_multi_target(targets, api_key=api_key, no_pdf=no_pdf)
    _print_result(summary)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

async def _async_main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    _configure_logging(args.verbose)

    # No subcommand or explicit 'shell' → launch REPL
    if args.command in (None, "shell"):
        from openosint.repl import run_repl
        run_repl(
            api_key=getattr(args, "api_key", None),
            provider=getattr(args, "provider", "anthropic"),
            ollama_model=getattr(args, "ollama_model", "llama3.2"),
            ollama_host=getattr(args, "ollama_host", "http://localhost:11434"),
            no_pdf=getattr(args, "no_pdf", False),
        )
        return

    parallel = getattr(args, "parallel", False)
    json_output = getattr(args, "json_output", False)
    no_pdf = getattr(args, "no_pdf", False)

    if args.command == "email":
        await _handle_email(
            args.target, args.timeout, parallel=parallel, json_output=json_output
        )
    elif args.command == "username":
        await _handle_username(
            args.target, args.timeout, parallel=parallel, json_output=json_output
        )
    elif args.command == "shodan":
        await _handle_shodan(args.query, args.timeout, json_output=json_output)
    elif args.command == "multi":
        await _handle_multi(
            args.targets, api_key=getattr(args, "api_key", None), no_pdf=no_pdf
        )
    else:
        parser.print_help()
        sys.exit(1)


def main() -> None:
    """Synchronous entry point registered in pyproject.toml."""
    try:
        asyncio.run(_async_main())
    except KeyboardInterrupt:
        print("\n[!] Interrupted.", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f"[!] Fatal: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
