"""Unified artifact ledger primitives.

The ledger records outputs produced by tool calls without mixing those outputs
back into model prompts as raw, unbounded context. It is intentionally small and
file-backed so future tool contracts can attach artifacts consistently.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from hermes_constants import get_hermes_home
from tools.tool_input_packet import CREDENTIAL_VALUE_RE, ToolInputPacket, packet_hash


class ArtifactStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    source_tool: str
    input_packet_hash: str
    output_path: str | None = None
    output_url: str | None = None
    verification: dict[str, Any] = field(default_factory=dict)
    status: ArtifactStatus | str = ArtifactStatus.PENDING
    lifetime: str = "session"


def make_artifact_id(source_tool: str, input_packet_hash: str, output_reference: str) -> str:
    payload = json.dumps(
        {
            "source_tool": source_tool,
            "input_packet_hash": input_packet_hash,
            "output_reference": output_reference,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "artifact_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def default_artifact_ledger_path() -> Path:
    return get_hermes_home() / "artifacts" / "ledger.jsonl"


def _coerce_status(status: ArtifactStatus | str) -> ArtifactStatus | None:
    try:
        return ArtifactStatus(status)
    except ValueError:
        return None


def validate_artifact_record(record: ArtifactRecord) -> list[str]:
    violations: list[str] = []
    if not (record.artifact_id or "").strip():
        violations.append("missing_artifact_id")
    if not (record.source_tool or "").strip():
        violations.append("missing_source_tool")
    if not (record.input_packet_hash or "").strip():
        violations.append("missing_input_packet_hash")
    if not (record.output_path or record.output_url):
        violations.append("missing_output_reference")
    if not (record.lifetime or "").strip():
        violations.append("missing_lifetime")
    if _coerce_status(record.status) is None:
        violations.append("invalid_status")
    return sorted(set(violations))


def _record_to_json_line(record: ArtifactRecord) -> str:
    status = _coerce_status(record.status)
    if status is None:
        raise ValueError("invalid_artifact_record: invalid_status")
    data = asdict(replace(record, status=status))
    data["status"] = status.value
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _record_from_json_line(line: str) -> ArtifactRecord:
    data = json.loads(line)
    data["status"] = ArtifactStatus(data.get("status", ArtifactStatus.PENDING))
    return ArtifactRecord(**data)


class ArtifactLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def append(self, record: ArtifactRecord) -> ArtifactRecord:
        violations = validate_artifact_record(record)
        if violations:
            raise ValueError("invalid_artifact_record: " + ", ".join(violations))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(_record_to_json_line(record) + "\n")
        return replace(record, status=_coerce_status(record.status) or record.status)

    def read_all(self) -> list[ArtifactRecord]:
        if not self.path.exists():
            return []
        records: list[ArtifactRecord] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(_record_from_json_line(line))
        return records

    def mark(
        self,
        artifact_id: str,
        status: ArtifactStatus,
        *,
        verification: dict[str, Any] | None = None,
    ) -> ArtifactRecord:
        records = self.read_all()
        updated: ArtifactRecord | None = None
        new_records: list[ArtifactRecord] = []
        for record in records:
            if record.artifact_id == artifact_id:
                merged_verification = dict(record.verification or {})
                if verification is not None:
                    merged_verification = dict(verification)
                record = replace(record, status=ArtifactStatus(status), verification=merged_verification)
                updated = record
            new_records.append(record)
        if updated is None:
            raise KeyError(artifact_id)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            "".join(_record_to_json_line(record) + "\n" for record in new_records),
            encoding="utf-8",
        )
        return updated


def looks_like_absolute_file_path(value: str) -> bool:
    """Return True for local absolute paths without treating URLs as files."""
    if not isinstance(value, str) or not value:
        return False
    if "://" in value:
        return False
    return Path(value).is_absolute()


RAW_HTML_RE = re.compile(r"<\s*(?:!doctype\s+html|html|body|script|iframe|style)\b", re.IGNORECASE)
DATA_URI_OR_BASE64_RE = re.compile(
    r"\bdata:[^,;]+(?:;base64)?,|\bbase64\s*,|[A-Za-z0-9+/]{80,}={0,2}",
    re.IGNORECASE,
)
URL_SECRET_RE = re.compile(
    r"(?:[?&](?:token|access_token|api_key|apikey|secret|password|signature|sig)=)[^&#\s]+|"
    r"^[a-z][a-z0-9+.-]*://[^/@\s]+:[^/@\s]+@",
    re.IGNORECASE,
)


def validate_artifact_output_reference(output_reference: str) -> list[str]:
    """Validate that an artifact reference is bounded and non-secret.

    The ledger persists pointers to artifacts, not raw artifact bytes/source or
    bearer/signed credentials embedded in those pointers.
    """
    if not isinstance(output_reference, str) or not output_reference.strip():
        return ["missing_output_reference"]
    value = output_reference.strip()
    violations: list[str] = []
    if len(value) > 2048:
        violations.append("output_reference_too_large")
    lowered = value.lower()
    if lowered.startswith("data:") or DATA_URI_OR_BASE64_RE.search(value):
        violations.append("data_uri_or_base64_output_reference")
    if lowered.startswith("file://"):
        violations.append("file_url_output_reference")
    if RAW_HTML_RE.search(value):
        violations.append("raw_html_output_reference")
    if CREDENTIAL_VALUE_RE.search(value) or URL_SECRET_RE.search(value):
        violations.append("secret_output_reference")
    parsed = urlsplit(value)
    if parsed.scheme and parsed.scheme not in {"http", "https"}:
        violations.append("unsupported_output_reference_scheme")
    return sorted(set(violations))


def record_tool_artifact(
    *,
    source_tool: str,
    native_arguments: dict[str, Any],
    output_reference: str,
    kind: str | None = None,
    lifetime: str = "persistent_or_remote",
    ledger_path: str | Path | None = None,
) -> str | None:
    """Record a generated artifact and return its stable artifact id.

    Stores only a bounded artifact reference plus verification metadata, never
    raw artifact bytes/content.
    """
    if not isinstance(output_reference, str) or not output_reference:
        return None
    if validate_artifact_output_reference(output_reference):
        return None
    packet = ToolInputPacket(
        tool_name=source_tool,
        intent=f"Record artifact output from {source_tool}",
        native_arguments=native_arguments if isinstance(native_arguments, dict) else {},
    )
    input_hash = packet_hash(packet)
    artifact_id = make_artifact_id(source_tool, input_hash, output_reference)
    is_file = looks_like_absolute_file_path(output_reference)
    verification: dict[str, Any] = {
        "exists": Path(output_reference).exists(),
    } if is_file else {"remote": True}
    if kind:
        verification["kind"] = kind
    record = ArtifactRecord(
        artifact_id=artifact_id,
        source_tool=source_tool,
        input_packet_hash=input_hash,
        output_path=output_reference if is_file else None,
        output_url=output_reference if not is_file else None,
        verification=verification,
        status=ArtifactStatus.ACCEPTED,
        lifetime=lifetime,
    )
    ArtifactLedger(ledger_path or default_artifact_ledger_path()).append(record)
    return artifact_id
