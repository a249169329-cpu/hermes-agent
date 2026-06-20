"""Tool-class adapter registry.

This is the narrow waist between generic ToolInputPacket/ToolOutputPacket guards
and per-class tool contracts (Codex, OD, image, video, TTS, browser, web,
messaging, MCP, ...).  The first slice is intentionally small: infer a class
from registry metadata, expose class policies, and provide common input/output
validation hooks without migrating every concrete tool at once.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from tools.registry import ToolEntry
from tools.tool_input_packet import ToolInputPacket, validate_tool_input_packet
from tools.tool_output_packet import ToolOutputPacket, render_tool_output_packet_for_model

_RUNTIME_ONLY_ARGUMENTS = {
    "runtime_authorization",
    "approved",
    "approval",
    "permission_tier",
    "user_approved",
}


@dataclass(frozen=True)
class RuntimePolicy:
    requires_runtime_authorization: bool = False
    requires_artifact_ledger: bool = False
    may_access_network: bool = False
    may_modify_remote_state: bool = False
    fail_closed: bool = False
    cost_sensitive: bool = False


@dataclass(frozen=True)
class OutputPolicy:
    max_chars: int = 8_000
    artifact_reference_only: bool = False
    summary_required: bool = True


@dataclass(frozen=True)
class ToolClassAdapter:
    tool_class: str
    input_fields: tuple[str, ...] = ()
    output_fields: tuple[str, ...] = ()
    runtime_policy: RuntimePolicy = field(default_factory=RuntimePolicy)
    output_policy: OutputPolicy = field(default_factory=OutputPolicy)
    artifact_policy: str = "bounded_payload"

    def validate_input(self, packet: ToolInputPacket) -> list[str]:
        violations = validate_tool_input_packet(packet)
        native_arguments = packet.native_arguments if isinstance(packet.native_arguments, dict) else {}
        for key in _RUNTIME_ONLY_ARGUMENTS:
            if key in native_arguments:
                violations.append(f"model_supplied_{key}")
        return sorted(set(violations))

    def render_output(self, packet: ToolOutputPacket) -> str:
        if packet.tool_class != self.tool_class:
            packet = replace(packet, tool_class=self.tool_class)
        return render_tool_output_packet_for_model(packet)


_TOOL_CLASS_ADAPTERS: dict[str, ToolClassAdapter] = {
    "codex": ToolClassAdapter(
        tool_class="codex",
        input_fields=("objective", "workdir", "allowed_files", "docs_to_read", "verification", "stop_conditions", "output_contract"),
        output_fields=("touched_files", "summary", "tests_run", "candidate_status", "review_needed"),
        runtime_policy=RuntimePolicy(may_modify_remote_state=True),
    ),
    "od": ToolClassAdapter(
        tool_class="od",
        input_fields=("design_brief", "style_constraints", "allowed_assets", "target_format", "output_size", "acceptance_criteria"),
        output_fields=("project_id", "run_id", "html_path", "screenshot_path", "preview_url", "summary", "artifact_id"),
        runtime_policy=RuntimePolicy(requires_artifact_ledger=True, may_access_network=True, cost_sensitive=True),
        output_policy=OutputPolicy(artifact_reference_only=True),
        artifact_policy="artifact_reference_only",
    ),
    "image": ToolClassAdapter(
        tool_class="image",
        input_fields=("prompt", "aspect_ratio", "reference_image_path", "style_constraints"),
        output_fields=("image_path", "image_url", "artifact_id", "provider_metadata_summary"),
        runtime_policy=RuntimePolicy(requires_artifact_ledger=True, may_access_network=True, cost_sensitive=True),
        output_policy=OutputPolicy(artifact_reference_only=True),
        artifact_policy="artifact_reference_only",
    ),
    "video": ToolClassAdapter(
        tool_class="video",
        input_fields=("prompt", "duration", "resolution", "reference_assets", "style_constraints", "cost_limit"),
        output_fields=("video_path", "preview_path", "artifact_id", "duration", "provider_job_id"),
        runtime_policy=RuntimePolicy(requires_artifact_ledger=True, may_access_network=True, cost_sensitive=True),
        output_policy=OutputPolicy(artifact_reference_only=True),
        artifact_policy="artifact_reference_only",
    ),
    "tts": ToolClassAdapter(
        tool_class="tts",
        input_fields=("text", "voice", "format", "speed"),
        output_fields=("audio_path", "duration", "artifact_id"),
        runtime_policy=RuntimePolicy(requires_artifact_ledger=True, may_access_network=True, cost_sensitive=True),
        output_policy=OutputPolicy(artifact_reference_only=True),
        artifact_policy="artifact_reference_only",
    ),
    "browser": ToolClassAdapter(
        tool_class="browser",
        input_fields=("url", "action", "selector", "ref", "allowed_hosts"),
        output_fields=("snapshot_summary", "screenshot_path", "console_summary"),
        runtime_policy=RuntimePolicy(may_access_network=True),
        output_policy=OutputPolicy(max_chars=6_000, artifact_reference_only=True),
        artifact_policy="bounded_snapshot_or_artifact_reference",
    ),
    "messaging": ToolClassAdapter(
        tool_class="messaging",
        input_fields=("target", "message", "attachments", "delivery_mode"),
        output_fields=("message_id", "platform", "delivered_status"),
        runtime_policy=RuntimePolicy(requires_runtime_authorization=True, may_modify_remote_state=True),
    ),
    "web": ToolClassAdapter(
        tool_class="web",
        input_fields=("query", "url", "limit"),
        output_fields=("title", "url", "snippet", "summary"),
        runtime_policy=RuntimePolicy(may_access_network=True),
        output_policy=OutputPolicy(max_chars=6_000),
    ),
    "mcp": ToolClassAdapter(
        tool_class="mcp",
        input_fields=("server_name", "tool_name", "declared_side_effect", "input_schema", "output_schema", "artifact_policy", "approval_policy"),
        output_fields=("summary", "artifact_id", "bounded_payload"),
        runtime_policy=RuntimePolicy(may_access_network=True, fail_closed=True),
        output_policy=OutputPolicy(max_chars=4_000),
    ),
    "unknown": ToolClassAdapter(
        tool_class="unknown",
        runtime_policy=RuntimePolicy(fail_closed=True),
        output_policy=OutputPolicy(max_chars=4_000),
        artifact_policy="summary_only",
    ),
}


def get_tool_class_adapter(tool_class: str) -> ToolClassAdapter:
    return _TOOL_CLASS_ADAPTERS.get(tool_class, _TOOL_CLASS_ADAPTERS["unknown"])


def _artifact_kinds(entry: ToolEntry) -> set[str]:
    kinds: set[str] = set()
    for item in entry.artifact_outputs or []:
        if isinstance(item, dict) and item.get("kind"):
            kinds.add(str(item["kind"]).lower())
        elif item:
            kinds.add(str(item).lower())
    return kinds


def infer_tool_class(entry: ToolEntry) -> str:
    name = (entry.name or "").lower()
    toolset = (entry.toolset or "").lower()
    side_effects = entry.side_effects if isinstance(entry.side_effects, dict) else {}
    effect_class = str(side_effects.get("class") or "").lower()
    artifacts = _artifact_kinds(entry)

    if toolset.startswith("mcp-") or effect_class in {"external_mcp_tool", "mcp_utility"}:
        return "mcp"
    if "codex" in name or "codex" in toolset:
        return "codex"
    if name.startswith("open_design") or "open_design" in name or toolset in {"open_design", "od"}:
        return "od"
    if toolset in {"image_gen", "image"} or "image" in artifacts or effect_class == "generate_media":
        return "image"
    if toolset == "video" or "video" in artifacts or name.startswith("video_"):
        return "video"
    if toolset == "tts" or "audio" in artifacts or name in {"text_to_speech"}:
        return "tts"
    if toolset == "browser" or name.startswith("browser_"):
        return "browser"
    if toolset in {"messaging", "communication", "cronjob", "homeassistant", "spotify"}:
        return "messaging"
    if effect_class in {"external_message_send", "external_messaging", "manage_schedule", "smart_home_control", "spotify_control"}:
        return "messaging"
    if toolset in {"web", "search"} or name in {"web_search", "web_extract"}:
        return "web"
    return "unknown"


def resolve_tool_class_adapter(entry: ToolEntry) -> ToolClassAdapter:
    adapter = get_tool_class_adapter(infer_tool_class(entry))
    if entry.artifact_outputs and not adapter.runtime_policy.requires_artifact_ledger:
        return replace(
            adapter,
            runtime_policy=replace(adapter.runtime_policy, requires_artifact_ledger=True),
            output_policy=replace(adapter.output_policy, artifact_reference_only=True),
            artifact_policy="artifact_reference_only",
        )
    side_effects = entry.side_effects if isinstance(entry.side_effects, dict) else {}
    if side_effects.get("may_modify_remote_state") and not adapter.runtime_policy.may_modify_remote_state:
        return replace(
            adapter,
            runtime_policy=replace(adapter.runtime_policy, may_modify_remote_state=True),
        )
    return adapter
