import json
import subprocess
from pathlib import Path

from scripts.runtime import codex_impl_guard as guard
from tools.codex_input_packet import CodexInputPacket, render_codex_exec_prompt


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


def test_run_rejects_verbose_hermes_transcript_prompt_before_codex(tmp_path, capsys, monkeypatch):
    repo = _clean_repo(tmp_path)
    calls = []

    def fake_run_codex(**kwargs):
        calls.append(kwargs)
        return {
            "codex_exit_code": 0,
            "terminated_by_guard": False,
            "reason": "ok",
            "stdout_chars": 0,
            "stdout_lines": 0,
            "source_like_lines": 0,
            "diff_like_lines": 0,
            "source_flood_detected": False,
            "diff_flood_detected": False,
            "json_field_flood_detected": False,
        }

    monkeypatch.setenv("HERMES_CODEX_IMPL_GUARD_ALLOW_FAKE_CODEX", "1")
    monkeypatch.setattr(guard, "_run_codex", fake_run_codex)
    verbose_prompt = "\n".join(
        [
            "技能检查点：已加载 hermes-agent/codex。",
            "MEMORY (your personal notes) [99%]",
            "USER PROFILE (who the user is)",
            "准备执行：把我的整段解释都交给 Codex。",
            "Task: make the README clearer.",
        ]
    )

    exit_code = guard.run([
        "--workdir",
        str(repo),
        "--prompt",
        verbose_prompt,
        "--allowed-file",
        "README.md",
    ])
    result = _payload(capsys)

    assert exit_code == 3
    assert result["status"] == "unusable"
    assert result["reason"] == "unsafe_prompt_packet"
    assert "hermes_or_session_transcript_marker" in result["prompt_packet_violations"]
    assert calls == []


def test_prompt_packet_policy_rejects_large_context_without_hermes_markers():
    violations = guard._prompt_packet_violations("x" * (guard._MAX_PROMPT_PACKET_CHARS + 1))

    assert violations == ["prompt_packet_too_large"]


def test_prompt_packet_policy_allows_structured_codex_packet_bullets(tmp_path):
    packet = CodexInputPacket(
        objective="Do bounded edit",
        workdir=str(tmp_path),
        allowed_files=["README.md"],
        verification=["python -m pytest tests/tools/test_codex_staged_implement_tool.py -q"],
        stop_conditions=["stop on failure"],
    )
    prompt = render_codex_exec_prompt(packet)

    assert "Allowed files:\n- README.md" in prompt
    assert "Verification:\n- python -m pytest" in prompt
    assert guard._prompt_packet_violations(prompt) == []
