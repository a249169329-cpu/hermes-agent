import json

from scripts.runtime import codex_review_guard as guard
from scripts.runtime import codex_review_packet


def _payload(capsys):
    out = capsys.readouterr().out.strip()
    assert out
    return json.loads(out)


def test_json_field_flood_detects_nested_aggregated_output():
    text = "\n".join([
        "def first():",
        "    return 1",
        "class Second:",
    ])
    line = json.dumps({"event": {"aggregated_output": text}})

    result = guard._json_field_flood(
        line,
        source_line_threshold=2,
        diff_line_threshold=99,
        char_threshold=999,
    )

    assert result is not None
    assert result["reason"] == "aggregated_output_flood"
    assert result["json_flood_field"] == "aggregated_output"
    assert result["json_flood_source_like_lines"] >= 2
    assert result["json_flood_limit"] == "source_line_threshold"


def test_review_from_json_line_recovers_nested_final_review():
    review = {
        "verdict": "failed",
        "summary": "needs changes",
        "must_fix": ["fix packet validation"],
        "suggested_fixes": [],
        "verification_commands": ["pytest tests/scripts/test_codex_review_guard.py -q"],
        "final_judgment": "需要先修",
    }
    line = json.dumps({"type": "message", "content": [{"text": json.dumps({"review": review})}]})

    recovered = guard._review_from_json_line(line)

    assert recovered == review
    assert guard._status_from_review(recovered) == "failed"


def test_run_missing_review_packet_file_fails_before_codex_launch(tmp_path, capsys):
    missing_packet = tmp_path / "missing-packet.md"

    exit_code = guard.run([
        "--workdir",
        str(tmp_path),
        "--prompt",
        "review this packet",
        "--review-packet-file",
        str(missing_packet),
    ])
    result = _payload(capsys)

    assert exit_code == 2
    assert result["status"] == "unusable"
    assert result["reason"] == "review_packet_file_missing"
    assert result["review_packet_file"] == str(missing_packet.resolve())
    assert "codex_exit_code" not in result


def test_run_rejects_verbose_hermes_review_prompt_before_codex_launch(tmp_path, capsys, monkeypatch):
    calls = []

    def fake_popen(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("Codex must not launch for unsafe review prompt packets")

    monkeypatch.setattr(guard.subprocess, "Popen", fake_popen)
    verbose_prompt = "\n".join([
        "技能检查点：已加载 hermes-agent/codex。",
        "MEMORY (your personal notes) [99%]",
        "USER PROFILE (who the user is)",
        "准备执行：把我的整段解释都交给 Codex review。",
        "Review this tiny diff.",
    ])

    exit_code = guard.run([
        "--workdir",
        str(tmp_path),
        "--prompt",
        verbose_prompt,
    ])
    result = _payload(capsys)

    assert exit_code == 2
    assert result["status"] == "unusable"
    assert result["reason"] == "unsafe_review_prompt_packet"
    assert "hermes_or_session_transcript_marker" in result["review_prompt_packet_violations"]
    assert result["next_action"] == "provide_minimal_review_prompt_and_bounded_review_packet"
    assert "codex_exit_code" not in result
    assert calls == []


def test_run_rejects_unsafe_review_packet_file_before_codex_launch(tmp_path, capsys, monkeypatch):
    calls = []

    def fake_popen(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("Codex must not launch for unsafe review packet files")

    monkeypatch.setattr(guard.subprocess, "Popen", fake_popen)
    packet = tmp_path / "review-packet.md"
    packet.write_text(
        "\n".join([
            "## bounded review packet",
            "MEMORY (your personal notes)",
            "diff --git a/secret.py b/secret.py",
            "+TOKEN=sk-proj-abcdef1234567890",
        ]),
        encoding="utf-8",
    )

    exit_code = guard.run([
        "--workdir",
        str(tmp_path),
        "--prompt",
        "review this bounded packet",
        "--review-packet-file",
        str(packet),
    ])
    result = _payload(capsys)

    assert exit_code == 2
    assert result["status"] == "unusable"
    assert result["reason"] == "unsafe_review_packet_file"
    assert "hermes_or_session_transcript_marker" in result["review_packet_violations"]
    assert "raw_diff_or_patch_marker" in result["review_packet_violations"]
    assert "secret_marker" in result["review_packet_violations"]
    assert "codex_exit_code" not in result
    assert calls == []


def test_review_packet_guard_allows_structured_packet_bullets(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("hello\n", encoding="utf-8")

    packet = codex_review_packet.build_packet(
        workdir=repo,
        files=["README.md"],
        max_stat_chars=1000,
        max_name_chars=1000,
        max_diff_chars=3000,
        max_total_chars=5000,
        tests_run=["focused tests passed"],
    )

    assert "- `README.md`" in packet
    assert "- focused tests passed" in packet
    assert guard._review_packet_file_violations(packet) == []
