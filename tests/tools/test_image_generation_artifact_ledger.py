import json

import tools.image_generation_tool as image_generation_tool
from tools.artifact_ledger import ArtifactLedger, default_artifact_ledger_path


def test_image_generate_records_successful_artifact(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(
        image_generation_tool,
        "_dispatch_to_plugin_provider",
        lambda prompt, aspect_ratio: {
            "success": True,
            "image": "https://cdn.example.com/image.png",
            "provider": "fake",
        },
    )

    result = json.loads(
        image_generation_tool._handle_image_generate(
            {"prompt": "a safe cat", "aspect_ratio": "square"}
        )
    )

    assert result["artifact_id"].startswith("artifact_")
    records = ArtifactLedger(default_artifact_ledger_path()).read_all()
    assert len(records) == 1
    [record] = records
    assert record.artifact_id == result["artifact_id"]
    assert record.source_tool == "image_generate"
    assert record.output_url == "https://cdn.example.com/image.png"
    assert record.lifetime == "persistent_or_remote"
