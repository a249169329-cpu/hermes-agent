import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from tools.registry import registry


_SUPPORTED_MODES = {"dry_run_plan", "prepare_goal"}
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
                next_action="use_dry_run_plan_or_prepare_goal",
                candidate_disposition="planning_only",
                reason="Slice 1 only supports dry_run_plan and prepare_goal.",
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
    plan = {
        "driver": _DRIVER,
        "launch_method": "official Codex TUI /goal",
        "not_used": ["codex exec", "codex-yuna exec", "codex-yuna --enable goals"],
        "would_write_goal_files": mode == "prepare_goal",
        "scope": {
            "allowed_files": _string_list(args.get("allowed_files")),
            "allowed_globs": _string_list(args.get("allowed_globs")),
        },
        "docs_to_read": _string_list(args.get("docs_to_read")),
        "stop_conditions": _string_list(args.get("stop_conditions")),
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
        "implementation work. Slice 1 never launches Codex TUI, never calls raw "
        "`codex exec`, and only supports dry_run_plan or prepare_goal."
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
            "mode": {"type": "string", "enum": ["dry_run_plan", "prepare_goal"]},
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
