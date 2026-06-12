import json
import subprocess
from pathlib import Path

from scripts.runtime import codex_stage_runner as runner


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


def test_run_without_plan_file_returns_bounded_missing_plan_json(capsys):
    exit_code = runner.run([])
    result = _payload(capsys)

    assert exit_code == 1
    assert result["status"] == "unusable"
    assert result["reason"] == "missing_plan"
    assert result["completed_slices"] == []
    assert result["recommended_next_action"] == "Provide --plan-file pointing to a JSON stage plan."


def test_validate_plan_rejects_prompt_file_outside_repo_and_plan_dir(tmp_path):
    repo = _clean_repo(tmp_path)
    plan_dir = tmp_path / "plans"
    plan_dir.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_prompt = outside_dir / "prompt.md"
    outside_prompt.write_text("do work\n", encoding="utf-8")

    plan = {
        "repo": str(repo),
        "slices": [
            {
                "id": "slice-1",
                "prompt_file": str(outside_prompt),
                "allowed_files": ["README.md"],
                "allowed_globs": [],
                "verify_cmd_ids": ["diff-check"],
            }
        ],
    }

    normalized, error = runner._validate_plan(plan, plan_dir=plan_dir)

    assert normalized is None
    assert error == "prompt_file_outside_allowed_roots"


def test_validate_plan_and_guard_argv_normalize_valid_slice(tmp_path):
    repo = _clean_repo(tmp_path)
    plan_dir = tmp_path / "plans"
    plan_dir.mkdir()
    prompt = plan_dir / "prompt.md"
    prompt.write_text("do work\n", encoding="utf-8")
    raw_dir = tmp_path / "raw"

    plan = {
        "repo": str(repo),
        "continue_policy": "stop-on-review-needed",
        "dirty_baseline_policy": "require-clean",
        "slices": [
            {
                "id": "slice-1",
                "prompt_file": "prompt.md",
                "allowed_files": ["README.md"],
                "allowed_globs": ["tests/*.py"],
                "verify_cmd_ids": ["diff-check"],
            }
        ],
    }

    normalized, error = runner._validate_plan(plan, plan_dir=plan_dir)
    assert error is None
    assert normalized is not None
    item = normalized["slices"][0]

    argv = runner._guard_argv(
        Path("/tmp/codex_impl_guard.py"),
        normalized["repo"],
        item,
        raw_dir=raw_dir,
        timeout_seconds=12.5,
    )

    assert "--workdir" in argv
    assert normalized["repo"] in argv
    assert "--prompt-file" in argv
    assert str(prompt.resolve()) in argv
    assert [argv[i + 1] for i, value in enumerate(argv) if value == "--allowed-file"] == ["README.md"]
    assert [argv[i + 1] for i, value in enumerate(argv) if value == "--allowed-glob"] == ["tests/*.py"]
    assert [argv[i + 1] for i, value in enumerate(argv) if value == "--verify-cmd-id"] == ["diff-check"]
    assert str(raw_dir / "slice-1.raw.log") in argv
    assert str(raw_dir / "slice-1.final.json") in argv
