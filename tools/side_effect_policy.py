"""Runtime-only side-effect authorization for high-risk tools.

The model-facing schemas must not contain approval fields.  This module is used
from the dispatcher with out-of-band runtime authorization metadata supplied by
Hermes/UI/gateway code, not by model-authored tool arguments.
"""

from __future__ import annotations

import json
from typing import Any

from tools.registry import ToolEntry, registry


_RUNTIME_AUTH_CLASSES = {
    "external_message_send",
    "external_messaging",
    "yuanbao_message_send",
    "manage_schedule",
    "smart_home_control",
    "external_mcp_tool",
    "spotify_control",
}
_RUNTIME_AUTH_RISKS = {
    "physical_world_action",
    "scheduled_side_effect",
    "delegated_external_tool",
}
_RUNTIME_AUTH_FLAGS = {
    "may_send_messages",
    "may_deliver_messages",
    "may_schedule_jobs",
    "may_modify_remote_state",
    "may_control_playback",
}
_CRON_MUTATING_ACTIONS = {
    "create",
    "update",
    "pause",
    "resume",
    "remove",
    "run",
}
_SPOTIFY_MUTATING_ACTIONS_BY_TOOL = {
    "spotify_playback": {
        "play",
        "pause",
        "next",
        "previous",
        "seek",
        "set_repeat",
        "set_shuffle",
        "set_volume",
    },
    "spotify_devices": {"transfer"},
    "spotify_queue": {"add"},
    "spotify_playlists": {"create", "add_items", "remove_items", "update_details"},
    "spotify_library": {"save", "remove"},
}


def _entry_for(tool_name: str) -> ToolEntry | None:
    try:
        return registry.get_entry(tool_name)
    except Exception:
        return None


def _side_effect_class(entry: ToolEntry | None) -> str:
    side_effects = entry.side_effects if entry and isinstance(entry.side_effects, dict) else {}
    return str(side_effects.get("class") or "")


def requires_runtime_authorization(tool_name: str, args: dict[str, Any] | None = None) -> bool:
    """Return True when a tool call needs out-of-band runtime authorization."""
    entry = _entry_for(tool_name)
    if entry is None:
        # Dynamic MCP tools may be registered under server-specific toolsets;
        # unknown tools are rejected elsewhere.
        return False
    side_effects = entry.side_effects if isinstance(entry.side_effects, dict) else {}
    effect_class = str(side_effects.get("class") or "")
    risk = str(side_effects.get("risk") or "")
    toolset = str(getattr(entry, "toolset", "") or "")

    # Read-only cron/list-like actions are inspectable; persistent mutations
    # must have runtime approval.
    if effect_class == "manage_schedule":
        action = str((args or {}).get("action") or "").strip().lower()
        return action in _CRON_MUTATING_ACTIONS

    if effect_class == "spotify_control":
        action = str((args or {}).get("action") or "").strip().lower()
        return action in _SPOTIFY_MUTATING_ACTIONS_BY_TOOL.get(tool_name, set())

    if effect_class == "external_mcp_tool":
        return bool(side_effects.get("may_modify_remote_state")) or risk in _RUNTIME_AUTH_RISKS

    if effect_class in _RUNTIME_AUTH_CLASSES or risk in _RUNTIME_AUTH_RISKS:
        return True
    if any(bool(side_effects.get(flag)) for flag in _RUNTIME_AUTH_FLAGS):
        return True
    if toolset.startswith("mcp-") and side_effects.get("may_modify_remote_state"):
        return True
    return False


def runtime_authorization_allows(
    tool_name: str,
    side_effect_class: str,
    runtime_authorization: dict[str, Any] | None,
    *,
    tool_call_id: str | None = None,
) -> bool:
    """Validate out-of-band runtime authorization.

    The authorization object is intentionally small and permissive for this
    first slice: approved=true plus a scope matching either the tool name,
    side-effect class, or wildcard.  A mismatched tool_call_id fails closed.
    """
    if not isinstance(runtime_authorization, dict):
        return False
    if runtime_authorization.get("approved") is not True:
        return False
    auth_call_id = runtime_authorization.get("tool_call_id")
    if auth_call_id and tool_call_id and auth_call_id != tool_call_id:
        return False
    raw_scope = runtime_authorization.get("scope") or []
    if isinstance(raw_scope, str):
        scope = {raw_scope}
    elif isinstance(raw_scope, (list, tuple, set)):
        scope = {str(item) for item in raw_scope}
    else:
        scope = set()
    return "*" in scope or tool_name in scope or side_effect_class in scope


def reject_side_effect_payload(tool_name: str, side_effect_class: str) -> str:
    return json.dumps(
        {
            "error": "Runtime authorization required for side-effecting tool call",
            "status": "rejected_side_effect_policy",
            "reason": "runtime_authorization_required",
            "tool_name": tool_name,
            "side_effect_class": side_effect_class,
        },
        ensure_ascii=False,
    )


def guard_side_effect_policy(
    tool_name: str,
    args: dict[str, Any] | None,
    *,
    runtime_authorization: dict[str, Any] | None = None,
    tool_call_id: str | None = None,
) -> str | None:
    """Return rejection JSON when a side-effecting tool lacks runtime auth."""
    if not requires_runtime_authorization(tool_name, args):
        return None
    side_effect_class = _side_effect_class(_entry_for(tool_name))
    if runtime_authorization_allows(
        tool_name,
        side_effect_class,
        runtime_authorization,
        tool_call_id=tool_call_id,
    ):
        return None
    return reject_side_effect_payload(tool_name, side_effect_class)
