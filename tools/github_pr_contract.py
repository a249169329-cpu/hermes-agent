"""GitHub / PR operation contract helpers.

This module is intentionally transport-agnostic: it validates the bounded
contract before any future gh/API renderer posts to GitHub.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from tools.artifact_ledger import record_tool_artifact
from tools.tool_input_packet import HERMES_OR_SESSION_MARKERS, PacketLimits, validate_text_packet
from tools.tool_output_packet import ToolOutputPacket


class GitHubOperationKind(StrEnum):
    ISSUE_VIEW = "issue_view"
    ISSUE_COMMENT = "issue_comment"
    PR_VIEW = "pr_view"
    PR_CREATE = "pr_create"
    PR_COMMENT = "pr_comment"
    PR_REVIEW = "pr_review"
    PR_MERGE = "pr_merge"
    RELEASE_CREATE = "release_create"


_WRITE_OPERATIONS = {
    GitHubOperationKind.ISSUE_COMMENT,
    GitHubOperationKind.PR_CREATE,
    GitHubOperationKind.PR_COMMENT,
    GitHubOperationKind.PR_REVIEW,
    GitHubOperationKind.PR_MERGE,
    GitHubOperationKind.RELEASE_CREATE,
}

_OPERATION_SIDE_EFFECT_CLASS = {
    GitHubOperationKind.ISSUE_VIEW: "read_external_service",
    GitHubOperationKind.PR_VIEW: "read_external_service",
    GitHubOperationKind.ISSUE_COMMENT: "external_issue_write",
    GitHubOperationKind.PR_CREATE: "external_pr_write",
    GitHubOperationKind.PR_COMMENT: "external_pr_write",
    GitHubOperationKind.PR_REVIEW: "external_pr_write",
    GitHubOperationKind.PR_MERGE: "external_pr_write",
    GitHubOperationKind.RELEASE_CREATE: "external_release_write",
}

_SECRET_RE = re.compile(
    r"Bearer\s+[A-Za-z0-9._\-]{8,}|\b(?:sk|pk|rk)-[A-Za-z0-9._\-]{8,}\b|"
    r"\b(?:ghp|github_pat)_[A-Za-z0-9_\-]{8,}\b|"
    r"\b[A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD)\s*=\s*[^\s]+",
    re.IGNORECASE,
)
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class GitHubOperationContract:
    operation: GitHubOperationKind
    repo: str
    issue_number: int | None = None
    pr_number: int | None = None
    head_branch: str | None = None
    base_branch: str | None = None
    title: str | None = None
    body: str | None = None
    evidence: list[str] | None = None


def side_effect_class_for_operation(operation: GitHubOperationKind) -> str:
    return _OPERATION_SIDE_EFFECT_CLASS[GitHubOperationKind(operation)]


def _contains_hermes_context(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker.lower() in lowered for marker in HERMES_OR_SESSION_MARKERS)


def validate_github_operation_contract(
    contract: GitHubOperationContract,
    *,
    runtime_approved: bool = False,
) -> list[str]:
    violations: list[str] = []
    operation = GitHubOperationKind(contract.operation)
    if not contract.repo or not _REPO_RE.match(contract.repo):
        violations.append("invalid_repo")
    if operation in {GitHubOperationKind.ISSUE_VIEW, GitHubOperationKind.ISSUE_COMMENT} and not contract.issue_number:
        violations.append("missing_issue_number")
    if operation in {
        GitHubOperationKind.PR_VIEW,
        GitHubOperationKind.PR_COMMENT,
        GitHubOperationKind.PR_REVIEW,
        GitHubOperationKind.PR_MERGE,
    } and not contract.pr_number:
        violations.append("missing_pr_number")
    if operation == GitHubOperationKind.PR_CREATE:
        if not contract.head_branch:
            violations.append("missing_head_branch")
        if not contract.base_branch:
            violations.append("missing_base_branch")
    if operation in _WRITE_OPERATIONS and not runtime_approved:
        violations.append("github_operation_requires_approval")
    body = contract.body or ""
    if body:
        body_violations = validate_text_packet(
            body,
            limits=PacketLimits(max_chars=4_000, max_lines=120),
            too_large_code="github_body_too_large",
            too_many_lines_code="github_body_too_many_lines",
        )
        if _contains_hermes_context(body) or "hermes_or_session_transcript_marker" in body_violations:
            violations.append("github_body_contains_hermes_context")
        if _SECRET_RE.search(body) or "secret_marker" in body_violations:
            violations.append("github_body_contains_secret_marker")
        if "raw_diff_or_patch_marker" in body_violations or "raw_log_marker" in body_violations:
            violations.append("github_body_contains_raw_diff_or_log")
        if "github_body_too_large" in body_violations:
            violations.append("github_body_too_large")
        if "github_body_too_many_lines" in body_violations:
            violations.append("github_body_too_many_lines")
    return sorted(set(violations))


def _require_valid_contract(
    contract: GitHubOperationContract,
    *,
    runtime_approved: bool = False,
) -> GitHubOperationKind:
    violations = validate_github_operation_contract(contract, runtime_approved=runtime_approved)
    if violations:
        raise ValueError("invalid_github_operation_contract: " + ", ".join(violations))
    return GitHubOperationKind(contract.operation)


def render_gh_command(
    contract: GitHubOperationContract,
    *,
    runtime_approved: bool = False,
) -> list[str]:
    """Render a validated contract to a bounded `gh` argv packet.

    This function does not execute anything. The caller still owns approval,
    terminal dispatch, and post-command remote verification.
    """
    operation = _require_valid_contract(contract, runtime_approved=runtime_approved)
    repo_args = ["--repo", contract.repo]
    if operation == GitHubOperationKind.PR_VIEW:
        return ["gh", "pr", "view", str(contract.pr_number), *repo_args]
    if operation == GitHubOperationKind.PR_COMMENT:
        return ["gh", "pr", "comment", str(contract.pr_number), *repo_args, "--body", contract.body or ""]
    if operation == GitHubOperationKind.PR_REVIEW:
        return ["gh", "pr", "review", str(contract.pr_number), *repo_args, "--comment", "--body", contract.body or ""]
    if operation == GitHubOperationKind.PR_CREATE:
        return [
            "gh",
            "pr",
            "create",
            *repo_args,
            "--head",
            contract.head_branch or "",
            "--base",
            contract.base_branch or "",
            "--title",
            contract.title or "",
            "--body",
            contract.body or "",
        ]
    if operation == GitHubOperationKind.ISSUE_VIEW:
        return ["gh", "issue", "view", str(contract.issue_number), *repo_args]
    if operation == GitHubOperationKind.ISSUE_COMMENT:
        return ["gh", "issue", "comment", str(contract.issue_number), *repo_args, "--body", contract.body or ""]
    if operation == GitHubOperationKind.PR_MERGE:
        return ["gh", "pr", "merge", str(contract.pr_number), *repo_args, "--merge"]
    if operation == GitHubOperationKind.RELEASE_CREATE:
        return ["gh", "release", "create", contract.title or "", *repo_args, "--notes", contract.body or ""]
    raise ValueError(f"unsupported_github_operation: {operation}")


def _github_artifact_kind(operation: GitHubOperationKind) -> str:
    if operation in {GitHubOperationKind.PR_VIEW, GitHubOperationKind.PR_CREATE, GitHubOperationKind.PR_COMMENT, GitHubOperationKind.PR_REVIEW, GitHubOperationKind.PR_MERGE}:
        return "github_pr"
    if operation in {GitHubOperationKind.ISSUE_VIEW, GitHubOperationKind.ISSUE_COMMENT}:
        return "github_issue"
    if operation == GitHubOperationKind.RELEASE_CREATE:
        return "github_release"
    return "github_operation"


def build_github_operation_output_packet(
    contract: GitHubOperationContract,
    *,
    success: bool,
    html_url: str | None = None,
    number: int | None = None,
    node_id: str | None = None,
    warnings: list[str] | None = None,
) -> ToolOutputPacket:
    """Build a bounded model-visible result packet for a GitHub operation.

    The packet carries verification handles (URL/number/repo) and governance
    metadata, never raw GitHub API responses, full PR bodies, or tokens.
    """
    operation = GitHubOperationKind(contract.operation)
    effective_number = number or contract.pr_number or contract.issue_number
    bounded_payload = {
        "repo": contract.repo,
        "operation": operation.value,
    }
    if effective_number is not None:
        bounded_payload["number"] = effective_number
    if html_url:
        bounded_payload["html_url"] = html_url
    metadata = {
        "repo": contract.repo,
        "operation": operation.value,
        "side_effect_class": side_effect_class_for_operation(operation),
    }
    if effective_number is not None:
        metadata["number"] = effective_number
    if node_id:
        metadata["node_id"] = node_id
    refs = [html_url] if html_url else []
    return ToolOutputPacket(
        tool_name="github_pr_contract",
        tool_class="github",
        success=bool(success),
        summary=f"GitHub {operation.value} {'succeeded' if success else 'failed'} for {contract.repo}.",
        output_references=refs,
        bounded_payload=bounded_payload,
        provider_metadata_summary=metadata,
        warnings=list(warnings or []),
    )


def record_github_operation_artifact(
    contract: GitHubOperationContract,
    *,
    output_url: str,
    number: int | None = None,
    ledger_path=None,
) -> str | None:
    """Record a GitHub URL as a remote artifact verification handle."""
    operation = GitHubOperationKind(contract.operation)
    native_arguments = {
        "repo": contract.repo,
        "operation": operation.value,
    }
    effective_number = number or contract.pr_number or contract.issue_number
    if effective_number is not None:
        native_arguments["number"] = effective_number
    if contract.head_branch:
        native_arguments["head_branch"] = contract.head_branch
    if contract.base_branch:
        native_arguments["base_branch"] = contract.base_branch
    return record_tool_artifact(
        source_tool="github_pr_contract",
        native_arguments=native_arguments,
        output_reference=output_url,
        kind=_github_artifact_kind(operation),
        lifetime="persistent_or_remote",
        ledger_path=ledger_path,
    )
