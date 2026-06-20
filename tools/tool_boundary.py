"""Runtime boundary checks for model-authored tool inputs.

This module is intentionally separate from model-facing tool schemas.  It uses
registry metadata at dispatch time so Hermes can enforce common safety rules
without expanding the prompt-cached tool definitions sent to the model.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from tools.registry import ToolEntry, registry
from tools.tool_input_packet import (
    ToolInputPacket,
    validate_tool_input_packet,
)

logger = logging.getLogger(__name__)

# First-slice default: guard tools that send model-authored text or media to
# external providers / platforms.  Local shell/file tools keep their specialist
# approval and path/diff handling because raw patches/logs can be legitimate
# native input there.
_GUARDED_RISKS = {
    "external_api_call",
}
_GUARDED_CLASSES = {
    "external_web_read",
    "external_message_send",
    "external_mcp_tool",
    "generate_media",
    "generate_audio",
    "analyze_media",
    "codex_candidate_workflow",
    "codex_goal_workflow",
    "spawn_subagent",
}


def _entry_for(tool_name: str) -> ToolEntry | None:
    try:
        return registry.get_entry(tool_name)
    except Exception:
        return None


def should_guard_tool_input(entry: ToolEntry | None) -> bool:
    """Return True when common text-boundary checks should run for a tool."""
    if entry is None:
        return False
    side_effects = entry.side_effects if isinstance(entry.side_effects, dict) else {}
    effect_class = str(side_effects.get("class") or "")
    risk = str(side_effects.get("risk") or "")
    if effect_class in _GUARDED_CLASSES or risk in _GUARDED_RISKS:
        return True
    toolset = str(getattr(entry, "toolset", "") or "")
    if toolset.startswith("mcp-") or toolset in {"mcp"}:
        return True
    return False


def build_tool_input_packet(tool_name: str, args: dict[str, Any]) -> ToolInputPacket:
    """Build the minimal generic packet for a native Hermes tool call."""
    return ToolInputPacket(
        tool_name=tool_name,
        intent=f"Invoke native Hermes tool {tool_name} with model-authored arguments.",
        native_arguments=args,
    )


def reject_tool_input_payload(tool_name: str, violations: list[str]) -> str:
    """Return a stable JSON rejection payload for unsafe model-authored input."""
    return json.dumps(
        {
            "error": "Unsafe tool input packet rejected before tool dispatch",
            "status": "rejected_tool_input_packet",
            "reason": "unsafe_tool_input_packet",
            "tool_name": tool_name,
            "tool_input_violations": sorted(set(violations)),
        },
        ensure_ascii=False,
    )


def guard_tool_input(tool_name: str, args: dict[str, Any]) -> str | None:
    """Return a rejection JSON string when a guarded tool input is unsafe.

    ``None`` means the tool may proceed unchanged.
    """
    entry = _entry_for(tool_name)
    if not should_guard_tool_input(entry):
        return None
    packet = build_tool_input_packet(tool_name, args if isinstance(args, dict) else {})
    violations = validate_tool_input_packet(packet)
    if not violations:
        return None
    logger.warning("Tool input boundary rejected %s: %s", tool_name, violations)
    return reject_tool_input_payload(tool_name, violations)
