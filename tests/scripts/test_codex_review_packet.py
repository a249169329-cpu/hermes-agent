import json
import re
import subprocess
from pathlib import Path

from scripts.runtime import codex_review_packet as packet


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def _clean_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")
    return repo


def _metadata_from_packet(text: str) -> dict:
    match = re.search(r"## Packet metadata header\n\n```json\n(.*?)\n```", text, re.S)
    assert match, text
    return json.loads(match.group(1))


def test_build_packet_includes_tracked_and_untracked_scope_files(tmp_path):
    repo = _clean_repo(tmp_path)
    (repo / "README.md").write_text("hello\nSECRET_VALUE=should_not_leak\n", encoding="utf-8")
    (repo / "new_test.py").write_text("def test_new():\n    assert 'untracked body must not leak'\n", encoding="utf-8")

    text = packet.build_packet(
        workdir=repo,
        files=["README.md", "new_test.py"],
        max_stat_chars=1000,
        max_name_chars=1000,
        max_diff_chars=3000,
        max_total_chars=5000,
        completion_trusted=False,
        candidate_id="cand-1",
        candidate_disposition="pending_review",
    )
    metadata = _metadata_from_packet(text)

    assert metadata["schema_version"] == "review_packet.v3"
    assert metadata["touched_files"] == ["README.md", "new_test.py"]
    assert metadata["allowed_files"] == ["README.md", "new_test.py"]
    assert metadata["completion_trusted"] is False
    assert metadata["candidate_id"] == "cand-1"
    assert metadata["file_summaries"] == [
        {
            "path": "README.md",
            "tracked": True,
            "untracked": False,
            "content_sha256": metadata["file_summaries"][0]["content_sha256"],
        },
        {
            "path": "new_test.py",
            "tracked": False,
            "untracked": True,
            "content_sha256": metadata["file_summaries"][1]["content_sha256"],
        },
    ]
    assert len(metadata["file_summaries"][0]["content_sha256"]) == 64
    assert len(metadata["file_summaries"][1]["content_sha256"]) == 64
    assert "## structured diff summary" in text
    assert "## bounded git diff" not in text
    assert "## bounded untracked file previews" not in text
    assert "diff --git" not in text
    assert "@@" not in text
    assert "SECRET_VALUE=should_not_leak" not in text
    assert "untracked body must not leak" not in text
    assert "new_test.py" in text


def test_build_packet_respects_total_limit_and_records_limit_metadata(tmp_path):
    repo = _clean_repo(tmp_path)
    (repo / "README.md").write_text("hello\n" + "x" * 2000 + "\n", encoding="utf-8")

    text = packet.build_packet(
        workdir=repo,
        files=["README.md"],
        max_stat_chars=1000,
        max_name_chars=1000,
        max_diff_chars=3000,
        max_total_chars=900,
    )

    assert len(text) <= 900 + len("\n[truncated by max_total_chars]\n")
    assert "[truncated" in text


def test_completion_trusted_arg_parsing_is_tristate():
    assert packet._completion_trusted_value("true") is True
    assert packet._completion_trusted_value("false") is False
    assert packet._completion_trusted_value("unknown") is None
