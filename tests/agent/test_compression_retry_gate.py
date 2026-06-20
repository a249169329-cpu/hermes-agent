"""Unit tests for manual compression retry helper parsing."""

import pytest

from agent.compression_retry_gate import (
    format_manual_compression_retry_prompt,
    parse_manual_compression_retry_choice,
)


@pytest.mark.parametrize("text", ["重试", " retry ", "再试一次", "重新压缩"])
def test_parse_retry_choice(text):
    assert parse_manual_compression_retry_choice(text) == "retry"


@pytest.mark.parametrize("text", ["不重试", "降级", "fallback", "用fallback", "本地fallback"])
def test_parse_fallback_choice(text):
    assert parse_manual_compression_retry_choice(text) == "fallback"


@pytest.mark.parametrize("text", ["停止", "stop", "算了", "先不处理"])
def test_parse_stop_choice(text):
    assert parse_manual_compression_retry_choice(text) == "stop"


def test_retry_prompt_names_manual_choices_and_error():
    prompt = format_manual_compression_retry_prompt(
        "gpt-5.4 401 token invalidated",
        attempts=1,
        max_attempts=3,
    )

    assert "gpt-5.4 401 token invalidated" in prompt
    assert "重试" in prompt
    assert "不重试" in prompt
    assert "fallback" in prompt.lower()
    assert "1/3" not in prompt
    assert "0/3" not in prompt
    assert "可重复重试" in prompt


def test_retry_prompt_hides_provider_reset_countdown_fields():
    prompt = format_manual_compression_retry_prompt(
        "Error code: 429 - {'error': {'code': 'model_cooldown', "
        "'message': 'All credentials cooling down', 'model': 'gpt-5.4', "
        "'provider': 'codex', 'reset_seconds': 3526, "
        "'reset_time': '2026-06-20T13:00:00Z'}}",
        attempts=0,
        max_attempts=3,
    )

    assert "model_cooldown" in prompt
    assert "reset_seconds" not in prompt
    assert "reset_time" not in prompt
    assert "3526" not in prompt
    assert "0/3" not in prompt


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        ("gpt-5.4 401 token invalidated", "先修 auth"),
        ("429 model cooldown", "等一会儿"),
        ("Codex auxiliary Responses stream exceeded 300s total timeout", "可重试一次"),
        ("Your request was blocked by content_filter", "建议降级"),
    ],
)
def test_retry_prompt_gives_error_specific_guidance(error, expected):
    prompt = format_manual_compression_retry_prompt(error, attempts=0, max_attempts=3)

    assert expected in prompt
