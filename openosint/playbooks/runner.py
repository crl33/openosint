# openosint/playbooks/runner.py
"""Execute a playbook Recipe against a target and write a branded Markdown/PDF report."""

from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Awaitable, Callable

from openosint.tools.generate_dorks import run_dork_osint
from openosint.tools.search_breach import run_breach_osint
from openosint.tools.search_dns import run_dns_osint
from openosint.tools.search_domain import run_domain_osint
from openosint.tools.search_email import run_email_osint
from openosint.tools.search_footprint import run_footprint_osint
from openosint.tools.search_ip import run_ip_osint
from openosint.tools.search_paste import run_paste_osint
from openosint.tools.search_phone import run_phone_osint
from openosint.tools.search_shodan import run_shodan_osint
from openosint.tools.search_username import run_username_osint
from openosint.tools.search_virustotal import run_virustotal_osint
from openosint.tools.search_whois import run_whois_osint

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

TOOL_MAP: dict[str, Callable[..., Awaitable[str]]] = {
    "search_whois": run_whois_osint,
    "search_dns": run_dns_osint,
    "generate_dorks": run_dork_osint,
    "search_domain": run_domain_osint,
    "search_footprint": run_footprint_osint,
    "search_email": run_email_osint,
    "search_breach": run_breach_osint,
    "search_ip": run_ip_osint,
    "search_shodan": run_shodan_osint,
    "search_virustotal": run_virustotal_osint,
    "search_paste": run_paste_osint,
    "search_username": run_username_osint,
    "search_phone": run_phone_osint,
}

# ---------------------------------------------------------------------------
# Tool requirements
# Each entry: (env_vars, binaries, optional_note)
# An empty list means "no requirement — always available".
# ---------------------------------------------------------------------------

_Req = tuple[list[str], list[str], str | None]

TOOL_REQUIREMENTS: dict[str, _Req] = {
    "search_whois": ([], [], None),
    "search_dns": ([], [], None),
    "generate_dorks": ([], [], None),
    "search_domain": ([], ["sublist3r"], None),
    "search_footprint": (
        ["BRIGHTDATA_API_KEY", "BRIGHTDATA_SERP_ZONE"],
        [],
        "Sign up at brightdata.com to obtain your API key and SERP zone.",
    ),
    "search_email": ([], ["holehe"], None),
    "search_breach": (["HIBP_API_KEY"], [], None),
    "search_ip": ([], [], None),
    "search_shodan": (["SHODAN_API_KEY"], [], None),
    "search_virustotal": (["VIRUSTOTAL_API_KEY"], [], None),
    "search_paste": ([], [], None),
    "search_username": ([], ["sherlock"], None),
    "search_phone": ([], ["phoneinfoga"], None),
}

# ---------------------------------------------------------------------------
# Step state
# ---------------------------------------------------------------------------


class StepState(Enum):
    NOT_CONFIGURED = "not_configured"
    EMPTY = "empty"
    ERROR = "error"
    SUCCESS = "success"


# ---------------------------------------------------------------------------
# Requirements check
# ---------------------------------------------------------------------------


def _missing_requirements(tool: str) -> tuple[list[str], str | None]:
    """Return (list_of_missing_items, optional_note) for *tool*."""
    env_vars, binaries, note = TOOL_REQUIREMENTS.get(tool, ([], [], None))
    missing: list[str] = []
    for var in env_vars:
        if not os.environ.get(var):
            missing.append(var)
    for binary in binaries:
        if shutil.which(binary) is None:
            missing.append(binary)
    return missing, note


# ---------------------------------------------------------------------------
# Per-step execution
# ---------------------------------------------------------------------------


async def _run_step(tool: str, target: str) -> tuple[StepState, str]:
    """Run a single tool step.  Never raises."""
    missing, _note = _missing_requirements(tool)
    if missing:
        return StepState.NOT_CONFIGURED, ""

    try:
        output: str = await TOOL_MAP[tool](target)  # type: ignore[call-arg]
    except Exception as exc:
        logger.debug("Step '%s' raised: %s", tool, exc)
        return StepState.ERROR, str(exc)

    if not output or not output.strip():
        return StepState.EMPTY, ""

    return StepState.SUCCESS, output


# ---------------------------------------------------------------------------
# Executive summary (via EXTRACTOR_REGISTRY — no ad-hoc regex)
# ---------------------------------------------------------------------------


def _build_summary(
    target: str,
    recipe_target_type: str,
    step_results: list[tuple[str, str, StepState, str]],
) -> str:
    """
    Build a deterministic executive summary using EXTRACTOR_REGISTRY.

    Parameters
    ----------
    target:
        The investigation target string.
    recipe_target_type:
        The target_type declared in the recipe (e.g. "domain").
    step_results:
        List of (step_id, tool_name, state, output) tuples.
    """
    from openosint.correlation import EntityType, make_entity
    from openosint.extractors import EXTRACTOR_REGISTRY

    _ENTITY_TYPE_MAP: dict[str, EntityType] = {
        "domain": EntityType.DOMAIN,
        "email": EntityType.EMAIL,
        "ip": EntityType.IP,
        "username": EntityType.USERNAME,
        "phone": EntityType.PHONE,
        "url": EntityType.URL,
        "hash": EntityType.HASH,
        "person": EntityType.PERSON,
    }
    seed_type = _ENTITY_TYPE_MAP.get(recipe_target_type, EntityType.DOMAIN)
    seed = make_entity(seed_type, target, 1.0, "playbook")

    completed = sum(1 for _, _, state, _ in step_results if state == StepState.SUCCESS)
    skipped = sum(1 for _, _, state, _ in step_results if state == StepState.NOT_CONFIGURED)
    total = len(step_results)

    entity_counts: dict[EntityType, set[str]] = {}
    for _step_id, tool_name, state, output in step_results:
        if state != StepState.SUCCESS:
            continue
        extractor = EXTRACTOR_REGISTRY.get(tool_name)
        if extractor is None:
            continue
        entities, _ = extractor(output, seed)
        for entity in entities:
            entity_counts.setdefault(entity.type, set()).add(entity.value)

    lines: list[str] = []
    skip_note = f" ({skipped} skipped — not configured)" if skipped else ""
    lines.append(f"- **Steps completed:** {completed}/{total}{skip_note}")

    _LABEL: dict[EntityType, str] = {
        EntityType.DOMAIN: "Subdomains / domains found",
        EntityType.IP: "IP addresses found",
        EntityType.EMAIL: "Registrant emails",
        EntityType.ORG: "Organisations found",
        EntityType.ASN: "ASNs found",
        EntityType.URL: "SERP URLs found",
        EntityType.USERNAME: "Usernames found",
    }
    for etype, label in _LABEL.items():
        count = len(entity_counts.get(etype, set()))
        if count:
            lines.append(f"- **{label}:** {count}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Markdown report builder
# ---------------------------------------------------------------------------


def _build_report(
    recipe_label: str,
    recipe_name: str,
    target_type: str,
    target: str,
    date_str: str,
    step_results: list[tuple[str, str, StepState, str]],
    summary: str,
    steps_map: dict[str, tuple[str, str]],
) -> str:
    """Assemble the full Markdown report string."""
    lines: list[str] = [
        f"# {recipe_label} — {target}",
        "",
        f"**Target:** {target}  ",
        f"**Target type:** {target_type}  ",
        f"**Date:** {date_str}  ",
        f"**Recipe:** {recipe_name}  ",
        "",
        "---",
        "",
        "## Executive Summary",
        "",
        summary,
        "",
        "---",
        "",
    ]

    for step_id, tool_name, state, output in step_results:
        section, _ = steps_map[step_id]
        lines.append(f"## {section}")
        lines.append("")

        if state == StepState.SUCCESS:
            lines.append("```")
            lines.append(output)
            lines.append("```")
        elif state == StepState.NOT_CONFIGURED:
            missing, note = _missing_requirements(tool_name)
            missing_str = " and ".join(missing)
            lines.append(
                f"> ℹ️ Skipped — set {missing_str} to enable this section."
            )
            if note:
                lines.append(f"> {note}")
        elif state == StepState.EMPTY:
            lines.append("> No results found.")
        else:
            lines.append(f"> ⚠ Step error: {output}")

        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def run_playbook(
    recipe: "Recipe",  # type: ignore[name-defined]  # noqa: F821
    target: str,
    is_pdf_disabled: bool = False,
    reports_dir: Path | None = None,
) -> Path:
    """
    Execute *recipe* against *target*.

    Returns the Path to the written Markdown report.  Individual step failures
    (tool errors, missing keys/binaries) are always captured in the report and
    never propagate.  Raises ``OSError`` only when the reports directory cannot
    be created or the report file cannot be written — the caller is responsible
    for handling filesystem-level errors.
    """
    from openosint.playbooks.loader import Recipe  # local import to avoid circular

    reports_path = reports_dir or Path("reports")
    try:
        reports_path.mkdir(exist_ok=True)
    except OSError as exc:
        raise OSError(
            f"Cannot create reports directory '{reports_path}': {exc}"
        ) from exc

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    date_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    safe_target = "".join(c if c.isalnum() or c in "-_." else "_" for c in target)
    md_path = reports_path / f"{date_prefix}_{safe_target}_{recipe.name}_report.md"

    steps_map: dict[str, tuple[str, str]] = {
        step.id: (step.section, step.tool) for step in recipe.steps
    }

    step_results: list[tuple[str, str, StepState, str]] = []
    for step in recipe.steps:
        logger.info("Playbook '%s': running step '%s' (%s)", recipe.name, step.id, step.tool)
        state, output = await _run_step(step.tool, target)
        step_results.append((step.id, step.tool, state, output))

    summary = _build_summary(target, recipe.target_type, step_results)
    report_md = _build_report(
        recipe_label=recipe.label,
        recipe_name=recipe.name,
        target_type=recipe.target_type,
        target=target,
        date_str=date_str,
        step_results=step_results,
        summary=summary,
        steps_map=steps_map,
    )

    try:
        md_path.write_text(report_md, encoding="utf-8")
    except OSError as exc:
        raise OSError(f"Cannot write report to '{md_path}': {exc}") from exc

    logger.info("Playbook report written: %s", md_path)

    if not is_pdf_disabled:
        try:
            from openosint.pdf_report import generate_pdf_report

            await generate_pdf_report(md_path)
        except Exception:
            logger.debug("PDF generation skipped.", exc_info=True)

    return md_path
