import pytest

from tools.codex_input_packet import (
    CodexInputPacket,
    PacketLimits,
    render_codex_exec_prompt,
    render_goal_text,
    validate_text_packet,
)


def test_render_codex_exec_prompt_uses_structured_packet_not_transcript():
    packet = CodexInputPacket(
        objective="Fix the terminal timeout regression.",
        workdir="/repo",
        docs_to_read=["AGENTS.md", "docs/terminal.md"],
        allowed_files=["tools/terminal_tool.py", "tests/tools/test_terminal_tool.py"],
        allowed_globs=["tests/tools/test_terminal_*.py"],
        constraints=["Do not push.", "Keep changes minimal."],
        verification=["python -m pytest tests/tools/test_terminal_tool.py -q -o addopts=''"],
        stop_conditions=["Stop when candidate diff is ready.", "Stop if scope expands."],
        output_contract=["Summarize changed files.", "Do not print full diffs or large logs."],
    )

    prompt = render_codex_exec_prompt(packet)

    assert "Objective:\nFix the terminal timeout regression." in prompt
    assert "Workdir:\n/repo" in prompt
    assert "Read first:\n- AGENTS.md\n- docs/terminal.md" in prompt
    assert "Allowed files:\n- tools/terminal_tool.py\n- tests/tools/test_terminal_tool.py" in prompt
    assert "Allowed globs:\n- tests/tools/test_terminal_*.py" in prompt
    assert "Constraints:\n- Do not push.\n- Keep changes minimal." in prompt
    assert "Verification:\n- python -m pytest tests/tools/test_terminal_tool.py -q -o addopts=''" in prompt
    assert "Stop conditions:\n- Stop when candidate diff is ready.\n- Stop if scope expands." in prompt
    assert "Output contract:\n- Summarize changed files.\n- Do not print full diffs or large logs." in prompt
    assert "MEMORY (your personal notes)" not in prompt
    assert "USER PROFILE" not in prompt


def test_validate_text_packet_rejects_hermes_transcript_markers():
    text = "\n".join([
        "技能检查点：已加载 codex。",
        "MEMORY (your personal notes) [99%]",
        "USER PROFILE (who the user is)",
        "Task: fix README.",
    ])

    violations = validate_text_packet(
        text,
        limits=PacketLimits(max_chars=6000, max_lines=80),
        too_large_code="prompt_packet_too_large",
        too_many_lines_code="prompt_packet_too_many_lines",
    )

    assert violations == ["hermes_or_session_transcript_marker"]


def test_validate_text_packet_reports_configured_size_codes():
    text = "line\n" * 4

    violations = validate_text_packet(
        text,
        limits=PacketLimits(max_chars=10, max_lines=2),
        too_large_code="goal_packet_too_large",
        too_many_lines_code="goal_packet_too_many_lines",
    )

    assert violations == ["goal_packet_too_large", "goal_packet_too_many_lines"]


def test_render_goal_text_is_short_stage_scoped_goal():
    packet = CodexInputPacket(
        objective="Complete Stage 2 only: add bounded Codex input packet renderer.",
        workdir="/repo",
        allowed_files=["tools/codex_input_packet.py"],
        verification=["python -m pytest tests/tools/test_codex_input_packet.py -q -o addopts=''"],
        stop_conditions=["Stop for Hermes review after tests pass."],
    )

    goal_text = render_goal_text(packet)

    assert goal_text.startswith("/goal ")
    assert "Complete Stage 2 only" in goal_text
    assert "Allowed files: tools/codex_input_packet.py" in goal_text
    assert "Verify: python -m pytest tests/tools/test_codex_input_packet.py -q -o addopts=''" in goal_text
    assert "Stop for Hermes review after tests pass." in goal_text
    assert "MEMORY" not in goal_text
