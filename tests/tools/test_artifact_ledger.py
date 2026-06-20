from pathlib import Path

import pytest

from tools.artifact_ledger import (
    ArtifactLedger,
    ArtifactRecord,
    ArtifactStatus,
    make_artifact_id,
    validate_artifact_record,
)


def test_artifact_ledger_records_required_fields_and_round_trips(tmp_path):
    ledger = ArtifactLedger(tmp_path / "artifacts.jsonl")
    output = tmp_path / "image.png"
    output.write_bytes(b"fake")
    record = ArtifactRecord(
        artifact_id=make_artifact_id("image_generate", "abc123", str(output)),
        source_tool="image_generate",
        input_packet_hash="abc123",
        output_path=str(output),
        verification={"exists": True, "sha256": "deadbeef"},
        status=ArtifactStatus.ACCEPTED,
        lifetime="persistent",
    )

    ledger.append(record)

    assert ledger.read_all() == [record]


def test_artifact_record_requires_tool_packet_hash_output_and_lifetime():
    record = ArtifactRecord(
        artifact_id="",
        source_tool="",
        input_packet_hash="",
        output_path=None,
        output_url=None,
        lifetime="",
    )

    assert validate_artifact_record(record) == [
        "missing_artifact_id",
        "missing_input_packet_hash",
        "missing_lifetime",
        "missing_output_reference",
        "missing_source_tool",
    ]
    with pytest.raises(ValueError, match="invalid_artifact_record"):
        ArtifactLedger(Path("/tmp/not-used.jsonl")).append(record)


def test_artifact_id_is_stable_for_same_source_packet_and_output_reference():
    assert make_artifact_id("browser_vision", "packet", "screenshot.png") == make_artifact_id(
        "browser_vision", "packet", "screenshot.png"
    )
    assert make_artifact_id("browser_vision", "packet", "a.png") != make_artifact_id(
        "browser_vision", "packet", "b.png"
    )


def test_artifact_ledger_status_helpers_update_existing_record(tmp_path):
    ledger = ArtifactLedger(tmp_path / "artifacts.jsonl")
    record = ArtifactRecord(
        artifact_id="artifact_123",
        source_tool="codex_staged_implement",
        input_packet_hash="packet-hash",
        output_url="file:///tmp/candidate.diff",
        status=ArtifactStatus.PENDING,
        lifetime="session",
    )
    ledger.append(record)

    ledger.mark("artifact_123", ArtifactStatus.REJECTED, verification={"reason": "failed tests"})

    [updated] = ledger.read_all()
    assert updated.status is ArtifactStatus.REJECTED
    assert updated.verification == {"reason": "failed tests"}


def test_artifact_ledger_refuses_unknown_status(tmp_path):
    record = ArtifactRecord(
        artifact_id="artifact_123",
        source_tool="web_extract",
        input_packet_hash="packet-hash",
        output_url="https://example.com",
        status="done",  # type: ignore[arg-type]
        lifetime="turn",
    )

    assert validate_artifact_record(record) == ["invalid_status"]
