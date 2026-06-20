"""Browser/UI test contract and browser escape-hatch permission tiers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any
from urllib.parse import urlparse


class BrowserPermissionTier(IntEnum):
    READ_ONLY = 0
    NAVIGATE = 1
    INTERACT = 2
    CDP_READ = 3
    CDP_MUTATE = 4
    COOKIE_STORAGE = 5
    SUBMIT = 6


_PERMISSION_NAME_TO_TIER = {
    "read_only": BrowserPermissionTier.READ_ONLY,
    "navigate": BrowserPermissionTier.NAVIGATE,
    "interact": BrowserPermissionTier.INTERACT,
    "cdp_read": BrowserPermissionTier.CDP_READ,
    "cdp_mutate": BrowserPermissionTier.CDP_MUTATE,
    "cookie_storage": BrowserPermissionTier.COOKIE_STORAGE,
    "submit": BrowserPermissionTier.SUBMIT,
}


_MUTATION_POLICY_TO_TIER = {
    # A read-only UI smoke still needs to load/navigate within allowed_hosts;
    # mutation_policy governs page/data mutation, not initial navigation.
    "read_only": BrowserPermissionTier.NAVIGATE,
    "navigate": BrowserPermissionTier.NAVIGATE,
    "interact": BrowserPermissionTier.INTERACT,
    "cdp_read": BrowserPermissionTier.CDP_READ,
    "cdp_mutate": BrowserPermissionTier.CDP_MUTATE,
    "cookie_storage": BrowserPermissionTier.COOKIE_STORAGE,
    "submit": BrowserPermissionTier.SUBMIT,
}

_CONSOLE_POLICIES = {"none", "errors_only", "read_only", "full"}


def permission_tier_from_name(value: str | BrowserPermissionTier | None) -> BrowserPermissionTier:
    if isinstance(value, BrowserPermissionTier):
        return value
    if value is None:
        return BrowserPermissionTier.CDP_READ
    key = str(value).strip().lower().replace("-", "_")
    if key in _PERMISSION_NAME_TO_TIER:
        return _PERMISSION_NAME_TO_TIER[key]
    try:
        return BrowserPermissionTier[key.upper()]
    except KeyError:
        return BrowserPermissionTier.CDP_READ


def browser_permission_allows(
    required: BrowserPermissionTier,
    granted: str | BrowserPermissionTier | None,
) -> bool:
    return permission_tier_from_name(granted) >= required


_STEP_REQUIRED_TIERS = {
    "snapshot": BrowserPermissionTier.READ_ONLY,
    "vision": BrowserPermissionTier.READ_ONLY,
    "get_images": BrowserPermissionTier.READ_ONLY,
    "console": BrowserPermissionTier.CDP_READ,
    "navigate": BrowserPermissionTier.NAVIGATE,
    "back": BrowserPermissionTier.NAVIGATE,
    "scroll": BrowserPermissionTier.INTERACT,
    "click": BrowserPermissionTier.INTERACT,
    "type": BrowserPermissionTier.INTERACT,
    "press": BrowserPermissionTier.INTERACT,
    "cdp_read": BrowserPermissionTier.CDP_READ,
    "cdp_mutate": BrowserPermissionTier.CDP_MUTATE,
    "cookie_storage": BrowserPermissionTier.COOKIE_STORAGE,
    "submit": BrowserPermissionTier.SUBMIT,
}


@dataclass(frozen=True)
class BrowserUITestContract:
    base_url: str
    allowed_hosts: list[str]
    steps: list[dict[str, Any]]
    assertions: list[str]
    screenshot_targets: list[str] = field(default_factory=list)
    console_policy: str = "errors_only"
    mutation_policy: str = "read_only"
    permission_tier: BrowserPermissionTier | None = None


def _host_for_url(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _allowed_hosts(contract: BrowserUITestContract) -> set[str]:
    return {host.lower() for host in contract.allowed_hosts if host}


def _effective_tier(contract: BrowserUITestContract) -> BrowserPermissionTier:
    if contract.permission_tier is not None:
        return BrowserPermissionTier(contract.permission_tier)
    return _MUTATION_POLICY_TO_TIER.get(contract.mutation_policy, BrowserPermissionTier.READ_ONLY)


def _step_required_tier(step: dict[str, Any]) -> BrowserPermissionTier:
    action = str(step.get("action") or "").strip().lower()
    if action == "cdp":
        return classify_cdp_method(str(step.get("method") or ""))
    if action == "console":
        return classify_console_expression(str(step.get("expression") or ""))
    return _STEP_REQUIRED_TIERS.get(action, BrowserPermissionTier.READ_ONLY)


def _permission_violation(required: BrowserPermissionTier) -> str:
    if required == BrowserPermissionTier.SUBMIT:
        return "step_requires_submit_permission"
    if required == BrowserPermissionTier.COOKIE_STORAGE:
        return "step_requires_cookie_storage_permission"
    if required == BrowserPermissionTier.CDP_MUTATE:
        return "step_requires_cdp_mutate_permission"
    if required == BrowserPermissionTier.CDP_READ:
        return "step_requires_cdp_read_permission"
    if required == BrowserPermissionTier.INTERACT:
        return "step_requires_interact_permission"
    if required == BrowserPermissionTier.NAVIGATE:
        return "step_requires_navigate_permission"
    return "step_permission_violation"


def classify_cdp_method(method: str) -> BrowserPermissionTier:
    name = (method or "").strip().lower()
    if name.startswith("storage.") or "cookie" in name or name.startswith("network.getcookies"):
        return BrowserPermissionTier.COOKIE_STORAGE
    if name.startswith("input.") or "dispatchkeyevent" in name or "dispatchmouseevent" in name:
        return BrowserPermissionTier.SUBMIT
    mutate_markers = (
        ".set",
        ".add",
        ".remove",
        ".delete",
        ".clear",
        ".enable",
        ".disable",
        "evaluateonnewdocument",
        "setattribute",
        "setscript",
    )
    if any(marker in name for marker in mutate_markers):
        return BrowserPermissionTier.CDP_MUTATE
    return BrowserPermissionTier.CDP_READ


def classify_console_expression(expression: str) -> BrowserPermissionTier:
    expr = (expression or "").strip().lower()
    if not expr:
        return BrowserPermissionTier.CDP_READ
    if "document.cookie" in expr or "localstorage" in expr or "sessionstorage" in expr:
        return BrowserPermissionTier.COOKIE_STORAGE
    submit_markers = ("method: 'post'", 'method:"post"', "method: \"post\"", ".submit(", "form.submit", "dispatchkeyevent")
    if any(marker in expr for marker in submit_markers):
        return BrowserPermissionTier.SUBMIT
    network_or_navigation_markers = (
        "fetch(",
        "xmlhttprequest",
        "sendbeacon(",
        "navigator.sendbeacon",
        "location.href",
        "window.location",
        "document.location",
        "history.pushstate",
        "history.replacestate",
        "location.assign(",
        "location.replace(",
    )
    if any(marker in expr for marker in network_or_navigation_markers):
        return BrowserPermissionTier.CDP_MUTATE
    mutate_markers = ("=", "innerhtml", "outerhtml", "appendchild", "removechild", ".click(", "setattribute")
    if any(marker in expr for marker in mutate_markers):
        return BrowserPermissionTier.CDP_MUTATE
    # Fail closed for arbitrary JS calls: only simple property reads are CDP_READ.
    if "(" in expr or ";" in expr or "=>" in expr or "new " in expr or "await " in expr:
        return BrowserPermissionTier.CDP_MUTATE
    return BrowserPermissionTier.CDP_READ


def validate_browser_ui_contract(contract: BrowserUITestContract) -> list[str]:
    violations: list[str] = []
    allowed_hosts = _allowed_hosts(contract)
    base_host = _host_for_url(contract.base_url)
    if not contract.base_url:
        violations.append("missing_base_url")
    elif allowed_hosts and base_host not in allowed_hosts:
        violations.append("base_url_host_not_allowed")
    if not allowed_hosts:
        violations.append("missing_allowed_hosts")
    if not contract.steps:
        violations.append("missing_steps")
    if not contract.assertions:
        violations.append("missing_assertions")
    if contract.console_policy not in _CONSOLE_POLICIES:
        violations.append("invalid_console_policy")
    if contract.mutation_policy not in _MUTATION_POLICY_TO_TIER:
        violations.append("invalid_mutation_policy")

    effective_tier = _effective_tier(contract)
    for step in contract.steps:
        step_url = step.get("url")
        if step_url:
            step_host = _host_for_url(str(step_url))
            if allowed_hosts and step_host not in allowed_hosts:
                violations.append("step_url_host_not_allowed")
        required = _step_required_tier(step)
        if effective_tier < required:
            violations.append(_permission_violation(required))
    return sorted(set(violations))
