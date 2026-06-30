import asyncio
import base64
import json


_TINY_PNG = base64.b64decode(
    b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


def test_vision_analyze_records_analysis_artifact_without_raw_image(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    from tools import vision_tools
    from tools.artifact_ledger import ArtifactLedger, default_artifact_ledger_path

    img = tmp_path / "input.png"
    img.write_bytes(_TINY_PNG)

    class _Message:
        content = "A small transparent pixel."

    class _Choice:
        message = _Message()

    class _Response:
        choices = [_Choice()]

    async def fake_call_llm(**_kwargs):
        return _Response()

    monkeypatch.setattr(vision_tools, "async_call_llm", fake_call_llm)

    result = json.loads(asyncio.get_event_loop().run_until_complete(
        vision_tools.vision_analyze_tool(str(img), "describe")
    ))

    assert result["success"] is True
    assert result["artifact_id"].startswith("artifact_")
    assert "analysis_artifact_path" in result

    analysis_file = result["analysis_artifact_path"]
    assert analysis_file.endswith(".json")
    from pathlib import Path
    assert Path(analysis_file).exists()
    analysis_payload = json.loads(Path(analysis_file).read_text(encoding="utf-8"))
    assert analysis_payload["analysis"] == "A small transparent pixel."
    analysis_dump = json.dumps(analysis_payload, ensure_ascii=False)
    assert "data:image" not in analysis_dump
    assert "iVBOR" not in analysis_dump

    records = ArtifactLedger(default_artifact_ledger_path()).read_all()
    assert len(records) == 1
    [record] = records
    assert record.artifact_id == result["artifact_id"]
    assert record.source_tool == "vision_analyze"
    assert record.output_path == analysis_file
    assert record.verification["kind"] == "vision_analysis"
    dumped_record = json.dumps(record.__dict__, ensure_ascii=False)
    assert "data:image" not in dumped_record
    assert "iVBOR" not in dumped_record


def test_record_vision_analysis_artifact_redacts_data_image_reference(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    from pathlib import Path
    from tools.vision_tools import _record_vision_analysis_artifact

    artifact_id, analysis_file = _record_vision_analysis_artifact(
        image_url="data:image/png;base64," + "iVBOR" * 40,
        user_prompt="describe",
        model="vision-model",
        analysis="safe analysis",
    )

    assert artifact_id and artifact_id.startswith("artifact_")
    assert analysis_file
    payload = json.loads(Path(analysis_file).read_text(encoding="utf-8"))
    assert payload["analysis"] == "safe analysis"
    dumped = json.dumps(payload, ensure_ascii=False)
    assert "data:image" not in dumped
    assert "iVBOR" not in dumped
    assert payload["source_image_reference"] == "[omitted:data_uri_image]"


def test_vision_analyze_resolves_to_image_adapter():
    from tools.registry import registry
    from tools import vision_tools  # noqa: F401 - ensure registration
    from tools.tool_class_adapter import resolve_tool_class_adapter

    entry = registry.get_entry("vision_analyze")
    adapter = resolve_tool_class_adapter(entry)

    assert adapter.tool_class == "image"
    assert adapter.runtime_policy.requires_artifact_ledger is True
    assert adapter.output_policy.artifact_reference_only is True


def test_vision_analyze_model_context_is_wrapped_without_raw_image_reference():
    from model_tools import _wrap_tool_result_for_model_context
    from tools import vision_tools  # noqa: F401 - ensure registration

    raw = json.dumps({
        "success": True,
        "analysis": "A cat on a sofa. " * 800,
        "image_url": "data:image/png;base64," + "A" * 120,
        "model": "vision-model",
        "artifact_id": "artifact_vision123",
        "analysis_artifact_path": "/tmp/vision_analysis.json",
    })

    wrapped = json.loads(_wrap_tool_result_for_model_context("vision_analyze", raw))

    assert wrapped["tool_name"] == "vision_analyze"
    assert wrapped["tool_class"] == "image"
    assert wrapped["success"] is True
    assert wrapped["summary"] == "vision_analyze returned image analysis"
    assert wrapped["artifact_ids"] == ["artifact_vision123"]
    assert wrapped["output_references"] == ["/tmp/vision_analysis.json"]
    assert wrapped["bounded_payload"] == {
        "success": True,
        "analysis_preview": ("A cat on a sofa. " * 800)[:2048],
        "analysis_truncated": True,
    }
    dumped = json.dumps(wrapped, ensure_ascii=False)
    assert "data:image" not in dumped
    assert "A" * 100 not in dumped


def test_text_to_speech_model_context_uses_artifact_reference_only(tmp_path):
    from model_tools import _wrap_tool_result_for_model_context
    from tools import tts_tool  # noqa: F401 - ensure registration

    audio_path = tmp_path / "speech.mp3"
    audio_path.write_bytes(b"mp3")
    raw = json.dumps({
        "success": True,
        "file_path": str(audio_path),
        "media_tag": f"MEDIA:{audio_path}",
        "provider": "piper",
        "voice_compatible": False,
        "artifact_id": "artifact_audio123",
    })

    wrapped = json.loads(_wrap_tool_result_for_model_context("text_to_speech", raw))

    assert wrapped["tool_name"] == "text_to_speech"
    assert wrapped["tool_class"] == "tts"
    assert wrapped["success"] is True
    assert wrapped["summary"] == "text_to_speech produced audio artifact"
    assert wrapped["artifact_ids"] == ["artifact_audio123"]
    assert wrapped["output_references"] == [str(audio_path)]
    assert wrapped["bounded_payload"] == {
        "success": True,
        "provider": "piper",
        "voice_compatible": False,
        "file_path": str(audio_path),
    }
    assert "MEDIA:" not in json.dumps(wrapped, ensure_ascii=False)
