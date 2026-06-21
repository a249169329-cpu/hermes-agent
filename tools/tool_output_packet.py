"""Bounded tool output packet helpers.

Tool handlers can produce very different native results.  This module provides a
small common envelope for what is allowed back into the model context: bounded
summary, artifact references, and compact provider metadata rather than raw
artifacts/logs/source dumps.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from tools.artifact_ledger import validate_artifact_output_reference
from tools.tool_input_packet import DEFAULT_TOOL_PACKET_LIMITS, PacketLimits, validate_text_packet
from tools.tool_output_guard import sanitize_tool_result_for_model


@dataclass(frozen=True)
class ToolOutputPacket:
    tool_name: str
    tool_class: str
    success: bool
    summary: str
    artifact_ids: list[str] = field(default_factory=list)
    output_references: list[str] = field(default_factory=list)
    bounded_payload: dict[str, Any] = field(default_factory=dict)
    provider_metadata_summary: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


DEFAULT_TOOL_OUTPUT_LIMITS = PacketLimits(max_chars=8_000, max_lines=120)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _packet_text_for_validation(packet: ToolOutputPacket) -> str:
    try:
        payload_text = _json_dumps(
            {
                "summary": packet.summary,
                "bounded_payload": packet.bounded_payload,
                "provider_metadata_summary": packet.provider_metadata_summary,
                "warnings": packet.warnings,
                "output_references": packet.output_references,
                "artifact_ids": packet.artifact_ids,
            }
        )
    except (TypeError, ValueError):
        payload_text = repr(packet)
    return "\n".join([packet.tool_name or "", packet.tool_class or "", payload_text])


def validate_tool_output_packet(
    packet: ToolOutputPacket,
    *,
    limits: PacketLimits = DEFAULT_TOOL_OUTPUT_LIMITS,
) -> list[str]:
    violations = validate_text_packet(
        _packet_text_for_validation(packet),
        limits=limits,
        too_large_code="tool_output_packet_too_large",
        too_many_lines_code="tool_output_packet_too_many_lines",
    )
    if not (packet.tool_name or "").strip():
        violations.append("missing_tool_name")
    if not (packet.tool_class or "").strip():
        violations.append("missing_tool_class")
    if not isinstance(packet.success, bool):
        violations.append("success_not_bool")
    try:
        _json_dumps(packet.bounded_payload)
        _json_dumps(packet.provider_metadata_summary)
    except (TypeError, ValueError):
        violations.append("tool_output_packet_not_json_serializable")
    for reference in packet.output_references:
        for violation in validate_artifact_output_reference(reference):
            violations.append(f"output_reference_{violation}")
    return sorted(set(violations))


def _compact_model_payload(packet: ToolOutputPacket) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "success": packet.success,
        "tool_name": packet.tool_name,
        "tool_class": packet.tool_class,
        "summary": packet.summary,
    }
    if packet.artifact_ids:
        payload["artifact_ids"] = list(packet.artifact_ids)
    if packet.output_references:
        payload["output_references"] = list(packet.output_references)
    if packet.bounded_payload:
        payload["bounded_payload"] = dict(packet.bounded_payload)
        if isinstance(packet.bounded_payload, dict):
            if "data" in packet.bounded_payload and "data" not in payload:
                payload["data"] = packet.bounded_payload["data"]
            if "results" in packet.bounded_payload and "results" not in payload:
                payload["results"] = packet.bounded_payload["results"]
            if "error" in packet.bounded_payload and "error" not in payload:
                payload["error"] = packet.bounded_payload["error"]
    if packet.provider_metadata_summary:
        payload["provider_metadata_summary"] = dict(packet.provider_metadata_summary)
    if packet.warnings:
        payload["warnings"] = list(packet.warnings)
    return payload


def render_tool_output_packet_for_model(packet: ToolOutputPacket) -> str:
    """Render a compact JSON envelope after applying the shared output guard."""
    payload = _compact_model_payload(packet)
    rendered = json.dumps(payload, ensure_ascii=False)
    sanitized = sanitize_tool_result_for_model(packet.tool_name, rendered)
    if isinstance(sanitized, str):
        return sanitized
    return json.dumps(sanitized, ensure_ascii=False)
