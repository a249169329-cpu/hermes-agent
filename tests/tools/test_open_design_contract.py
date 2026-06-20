import json

from tools.artifact_ledger import ArtifactLedger, default_artifact_ledger_path


def test_open_design_input_packet_rejects_hermes_context_markers():
    from tools.open_design_contract import OpenDesignInputPacket, validate_open_design_input_packet

    packet = OpenDesignInputPacket(
        objective="Build a landing page",
        design_brief="MEMORY (your personal notes) must not be sent to OD",
        project_id="proj_1",
    )

    violations = validate_open_design_input_packet(packet)

    assert "hermes_or_session_transcript_marker" in violations


def test_open_design_output_envelope_rejects_raw_html_payload():
    from tools.open_design_contract import OpenDesignOutputEnvelope, validate_open_design_output_envelope

    envelope = OpenDesignOutputEnvelope(
        project_id="proj_1",
        run_id="run_1",
        summary="ok",
        output_url="https://open.yumeapi.cn/runs/run_1",
        raw_html="<html><body>raw artifact must not enter model context</body></html>",
    )

    violations = validate_open_design_output_envelope(envelope)

    assert "raw_html_output" in violations


def test_open_design_output_envelope_records_artifact_reference(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    from tools.open_design_contract import OpenDesignInputPacket, OpenDesignOutputEnvelope, record_open_design_artifact

    packet = OpenDesignInputPacket(
        objective="Design a dashboard",
        design_brief="Use the confirmed blue visual direction",
        project_id="proj_1",
    )
    envelope = OpenDesignOutputEnvelope(
        project_id="proj_1",
        run_id="run_1",
        summary="Generated dashboard direction",
        output_url="https://open.yumeapi.cn/runs/run_1",
    )

    artifact_id = record_open_design_artifact(packet, envelope)

    assert artifact_id.startswith("artifact_")
    assert envelope.artifact_id == artifact_id
    records = ArtifactLedger(default_artifact_ledger_path()).read_all()
    assert len(records) == 1
    [record] = records
    assert record.artifact_id == artifact_id
    assert record.source_tool == "open_design"
    assert record.output_url == "https://open.yumeapi.cn/runs/run_1"
    assert record.lifetime == "persistent_or_remote"


def test_open_design_output_envelope_serializes_bounded_model_payload():
    from tools.open_design_contract import OpenDesignOutputEnvelope, render_open_design_output_for_model

    envelope = OpenDesignOutputEnvelope(
        project_id="proj_1",
        run_id="run_1",
        summary="Generated direction",
        output_url="https://open.yumeapi.cn/runs/run_1",
        artifact_id="artifact_abc",
    )

    payload = json.loads(render_open_design_output_for_model(envelope))

    assert payload == {
        "success": True,
        "project_id": "proj_1",
        "run_id": "run_1",
        "summary": "Generated direction",
        "output_url": "https://open.yumeapi.cn/runs/run_1",
        "artifact_id": "artifact_abc",
    }


def test_open_design_input_rejects_raw_html_and_data_uri():
    from tools.open_design_contract import OpenDesignInputPacket, validate_open_design_input_packet

    packet = OpenDesignInputPacket(
        objective="Create page",
        design_brief="<html><body>raw source</body></html>",
        allowed_assets=["data:image/png;base64,AAAA"],
    )

    violations = validate_open_design_input_packet(packet)

    assert "raw_html_input" in violations
    assert "data_uri_or_base64_input" in violations


def test_open_design_output_rejects_raw_summary_and_data_uri_reference():
    from tools.open_design_contract import (
        OpenDesignOutputEnvelope,
        render_open_design_output_for_model,
        validate_open_design_output_envelope,
    )

    envelope = OpenDesignOutputEnvelope(
        project_id="project-1",
        run_id="run-1",
        summary="<html><body>raw source</body></html>",
        output_url="data:text/html;base64,PGh0bWw+PC9odG1sPg==",
    )

    violations = validate_open_design_output_envelope(envelope)
    result = json.loads(render_open_design_output_for_model(envelope))

    assert "raw_html_output" in violations
    assert "data_uri_or_base64_output" in violations
    assert result["success"] is False
    assert result["status"] == "rejected_open_design_output"
