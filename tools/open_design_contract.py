"""Open Design adapter contracts.

These primitives keep Open Design sidecar calls on the same governance model as
other external/AI tools: structured input, bounded output envelope, and artifact
ledger references instead of raw HTML/source flowing back into model context.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from tools.artifact_ledger import (
    RAW_HTML_RE,
    DATA_URI_OR_BASE64_RE,
    record_tool_artifact,
    validate_artifact_output_reference,
)
from tools.tool_input_packet import CREDENTIAL_VALUE_RE, ToolInputPacket, validate_tool_input_packet


@dataclass
class OpenDesignInputPacket:
    objective: str
    design_brief: str
    project_id: str | None = None
    run_id: str | None = None
    allowed_assets: list[str] | None = None
    constraints: list[str] | None = None

    def to_tool_input_packet(self) -> ToolInputPacket:
        native_arguments: dict[str, Any] = {
            "objective": self.objective,
            "design_brief": self.design_brief,
        }
        if self.project_id:
            native_arguments["project_id"] = self.project_id
        if self.run_id:
            native_arguments["run_id"] = self.run_id
        if self.allowed_assets:
            native_arguments["allowed_assets"] = list(self.allowed_assets)
        if self.constraints:
            native_arguments["constraints"] = list(self.constraints)
        return ToolInputPacket(
            tool_name="open_design",
            intent="Run an Open Design sidecar task with a bounded design brief.",
            native_arguments=native_arguments,
        )


@dataclass
class OpenDesignOutputEnvelope:
    project_id: str
    run_id: str
    summary: str
    output_url: str | None = None
    output_path: str | None = None
    artifact_id: str | None = None
    raw_html: str | None = None
    raw_source: str | None = None


def _validate_open_design_text(value: str, *, suffix: str) -> list[str]:
    violations: list[str] = []
    text = value or ""
    if RAW_HTML_RE.search(text):
        violations.append(f"raw_html_{suffix}")
    if DATA_URI_OR_BASE64_RE.search(text):
        violations.append(f"data_uri_or_base64_{suffix}")
    if CREDENTIAL_VALUE_RE.search(text):
        violations.append(f"secret_{suffix}")
    return violations


def validate_open_design_input_packet(packet: OpenDesignInputPacket) -> list[str]:
    violations: list[str] = []
    if not (packet.objective or "").strip():
        violations.append("missing_objective")
    if not (packet.design_brief or "").strip():
        violations.append("missing_design_brief")
    violations.extend(validate_tool_input_packet(packet.to_tool_input_packet()))
    violations.extend(_validate_open_design_text(packet.objective, suffix="input"))
    violations.extend(_validate_open_design_text(packet.design_brief, suffix="input"))
    for value in packet.allowed_assets or []:
        violations.extend(_validate_open_design_text(value, suffix="input"))
    for value in packet.constraints or []:
        violations.extend(_validate_open_design_text(value, suffix="input"))
    return sorted(set(violations))


def validate_open_design_output_envelope(envelope: OpenDesignOutputEnvelope) -> list[str]:
    violations: list[str] = []
    if not (envelope.project_id or "").strip():
        violations.append("missing_project_id")
    if not (envelope.run_id or "").strip():
        violations.append("missing_run_id")
    if not (envelope.summary or "").strip():
        violations.append("missing_summary")
    if not (envelope.output_url or envelope.output_path):
        violations.append("missing_output_reference")
    violations.extend(_validate_open_design_text(envelope.summary, suffix="output"))
    if envelope.output_url:
        violations.extend(validate_artifact_output_reference(envelope.output_url))
    if envelope.output_path:
        violations.extend(validate_artifact_output_reference(envelope.output_path))
    if envelope.raw_html:
        violations.append("raw_html_output")
    if envelope.raw_source:
        violations.append("raw_source_output")
    # Preserve the OD-specific public violation name expected by callers/tests.
    if "data_uri_or_base64_output_reference" in violations:
        violations.append("data_uri_or_base64_output")
    return sorted(set(violations))


def record_open_design_artifact(
    packet: OpenDesignInputPacket,
    envelope: OpenDesignOutputEnvelope,
) -> str:
    violations = validate_open_design_input_packet(packet) + validate_open_design_output_envelope(envelope)
    # raw_html/raw_source are invalid for model-facing envelope, but should not
    # block ledger recording when callers explicitly use this helper for a
    # bounded URL/path reference. Missing references still must fail.
    hard_violations = [
        item for item in violations
        if item not in {"raw_html_output", "raw_source_output"}
    ]
    if hard_violations:
        raise ValueError("invalid_open_design_contract: " + ", ".join(sorted(set(hard_violations))))
    output_reference = envelope.output_url or envelope.output_path or ""
    artifact_id = record_tool_artifact(
        source_tool="open_design",
        native_arguments=packet.to_tool_input_packet().native_arguments,
        output_reference=output_reference,
        kind="open_design_run",
        lifetime="persistent_or_remote",
    )
    if not artifact_id:
        raise ValueError("invalid_open_design_contract: missing_output_reference")
    envelope.artifact_id = artifact_id
    return artifact_id


def render_open_design_output_for_model(envelope: OpenDesignOutputEnvelope) -> str:
    violations = validate_open_design_output_envelope(envelope)
    if violations:
        return json.dumps(
            {
                "success": False,
                "status": "rejected_open_design_output",
                "reason": "invalid_open_design_output_envelope",
                "violations": violations,
            },
            ensure_ascii=False,
        )
    payload = {
        "success": True,
        "project_id": envelope.project_id,
        "run_id": envelope.run_id,
        "summary": envelope.summary,
    }
    if envelope.output_url:
        payload["output_url"] = envelope.output_url
    if envelope.output_path:
        payload["output_path"] = envelope.output_path
    if envelope.artifact_id:
        payload["artifact_id"] = envelope.artifact_id
    return json.dumps(payload, ensure_ascii=False)
