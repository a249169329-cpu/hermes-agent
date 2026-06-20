"""Gateway handling for pending manual compression retry decisions."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import gateway.run as gateway_run
from gateway.config import Platform
from gateway.session import SessionSource


class _Store:
    def __init__(self):
        self.save_calls = 0

    def _save(self):
        self.save_calls += 1


class _Event:
    def __init__(self, text):
        self.text = text
        self.message_id = "msg-1"


def _runner(result_text):
    runner = object.__new__(gateway_run.GatewayRunner)
    runner.session_store = _Store()
    runner._handle_compress_command = AsyncMock(return_value=result_text)
    return runner


def _runner_with_structured_result(result_text, state):
    runner = object.__new__(gateway_run.GatewayRunner)
    runner.session_store = _Store()

    async def _handle(*args, **kwargs):
        runner._last_manual_compress_result = state
        return result_text

    runner._handle_compress_command = AsyncMock(side_effect=_handle)
    return runner


def _entry(attempts=0):
    return SimpleNamespace(
        session_key="agent:main:qqbot:dm:123",
        compression_retry_pending={
            "error": "401 token invalidated",
            "attempts": attempts,
            "max_attempts": 3,
        },
    )


_SOURCE = SessionSource(platform=Platform.QQBOT, chat_id="123", chat_type="dm", user_id="u")


@pytest.mark.asyncio
async def test_pending_compression_stop_clears_gate_without_agent_run():
    runner = _runner("should not be used")
    entry = _entry()

    response = await runner._handle_pending_compression_retry_choice(
        _Event("停止"), _SOURCE, entry, entry.session_key
    )

    assert "已停止" in response
    assert entry.compression_retry_pending is None
    assert runner.session_store.save_calls == 1
    runner._handle_compress_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_pending_compression_retry_runs_manual_compress_and_keeps_gate_on_abort():
    runner = _runner("⚠️ Compression aborted: 401 token invalidated. No messages were dropped.")
    entry = _entry(attempts=1)

    response = await runner._handle_pending_compression_retry_choice(
        _Event("重试"), _SOURCE, entry, entry.session_key
    )

    runner._handle_compress_command.assert_awaited_once()
    compress_event = runner._handle_compress_command.await_args.args[0]
    assert compress_event.text == "/compress"
    assert runner._handle_compress_command.await_args.kwargs["abort_on_summary_failure"] is True
    assert entry.compression_retry_pending["attempts"] == 2
    assert "2/3" not in response
    assert "不重试" in response


@pytest.mark.asyncio
async def test_pending_compression_retry_has_no_max_attempts_gate():
    runner = _runner_with_structured_result(
        "⚠️ 压缩已中止：429 model_cooldown。未丢弃消息。",
        {"summary_aborted": True, "failed": False, "error": "429 model_cooldown reset_seconds=3526"},
    )
    entry = _entry(attempts=3)

    response = await runner._handle_pending_compression_retry_choice(
        _Event("重试"), _SOURCE, entry, entry.session_key
    )

    runner._handle_compress_command.assert_awaited_once()
    assert entry.compression_retry_pending["attempts"] == 4
    assert "重试上限" not in response
    assert "4/3" not in response
    assert "reset_seconds" not in response
    assert "3526" not in response
    assert "可重复重试" in response


@pytest.mark.asyncio
async def test_pending_compression_retry_uses_structured_abort_state_not_english_text():
    runner = _runner_with_structured_result(
        "⚠️ 压缩已中止：401 token invalidated。未丢弃消息。",
        {"summary_aborted": True, "failed": False, "error": "401 token invalidated"},
    )
    entry = _entry(attempts=1)

    response = await runner._handle_pending_compression_retry_choice(
        _Event("重试"), _SOURCE, entry, entry.session_key
    )

    runner._handle_compress_command.assert_awaited_once()
    assert entry.compression_retry_pending["attempts"] == 2
    assert "2/3" not in response
    assert "不重试" in response


@pytest.mark.asyncio
async def test_pending_compression_retry_requires_structured_state_even_if_text_looks_successful():
    runner = _runner("🗜️ Compressed: 200 → 20 messages")
    entry = _entry(attempts=1)

    response = await runner._handle_pending_compression_retry_choice(
        _Event("重试"), _SOURCE, entry, entry.session_key
    )

    runner._handle_compress_command.assert_awaited_once()
    assert entry.compression_retry_pending is not None
    assert entry.compression_retry_pending["attempts"] == 2
    assert "structured" in entry.compression_retry_pending["error"]
    assert "仍未压缩成功" in response


@pytest.mark.asyncio
async def test_pending_compression_fallback_runs_local_fallback_and_clears_gate():
    runner = _runner_with_structured_result(
        "🗜️ Compressed: 200 → 20 messages",
        {"summary_aborted": False, "failed": False, "error": None},
    )
    entry = _entry(attempts=1)

    response = await runner._handle_pending_compression_retry_choice(
        _Event("不重试"), _SOURCE, entry, entry.session_key
    )

    runner._handle_compress_command.assert_awaited_once()
    compress_event = runner._handle_compress_command.await_args.args[0]
    assert compress_event.text == "/compress"
    assert runner._handle_compress_command.await_args.kwargs["abort_on_summary_failure"] is False
    assert "Compressed" in response
    assert entry.compression_retry_pending is None
    assert runner.session_store.save_calls == 1


@pytest.mark.asyncio
async def test_pending_compression_fallback_keeps_gate_when_fallback_failed():
    runner = _runner_with_structured_result(
        "压缩失败：no provider",
        {"summary_aborted": False, "failed": True, "error": "no provider"},
    )
    entry = _entry(attempts=1)

    response = await runner._handle_pending_compression_retry_choice(
        _Event("不重试"), _SOURCE, entry, entry.session_key
    )

    runner._handle_compress_command.assert_awaited_once()
    assert "压缩失败" in response
    assert entry.compression_retry_pending is not None
    assert runner.session_store.save_calls == 1


@pytest.mark.asyncio
async def test_pending_compression_unknown_reply_does_not_run_agent():
    runner = _runner("should not be used")
    entry = _entry()

    response = await runner._handle_pending_compression_retry_choice(
        _Event("继续干活"), _SOURCE, entry, entry.session_key
    )

    assert "请先回复" in response
    assert "重试" in response
    assert entry.compression_retry_pending is not None
    runner._handle_compress_command.assert_not_awaited()
