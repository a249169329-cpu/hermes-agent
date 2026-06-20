import pytest

from tools.tool_input_packet import (
    PacketLimits,
    ToolInputPacket,
    packet_hash,
    render_native_tool_args,
    validate_tool_input_packet,
)


def test_tool_input_packet_renders_native_arguments_without_hermes_context():
    packet = ToolInputPacket(
        tool_name="browser_navigate",
        intent="Open the app landing page only.",
        native_arguments={"url": "https://example.com"},
        context_refs=["AGENTS.md"],
        constraints=["Do not submit forms."],
        output_contract=["Return browser state only."],
    )

    args = render_native_tool_args(packet)

    assert args == {"url": "https://example.com"}
    assert "MEMORY" not in repr(args)
    assert "USER PROFILE" not in repr(args)


def test_tool_input_packet_rejects_hermes_transcript_markers_anywhere():
    packet = ToolInputPacket(
        tool_name="send_message",
        intent="Send this summary.",
        native_arguments={"message": "MEMORY (your personal notes) should never leak"},
    )

    assert validate_tool_input_packet(packet) == ["hermes_or_session_transcript_marker"]
    with pytest.raises(ValueError, match="unsafe_tool_input_packet"):
        render_native_tool_args(packet)


def test_tool_input_packet_rejects_raw_diff_logs_and_secret_markers():
    packet = ToolInputPacket(
        tool_name="github_pr_comment",
        intent="Post review body.",
        native_arguments={
            "body": "\n".join([
                "diff --git a/app.py b/app.py",
                "@@ -1 +1 @@",
                "+TOKEN=sk-pro...7890",
                "raw_log: traceback follows",
            ])
        },
    )

    assert validate_tool_input_packet(packet) == [
        "raw_diff_or_patch_marker",
        "raw_log_marker",
        "secret_marker",
    ]


def test_tool_input_packet_rejects_secret_named_credentials():
    packet = ToolInputPacket(
        tool_name="codex_staged_implement",
        intent="Run bounded Codex task.",
        native_arguments={"task": "use CLIENT_SECRET=abc123456789 to call service"},
    )

    assert validate_tool_input_packet(packet) == ["secret_marker"]


def test_tool_input_packet_rejects_non_json_native_arguments():
    packet = ToolInputPacket(
        tool_name="web_search",
        intent="Search docs.",
        native_arguments={"query": object()},
    )

    assert validate_tool_input_packet(packet) == ["native_arguments_not_json_serializable"]


def test_tool_input_packet_reports_size_and_required_field_violations():
    packet = ToolInputPacket(
        tool_name="",
        intent="line\n" * 5,
        native_arguments={},
    )

    assert validate_tool_input_packet(
        packet,
        limits=PacketLimits(max_chars=12, max_lines=2),
    ) == ["missing_tool_name", "tool_input_packet_too_large", "tool_input_packet_too_many_lines"]


def test_tool_input_packet_hash_is_stable_for_equivalent_payload_order():
    left = ToolInputPacket(
        tool_name="image_generate",
        intent="Generate safe illustration.",
        native_arguments={"prompt": "a cat", "aspect_ratio": "square"},
    )
    right = ToolInputPacket(
        tool_name="image_generate",
        intent="Generate safe illustration.",
        native_arguments={"aspect_ratio": "square", "prompt": "a cat"},
    )

    assert packet_hash(left) == packet_hash(right)
