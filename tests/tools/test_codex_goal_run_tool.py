import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import toolsets
from tools import codex_goal_run_tool as tool
from tools.registry import registry


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


def _args(repo: Path, **overrides):
    args = {
        "workdir": str(repo),
        "stage_id": "slice-1",
        "objective": "Add the narrow goal-run preparation slice",
        "docs_to_read": ["docs/working-notes/hermes-codex-goal-run-design.md"],
        "allowed_files": ["tools/codex_goal_run_tool.py"],
        "allowed_globs": ["tests/tools/test_codex_goal_run_tool.py"],
        "non_goals": ["do not launch Codex TUI", "do not call codex exec"],
        "required_verification": ["python3 -m pytest tests/tools/test_codex_goal_run_tool.py -q -o addopts=''"],
        "stop_conditions": ["dirty worktree", "missing goals feature"],
        "mode": "dry_run_plan",
        "dirty_baseline_policy": "require-clean",
    }
    args.update(overrides)
    return args


def _call(repo: Path, **overrides):
    return json.loads(tool.codex_goal_run(_args(repo, **overrides)))


def test_schema_registration_and_toolset_exposure():
    schema = registry.get_schema("codex_goal_run")

    assert schema is not None
    props = schema["parameters"]["properties"]
    for field in [
        "workdir",
        "stage_id",
        "objective",
        "docs_to_read",
        "allowed_files",
        "allowed_globs",
        "non_goals",
        "required_verification",
        "stop_conditions",
        "mode",
        "dirty_baseline_policy",
        "allow_isolated_worktree",
        "goal_artifact_dir",
        "rich_goal_file",
        "one_line_goal_file",
        "session_id",
        "timeout_seconds",
        "monitor_interval_seconds",
        "max_wait_windows",
        "standing_authorization",
    ]:
        assert field in props
    assert schema["parameters"]["required"] == [
        "workdir",
        "stage_id",
        "objective",
        "mode",
        "dirty_baseline_policy",
    ]
    assert props["mode"]["enum"] == ["dry_run_plan", "prepare_goal"]
    assert props["standing_authorization"]["type"] == "boolean"
    assert "codex_goal_run" in toolsets._HERMES_CORE_TOOLS
    assert toolsets.TOOLSETS["codex_goal_run"]["tools"] == ["codex_goal_run"]


def test_codex_goals_preflight_uses_features_list(monkeypatch):
    calls = []
    monkeypatch.setattr(tool.shutil, "which", lambda name: "/tmp/codex-yuna" if name == "codex-yuna" else None)

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout="goals stable true\n", stderr="")

    monkeypatch.setattr(tool.subprocess, "run", fake_run)

    result = tool._codex_goals_preflight()

    assert calls == [["/tmp/codex-yuna", "features", "list"]]
    assert result["status"] == "passed"
    assert result["checks"]["goals_feature_available"] is True
    assert result["blockers"] == []


def test_codex_goals_preflight_blocks_failed_features_list(monkeypatch):
    monkeypatch.setattr(tool.shutil, "which", lambda name: "/tmp/codex-yuna" if name == "codex-yuna" else None)

    def fake_run(argv, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(tool.subprocess, "run", fake_run)

    result = tool._codex_goals_preflight()

    assert result["status"] == "blocked"
    assert "codex_features_list_failed" in result["blockers"]
    assert "missing_goals_feature" in result["blockers"]


def test_dry_run_plan_returns_bounded_plan_and_writes_nothing(tmp_path, monkeypatch):
    repo = _clean_repo(tmp_path)
    artifact_dir = tmp_path / "artifacts"
    monkeypatch.setattr(tool, "_codex_goals_preflight", lambda: {"status": "passed", "checks": {}, "blockers": []})

    result = _call(repo, goal_artifact_dir=str(artifact_dir))

    assert result["status"] == "dry_run_plan"
    assert result["mode"] == "dry_run_plan"
    assert result["driver"] == "codex_tui_goal"
    assert result["goal_files"] == {}
    assert result["completion_trusted"] is False
    assert result["candidate_disposition"] == "planning_only"
    assert result["plan"]["launch_method"] == "official Codex TUI /goal"
    assert "codex-yuna exec" in result["plan"]["not_used"]
    assert not artifact_dir.exists()
    assert _git(repo, "status", "--porcelain") == ""


def test_prepare_goal_creates_artifacts_with_single_line_goal(tmp_path, monkeypatch):
    repo = _clean_repo(tmp_path)
    artifact_dir = tmp_path / "goal-artifacts"
    monkeypatch.setattr(tool, "_codex_goals_preflight", lambda: {"status": "passed", "checks": {}, "blockers": []})

    result = _call(repo, mode="prepare_goal", goal_artifact_dir=str(artifact_dir))

    assert result["status"] == "prepared"
    assert result["candidate_disposition"] == "needs_review"
    rich = Path(result["goal_files"]["rich_goal_file"])
    one_line = Path(result["goal_files"]["one_line_goal_file"])
    assert rich.is_file()
    assert one_line.is_file()
    assert artifact_dir in rich.parents
    assert artifact_dir in one_line.parents
    rich_text = rich.read_text(encoding="utf-8")
    one_line_text = one_line.read_text(encoding="utf-8")
    assert "# Codex Goal" in rich_text
    assert "This is candidate work for Hermes review" in rich_text
    assert "do not push, deploy, restart" in rich_text
    assert "do not use codex exec" in rich_text
    assert one_line_text.endswith("\n")
    stripped = one_line_text.rstrip("\n")
    assert stripped.startswith("/goal ")
    assert "\n" not in stripped
    assert "Scope:" in stripped
    assert "Non-goals:" in stripped
    assert "Tests:" in stripped
    assert "Stop conditions:" in stripped
    assert "Hermes review" in stripped
    assert "do not push, deploy, restart" in stripped
    assert "do not use codex exec" in stripped
    assert "raw diff" not in stripped.lower()
    assert _git(repo, "status", "--porcelain") == ""


def test_prepare_goal_rejects_artifact_dir_inside_repo(tmp_path, monkeypatch):
    repo = _clean_repo(tmp_path)
    artifact_dir = repo / "goal-artifacts"
    monkeypatch.setattr(tool, "_codex_goals_preflight", lambda: {"status": "passed", "checks": {}, "blockers": []})

    result = _call(repo, mode="prepare_goal", goal_artifact_dir=str(artifact_dir))

    assert result["status"] == "invalid_artifact_path"
    assert "artifact_path_inside_repo" in result["preflight"]["blockers"]
    assert result["goal_files"] == {}
    assert not artifact_dir.exists()
    assert _git(repo, "status", "--porcelain") == ""


def test_prepare_goal_rejects_artifact_dir_outside_tmp(tmp_path, monkeypatch):
    repo = _clean_repo(tmp_path)
    artifact_dir = Path.cwd() / "codex-goal-should-not-be-created"
    monkeypatch.setattr(tool, "_codex_goals_preflight", lambda: {"status": "passed", "checks": {}, "blockers": []})

    result = _call(repo, mode="prepare_goal", goal_artifact_dir=str(artifact_dir))

    assert result["status"] == "invalid_artifact_path"
    assert "artifact_path_outside_tmp" in result["preflight"]["blockers"]
    assert result["goal_files"] == {}
    assert not artifact_dir.exists()
    assert _git(repo, "status", "--porcelain") == ""


def test_dirty_worktree_blocks_without_artifact_writes(tmp_path, monkeypatch):
    repo = _clean_repo(tmp_path)
    artifact_dir = tmp_path / "artifacts"
    (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    def fail_preflight():
        raise AssertionError("codex preflight should not run for dirty worktree")

    monkeypatch.setattr(tool, "_codex_goals_preflight", fail_preflight)

    result = _call(repo, mode="prepare_goal", goal_artifact_dir=str(artifact_dir))

    assert result["status"] == "dirty_worktree"
    assert result["preflight"]["dirty_check"]["is_clean"] is False
    assert result["preflight"]["dirty_check"]["dirty_paths"] == ["dirty.txt"]
    assert result["goal_files"] == {}
    assert not artifact_dir.exists()


def test_unsupported_launch_goal_blocks_without_subprocess(monkeypatch):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("unsupported mode must not call subprocess")

    monkeypatch.setattr(tool.subprocess, "run", fake_run)

    result = json.loads(
        tool.codex_goal_run(
            {
                "workdir": "/tmp/repo",
                "stage_id": "slice-2",
                "objective": "Launch a goal",
                "mode": "launch_goal",
                "dirty_baseline_policy": "require-clean",
            }
        )
    )

    assert result["status"] == "unsupported_mode"
    assert result["preflight"]["status"] == "not_run"
    assert result["next_action"] == "use_dry_run_plan_or_prepare_goal"
    assert calls == []


def test_missing_goals_feature_is_reported_as_preflight_blocker(tmp_path, monkeypatch):
    repo = _clean_repo(tmp_path)
    monkeypatch.setattr(
        tool,
        "_codex_goals_preflight",
        lambda: {
            "status": "blocked",
            "checks": {"codex_binary_found": True, "goals_feature_available": False},
            "blockers": ["missing_goals_feature"],
        },
    )

    dry_run = _call(repo)
    prepare = _call(repo, mode="prepare_goal", goal_artifact_dir=str(tmp_path / "artifacts"))

    assert dry_run["status"] == "dry_run_plan"
    assert dry_run["preflight"]["status"] == "blocked"
    assert "missing_goals_feature" in dry_run["preflight"]["blockers"]
    assert prepare["status"] == "preflight_blocked"
    assert prepare["goal_files"] == {}
    assert "missing_goals_feature" in prepare["preflight"]["blockers"]


@pytest.mark.xfail(strict=True, reason="Slice 2 launch_goal PTY lifecycle is specified but not implemented yet")
def test_launch_goal_uses_pty_background_notify_and_raw_enter_without_real_tui(tmp_path, monkeypatch):
    repo = _clean_repo(tmp_path)
    one_line = tmp_path / "slice-2.goal.txt"
    one_line.write_text("/goal Complete Slice 2 only. Stop for Hermes review.\n", encoding="utf-8")
    calls = {}
    monkeypatch.setattr(tool, "_codex_goals_preflight", lambda: {"status": "passed", "checks": {}, "blockers": []})

    def fake_launch_goal_tui(*, workdir, command, pty, background, notify_on_complete, timeout_seconds):
        calls["launch"] = {
            "workdir": workdir,
            "command": command,
            "pty": pty,
            "background": background,
            "notify_on_complete": notify_on_complete,
            "timeout_seconds": timeout_seconds,
        }
        return {"session_id": "session-1", "started": True, "still_running": True, "exit_code": None}

    def fake_submit_goal_text(*, session_id, data):
        calls["submit"] = {"session_id": session_id, "data": data}

    def fake_write_goal_input(*, session_id, data):
        calls["write"] = {"session_id": session_id, "data": data}

    monkeypatch.setattr(tool, "_launch_goal_tui", fake_launch_goal_tui, raising=False)
    monkeypatch.setattr(tool, "_submit_goal_text", fake_submit_goal_text, raising=False)
    monkeypatch.setattr(tool, "_write_goal_input", fake_write_goal_input, raising=False)

    result = json.loads(
        tool.codex_goal_run(
            _args(
                repo,
                mode="launch_goal",
                one_line_goal_file=str(one_line),
                timeout_seconds=600,
            )
        )
    )

    assert result["status"] == "launched"
    assert result["process"]["session_id"] == "session-1"
    assert calls["launch"]["workdir"] == str(repo)
    assert "codex-yuna --enable goals" in calls["launch"]["command"]
    assert "codex-yuna exec" not in calls["launch"]["command"]
    assert calls["launch"]["pty"] is True
    assert calls["launch"]["background"] is True
    assert calls["launch"]["notify_on_complete"] is True
    assert calls["submit"] == {"session_id": "session-1", "data": "/goal Complete Slice 2 only. Stop for Hermes review."}
    assert calls["write"] == {"session_id": "session-1", "data": "\r"}
    assert _git(repo, "status", "--porcelain") == ""


@pytest.mark.xfail(strict=True, reason="Slice 2 launch_goal PTY lifecycle is specified but not implemented yet")
def test_launch_goal_rejects_missing_or_multiline_goal_before_tui_launch(tmp_path, monkeypatch):
    repo = _clean_repo(tmp_path)
    calls = []
    monkeypatch.setattr(tool, "_codex_goals_preflight", lambda: {"status": "passed", "checks": {}, "blockers": []})
    monkeypatch.setattr(tool, "_launch_goal_tui", lambda **kwargs: calls.append(kwargs), raising=False)

    missing = json.loads(
        tool.codex_goal_run(
            _args(
                repo,
                mode="launch_goal",
            )
        )
    )
    assert missing["status"] == "missing_goal_text"
    assert calls == []

    multiline = tmp_path / "bad.goal.txt"
    multiline.write_text("/goal first line\nsecond line\n", encoding="utf-8")
    bad = json.loads(
        tool.codex_goal_run(
            _args(
                repo,
                mode="launch_goal",
                one_line_goal_file=str(multiline),
            )
        )
    )
    assert bad["status"] == "invalid_goal_text"
    assert calls == []
