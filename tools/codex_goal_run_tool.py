import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from tools.registry import registry


_SUPPORTED_MODES = {"dry_run_plan", "prepare_goal", "launch_goal", "monitor_goal", "collect_candidate"}
_SUPPORTED_DIRTY_POLICY = "require-clean"
_DRIVER = "codex_tui_goal"
_DEFAULT_ARTIFACT_ROOT = Path("/tmp/hermes-codex-goals")
_TMP_ROOT = Path("/tmp").resolve()
_LIST_LIMIT = 80
_STRING_LIMIT = 4000
_DIRTY_PATH_LIMIT = 80
_MANDATORY_NON_GOALS = [
    "do not push, deploy, restart, merge, access secrets, or run real providers/data/media without explicit Hermes/user authorization",
    "do not use codex exec; this is an official Codex TUI /goal handoff",
]


def _bound(value: Any) -> Any:
    if isinstance(value, str):
        if len(value) <= _STRING_LIMIT:
            return value
        return value[: _STRING_LIMIT - 14] + "...[truncated]"
    if isinstance(value, list):
        items = [_bound(item) for item in value[:_LIST_LIMIT]]
        if len(value) > _LIST_LIMIT:
            items.append(f"...[{len(value) - _LIST_LIMIT} more]")
        return items
    if isinstance(value, dict):
        return {str(key)[:_STRING_LIMIT]: _bound(item) for key, item in value.items()}
    return value


def _json_result(payload: dict[str, Any]) -> str:
    return json.dumps(_bound(payload), ensure_ascii=False)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
    )


def _resolve_repo(workdir: Any) -> tuple[Path | None, str | None, str | None]:
    if not isinstance(workdir, str) or not workdir.strip():
        return None, None, "missing_workdir"
    candidate = Path(workdir).expanduser().resolve()
    if not candidate.is_dir():
        return None, None, "workdir_not_found"
    proc = _git(candidate, "rev-parse", "--show-toplevel")
    if proc.returncode != 0:
        return None, None, "not_git_repo"
    repo = Path(proc.stdout.strip()).resolve()
    head_proc = _git(repo, "rev-parse", "HEAD")
    git_head = head_proc.stdout.strip() if head_proc.returncode == 0 else None
    return repo, git_head, None


def _dirty_check(repo: Path) -> dict[str, Any]:
    proc = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    lines = [line for line in proc.stdout.splitlines() if line]
    paths: list[str] = []
    for line in lines:
        path = line[3:] if len(line) > 3 else line
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.append(path.strip())
    digest = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()[:24]
    return {
        "is_clean": proc.returncode == 0 and not lines,
        "dirty_count": len(paths),
        "porcelain_count": len(lines),
        "dirty_paths": paths[:_DIRTY_PATH_LIMIT],
        "dirty_paths_truncated": len(paths) > _DIRTY_PATH_LIMIT,
        "dirty_state_id": digest,
    }


def _git_stdout_lines(proc: subprocess.CompletedProcess) -> list[str]:
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _collect_candidate_git_evidence(repo: Path) -> dict[str, Any]:
    changed_proc = _git(repo, "diff", "--name-only")
    staged_proc = _git(repo, "diff", "--cached", "--name-only")
    untracked_proc = _git(repo, "ls-files", "--others", "--exclude-standard")
    diff_stat_proc = _git(repo, "diff", "--stat")
    staged_diff_stat_proc = _git(repo, "diff", "--cached", "--stat")
    status_proc = _git(repo, "status", "--short", "--branch", "--untracked-files=all")
    errors = []
    for label, proc in [
        ("changed_files", changed_proc),
        ("staged_files", staged_proc),
        ("untracked_files", untracked_proc),
        ("diff_stat", diff_stat_proc),
        ("staged_diff_stat", staged_diff_stat_proc),
        ("status_short", status_proc),
    ]:
        if proc.returncode != 0:
            errors.append({"source": label, "stderr": proc.stderr.strip()})

    changed_files = _git_stdout_lines(changed_proc)
    staged_files = _git_stdout_lines(staged_proc)
    untracked_files = _git_stdout_lines(untracked_proc)
    return {
        "repo": str(repo),
        "is_clean": not (changed_files or staged_files or untracked_files),
        "changed_files": changed_files,
        "staged_files": staged_files,
        "untracked_files": untracked_files,
        "diff_stat": diff_stat_proc.stdout.strip() if diff_stat_proc.returncode == 0 else "",
        "staged_diff_stat": staged_diff_stat_proc.stdout.strip() if staged_diff_stat_proc.returncode == 0 else "",
        "status_short": status_proc.stdout.strip() if status_proc.returncode == 0 else "",
        "errors": errors,
    }


def _build_candidate_review_handoff(
    *,
    repo: Path,
    args: dict[str, Any],
    git_head: str | None,
    dirty: dict[str, Any],
    candidate_evidence: dict[str, Any],
) -> dict[str, Any]:
    has_candidate_changes = bool(
        candidate_evidence.get("changed_files")
        or candidate_evidence.get("staged_files")
        or candidate_evidence.get("untracked_files")
    )
    status = "candidate_ready_for_review" if has_candidate_changes else "no_candidate_changes"
    return {
        "status": status,
        "completion_trusted": False,
        "raw_log_included": False,
        "review_packet": {
            "driver": _DRIVER,
            "stage_id": args.get("stage_id"),
            "workdir": str(repo),
            "git_head": git_head,
            "objective": args.get("objective"),
            "scope": {
                "allowed_files": _string_list(args.get("allowed_files")),
                "allowed_globs": _string_list(args.get("allowed_globs")),
            },
            "required_verification": _string_list(args.get("required_verification")),
            "candidate_evidence": candidate_evidence,
            "dirty_check": dirty,
            "review_guidance": [
                "inspect_changed_staged_and_untracked_files",
                "run_required_verification_before_success_claim",
                "treat_codex_goal_output_as_untrusted_candidate_evidence",
            ],
        },
    }


def _codex_goals_preflight() -> dict[str, Any]:
    codex_path = shutil.which("codex-yuna") or shutil.which("codex")
    checks: dict[str, Any] = {
        "codex_binary_found": codex_path is not None,
        "goals_feature_available": False,
        "goals_feature": "missing",
    }
    blockers: list[str] = []
    if not codex_path:
        blockers.extend(["missing_codex_binary", "missing_goals_feature"])
        return {"status": "blocked", "checks": checks, "blockers": blockers}

    try:
        proc = subprocess.run(
            [codex_path, "features", "list"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
    except Exception:
        proc = None

    if proc is not None and proc.returncode != 0:
        blockers.append("codex_features_list_failed")

    feature_text = ((proc.stdout or "") + "\n" + (proc.stderr or "")).lower() if proc else ""
    goal_lines = [line.strip() for line in feature_text.splitlines() if "goals" in line]
    checks["goals_feature_available"] = any(
        parts and parts[0] == "goals" and "true" in parts for parts in (line.split() for line in goal_lines)
    )
    checks["goals_feature"] = goal_lines[0] if goal_lines else "missing"
    if not checks["goals_feature_available"]:
        blockers.append("missing_goals_feature")
    return {"status": "passed" if not blockers else "blocked", "checks": checks, "blockers": blockers}


def _base_result(
    *,
    status: str,
    mode: Any,
    workdir: Any = None,
    stage_id: Any = None,
    preflight: dict[str, Any] | None = None,
    classification: str = "planning",
    next_action: str = "review_result",
    candidate_disposition: str = "planning_only",
    goal_files: dict[str, str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    result = {
        "status": status,
        "mode": mode,
        "workdir": str(workdir) if workdir is not None else None,
        "stage_id": stage_id,
        "driver": _DRIVER,
        "goal_files": goal_files or {},
        "preflight": preflight or {},
        "classification": classification,
        "next_action": next_action,
        "candidate_disposition": candidate_disposition,
        "completion_trusted": False,
    }
    result.update(extra)
    return result


def _scope_summary(args: dict[str, Any]) -> str:
    files = _string_list(args.get("allowed_files"))
    globs = _string_list(args.get("allowed_globs"))
    parts = []
    if files:
        parts.append("files: " + ", ".join(files[:20]))
    if globs:
        parts.append("globs: " + ", ".join(globs[:20]))
    return "; ".join(parts) if parts else "scope not specified"


def _sentence_list(label: str, values: list[str], fallback: str) -> str:
    if not values:
        return f"{label}: {fallback}"
    return f"{label}: " + "; ".join(item.replace("\n", " ").strip() for item in values[:20])


def _non_goals_with_mandatory(args: dict[str, Any]) -> list[str]:
    non_goals = _string_list(args.get("non_goals"))
    for item in _MANDATORY_NON_GOALS:
        if item not in non_goals:
            non_goals.append(item)
    return non_goals


def _one_line_goal(args: dict[str, Any]) -> str:
    objective = str(args.get("objective", "")).replace("\n", " ").strip()
    docs = _string_list(args.get("docs_to_read"))
    non_goals = _non_goals_with_mandatory(args)
    verification = _string_list(args.get("required_verification"))
    stop_conditions = _string_list(args.get("stop_conditions"))
    parts = [
        f"/goal {objective}",
        f"Scope: {_scope_summary(args)}",
        _sentence_list("Docs", docs, "none specified"),
        _sentence_list("Non-goals", non_goals, "do not expand beyond stated scope"),
        _sentence_list("Tests", verification, "Hermes will verify separately"),
        _sentence_list("Stop conditions", stop_conditions, "stop for blockers or uncertainty"),
        "Return a candidate for Hermes review; do not claim completion without Hermes review.",
    ]
    return " | ".join(part for part in parts if part).replace("\r", " ").replace("\n", " ")


def _rich_goal_markdown(args: dict[str, Any], repo: Path, git_head: str | None) -> str:
    def bullets(values: list[str]) -> str:
        return "\n".join(f"- {item}" for item in values) if values else "- None specified"

    return "\n".join(
        [
            "# Codex Goal",
            "",
            f"Stage ID: {args.get('stage_id')}",
            f"Workdir: {repo}",
            f"Git HEAD: {git_head or 'unknown'}",
            "",
            "## Objective",
            str(args.get("objective", "")).strip(),
            "",
            "## Docs To Read",
            bullets(_string_list(args.get("docs_to_read"))),
            "",
            "## Allowed Files",
            bullets(_string_list(args.get("allowed_files"))),
            "",
            "## Allowed Globs",
            bullets(_string_list(args.get("allowed_globs"))),
            "",
            "## Non Goals",
            bullets(_non_goals_with_mandatory(args)),
            "",
            "## Required Verification",
            bullets(_string_list(args.get("required_verification"))),
            "",
            "## Stop Conditions",
            bullets(_string_list(args.get("stop_conditions"))),
            "",
            "## Review",
            "This is candidate work for Hermes review. Do not treat completion as trusted.",
            "",
        ]
    )


def _safe_artifact_name(stage_id: Any, objective: Any) -> str:
    raw = f"{stage_id}-{objective}"
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in str(raw).lower())
    safe = "-".join(part for part in safe.split("-") if part)[:80]
    digest = hashlib.sha256(str(raw).encode("utf-8")).hexdigest()[:10]
    return f"{safe or 'goal'}-{digest}"


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def _artifact_path_error(path: Path, repo: Path) -> str | None:
    if not _is_relative_to(path, _TMP_ROOT):
        return "artifact_path_outside_tmp"
    if _is_relative_to(path, repo):
        return "artifact_path_inside_repo"
    return None


def _artifact_paths(args: dict[str, Any], repo: Path) -> tuple[Path, Path, str | None]:
    root_value = args.get("goal_artifact_dir") or str(_DEFAULT_ARTIFACT_ROOT)
    root = Path(str(root_value)).expanduser().resolve()
    name = _safe_artifact_name(args.get("stage_id"), args.get("objective"))
    rich = args.get("rich_goal_file")
    one_line = args.get("one_line_goal_file")
    rich_path = Path(str(rich)).expanduser().resolve() if rich else root / f"{name}.md"
    one_line_path = Path(str(one_line)).expanduser().resolve() if one_line else root / f"{name}.goal.txt"
    for candidate in (root, rich_path, one_line_path):
        error = _artifact_path_error(candidate, repo)
        if error:
            return rich_path, one_line_path, error
    return rich_path, one_line_path, None


def _write_goal_files(args: dict[str, Any], repo: Path, git_head: str | None) -> dict[str, str]:
    rich_path, one_line_path, artifact_error = _artifact_paths(args, repo)
    if artifact_error:
        raise ValueError(artifact_error)
    rich_path.parent.mkdir(parents=True, exist_ok=True)
    one_line_path.parent.mkdir(parents=True, exist_ok=True)
    rich_path.write_text(_rich_goal_markdown(args, repo, git_head), encoding="utf-8")
    one_line_path.write_text(_one_line_goal(args) + "\n", encoding="utf-8")
    return {"rich_goal_file": str(rich_path), "one_line_goal_file": str(one_line_path)}


def _read_one_line_goal(args: dict[str, Any], repo: Path) -> tuple[str | None, str | None]:
    goal_file = args.get("one_line_goal_file")
    if not isinstance(goal_file, str) or not goal_file.strip():
        return None, "missing_goal_text"
    goal_path = Path(goal_file).expanduser().resolve()
    path_error = _artifact_path_error(goal_path, repo)
    if path_error:
        return None, path_error
    try:
        text = goal_path.read_text(encoding="utf-8")
    except OSError:
        return None, "goal_text_not_readable"
    lines = text.splitlines()
    if len(lines) != 1:
        return None, "invalid_goal_text"
    stripped = lines[0].strip()
    if not stripped.startswith("/goal ") or not stripped[len("/goal ") :].strip():
        return None, "invalid_goal_text"
    return stripped, None


def _coerce_timeout_seconds(value: Any) -> int:
    if isinstance(value, int) and value > 0:
        return value
    return 600


def _coerce_positive_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return max(minimum, min(value, maximum))
    return default


def _launch_goal_tui(
    *,
    workdir: str,
    command: str,
    pty: bool,
    background: bool,
    notify_on_complete: bool,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Mock-only launch hook for Slice 2.

    The real PTY launcher is intentionally not wired in this slice. Tests may
    monkeypatch this function to prove lifecycle orchestration without starting
    Codex TUI.
    """
    return {
        "started": False,
        "status": "mock_launcher_only",
        "blockers": ["mock_launcher_only"],
        "workdir": workdir,
        "command": command,
        "pty": pty,
        "background": background,
        "notify_on_complete": notify_on_complete,
        "timeout_seconds": timeout_seconds,
    }


def _submit_goal_text(*, session_id: str, data: str) -> dict[str, Any]:
    """Mockable submit hook. Default performs no side effects."""
    return {"submitted": False, "status": "mock_submit_only", "session_id": session_id, "chars": len(data)}


def _write_goal_input(*, session_id: str, data: str) -> dict[str, Any]:
    """Mockable raw-input hook. Default performs no side effects."""
    return {"written": False, "status": "mock_write_only", "session_id": session_id, "chars": len(data)}


def _poll_goal_session(*, session_id: str, wait_seconds: int) -> dict[str, Any]:
    """Mockable monitor hook. Default performs no process, terminal, or TUI work."""
    return {
        "session_id": session_id,
        "status": "running",
        "still_running": True,
        "exit_code": None,
        "new_output": "",
        "wait_seconds": wait_seconds,
    }


def _bounded_log_tail(raw: str, *, max_lines: int, max_chars: int) -> dict[str, Any]:
    text = raw if isinstance(raw, str) else str(raw or "")
    lines = text.splitlines()
    line_count = len(lines)
    limited_lines = lines[-max(0, max_lines) :] if max_lines > 0 else []
    tail = "\n".join(limited_lines)
    if max_chars >= 0 and len(tail) > max_chars:
        tail = tail[-max_chars:] if max_chars else ""
    included_chars = len(tail)
    return {
        "text": tail,
        "line_count": line_count,
        "included_lines": len(limited_lines),
        "omitted_lines": max(0, line_count - len(limited_lines)),
        "char_count": len(text),
        "included_chars": included_chars,
        "omitted_chars": max(0, len(text) - included_chars),
        "truncated": line_count > len(limited_lines) or len(text) > included_chars,
    }


def _normalize_goal_process(value: Any) -> dict[str, Any]:
    process = value if isinstance(value, dict) else {}
    exit_code = process.get("exit_code")
    if isinstance(exit_code, bool) or not isinstance(exit_code, int):
        exit_code = None
    return {
        "found": bool(process.get("found", False)),
        "still_running": bool(process.get("still_running", False)),
        "exit_code": exit_code,
    }


def _normalize_goal_log(value: Any) -> dict[str, str]:
    log = value if isinstance(value, dict) else {}
    return {
        "new_output": str(log.get("new_output") or ""),
        "raw": str(log.get("raw") or ""),
    }


def _normalize_goal_git_evidence(repo: Path, value: Any) -> dict[str, Any]:
    evidence = value if isinstance(value, dict) else {}
    return {
        "repo": str(repo),
        "is_clean": bool(evidence.get("is_clean", True)),
        "changed_files": _string_list(evidence.get("changed_files")),
        "staged_files": _string_list(evidence.get("staged_files")),
        "untracked_files": _string_list(evidence.get("untracked_files")),
        "diff_stat": str(evidence.get("diff_stat") or ""),
        "staged_diff_stat": str(evidence.get("staged_diff_stat") or ""),
    }


def _collect_goal_process_snapshot(
    *,
    session_id: str,
    wait_seconds: int,
    replay_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(replay_snapshot, dict):
        return {
            "adapter_status": "replay",
            "session_id": str(session_id),
            "wait_seconds": wait_seconds,
            "process": _normalize_goal_process(replay_snapshot.get("process")),
            "log": _normalize_goal_log(replay_snapshot.get("log")),
        }

    return {
        "adapter_status": "disabled",
        "session_id": str(session_id),
        "wait_seconds": wait_seconds,
        "process": {"found": False, "still_running": False, "exit_code": None},
        "log": {"new_output": "", "raw": ""},
    }


def _collect_goal_git_evidence(
    *,
    repo: Path,
    replay_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(replay_evidence, dict):
        return {
            "adapter_status": "replay",
            **_normalize_goal_git_evidence(repo, replay_evidence),
        }

    return {
        "adapter_status": "disabled",
        **_normalize_goal_git_evidence(repo, {}),
    }


def _compose_goal_snapshot(
    *,
    session_id: str,
    repo: Path,
    wait_seconds: int,
    wait_windows: int | None = None,
    idle_windows: int | None = None,
    process_replay: dict[str, Any] | None = None,
    git_replay: dict[str, Any] | None = None,
) -> dict[str, Any]:
    process_snapshot = _collect_goal_process_snapshot(
        session_id=session_id,
        wait_seconds=wait_seconds,
        replay_snapshot=process_replay,
    )
    git_evidence = _collect_goal_git_evidence(repo=repo, replay_evidence=git_replay)
    snapshot = {
        "session_id": str(session_id),
        "wait_seconds": wait_seconds,
        "adapter_status": {
            "process": process_snapshot["adapter_status"],
            "git": git_evidence["adapter_status"],
        },
        "process": process_snapshot["process"],
        "log": process_snapshot["log"],
        "git": git_evidence,
    }
    if wait_windows is not None:
        snapshot["wait_windows"] = wait_windows
    if idle_windows is not None:
        snapshot["idle_windows"] = idle_windows
    return snapshot


def _classify_goal_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    session_id = str(snapshot.get("session_id") or "")
    process = snapshot.get("process") if isinstance(snapshot.get("process"), dict) else {}
    log = snapshot.get("log") if isinstance(snapshot.get("log"), dict) else {}
    git = snapshot.get("git") if isinstance(snapshot.get("git"), dict) else {}
    raw_log = str(log.get("raw") or "")
    new_output = str(log.get("new_output") or "")
    log_tail = _bounded_log_tail(raw_log, max_lines=40, max_chars=4000)
    combined_log = f"{raw_log}\n{new_output}".lower()
    goal_achieved_seen = "goal achieved" in combined_log
    goal_blocked_seen = "goal blocked" in combined_log
    pasted_content_suspected = "[pasted content]" in combined_log
    wait_windows = snapshot.get("wait_windows")
    idle_windows = snapshot.get("idle_windows")

    changed_files = _string_list(git.get("changed_files"))
    staged_files = _string_list(git.get("staged_files"))
    untracked_files = _string_list(git.get("untracked_files"))
    candidate_evidence = {
        "changed_files": changed_files,
        "staged_files": staged_files,
        "untracked_files": untracked_files,
        "diff_stat": str(git.get("diff_stat") or ""),
        "staged_diff_stat": str(git.get("staged_diff_stat") or ""),
    }
    has_candidate_evidence = bool(changed_files or staged_files or untracked_files)
    still_running = bool(process.get("still_running"))
    exit_code = process.get("exit_code")

    def monitor(state: str, **extra: Any) -> dict[str, Any]:
        data = {
            "session_id": session_id,
            "state": state,
            "wait_windows": wait_windows,
            "idle_windows": idle_windows,
            "log_tail": log_tail,
        }
        if new_output:
            data["last_output"] = new_output
        data.update(extra)
        return data

    if process.get("found") is False:
        return {
            "result_status": "process_missing",
            "classification": "blocked",
            "candidate_disposition": "planning_only",
            "next_action": "inspect_process_registry",
            "completion_trusted": False,
            "monitor": monitor("process_missing"),
            "candidate_evidence": candidate_evidence,
        }

    if not still_running and exit_code not in (None, 0):
        return {
            "result_status": "failed",
            "classification": "blocked",
            "candidate_disposition": "needs_review",
            "next_action": "inspect_goal_failure",
            "completion_trusted": False,
            "monitor": monitor("failed", exit_code=exit_code, goal_achieved_seen=goal_achieved_seen),
            "candidate_evidence": candidate_evidence,
        }

    if goal_achieved_seen and has_candidate_evidence:
        return {
            "result_status": "completed",
            "classification": "monitoring",
            "candidate_disposition": "needs_review",
            "next_action": "collect_candidate_for_hermes_review",
            "completion_trusted": False,
            "monitor": monitor("completed", goal_achieved_seen=True, exit_code=exit_code),
            "candidate_evidence": candidate_evidence,
        }

    if goal_blocked_seen and has_candidate_evidence:
        return {
            "result_status": "completed",
            "classification": "monitoring",
            "candidate_disposition": "needs_review",
            "next_action": "collect_candidate_for_hermes_review",
            "completion_trusted": False,
            "monitor": monitor("completed", goal_blocked_seen=True, exit_code=exit_code),
            "candidate_evidence": candidate_evidence,
        }

    if still_running and pasted_content_suspected and not has_candidate_evidence:
        return {
            "result_status": "needs_attention",
            "classification": "blocked",
            "candidate_disposition": "running",
            "next_action": "send_raw_enter_or_ask",
            "completion_trusted": False,
            "monitor": monitor("pasted_content_suspected", pasted_content_suspected=True),
            "candidate_evidence": candidate_evidence,
        }

    if still_running and new_output:
        return {
            "result_status": "running",
            "classification": "monitoring",
            "candidate_disposition": "running",
            "next_action": "continue_monitoring_goal",
            "completion_trusted": False,
            "monitor": monitor("running"),
            "candidate_evidence": candidate_evidence,
        }

    if still_running and not has_candidate_evidence:
        return {
            "result_status": "idle_wait",
            "classification": "monitoring",
            "candidate_disposition": "running",
            "next_action": "continue_monitoring_or_inspect_tui",
            "completion_trusted": False,
            "monitor": monitor("idle", recommendation="continue_monitoring_or_inspect_tui"),
            "candidate_evidence": candidate_evidence,
        }

    if not still_running and exit_code == 0 and has_candidate_evidence:
        return {
            "result_status": "completed",
            "classification": "monitoring",
            "candidate_disposition": "needs_review",
            "next_action": "collect_candidate_for_hermes_review",
            "completion_trusted": False,
            "monitor": monitor("completed", goal_achieved_seen=goal_achieved_seen, exit_code=exit_code),
            "candidate_evidence": candidate_evidence,
        }

    if not still_running and exit_code == 0:
        return {
            "result_status": "needs_attention",
            "classification": "blocked",
            "candidate_disposition": "planning_only",
            "next_action": "inspect_no_diff_exit",
            "completion_trusted": False,
            "monitor": monitor("process_exited_no_diff", exit_code=exit_code),
            "candidate_evidence": candidate_evidence,
        }

    return {
        "result_status": "running" if still_running else "needs_attention",
        "classification": "monitoring" if still_running else "blocked",
        "candidate_disposition": "running" if still_running else "needs_review",
        "next_action": "continue_monitoring_goal" if still_running else "inspect_goal_failure",
        "completion_trusted": False,
        "monitor": monitor("running" if still_running else "failed", exit_code=exit_code),
        "candidate_evidence": candidate_evidence,
    }


def _goal_adapter_stop_condition(classification: dict[str, Any]) -> dict[str, Any]:
    completion_trusted = bool(classification.get("completion_trusted", False))
    result_status = str(classification.get("result_status") or "")
    next_action = str(classification.get("next_action") or "")
    state = str(classification.get("classification") or "")

    if result_status == "completed" and next_action == "collect_candidate_for_hermes_review":
        return {
            "should_stop": True,
            "reason": "candidate_ready_for_review",
            "completion_trusted": completion_trusted,
        }

    if result_status in {"failed", "needs_attention", "process_missing"}:
        return {
            "should_stop": True,
            "reason": result_status,
            "completion_trusted": completion_trusted,
        }

    if state == "blocked":
        return {
            "should_stop": True,
            "reason": "blocked",
            "completion_trusted": completion_trusted,
        }

    return {
        "should_stop": False,
        "reason": "continue_monitoring",
        "completion_trusted": completion_trusted,
    }


def _run_goal_adapter_once(
    *,
    session_id: str,
    repo: Path,
    wait_seconds: int,
    wait_windows: int | None = None,
    idle_windows: int | None = None,
    adapter_enabled: bool = False,
    allow_real_adapter: bool = False,
    process_runner: Any = None,
    git_runner: Any = None,
) -> dict[str, Any]:
    if not adapter_enabled:
        snapshot = _compose_goal_snapshot(
            session_id=session_id,
            repo=repo,
            wait_seconds=wait_seconds,
            wait_windows=wait_windows,
            idle_windows=idle_windows,
        )
        classification = _classify_goal_snapshot(snapshot)
        return {
            "status": "adapter_disabled",
            "adapter_status": "disabled",
            "blockers": ["real_adapter_disabled"],
            "snapshot": snapshot,
            "classification": classification,
            "stop_condition": _goal_adapter_stop_condition(classification),
            "completion_trusted": False,
        }

    if not allow_real_adapter:
        snapshot = _compose_goal_snapshot(
            session_id=session_id,
            repo=repo,
            wait_seconds=wait_seconds,
            wait_windows=wait_windows,
            idle_windows=idle_windows,
        )
        classification = _classify_goal_snapshot(snapshot)
        return {
            "status": "real_adapter_not_authorized",
            "adapter_status": "blocked",
            "blockers": ["real_adapter_not_authorized"],
            "snapshot": snapshot,
            "classification": classification,
            "stop_condition": _goal_adapter_stop_condition(classification),
            "completion_trusted": False,
        }

    blockers = []
    if not callable(process_runner):
        blockers.append("missing_process_runner")
    if not callable(git_runner):
        blockers.append("missing_git_runner")
    if blockers:
        snapshot = _compose_goal_snapshot(
            session_id=session_id,
            repo=repo,
            wait_seconds=wait_seconds,
            wait_windows=wait_windows,
            idle_windows=idle_windows,
        )
        classification = _classify_goal_snapshot(snapshot)
        return {
            "status": "real_adapter_runner_missing",
            "adapter_status": "blocked",
            "blockers": blockers,
            "snapshot": snapshot,
            "classification": classification,
            "stop_condition": _goal_adapter_stop_condition(classification),
            "completion_trusted": False,
        }

    process_replay = process_runner(session_id=session_id, wait_seconds=wait_seconds)
    git_replay = git_runner(repo=repo)
    snapshot = _compose_goal_snapshot(
        session_id=session_id,
        repo=repo,
        wait_seconds=wait_seconds,
        wait_windows=wait_windows,
        idle_windows=idle_windows,
        process_replay=process_replay,
        git_replay=git_replay,
    )
    classification = _classify_goal_snapshot(snapshot)
    return {
        "status": classification["result_status"],
        "adapter_status": "injected",
        "blockers": [],
        "snapshot": snapshot,
        "classification": classification,
        "stop_condition": _goal_adapter_stop_condition(classification),
        "completion_trusted": False,
    }


def _monitor_goal_session(args: dict[str, Any]) -> dict[str, Any]:
    session_id = str(args.get("session_id") or "").strip()
    interval = _coerce_positive_int(args.get("monitor_interval_seconds"), default=30, minimum=1, maximum=300)
    max_windows = _coerce_positive_int(args.get("max_wait_windows"), default=3, minimum=1, maximum=20)

    last_output = ""
    idle_windows = 0
    for window in range(1, max_windows + 1):
        poll = _poll_goal_session(session_id=session_id, wait_seconds=interval)
        output = str(poll.get("new_output") or "")
        if output:
            last_output = output
            idle_windows = 0
        else:
            idle_windows += 1

        status = str(poll.get("status") or "")
        still_running = bool(poll.get("still_running", status == "running"))
        if status == "completed" or (not still_running and poll.get("exit_code") == 0):
            return {
                "result_status": "completed",
                "classification": "monitoring",
                "candidate_disposition": "needs_review",
                "next_action": "collect_candidate_for_hermes_review",
                "monitor": {
                    "session_id": session_id,
                    "state": "completed",
                    "wait_windows": window,
                    "idle_windows": idle_windows,
                    "max_wait_windows": max_windows,
                    "monitor_interval_seconds": interval,
                    "exit_code": poll.get("exit_code"),
                    "last_output": last_output,
                },
            }
        if status == "failed" or (not still_running and poll.get("exit_code") not in (None, 0)):
            return {
                "result_status": "failed",
                "classification": "blocked",
                "candidate_disposition": "needs_review",
                "next_action": "inspect_goal_failure",
                "monitor": {
                    "session_id": session_id,
                    "state": "failed",
                    "wait_windows": window,
                    "idle_windows": idle_windows,
                    "max_wait_windows": max_windows,
                    "monitor_interval_seconds": interval,
                    "exit_code": poll.get("exit_code"),
                    "last_output": last_output,
                },
            }

    if last_output and idle_windows == 0:
        return {
            "result_status": "running",
            "classification": "monitoring",
            "candidate_disposition": "running",
            "next_action": "continue_monitoring_goal",
            "monitor": {
                "session_id": session_id,
                "state": "running",
                "wait_windows": max_windows,
                "idle_windows": 0,
                "max_wait_windows": max_windows,
                "monitor_interval_seconds": interval,
                "last_output": last_output,
            },
        }

    monitor = {
        "session_id": session_id,
        "state": "idle",
        "wait_windows": max_windows,
        "idle_windows": idle_windows,
        "max_wait_windows": max_windows,
        "monitor_interval_seconds": interval,
        "message": (
            f"No new output for {idle_windows}/{max_windows} wait windows; "
            "goal may still be running or waiting for attention."
        ),
        "recommendation": "continue_monitoring_or_inspect_tui",
    }
    if last_output:
        monitor["last_output"] = last_output
    return {
        "result_status": "idle_wait",
        "classification": "monitoring",
        "candidate_disposition": "running",
        "next_action": "continue_monitoring_or_inspect_tui",
        "monitor": monitor,
    }


def _validate_required(args: dict[str, Any]) -> str | None:
    for field in ("workdir", "stage_id", "objective", "mode", "dirty_baseline_policy"):
        value = args.get(field)
        if not isinstance(value, str) or not value.strip():
            return f"missing_required_{field}"
    return None


def codex_goal_run(args: dict[str, Any]) -> str:
    if not isinstance(args, dict):
        args = {}

    mode = args.get("mode")
    if mode not in _SUPPORTED_MODES:
        return _json_result(
            _base_result(
                status="unsupported_mode",
                mode=mode,
                workdir=args.get("workdir"),
                stage_id=args.get("stage_id"),
                preflight={"status": "not_run", "blockers": ["unsupported_mode"]},
                classification="rejected",
                next_action="use_dry_run_plan_prepare_goal_launch_goal_monitor_goal_or_collect_candidate",
                candidate_disposition="planning_only",
                reason="Supported modes are dry_run_plan, prepare_goal, launch_goal, monitor_goal, and collect_candidate.",
            )
        )

    required_error = _validate_required(args)
    if required_error:
        return _json_result(
            _base_result(
                status="rejected",
                mode=mode,
                workdir=args.get("workdir"),
                stage_id=args.get("stage_id"),
                preflight={"status": "not_run", "blockers": [required_error]},
                classification="rejected",
                next_action="provide_required_fields",
            )
        )

    dirty_policy = args.get("dirty_baseline_policy")
    if dirty_policy != _SUPPORTED_DIRTY_POLICY:
        return _json_result(
            _base_result(
                status="unsupported_dirty_policy",
                mode=mode,
                workdir=args.get("workdir"),
                stage_id=args.get("stage_id"),
                preflight={"status": "not_run", "blockers": ["unsupported_dirty_policy"]},
                classification="rejected",
                next_action="use_require_clean_dirty_baseline_policy",
            )
        )

    repo, git_head, repo_error = _resolve_repo(args.get("workdir"))
    if repo is None:
        return _json_result(
            _base_result(
                status="rejected_workdir",
                mode=mode,
                workdir=args.get("workdir"),
                stage_id=args.get("stage_id"),
                preflight={"status": "blocked", "blockers": [repo_error or "invalid_workdir"]},
                classification="rejected",
                next_action="provide_existing_git_repo_workdir",
            )
        )

    dirty = _dirty_check(repo)
    plan = {
        "driver": _DRIVER,
        "launch_method": "official Codex TUI /goal",
        "not_used": ["codex exec", "codex-yuna exec"],
        "would_write_goal_files": mode == "prepare_goal",
        "scope": {
            "allowed_files": _string_list(args.get("allowed_files")),
            "allowed_globs": _string_list(args.get("allowed_globs")),
        },
        "docs_to_read": _string_list(args.get("docs_to_read")),
        "stop_conditions": _string_list(args.get("stop_conditions")),
    }

    if mode == "monitor_goal":
        session_id = str(args.get("session_id") or "").strip()
        adapter_enabled = args.get("adapter_enabled") is True
        allow_real_adapter = args.get("allow_real_adapter") is True
        preflight = {
            "status": "monitoring",
            "blockers": [],
            "dirty_check": dirty,
            "codex": {
                "status": "not_run",
                "reason": "monitor_goal_adapter_call_site" if adapter_enabled else "monitor_goal_mock_only",
                "allow_real_adapter": allow_real_adapter,
            },
        }
        if not session_id:
            return _json_result(
                _base_result(
                    status="missing_session_id",
                    mode=mode,
                    workdir=repo,
                    stage_id=args.get("stage_id"),
                    preflight={**preflight, "blockers": ["missing_session_id"]},
                    classification="blocked",
                    next_action="provide_session_id_from_launch_goal",
                    candidate_disposition="planning_only",
                    dirty_baseline_policy=dirty_policy,
                    git_head=git_head,
                    plan=plan,
                )
            )

        if adapter_enabled:
            interval = _coerce_positive_int(args.get("monitor_interval_seconds"), default=30, minimum=1, maximum=300)
            adapter_result = _run_goal_adapter_once(
                session_id=session_id,
                repo=repo,
                wait_seconds=interval,
                wait_windows=1,
                idle_windows=0,
                adapter_enabled=True,
                allow_real_adapter=allow_real_adapter,
            )
            classification = (
                adapter_result.get("classification") if isinstance(adapter_result.get("classification"), dict) else {}
            )
            return _json_result(
                _base_result(
                    status=str(adapter_result.get("status") or "adapter_error"),
                    mode=mode,
                    workdir=repo,
                    stage_id=args.get("stage_id"),
                    preflight=preflight,
                    classification=str(classification.get("classification") or "blocked"),
                    next_action=str(classification.get("next_action") or "inspect_process_registry"),
                    candidate_disposition=str(classification.get("candidate_disposition") or "planning_only"),
                    dirty_baseline_policy=dirty_policy,
                    git_head=git_head,
                    plan=plan,
                    monitor=classification.get("monitor"),
                    adapter=adapter_result,
                    completion_trusted=False,
                )
            )

        monitor_result = _monitor_goal_session({**args, "session_id": session_id})
        return _json_result(
            _base_result(
                status=monitor_result["result_status"],
                mode=mode,
                workdir=repo,
                stage_id=args.get("stage_id"),
                preflight=preflight,
                classification=monitor_result["classification"],
                next_action=monitor_result["next_action"],
                candidate_disposition=monitor_result["candidate_disposition"],
                dirty_baseline_policy=dirty_policy,
                git_head=git_head,
                plan=plan,
                monitor=monitor_result["monitor"],
            )
        )

    if mode == "collect_candidate":
        candidate_evidence = _collect_candidate_git_evidence(repo)
        has_candidate_changes = bool(
            candidate_evidence.get("changed_files")
            or candidate_evidence.get("staged_files")
            or candidate_evidence.get("untracked_files")
        )
        review_handoff = _build_candidate_review_handoff(
            repo=repo,
            args=args,
            git_head=git_head,
            dirty=dirty,
            candidate_evidence=candidate_evidence,
        )
        status = "candidate_ready_for_review" if has_candidate_changes else "no_candidate_changes"
        return _json_result(
            _base_result(
                status=status,
                mode=mode,
                workdir=repo,
                stage_id=args.get("stage_id"),
                preflight={
                    "status": "collecting" if has_candidate_changes else "no_candidate_changes",
                    "blockers": [] if has_candidate_changes else ["no_candidate_changes"],
                    "dirty_check": dirty,
                    "codex": {"status": "not_run", "reason": "collect_candidate_only"},
                },
                classification="review_handoff" if has_candidate_changes else "blocked",
                next_action="run_hermes_review_on_candidate_packet" if has_candidate_changes else "inspect_no_candidate_changes",
                candidate_disposition="needs_review" if has_candidate_changes else "planning_only",
                dirty_baseline_policy=dirty_policy,
                git_head=git_head,
                plan=plan,
                candidate_evidence=candidate_evidence,
                review_handoff=review_handoff,
            )
        )

    if not dirty["is_clean"]:
        return _json_result(
            _base_result(
                status="dirty_worktree",
                mode=mode,
                workdir=repo,
                stage_id=args.get("stage_id"),
                preflight={"status": "blocked", "blockers": ["dirty_worktree"], "dirty_check": dirty},
                classification="blocked",
                next_action="clean_worktree_before_goal_run",
                dirty_baseline_policy=dirty_policy,
                git_head=git_head,
            )
        )

    codex_preflight = _codex_goals_preflight()
    preflight = {
        "status": codex_preflight["status"],
        "blockers": codex_preflight.get("blockers", []),
        "codex": codex_preflight,
        "dirty_check": dirty,
    }

    if mode == "dry_run_plan":
        return _json_result(
            _base_result(
                status="dry_run_plan",
                mode=mode,
                workdir=repo,
                stage_id=args.get("stage_id"),
                preflight=preflight,
                classification="planning",
                next_action="review_plan_then_prepare_goal",
                candidate_disposition="planning_only",
                dirty_baseline_policy=dirty_policy,
                git_head=git_head,
                plan=plan,
            )
        )

    if codex_preflight["status"] != "passed":
        return _json_result(
            _base_result(
                status="preflight_blocked",
                mode=mode,
                workdir=repo,
                stage_id=args.get("stage_id"),
                preflight=preflight,
                classification="blocked",
                next_action="install_or_enable_official_codex_goals_before_preparing",
                candidate_disposition="planning_only",
                dirty_baseline_policy=dirty_policy,
                git_head=git_head,
                plan=plan,
            )
        )

    if mode == "launch_goal":
        goal_text, goal_error = _read_one_line_goal(args, repo)
        if goal_error:
            return _json_result(
                _base_result(
                    status=goal_error,
                    mode=mode,
                    workdir=repo,
                    stage_id=args.get("stage_id"),
                    preflight={**preflight, "blockers": [*preflight.get("blockers", []), goal_error]},
                    classification="blocked",
                    next_action="provide_single_line_goal_file_under_tmp_outside_repo",
                    candidate_disposition="planning_only",
                    dirty_baseline_policy=dirty_policy,
                    git_head=git_head,
                    plan=plan,
                )
            )

        timeout_seconds = _coerce_timeout_seconds(args.get("timeout_seconds"))
        command = "codex-yuna --enable goals"
        launch = _launch_goal_tui(
            workdir=str(repo),
            command=command,
            pty=True,
            background=True,
            notify_on_complete=True,
            timeout_seconds=timeout_seconds,
        )
        if not launch.get("started"):
            blockers = [str(item) for item in launch.get("blockers", ["mock_launcher_only"])]
            return _json_result(
                _base_result(
                    status="launch_unavailable",
                    mode=mode,
                    workdir=repo,
                    stage_id=args.get("stage_id"),
                    preflight={**preflight, "blockers": [*preflight.get("blockers", []), *blockers]},
                    classification="blocked",
                    next_action="wire_real_pty_launcher_or_provide_mock",
                    candidate_disposition="planning_only",
                    dirty_baseline_policy=dirty_policy,
                    git_head=git_head,
                    plan=plan,
                    process=launch,
                )
            )

        session_id = str(launch.get("session_id") or "")
        submit = _submit_goal_text(session_id=session_id, data=goal_text or "")
        raw_enter = _write_goal_input(session_id=session_id, data="\r")
        return _json_result(
            _base_result(
                status="launched",
                mode=mode,
                workdir=repo,
                stage_id=args.get("stage_id"),
                preflight=preflight,
                classification="launched_goal",
                next_action="monitor_goal_wait_windows_then_collect_candidate",
                candidate_disposition="needs_review",
                dirty_baseline_policy=dirty_policy,
                git_head=git_head,
                plan=plan,
                process=launch,
                submit=submit,
                raw_enter=raw_enter,
            )
        )

    try:
        goal_files = _write_goal_files(args, repo, git_head)
    except ValueError as exc:
        return _json_result(
            _base_result(
                status="invalid_artifact_path",
                mode=mode,
                workdir=repo,
                stage_id=args.get("stage_id"),
                preflight={**preflight, "blockers": [*preflight.get("blockers", []), str(exc)]},
                classification="blocked",
                next_action="use_tmp_artifact_path_outside_repo",
                candidate_disposition="planning_only",
                dirty_baseline_policy=dirty_policy,
                git_head=git_head,
                plan=plan,
            )
        )
    return _json_result(
        _base_result(
            status="prepared",
            mode=mode,
            workdir=repo,
            stage_id=args.get("stage_id"),
            preflight=preflight,
            classification="prepared_goal",
            next_action="open_codex_tui_and_submit_one_line_goal_for_hermes_review",
            candidate_disposition="needs_review",
            goal_files=goal_files,
            dirty_baseline_policy=dirty_policy,
            git_head=git_head,
            plan=plan,
        )
    )


_SCHEMA = {
    "name": "codex_goal_run",
    "description": (
        "Prepare or dry-run an official Codex TUI `/goal` handoff for candidate "
        "implementation work. Slice 2 can exercise a mock PTY launch lifecycle, "
        "and Slice 3 can exercise a mock monitor_goal wait-window state machine. "
        "The default hooks never start Codex TUI and never call raw `codex exec`."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "workdir": {"type": "string", "description": "Existing git repository workdir."},
            "stage_id": {"type": "string", "description": "Stable stage or slice identifier."},
            "objective": {"type": "string", "description": "Goal objective for Codex."},
            "docs_to_read": {"type": "array", "items": {"type": "string"}},
            "allowed_files": {"type": "array", "items": {"type": "string"}},
            "allowed_globs": {"type": "array", "items": {"type": "string"}},
            "non_goals": {"type": "array", "items": {"type": "string"}},
            "required_verification": {"type": "array", "items": {"type": "string"}},
            "stop_conditions": {"type": "array", "items": {"type": "string"}},
            "mode": {"type": "string", "enum": ["dry_run_plan", "prepare_goal", "launch_goal", "monitor_goal", "collect_candidate"]},
            "dirty_baseline_policy": {"type": "string", "enum": ["require-clean"]},
            "allow_isolated_worktree": {"type": "boolean"},
            "goal_artifact_dir": {"type": "string"},
            "rich_goal_file": {"type": "string"},
            "one_line_goal_file": {"type": "string"},
            "session_id": {"type": "string"},
            "timeout_seconds": {"type": "integer"},
            "monitor_interval_seconds": {"type": "integer"},
            "max_wait_windows": {"type": "integer"},
            "standing_authorization": {"type": "boolean"},
            "adapter_enabled": {"type": "boolean"},
            "allow_real_adapter": {"type": "boolean"},
        },
        "required": ["workdir", "stage_id", "objective", "mode", "dirty_baseline_policy"],
    },
}


registry.register(
    name="codex_goal_run",
    toolset="codex_goal_run",
    schema=_SCHEMA,
    handler=lambda args, **kwargs: codex_goal_run(args),
    description=_SCHEMA["description"],
)
