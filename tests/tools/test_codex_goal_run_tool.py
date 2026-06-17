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
    assert props["mode"]["enum"] == ["dry_run_plan", "prepare_goal", "launch_goal", "monitor_goal"]
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


def test_monitor_goal_mode_is_schema_exposed():
    schema = registry.get_schema("codex_goal_run")

    assert schema is not None
    assert schema["parameters"]["properties"]["mode"]["enum"] == [
        "dry_run_plan",
        "prepare_goal",
        "launch_goal",
        "monitor_goal",
    ]


def test_monitor_goal_idle_wait_composes_bounded_windows_without_real_tui(tmp_path, monkeypatch):
    repo = _clean_repo(tmp_path)
    polls = []
    monkeypatch.setattr(tool, "_codex_goals_preflight", lambda: {"status": "passed", "checks": {}, "blockers": []})

    def fake_poll_goal_session(*, session_id, wait_seconds):
        polls.append({"session_id": session_id, "wait_seconds": wait_seconds})
        return {
            "session_id": session_id,
            "status": "running",
            "still_running": True,
            "exit_code": None,
            "new_output": "",
        }

    monkeypatch.setattr(tool, "_poll_goal_session", fake_poll_goal_session, raising=False)

    result = json.loads(
        tool.codex_goal_run(
            _args(
                repo,
                mode="monitor_goal",
                session_id="session-1",
                monitor_interval_seconds=2,
                max_wait_windows=3,
            )
        )
    )

    assert result["status"] == "idle_wait"
    assert result["classification"] == "monitoring"
    assert result["candidate_disposition"] == "running"
    assert result["next_action"] == "continue_monitoring_or_inspect_tui"
    assert result["completion_trusted"] is False
    assert result["monitor"] == {
        "session_id": "session-1",
        "state": "idle",
        "wait_windows": 3,
        "idle_windows": 3,
        "max_wait_windows": 3,
        "monitor_interval_seconds": 2,
        "message": "No new output for 3/3 wait windows; goal may still be running or waiting for attention.",
        "recommendation": "continue_monitoring_or_inspect_tui",
    }
    assert polls == [
        {"session_id": "session-1", "wait_seconds": 2},
        {"session_id": "session-1", "wait_seconds": 2},
        {"session_id": "session-1", "wait_seconds": 2},
    ]
    assert _git(repo, "status", "--porcelain") == ""


def test_monitor_goal_running_output_is_not_reported_as_idle(tmp_path, monkeypatch):
    repo = _clean_repo(tmp_path)
    outputs = ["working 1", "working 2", "working 3"]
    monkeypatch.setattr(tool, "_codex_goals_preflight", lambda: {"status": "passed", "checks": {}, "blockers": []})

    def fake_poll_goal_session(*, session_id, wait_seconds):
        return {
            "session_id": session_id,
            "status": "running",
            "still_running": True,
            "exit_code": None,
            "new_output": outputs.pop(0),
        }

    monkeypatch.setattr(tool, "_poll_goal_session", fake_poll_goal_session, raising=False)

    result = json.loads(
        tool.codex_goal_run(_args(repo, mode="monitor_goal", session_id="session-1", max_wait_windows=3))
    )

    assert result["status"] == "running"
    assert result["classification"] == "monitoring"
    assert result["candidate_disposition"] == "running"
    assert result["next_action"] == "continue_monitoring_goal"
    assert result["monitor"]["state"] == "running"
    assert result["monitor"]["idle_windows"] == 0
    assert result["monitor"]["wait_windows"] == 3
    assert result["monitor"]["last_output"] == "working 3"


def test_monitor_goal_reports_completed_candidate_without_trusting_completion(tmp_path, monkeypatch):
    repo = _clean_repo(tmp_path)
    events = [
        {"session_id": "session-1", "status": "running", "still_running": True, "exit_code": None, "new_output": "working"},
        {"session_id": "session-1", "status": "completed", "still_running": False, "exit_code": 0, "new_output": "done"},
    ]
    monkeypatch.setattr(tool, "_codex_goals_preflight", lambda: {"status": "passed", "checks": {}, "blockers": []})
    monkeypatch.setattr(tool, "_poll_goal_session", lambda **kwargs: events.pop(0), raising=False)

    result = json.loads(
        tool.codex_goal_run(
            _args(repo, mode="monitor_goal", session_id="session-1", monitor_interval_seconds=1, max_wait_windows=5)
        )
    )

    assert result["status"] == "completed"
    assert result["candidate_disposition"] == "needs_review"
    assert result["completion_trusted"] is False
    assert result["next_action"] == "collect_candidate_for_hermes_review"
    assert result["monitor"]["state"] == "completed"
    assert result["monitor"]["last_output"] == "done"
    assert result["monitor"]["wait_windows"] == 2
    assert _git(repo, "status", "--porcelain") == ""


def test_monitor_goal_reports_failed_exit_without_trusting_completion(tmp_path, monkeypatch):
    repo = _clean_repo(tmp_path)
    monkeypatch.setattr(tool, "_codex_goals_preflight", lambda: {"status": "passed", "checks": {}, "blockers": []})
    monkeypatch.setattr(
        tool,
        "_poll_goal_session",
        lambda **kwargs: {
            "session_id": "session-1",
            "status": "failed",
            "still_running": False,
            "exit_code": 2,
            "new_output": "boom",
        },
        raising=False,
    )

    result = json.loads(tool.codex_goal_run(_args(repo, mode="monitor_goal", session_id="session-1")))

    assert result["status"] == "failed"
    assert result["classification"] == "blocked"
    assert result["candidate_disposition"] == "needs_review"
    assert result["completion_trusted"] is False
    assert result["next_action"] == "inspect_goal_failure"
    assert result["monitor"]["state"] == "failed"
    assert result["monitor"]["exit_code"] == 2
    assert result["monitor"]["last_output"] == "boom"


def test_monitor_goal_allows_dirty_candidate_worktree_as_monitor_evidence(tmp_path, monkeypatch):
    repo = _clean_repo(tmp_path)
    (repo / "candidate.txt").write_text("candidate diff\n", encoding="utf-8")

    def fail_preflight():
        raise AssertionError("monitor_goal should not run Codex goals preflight")

    monkeypatch.setattr(tool, "_codex_goals_preflight", fail_preflight)
    monkeypatch.setattr(
        tool,
        "_poll_goal_session",
        lambda **kwargs: {
            "session_id": "session-1",
            "status": "completed",
            "still_running": False,
            "exit_code": 0,
            "new_output": "candidate complete",
        },
        raising=False,
    )

    result = json.loads(tool.codex_goal_run(_args(repo, mode="monitor_goal", session_id="session-1")))

    assert result["status"] == "completed"
    assert result["preflight"]["dirty_check"]["is_clean"] is False
    assert result["preflight"]["dirty_check"]["dirty_paths"] == ["candidate.txt"]
    assert result["next_action"] == "collect_candidate_for_hermes_review"


def test_monitor_goal_requires_session_id_before_polling(tmp_path, monkeypatch):
    repo = _clean_repo(tmp_path)
    polls = []
    monkeypatch.setattr(tool, "_codex_goals_preflight", lambda: {"status": "passed", "checks": {}, "blockers": []})
    monkeypatch.setattr(tool, "_poll_goal_session", lambda **kwargs: polls.append(kwargs), raising=False)

    result = json.loads(tool.codex_goal_run(_args(repo, mode="monitor_goal", session_id="")))

    assert result["status"] == "missing_session_id"
    assert result["classification"] == "blocked"
    assert result["next_action"] == "provide_session_id_from_launch_goal"
    assert polls == []


def test_bounded_log_tail_limits_lines_and_chars_without_raw_flood():
    raw = "\n".join(f"line-{index:02d}-" + "x" * 20 for index in range(12))

    tail = tool._bounded_log_tail(raw, max_lines=3, max_chars=80)

    assert tail["line_count"] == 12
    assert tail["included_lines"] == 3
    assert tail["omitted_lines"] == 9
    assert tail["char_count"] == len(raw)
    assert tail["included_chars"] <= 80
    assert tail["omitted_chars"] == len(raw) - tail["included_chars"]
    assert tail["truncated"] is True
    assert "line-11" in tail["text"]
    assert "line-00" not in tail["text"]


def test_classify_goal_snapshot_reports_process_missing_without_guessing():
    result = tool._classify_goal_snapshot(
        {
            "session_id": "session-missing",
            "process": {"found": False},
            "log": {"raw": ""},
            "git": {"is_clean": True, "changed_files": [], "staged_files": [], "untracked_files": []},
        }
    )

    assert result["result_status"] == "process_missing"
    assert result["classification"] == "blocked"
    assert result["candidate_disposition"] == "planning_only"
    assert result["next_action"] == "inspect_process_registry"
    assert result["monitor"]["state"] == "process_missing"
    assert result["monitor"]["session_id"] == "session-missing"


def test_classify_goal_snapshot_running_output_is_not_idle():
    result = tool._classify_goal_snapshot(
        {
            "session_id": "session-1",
            "process": {"found": True, "still_running": True, "exit_code": None},
            "log": {"new_output": "working", "raw": "thinking\nworking"},
            "git": {"is_clean": True, "changed_files": [], "staged_files": [], "untracked_files": []},
            "wait_windows": 2,
            "idle_windows": 0,
        }
    )

    assert result["result_status"] == "running"
    assert result["classification"] == "monitoring"
    assert result["candidate_disposition"] == "running"
    assert result["next_action"] == "continue_monitoring_goal"
    assert result["monitor"]["state"] == "running"
    assert result["monitor"]["last_output"] == "working"
    assert result["monitor"]["log_tail"]["text"].endswith("working")


def test_classify_goal_snapshot_pasted_content_needs_attention_without_killing_process():
    result = tool._classify_goal_snapshot(
        {
            "session_id": "session-1",
            "process": {"found": True, "still_running": True, "exit_code": None},
            "log": {"new_output": "", "raw": "[Pasted Content]\ncomposer waiting"},
            "git": {"is_clean": True, "changed_files": [], "staged_files": [], "untracked_files": []},
            "wait_windows": 3,
            "idle_windows": 3,
        }
    )

    assert result["result_status"] == "needs_attention"
    assert result["classification"] == "blocked"
    assert result["candidate_disposition"] == "running"
    assert result["next_action"] == "send_raw_enter_or_ask"
    assert result["monitor"]["state"] == "pasted_content_suspected"
    assert result["monitor"]["pasted_content_suspected"] is True


def test_classify_goal_snapshot_completed_keeps_untracked_candidate_evidence():
    result = tool._classify_goal_snapshot(
        {
            "session_id": "session-1",
            "process": {"found": True, "still_running": False, "exit_code": 0},
            "log": {"new_output": "Goal achieved", "raw": "work\nGoal achieved"},
            "git": {
                "is_clean": False,
                "changed_files": [],
                "staged_files": [],
                "untracked_files": ["new_module.py"],
                "diff_stat": "",
                "staged_diff_stat": "",
            },
            "wait_windows": 4,
            "idle_windows": 0,
        }
    )

    assert result["result_status"] == "completed"
    assert result["classification"] == "monitoring"
    assert result["candidate_disposition"] == "needs_review"
    assert result["next_action"] == "collect_candidate_for_hermes_review"
    assert result["monitor"]["state"] == "completed"
    assert result["monitor"]["goal_achieved_seen"] is True
    assert result["candidate_evidence"]["untracked_files"] == ["new_module.py"]
    assert result["completion_trusted"] is False


def test_classify_goal_snapshot_exited_clean_needs_attention_not_success():
    result = tool._classify_goal_snapshot(
        {
            "session_id": "session-1",
            "process": {"found": True, "still_running": False, "exit_code": 0},
            "log": {"new_output": "", "raw": ""},
            "git": {"is_clean": True, "changed_files": [], "staged_files": [], "untracked_files": []},
            "wait_windows": 1,
            "idle_windows": 1,
        }
    )

    assert result["result_status"] == "needs_attention"
    assert result["classification"] == "blocked"
    assert result["candidate_disposition"] == "planning_only"
    assert result["next_action"] == "inspect_no_diff_exit"
    assert result["monitor"]["state"] == "process_exited_no_diff"


def test_classify_goal_snapshot_exited_nonzero_reports_failed_even_without_diff():
    result = tool._classify_goal_snapshot(
        {
            "session_id": "session-1",
            "process": {"found": True, "still_running": False, "exit_code": 2},
            "log": {"new_output": "", "raw": ""},
            "git": {"is_clean": True, "changed_files": [], "staged_files": [], "untracked_files": []},
        }
    )

    assert result["result_status"] == "failed"
    assert result["classification"] == "blocked"
    assert result["candidate_disposition"] == "needs_review"
    assert result["next_action"] == "inspect_goal_failure"
    assert result["monitor"]["state"] == "failed"
    assert result["monitor"]["exit_code"] == 2


def test_classify_goal_snapshot_exited_nonzero_with_goal_achieved_and_diff_still_failed():
    result = tool._classify_goal_snapshot(
        {
            "session_id": "session-1",
            "process": {"found": True, "still_running": False, "exit_code": 2},
            "log": {"new_output": "Goal achieved", "raw": "Goal achieved"},
            "git": {"is_clean": False, "changed_files": ["a.py"], "staged_files": [], "untracked_files": []},
        }
    )

    assert result["result_status"] == "failed"
    assert result["next_action"] == "inspect_goal_failure"
    assert result["candidate_evidence"]["changed_files"] == ["a.py"]
    assert result["monitor"]["state"] == "failed"
    assert result["monitor"]["goal_achieved_seen"] is True


def test_classify_goal_snapshot_process_missing_preserves_candidate_evidence():
    result = tool._classify_goal_snapshot(
        {
            "session_id": "session-missing",
            "process": {"found": False},
            "log": {"raw": ""},
            "git": {"is_clean": False, "changed_files": [], "staged_files": [], "untracked_files": ["new.py"]},
        }
    )

    assert result["result_status"] == "process_missing"
    assert result["candidate_evidence"]["untracked_files"] == ["new.py"]


def test_classify_goal_snapshot_pasted_content_in_new_output_takes_attention_path():
    result = tool._classify_goal_snapshot(
        {
            "session_id": "session-1",
            "process": {"found": True, "still_running": True, "exit_code": None},
            "log": {"new_output": "[Pasted Content]", "raw": "composer waiting"},
            "git": {"is_clean": True, "changed_files": [], "staged_files": [], "untracked_files": []},
            "wait_windows": 1,
            "idle_windows": 1,
        }
    )

    assert result["result_status"] == "needs_attention"
    assert result["next_action"] == "send_raw_enter_or_ask"
    assert result["monitor"]["state"] == "pasted_content_suspected"


def test_classify_goal_snapshot_goal_achieved_with_diff_while_running_collects_candidate():
    result = tool._classify_goal_snapshot(
        {
            "session_id": "session-1",
            "process": {"found": True, "still_running": True, "exit_code": None},
            "log": {"new_output": "Goal achieved", "raw": "Goal achieved\ncomposer open"},
            "git": {"is_clean": False, "changed_files": ["tools/example.py"], "staged_files": [], "untracked_files": []},
            "wait_windows": 4,
            "idle_windows": 0,
        }
    )

    assert result["result_status"] == "completed"
    assert result["next_action"] == "collect_candidate_for_hermes_review"
    assert result["candidate_evidence"]["changed_files"] == ["tools/example.py"]
    assert result["monitor"]["goal_achieved_seen"] is True


def test_classify_goal_snapshot_goal_achieved_with_diff_overrides_historical_paste_warning():
    result = tool._classify_goal_snapshot(
        {
            "session_id": "session-1",
            "process": {"found": True, "still_running": True, "exit_code": None},
            "log": {"new_output": "Goal achieved", "raw": "[Pasted Content]\nwork\nGoal achieved"},
            "git": {"is_clean": False, "changed_files": ["a.py"], "staged_files": [], "untracked_files": []},
            "wait_windows": 4,
            "idle_windows": 0,
        }
    )

    assert result["result_status"] == "completed"
    assert result["next_action"] == "collect_candidate_for_hermes_review"
    assert result["monitor"]["state"] == "completed"
    assert result["monitor"]["goal_achieved_seen"] is True


def test_classify_goal_snapshot_still_running_clean_idle_returns_idle_wait():
    result = tool._classify_goal_snapshot(
        {
            "session_id": "session-1",
            "process": {"found": True, "still_running": True, "exit_code": None},
            "log": {"new_output": "", "raw": ""},
            "git": {"is_clean": True, "changed_files": [], "staged_files": [], "untracked_files": []},
            "wait_windows": 3,
            "idle_windows": 3,
        }
    )

    assert result["result_status"] == "idle_wait"
    assert result["classification"] == "monitoring"
    assert result["candidate_disposition"] == "running"
    assert result["next_action"] == "continue_monitoring_or_inspect_tui"
    assert result["monitor"]["state"] == "idle"


@pytest.mark.xfail(reason="Slice 4C pending: disabled adapter wrappers are not implemented yet", strict=True)
def test_goal_snapshot_default_adapters_are_disabled_and_side_effect_free(tmp_path):
    missing_repo = tmp_path / "does-not-exist"

    snapshot = tool._compose_goal_snapshot(session_id="session-1", repo=missing_repo, wait_seconds=7)

    assert snapshot["session_id"] == "session-1"
    assert snapshot["wait_seconds"] == 7
    assert snapshot["adapter_status"] == {"process": "disabled", "git": "disabled"}
    assert snapshot["process"] == {"found": False, "still_running": False, "exit_code": None}
    assert snapshot["log"] == {"new_output": "", "raw": ""}
    assert snapshot["git"]["repo"] == str(missing_repo)
    assert snapshot["git"]["changed_files"] == []
    assert snapshot["git"]["staged_files"] == []
    assert snapshot["git"]["untracked_files"] == []
    assert snapshot["git"]["diff_stat"] == ""
    assert snapshot["git"]["staged_diff_stat"] == ""
    classified = tool._classify_goal_snapshot(snapshot)
    assert classified["result_status"] == "process_missing"


@pytest.mark.xfail(reason="Slice 4C pending: process replay adapter contract is not implemented yet", strict=True)
def test_collect_goal_process_snapshot_replay_normalizes_process_and_log():
    snapshot = tool._collect_goal_process_snapshot(
        session_id="session-1",
        wait_seconds=3,
        replay_snapshot={
            "process": {"found": True, "still_running": True, "exit_code": None},
            "log": {"new_output": "working", "raw": "thinking\nworking"},
        },
    )

    assert snapshot["adapter_status"] == "replay"
    assert snapshot["session_id"] == "session-1"
    assert snapshot["wait_seconds"] == 3
    assert snapshot["process"] == {"found": True, "still_running": True, "exit_code": None}
    assert snapshot["log"] == {"new_output": "working", "raw": "thinking\nworking"}


@pytest.mark.xfail(reason="Slice 4C pending: git replay adapter contract is not implemented yet", strict=True)
def test_collect_goal_git_evidence_replay_preserves_untracked_and_diff_stats(tmp_path):
    repo = tmp_path / "repo"
    replay = {
        "is_clean": False,
        "changed_files": ["changed.py"],
        "staged_files": ["staged.py"],
        "untracked_files": ["new.py"],
        "diff_stat": "changed.py | 2 ++",
        "staged_diff_stat": "staged.py | 1 +",
    }

    evidence = tool._collect_goal_git_evidence(repo=repo, replay_evidence=replay)

    assert evidence["adapter_status"] == "replay"
    assert evidence["repo"] == str(repo)
    assert evidence["is_clean"] is False
    assert evidence["changed_files"] == ["changed.py"]
    assert evidence["staged_files"] == ["staged.py"]
    assert evidence["untracked_files"] == ["new.py"]
    assert evidence["diff_stat"] == "changed.py | 2 ++"
    assert evidence["staged_diff_stat"] == "staged.py | 1 +"


@pytest.mark.xfail(reason="Slice 4C pending: composed replay snapshot contract is not implemented yet", strict=True)
def test_compose_goal_snapshot_replay_feeds_existing_classifier(tmp_path):
    repo = tmp_path / "repo"

    snapshot = tool._compose_goal_snapshot(
        session_id="session-1",
        repo=repo,
        wait_seconds=5,
        wait_windows=2,
        idle_windows=0,
        process_replay={
            "process": {"found": True, "still_running": False, "exit_code": 0},
            "log": {"new_output": "Goal achieved", "raw": "work\nGoal achieved"},
        },
        git_replay={"is_clean": False, "changed_files": [], "staged_files": [], "untracked_files": ["new.py"]},
    )

    assert snapshot["adapter_status"] == {"process": "replay", "git": "replay"}
    assert snapshot["wait_windows"] == 2
    assert snapshot["idle_windows"] == 0
    classified = tool._classify_goal_snapshot(snapshot)
    assert classified["result_status"] == "completed"
    assert classified["candidate_evidence"]["untracked_files"] == ["new.py"]


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

    no_objective = tmp_path / "empty.goal.txt"
    no_objective.write_text("/goal\n", encoding="utf-8")
    empty = json.loads(tool.codex_goal_run(_args(repo, mode="launch_goal", one_line_goal_file=str(no_objective))))
    assert empty["status"] == "invalid_goal_text"
    assert calls == []

    extra_blank = tmp_path / "extra-blank.goal.txt"
    extra_blank.write_text("/goal first line\n\n", encoding="utf-8")
    extra = json.loads(tool.codex_goal_run(_args(repo, mode="launch_goal", one_line_goal_file=str(extra_blank))))
    assert extra["status"] == "invalid_goal_text"
    assert calls == []


def test_launch_goal_default_launcher_is_disabled_and_side_effect_free(tmp_path, monkeypatch):
    repo = _clean_repo(tmp_path)
    one_line = tmp_path / "slice-2.goal.txt"
    one_line.write_text("/goal Complete Slice 2 only. Stop for Hermes review.\n", encoding="utf-8")
    monkeypatch.setattr(tool, "_codex_goals_preflight", lambda: {"status": "passed", "checks": {}, "blockers": []})

    result = json.loads(
        tool.codex_goal_run(
            _args(
                repo,
                mode="launch_goal",
                one_line_goal_file=str(one_line),
            )
        )
    )

    assert result["status"] == "launch_unavailable"
    assert "mock_launcher_only" in result["preflight"]["blockers"]
    assert result["process"]["started"] is False
    assert result["process"]["pty"] is True
    assert result["process"]["background"] is True
    assert result["process"]["notify_on_complete"] is True
    assert _git(repo, "status", "--porcelain") == ""
