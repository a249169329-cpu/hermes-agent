from tools.github_pr_contract import (
    GitHubOperationContract,
    GitHubOperationKind,
    build_github_operation_output_packet,
    record_github_operation_artifact,
    render_gh_command,
    side_effect_class_for_operation,
    validate_github_operation_contract,
)


def test_github_pr_contract_accepts_read_only_pr_view():
    contract = GitHubOperationContract(
        operation=GitHubOperationKind.PR_VIEW,
        repo="NousResearch/hermes-agent",
        pr_number=123,
    )

    assert validate_github_operation_contract(contract) == []
    assert side_effect_class_for_operation(contract.operation) == "read_external_service"


def test_github_operation_contract_does_not_carry_runtime_approval():
    contract = GitHubOperationContract(
        operation=GitHubOperationKind.PR_COMMENT,
        repo="NousResearch/hermes-agent",
        pr_number=123,
        body="Looks good.",
    )

    assert not hasattr(contract, "approved")


def test_github_pr_contract_requires_pr_number_for_pr_comment():
    contract = GitHubOperationContract(
        operation=GitHubOperationKind.PR_COMMENT,
        repo="NousResearch/hermes-agent",
        body="Looks good.",
    )

    assert validate_github_operation_contract(contract) == [
        "github_operation_requires_approval",
        "missing_pr_number",
    ]


def test_github_pr_contract_rejects_internal_context_and_secret_leaks():
    contract = GitHubOperationContract(
        operation=GitHubOperationKind.PR_COMMENT,
        repo="NousResearch/hermes-agent",
        pr_number=123,
        body="MEMORY (your personal notes) Bearer abcdef1234567890",
    )

    assert validate_github_operation_contract(contract, runtime_approved=True) == [
        "github_body_contains_hermes_context",
        "github_body_contains_secret_marker",
    ]


def test_github_pr_contract_rejects_openai_style_secret_leak():
    contract = GitHubOperationContract(
        operation=GitHubOperationKind.PR_COMMENT,
        repo="NousResearch/hermes-agent",
        pr_number=123,
        body="sk-proj-abcdef1234567890",
    )

    assert validate_github_operation_contract(contract, runtime_approved=True) == ["github_body_contains_secret_marker"]


def test_github_pr_contract_rejects_raw_diff_log_and_oversized_body():
    contract = GitHubOperationContract(
        operation=GitHubOperationKind.PR_COMMENT,
        repo="NousResearch/hermes-agent",
        pr_number=123,
        body="\n".join([
            "diff --git a/app.py b/app.py",
            "@@ -1 +1 @@",
            "raw_log: traceback follows",
            "x" * 5000,
        ]),
    )

    assert validate_github_operation_contract(contract, runtime_approved=True) == [
        "github_body_contains_raw_diff_or_log",
        "github_body_too_large",
    ]


def test_github_pr_contract_requires_branch_for_pr_create():
    contract = GitHubOperationContract(
        operation=GitHubOperationKind.PR_CREATE,
        repo="NousResearch/hermes-agent",
        base_branch="main",
        body="Open candidate PR.",
    )

    assert validate_github_operation_contract(contract, runtime_approved=True) == ["missing_head_branch"]


def test_github_pr_contract_classifies_write_operations():
    assert side_effect_class_for_operation(GitHubOperationKind.PR_COMMENT) == "external_pr_write"
    assert side_effect_class_for_operation(GitHubOperationKind.RELEASE_CREATE) == "external_release_write"


def test_render_gh_command_for_pr_comment_is_bounded_native_packet():
    contract = GitHubOperationContract(
        operation=GitHubOperationKind.PR_COMMENT,
        repo="NousResearch/hermes-agent",
        pr_number=123,
        body="Focused review comment.",
    )

    assert render_gh_command(contract, runtime_approved=True) == [
        "gh",
        "pr",
        "comment",
        "123",
        "--repo",
        "NousResearch/hermes-agent",
        "--body",
        "Focused review comment.",
    ]


def test_render_gh_command_refuses_invalid_contract():
    contract = GitHubOperationContract(
        operation=GitHubOperationKind.PR_COMMENT,
        repo="NousResearch/hermes-agent",
        pr_number=123,
        body="unsafe write without approval",
    )

    try:
        render_gh_command(contract)
    except ValueError as exc:
        assert "github_operation_requires_approval" in str(exc)
    else:  # pragma: no cover - assert above should always raise
        raise AssertionError("render_gh_command should reject invalid contracts")


def test_render_gh_command_for_pr_create_uses_explicit_branches_and_body():
    contract = GitHubOperationContract(
        operation=GitHubOperationKind.PR_CREATE,
        repo="NousResearch/hermes-agent",
        head_branch="feature/tool-contracts",
        base_branch="main",
        title="Add tool contracts",
        body="Bounded PR body.",
    )

    assert render_gh_command(contract, runtime_approved=True) == [
        "gh",
        "pr",
        "create",
        "--repo",
        "NousResearch/hermes-agent",
        "--head",
        "feature/tool-contracts",
        "--base",
        "main",
        "--title",
        "Add tool contracts",
        "--body",
        "Bounded PR body.",
    ]


def test_github_pr_create_result_builds_bounded_tool_output_packet():
    contract = GitHubOperationContract(
        operation=GitHubOperationKind.PR_CREATE,
        repo="NousResearch/hermes-agent",
        head_branch="feature/tool-contracts",
        base_branch="main",
        title="Add tool contracts",
        body="Bounded PR body.",
    )

    packet = build_github_operation_output_packet(
        contract,
        success=True,
        html_url="https://github.com/NousResearch/hermes-agent/pull/123",
        number=123,
        node_id="PR_kwDOexample",
    )

    assert packet.tool_name == "github_pr_contract"
    assert packet.tool_class == "github"
    assert packet.success is True
    assert packet.output_references == ["https://github.com/NousResearch/hermes-agent/pull/123"]
    assert packet.provider_metadata_summary == {
        "repo": "NousResearch/hermes-agent",
        "operation": "pr_create",
        "side_effect_class": "external_pr_write",
        "number": 123,
        "node_id": "PR_kwDOexample",
    }
    assert packet.bounded_payload == {
        "repo": "NousResearch/hermes-agent",
        "operation": "pr_create",
        "number": 123,
        "html_url": "https://github.com/NousResearch/hermes-agent/pull/123",
    }


def test_github_pr_create_result_records_artifact_ledger_reference(tmp_path):
    contract = GitHubOperationContract(
        operation=GitHubOperationKind.PR_CREATE,
        repo="NousResearch/hermes-agent",
        head_branch="feature/tool-contracts",
        base_branch="main",
        title="Add tool contracts",
        body="Bounded PR body.",
    )

    artifact_id = record_github_operation_artifact(
        contract,
        output_url="https://github.com/NousResearch/hermes-agent/pull/123",
        number=123,
        ledger_path=tmp_path / "ledger.jsonl",
    )

    assert artifact_id is not None
    lines = (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert "github_pr" in lines[0]
    assert "https://github.com/NousResearch/hermes-agent/pull/123" in lines[0]
