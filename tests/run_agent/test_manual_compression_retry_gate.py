"""Manual retry gate for failed context compression summaries."""

from unittest.mock import MagicMock, patch

from agent.conversation_loop import _COMPRESSION_CIRCUIT_BREAKER_MESSAGE
from run_agent import AIAgent


def _make_agent():
    with (
        patch("run_agent.get_tool_definitions", return_value=[]),
        patch("run_agent.check_toolset_requirements", return_value={}),
        patch("run_agent.OpenAI"),
    ):
        agent = AIAgent(
            api_key="test-key-1234567890",
            base_url="https://example.invalid/v1",
            model="test/model",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
            save_trajectories=False,
        )
    agent.platform = "qqbot"
    agent.client = MagicMock()
    agent.client.chat.completions.create.side_effect = AssertionError(
        "manual compression retry gate should stop before provider call"
    )
    agent.tools = []
    agent._cached_system_prompt = "system prompt"
    agent._use_prompt_caching = False
    agent.compression_enabled = True
    agent.manual_compression_retry_on_summary_failure = True
    agent.context_compressor.threshold_tokens = 1
    agent.context_compressor.abort_on_summary_failure = True
    agent.context_compressor.protect_first_n = 1
    agent.context_compressor.protect_last_n = 1
    return agent


def test_preflight_summary_abort_returns_manual_retry_gate_without_provider_call():
    agent = _make_agent()
    history = [
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "older question"},
        {"role": "assistant", "content": "older answer"},
    ]

    def fake_compress(messages, system_message, **kwargs):
        agent.context_compressor._last_compress_aborted = True
        agent.context_compressor._last_summary_error = "401 token invalidated"
        agent.context_compressor._last_summary_fallback_used = False
        return messages, system_message or "system prompt"

    with (
        patch.object(agent, "_compress_context", side_effect=fake_compress) as compress,
        patch.object(agent, "_persist_session"),
        patch.object(agent, "_cleanup_task_resources"),
    ):
        result = agent.run_conversation("fresh ask", conversation_history=history)

    compress.assert_called_once()
    agent.client.chat.completions.create.assert_not_called()
    assert result["completed"] is False
    assert result["partial"] is True
    assert result["failed"] is False
    assert result["compression_manual_retry_pending"] is True
    assert result["compression_summary_error"] == "401 token invalidated"
    assert "重试" in result["final_response"]
    assert "不重试" in result["final_response"]
    assert "fallback" in result["final_response"].lower()


def test_compression_circuit_breaker_message_asks_to_resend_current_question():
    assert "已完成压缩" in _COMPRESSION_CIRCUIT_BREAKER_MESSAGE
    assert "重新发送刚才的问题" in _COMPRESSION_CIRCUIT_BREAKER_MESSAGE
    assert "请新开会话" not in _COMPRESSION_CIRCUIT_BREAKER_MESSAGE
