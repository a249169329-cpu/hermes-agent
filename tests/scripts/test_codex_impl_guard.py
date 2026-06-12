import json
import subprocess
from pathlib import Path

from scripts.runtime import codex_impl_guard as guard


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


def _payload(capsys):
    out = capsys.readouterr().out.strip()
    assert out
    return json.loads(out)


def test_run_rejects_invalid_allowlist_before_codex_or_sandbox_checks(tmp_path, capsys):
    repo = _clean_repo(tmp_path)

    exit_code = guard.run([
        "--workdir",
        str(repo),
        "--prompt",
        "make a change",
        "--allowed-file",
        "../outside.py",
    ])
    result = _payload(capsys)

    assert exit_code == 3
    assert result["status"] == "unusable"
    assert result["reason"] == "invalid_allowlist"
    assert result["invalid_allowlist"] == ["../outside.py"]
    assert "required_env" not in result
    assert "codex_exit_code" not in result


def test_dirty_policy_allow_listed_owned_rejects_baseline_outside_allowlist(tmp_path):
    repo = _clean_repo(tmp_path)

    result = guard._dirty_policy_error(
        policy="allow-listed-owned",
        dirty_baseline=["README.md", "docs/notes.md"],
        workdir=repo,
        files=["README.md"],
        globs=[],
    )

    assert result is not None
    assert result["reason"] == "dirty_baseline_outside_allowlist"
    assert result["dirty_baseline_violations"] == ["docs/notes.md"]


def test_dirty_policy_fail_on_overlap_rejects_allowlist_overlap(tmp_path):
    repo = _clean_repo(tmp_path)

    result = guard._dirty_policy_error(
        policy="fail-on-overlap",
        dirty_baseline=["README.md", "docs/notes.md"],
        workdir=repo,
        files=["README.md"],
        globs=["tests/*.py"],
    )

    assert result is not None
    assert result["reason"] == "dirty_baseline_overlaps_allowlist"
    assert result["dirty_baseline_overlap"] == ["README.md"]


def test_safe_output_path_rejects_repo_local_outputs(tmp_path):
    repo = _clean_repo(tmp_path)
    output_path, error = guard._safe_output_path(repo / "raw.log", workdir=repo, label="raw_log_path")

    assert output_path == repo / "raw.log"
    assert error is not None
    assert error["reason"] == "unsafe_output_path"
    assert error["unsafe_output_path_detail"] == "inside_workdir"
