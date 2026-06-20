"""Generic native tool input packet helpers.

Hermes orchestrates many tools, but each target tool should receive only its
own native arguments plus a small, bounded intent contract. This module holds
shared validation/rendering primitives so Codex, browser, image, GitHub, and
future tools do not each reinvent transcript/size/native-argument guards.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable


HERMES_OR_SESSION_MARKERS: tuple[str, ...] = (
    "技能检查点",
    "准备执行：",
    "预计：",
    "卡住则：",
    "MEMORY (your personal notes)",
    "USER PROFILE (who the user is)",
    "Current Session Context",
    "[CONTEXT COMPACTION",
    "Conversation started:",
    "Active Hermes profile:",
    "Hermes Agent Persona",
    "<available_skills>",
    "════════",
)

RAW_DIFF_OR_PATCH_RE = re.compile(
    r"diff --git |@@|--- a/|\+\+\+ b/|(?:^|\n|\\\\n)[+-](?![+\-\s])",
    re.MULTILINE,
)
RAW_LOG_RE = re.compile(
    r"\b(raw[_-]?log|aggregated_output|stdout|stderr|traceback|exception stack)\b",
    re.IGNORECASE,
)
CREDENTIAL_VALUE_RE = re.compile(
    r"Bearer\s+[A-Za-z0-9._\-]{8,}|\b(?:sk|pk|rk)-[A-Za-z0-9._\-]{8,}\b|"
    r"\b(?:ghp|github_pat)_[A-Za-z0-9_\-]{8,}\b|"
    r"\b[A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD)\s*=\s*[^\s]+",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PacketLimits:
    max_chars: int
    max_lines: int


@dataclass(frozen=True)
class ToolInputPacket:
    """Bounded contract for invoking one native Hermes tool.

    `native_arguments` is the exact argument object intended for the target
    tool. Everything else is orchestration metadata for guards, audit, and
    bounded summaries; it is not a license to pass Hermes transcripts or
    system/memory/profile context through to the tool.
    """

    tool_name: str
    intent: str
    native_arguments: dict[str, Any]
    context_refs: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    output_contract: list[str] = field(default_factory=list)
    artifact_expectations: list[str] = field(default_factory=list)


DEFAULT_TOOL_PACKET_LIMITS = PacketLimits(max_chars=8_000, max_lines=120)


def _as_list(values: Iterable[str] | None) -> list[str]:
    if not values:
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _native_json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def validate_text_packet(
    text: str,
    *,
    limits: PacketLimits,
    too_large_code: str,
    too_many_lines_code: str,
    markers: tuple[str, ...] = HERMES_OR_SESSION_MARKERS,
) -> list[str]:
    """Return stable violation codes for bounded tool-bound text."""
    value = text or ""
    violations: list[str] = []
    if len(value) > limits.max_chars:
        violations.append(too_large_code)
    if len(value.splitlines()) > limits.max_lines:
        violations.append(too_many_lines_code)
    lowered = value.lower()
    if any(marker.lower() in lowered for marker in markers):
        violations.append("hermes_or_session_transcript_marker")
    if RAW_DIFF_OR_PATCH_RE.search(value):
        violations.append("raw_diff_or_patch_marker")
    if RAW_LOG_RE.search(value):
        violations.append("raw_log_marker")
    if CREDENTIAL_VALUE_RE.search(value):
        violations.append("secret_marker")
    return sorted(set(violations))


def _packet_text_for_validation(packet: ToolInputPacket) -> str:
    try:
        native_arguments_text = _native_json_dumps(packet.native_arguments)
    except (TypeError, ValueError):
        native_arguments_text = repr(packet.native_arguments)
    return "\n".join(
        [
            packet.tool_name or "",
            packet.intent or "",
            native_arguments_text,
            *_as_list(packet.context_refs),
            *_as_list(packet.constraints),
            *_as_list(packet.output_contract),
            *_as_list(packet.artifact_expectations),
        ]
    )


def validate_tool_input_packet(
    packet: ToolInputPacket,
    *,
    limits: PacketLimits = DEFAULT_TOOL_PACKET_LIMITS,
) -> list[str]:
    """Validate a generic native tool input packet before rendering/calling."""
    violations = validate_text_packet(
        _packet_text_for_validation(packet),
        limits=limits,
        too_large_code="tool_input_packet_too_large",
        too_many_lines_code="tool_input_packet_too_many_lines",
    )
    if not (packet.tool_name or "").strip():
        violations.append("missing_tool_name")
    if not isinstance(packet.native_arguments, dict):
        violations.append("native_arguments_not_object")
    else:
        try:
            _native_json_dumps(packet.native_arguments)
        except (TypeError, ValueError):
            violations.append("native_arguments_not_json_serializable")
    return sorted(set(violations))


def render_native_tool_args(packet: ToolInputPacket) -> dict[str, Any]:
    """Return validated native tool arguments as a defensive JSON round-trip copy."""
    violations = validate_tool_input_packet(packet)
    if violations:
        raise ValueError("unsafe_tool_input_packet: " + ", ".join(violations))
    return json.loads(_native_json_dumps(packet.native_arguments))


def packet_hash(packet: ToolInputPacket) -> str:
    """Stable hash suitable for future artifact-ledger correlation."""
    payload = _native_json_dumps(asdict(packet))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
