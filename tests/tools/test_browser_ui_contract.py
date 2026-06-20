from tools.browser_ui_contract import (
    BrowserPermissionTier,
    BrowserUITestContract,
    classify_cdp_method,
    classify_console_expression,
    validate_browser_ui_contract,
)


def test_browser_ui_contract_accepts_bounded_read_only_smoke():
    contract = BrowserUITestContract(
        base_url="https://example.com/app",
        allowed_hosts=["example.com"],
        steps=[{"action": "navigate", "url": "https://example.com/app"}],
        assertions=["page title contains Example"],
        screenshot_targets=["landing"],
        console_policy="errors_only",
        mutation_policy="read_only",
    )

    assert validate_browser_ui_contract(contract) == []


def test_browser_ui_contract_rejects_disallowed_hosts_and_missing_assertions():
    contract = BrowserUITestContract(
        base_url="https://example.com/app",
        allowed_hosts=["example.com"],
        steps=[{"action": "navigate", "url": "https://evil.test/phish"}],
        assertions=[],
    )

    assert validate_browser_ui_contract(contract) == [
        "missing_assertions",
        "step_url_host_not_allowed",
    ]


def test_browser_ui_contract_requires_permission_for_mutating_steps():
    contract = BrowserUITestContract(
        base_url="https://example.com",
        allowed_hosts=["example.com"],
        steps=[
            {"action": "type", "ref": "@e1", "text": "hello"},
            {"action": "submit", "ref": "@e2"},
        ],
        assertions=["submitted state visible"],
        mutation_policy="read_only",
    )

    assert validate_browser_ui_contract(contract) == [
        "step_requires_interact_permission",
        "step_requires_submit_permission",
    ]


def test_browser_ui_contract_allows_mutation_when_permissions_are_explicit():
    contract = BrowserUITestContract(
        base_url="https://example.com",
        allowed_hosts=["example.com"],
        steps=[
            {"action": "type", "ref": "@e1", "text": "hello"},
            {"action": "submit", "ref": "@e2"},
        ],
        assertions=["submitted state visible"],
        mutation_policy="submit",
        permission_tier=BrowserPermissionTier.SUBMIT,
    )

    assert validate_browser_ui_contract(contract) == []


def test_cdp_method_classification_separates_read_mutate_cookie_and_submit():
    assert classify_cdp_method("Runtime.evaluate") == BrowserPermissionTier.CDP_READ
    assert classify_cdp_method("DOM.setAttributeValue") == BrowserPermissionTier.CDP_MUTATE
    assert classify_cdp_method("Storage.getCookies") == BrowserPermissionTier.COOKIE_STORAGE
    assert classify_cdp_method("Input.dispatchKeyEvent") == BrowserPermissionTier.SUBMIT


def test_console_expression_classification_flags_escape_hatches():
    assert classify_console_expression("document.title") == BrowserPermissionTier.CDP_READ
    assert classify_console_expression("document.body.innerHTML = 'x'") == BrowserPermissionTier.CDP_MUTATE
    assert classify_console_expression("document.cookie") == BrowserPermissionTier.COOKIE_STORAGE
    assert classify_console_expression("fetch('/pay', {method: 'POST'})") == BrowserPermissionTier.SUBMIT
