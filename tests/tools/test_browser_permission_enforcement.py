import json

import tools.browser_tool as browser_tool
from tools.browser_cdp_tool import BROWSER_CDP_SCHEMA, _handle_browser_cdp_with_permissions
from tools.registry import registry


def test_browser_permission_tier_is_not_model_schema_argument():
    console_schema = browser_tool._BROWSER_SCHEMA_MAP["browser_console"]

    assert "permission_tier" not in console_schema["parameters"]["properties"]
    assert "permission_tier" not in BROWSER_CDP_SCHEMA["parameters"]["properties"]


def test_browser_console_registry_ignores_model_supplied_permission_tier(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("model-supplied permission_tier must not authorize eval")

    monkeypatch.setattr(browser_tool, "_browser_eval", fail_if_called)

    result = json.loads(
        registry.dispatch(
            "browser_console",
            {"expression": "document.body.innerHTML = 'x'", "permission_tier": "cdp_mutate"},
        )
    )

    assert result["success"] is False
    assert result["error_type"] == "browser_permission_guard"


def test_browser_cdp_handler_ignores_model_supplied_permission_tier(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("model-supplied permission_tier must not authorize CDP")

    monkeypatch.setattr("tools.browser_cdp_tool.browser_cdp", fail_if_called)

    result = json.loads(
        _handle_browser_cdp_with_permissions(
            {"method": "DOM.setAttributeValue", "permission_tier": "cdp_mutate"}
        )
    )

    assert result["success"] is False
    assert result["error_type"] == "browser_permission_guard"


def test_browser_console_rejects_mutating_expression_before_eval(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("browser eval should not run for mutating expression")

    monkeypatch.setattr(browser_tool, "_browser_eval", fail_if_called)

    result = json.loads(browser_tool.browser_console(expression="document.body.innerHTML = 'x'"))

    assert result["success"] is False
    assert result["error_type"] == "browser_permission_guard"
    assert result["required_permission"] == "CDP_MUTATE"


def test_browser_console_rejects_fetch_expression_without_explicit_permission(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("browser eval should not run for potentially side-effecting fetch")

    monkeypatch.setattr(browser_tool, "_browser_eval", fail_if_called)

    result = json.loads(browser_tool.browser_console(expression="fetch('/logout')"))

    assert result["success"] is False
    assert result["error_type"] == "browser_permission_guard"
    assert result["required_permission"] == "CDP_MUTATE"


def test_browser_console_rejects_navigation_expression_without_explicit_permission(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("browser eval should not run for navigation expression")

    monkeypatch.setattr(browser_tool, "_browser_eval", fail_if_called)

    result = json.loads(browser_tool.browser_console(expression="location.href = '/logout'"))

    assert result["success"] is False
    assert result["error_type"] == "browser_permission_guard"
    assert result["required_permission"] == "CDP_MUTATE"


def test_browser_console_allows_read_expression(monkeypatch):
    monkeypatch.setattr(browser_tool, "_browser_eval", lambda expression, task_id=None: json.dumps({"ok": expression}))

    assert json.loads(browser_tool.browser_console(expression="document.title")) == {"ok": "document.title"}


def test_browser_console_allows_explicit_mutate_permission(monkeypatch):
    monkeypatch.setattr(browser_tool, "_browser_eval", lambda expression, task_id=None: json.dumps({"ok": expression}))

    assert json.loads(
        browser_tool.browser_console(
            expression="document.body.innerHTML = 'x'",
            permission_tier="cdp_mutate",
        )
    ) == {"ok": "document.body.innerHTML = 'x'"}


def test_browser_cdp_handler_rejects_mutating_method_without_explicit_permission(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("browser_cdp should not run for mutating method")

    monkeypatch.setattr("tools.browser_cdp_tool.browser_cdp", fail_if_called)

    result = json.loads(_handle_browser_cdp_with_permissions({"method": "DOM.setAttributeValue"}))

    assert result["success"] is False
    assert result["error_type"] == "browser_permission_guard"
    assert result["required_permission"] == "CDP_MUTATE"


def test_browser_cdp_handler_rejects_mutating_runtime_evaluate_expression(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("browser_cdp should not run for mutating Runtime.evaluate")

    monkeypatch.setattr("tools.browser_cdp_tool.browser_cdp", fail_if_called)

    result = json.loads(
        _handle_browser_cdp_with_permissions(
            {
                "method": "Runtime.evaluate",
                "params": {"expression": "document.body.innerHTML = 'x'"},
            }
        )
    )

    assert result["success"] is False
    assert result["error_type"] == "browser_permission_guard"
    assert result["required_permission"] == "CDP_MUTATE"


def test_browser_cdp_handler_rejects_runtime_evaluate_fetch_without_explicit_permission(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("browser_cdp should not run for fetch Runtime.evaluate")

    monkeypatch.setattr("tools.browser_cdp_tool.browser_cdp", fail_if_called)

    result = json.loads(
        _handle_browser_cdp_with_permissions(
            {
                "method": "Runtime.evaluate",
                "params": {"expression": "fetch('/logout')"},
            }
        )
    )

    assert result["success"] is False
    assert result["error_type"] == "browser_permission_guard"
    assert result["required_permission"] == "CDP_MUTATE"


def test_browser_cdp_handler_allows_explicit_mutate_permission(monkeypatch):
    monkeypatch.setattr(
        "tools.browser_cdp_tool.browser_cdp",
        lambda **kwargs: json.dumps({"method": kwargs["method"]}),
    )

    assert json.loads(
        _handle_browser_cdp_with_permissions(
            {"method": "DOM.setAttributeValue"},
            permission_tier="cdp_mutate",
        )
    ) == {"method": "DOM.setAttributeValue"}
