import json

from tools.artifact_ledger import ArtifactLedger, default_artifact_ledger_path


def test_video_generate_records_successful_artifact(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    from agent import video_gen_registry
    from agent.video_gen_provider import VideoGenProvider
    from tools import video_generation_tool
    import hermes_cli.plugins as plugins_module

    class RecordingVideoProvider(VideoGenProvider):
        @property
        def name(self):
            return "fake-video"

        def default_model(self):
            return "model-a"

        def generate(self, prompt, **kwargs):
            return {
                "success": True,
                "video": "https://cdn.example.com/video.mp4",
                "provider": self.name,
                "model": kwargs.get("model") or "model-a",
            }

    video_gen_registry._reset_for_tests()
    video_gen_registry.register_provider(RecordingVideoProvider())
    monkeypatch.setattr(video_generation_tool, "_read_configured_video_provider", lambda: "fake-video")
    monkeypatch.setattr(plugins_module, "_ensure_plugins_discovered", lambda *_a, **_k: None)

    result = json.loads(video_generation_tool._handle_video_generate({"prompt": "safe video"}))

    assert result["artifact_id"].startswith("artifact_")
    records = ArtifactLedger(default_artifact_ledger_path()).read_all()
    assert len(records) == 1
    [record] = records
    assert record.artifact_id == result["artifact_id"]
    assert record.source_tool == "video_generate"
    assert record.output_url == "https://cdn.example.com/video.mp4"
    assert record.lifetime == "persistent_or_remote"

    video_gen_registry._reset_for_tests()


def test_text_to_speech_records_successful_artifact(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    from tools import tts_tool

    output = tmp_path / "speech.mp3"
    monkeypatch.setattr(tts_tool, "_load_tts_config", lambda: {"provider": "piper"})
    monkeypatch.setattr(tts_tool, "_import_piper", lambda: object)
    monkeypatch.setattr(tts_tool, "_generate_piper_tts", lambda text, output_path, config: output.write_bytes(b"mp3"))

    result = json.loads(tts_tool.text_to_speech_tool("hello", output_path=str(output)))

    assert result["success"] is True
    assert result["artifact_id"].startswith("artifact_")
    records = ArtifactLedger(default_artifact_ledger_path()).read_all()
    assert len(records) == 1
    [record] = records
    assert record.artifact_id == result["artifact_id"]
    assert record.source_tool == "text_to_speech"
    assert record.output_path == str(output)
    assert record.lifetime == "persistent_or_remote"


def test_record_tool_artifact_rejects_raw_or_secret_output_references(tmp_path, monkeypatch):
    from tools.artifact_ledger import record_tool_artifact

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    unsafe_refs = [
        "data:text/html;base64,PGh0bWw+PC9odG1sPg==",
        "https://example.invalid/video.mp4?token=SECRET_VALUE_1234567890",
        "file:///etc/passwd",
    ]

    for output_reference in unsafe_refs:
        assert record_tool_artifact(
            source_tool="video_generate",
            native_arguments={"prompt": "safe"},
            output_reference=output_reference,
            kind="video",
        ) is None
