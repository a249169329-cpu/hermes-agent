import json
from pathlib import Path

from tools.image_prompt_guard import (
    ImagePromptRequest,
    redact_debug_prompt,
    validate_image_prompt_request,
)
import tools.image_generation_tool as image_generation_tool


def test_image_prompt_guard_accepts_bounded_text_to_image_prompt():
    request = ImagePromptRequest(
        prompt="A watercolor cat reading a book, cozy room.",
        aspect_ratio="square",
        provider="custom:yuna",
        model="gpt-image-2-medium",
    )

    assert validate_image_prompt_request(request) == []


def test_image_prompt_guard_rejects_overlong_prompt_and_secret_markers():
    request = ImagePromptRequest(
        prompt="sk-live-secret " + ("x" * 5000),
        aspect_ratio="landscape",
        provider="openai-codex",
        model="gpt-image-2-medium",
        max_prompt_chars=200,
    )

    assert validate_image_prompt_request(request) == [
        "image_prompt_contains_secret_marker",
        "image_prompt_too_large",
    ]


def test_image_prompt_guard_rejects_hermes_context_and_raw_diff():
    request = ImagePromptRequest(
        prompt="\n".join([
            "MEMORY (your personal notes)",
            "diff --git a/prompt.md b/prompt.md",
            "raw_log: provider output",
        ]),
        aspect_ratio="square",
    )

    assert validate_image_prompt_request(request) == [
        "image_prompt_contains_hermes_context",
        "image_prompt_contains_raw_diff_or_log",
    ]


def test_image_prompt_guard_checks_input_file_existence(tmp_path):
    existing = tmp_path / "input.png"
    existing.write_bytes(b"\x89PNG\r\n\x1a\n")
    missing = tmp_path / "missing.png"

    request = ImagePromptRequest(
        prompt="Turn the provided sketch into a clean icon.",
        input_files=[str(existing), str(missing)],
    )

    assert validate_image_prompt_request(request) == ["image_input_file_missing"]


def test_image_prompt_guard_requires_consent_for_real_person_face():
    request = ImagePromptRequest(
        prompt="Make this real person's portrait look cinematic.",
        input_files=["/tmp/person.png"],
        real_person=True,
        person_consent=False,
        require_existing_input_files=False,
    )

    assert validate_image_prompt_request(request) == ["real_person_requires_consent"]


def test_image_prompt_guard_requires_external_cost_ack_when_configured():
    request = ImagePromptRequest(
        prompt="Generate a poster.",
        provider="openai-codex",
        model="gpt-image-2-medium",
        require_cost_ack=True,
        cost_acknowledged=False,
    )

    assert validate_image_prompt_request(request) == ["external_image_cost_not_acknowledged"]


def test_redact_debug_prompt_removes_secret_values():
    redacted = redact_debug_prompt("Bearer abcdef1234567890 and *** should not show")

    assert "abcdef1234567890" not in redacted
    assert "***" not in redacted
    assert "[REDACTED" in redacted


def test_image_generate_handler_applies_prompt_guard_before_provider(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("provider dispatch should not run for unsafe prompt")

    monkeypatch.setattr(image_generation_tool, "_dispatch_to_plugin_provider", fail_if_called)
    monkeypatch.setattr(image_generation_tool, "image_generate_tool", fail_if_called)

    result = json.loads(
        image_generation_tool._handle_image_generate(
            {"prompt": "Bearer abcdef1234567890", "aspect_ratio": "square"}
        )
    )

    assert result["success"] is False
    assert result["error_type"] == "image_prompt_guard"
    assert result["violations"] == ["image_prompt_contains_secret_marker"]
