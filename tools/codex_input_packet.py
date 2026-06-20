"""Shared Codex input packet validation and rendering.

Codex CLI accepts initial instructions plus execution flags / cwd / AGENTS.md.
Hermes should therefore normalize its higher-level intent into a small structured
packet, validate it, then render a concise prompt/goal string. This module keeps
Hermes transcript and prompt-size policy in one place instead of duplicating it
across every Codex entry point.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from tools.tool_input_packet import (
    HERMES_OR_SESSION_MARKERS,
    PacketLimits,
    ToolInputPacket,
    validate_text_packet,
)


DEFAULT_EXEC_PACKET_LIMITS = PacketLimits(max_chars=6_000, max_lines=80)
DEFAULT_GOAL_PACKET_LIMITS = PacketLimits(max_chars=4_000, max_lines=20)


@dataclass(frozen=True)
class CodexInputPacket:
    objective: str
    workdir: str | None = None
    docs_to_read: list[str] = field(default_factory=list)
    allowed_files: list[str] = field(default_factory=list)
    allowed_globs: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    verification: list[str] = field(default_factory=list)
    stop_conditions: list[str] = field(default_factory=list)
    output_contract: list[str] = field(default_factory=list)


def _as_list(values: Iterable[str] | None) -> list[str]:
    if not values:
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _validate_packet_fields(packet: CodexInputPacket, *, limits: PacketLimits) -> list[str]:
    text = "\n".join(
        [
            packet.objective or "",
            packet.workdir or "",
            *_as_list(packet.docs_to_read),
            *_as_list(packet.allowed_files),
            *_as_list(packet.allowed_globs),
            *_as_list(packet.constraints),
            *_as_list(packet.verification),
            *_as_list(packet.stop_conditions),
            *_as_list(packet.output_contract),
        ]
    )
    return validate_text_packet(
        text,
        limits=limits,
        too_large_code="codex_input_packet_too_large",
        too_many_lines_code="codex_input_packet_too_many_lines",
    )


def validate_codex_input_packet(packet: CodexInputPacket, *, limits: PacketLimits = DEFAULT_EXEC_PACKET_LIMITS) -> list[str]:
    """Validate a structured Codex packet before rendering."""
    violations = _validate_packet_fields(packet, limits=limits)
    if not (packet.objective or "").strip():
        violations.append("missing_objective")
    return sorted(set(violations))


def _append_section(lines: list[str], title: str, value: str | None = None, values: list[str] | None = None) -> None:
    if value is not None and value.strip():
        lines.extend([f"{title}:", value.strip(), ""])
        return
    cleaned = _as_list(values)
    if cleaned:
        lines.append(f"{title}:")
        lines.extend(f"- {item}" for item in cleaned)
        lines.append("")


def render_codex_exec_prompt(packet: CodexInputPacket) -> str:
    """Render a minimal Codex `exec` initial-instructions prompt."""
    violations = validate_codex_input_packet(packet)
    if violations:
        raise ValueError("unsafe_codex_input_packet: " + ", ".join(violations))

    lines: list[str] = []
    _append_section(lines, "Objective", packet.objective)
    _append_section(lines, "Workdir", packet.workdir)
    _append_section(lines, "Read first", values=packet.docs_to_read)
    _append_section(lines, "Allowed files", values=packet.allowed_files)
    _append_section(lines, "Allowed globs", values=packet.allowed_globs)
    _append_section(lines, "Constraints", values=packet.constraints)
    _append_section(lines, "Verification", values=packet.verification)
    _append_section(lines, "Stop conditions", values=packet.stop_conditions)
    _append_section(lines, "Output contract", values=packet.output_contract)
    return "\n".join(lines).rstrip() + "\n"


def render_goal_text(packet: CodexInputPacket) -> str:
    """Render a short official Codex TUI `/goal` command."""
    violations = validate_codex_input_packet(packet, limits=DEFAULT_GOAL_PACKET_LIMITS)
    if violations:
        raise ValueError("unsafe_codex_goal_packet: " + ", ".join(violations))

    parts = [packet.objective.strip()]
    if packet.allowed_files:
        parts.append("Allowed files: " + ", ".join(_as_list(packet.allowed_files)))
    if packet.allowed_globs:
        parts.append("Allowed globs: " + ", ".join(_as_list(packet.allowed_globs)))
    if packet.verification:
        parts.append("Verify: " + "; ".join(_as_list(packet.verification)))
    if packet.stop_conditions:
        parts.append("Stop: " + "; ".join(_as_list(packet.stop_conditions)))
    if packet.constraints:
        parts.append("Constraints: " + "; ".join(_as_list(packet.constraints)))
    return "/goal " + " ".join(parts).strip()
