import json

from scripts.runtime import codex_review_guard as guard


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
