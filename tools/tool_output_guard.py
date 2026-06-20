"""Common guard for tool results before they re-enter model context."""

from __future__ import annotations

import json
import re
from typing import Any

from tools.tool_input_packet import CREDENTIAL_VALUE_RE

_ROLE_TAG_RE = re.compile(
    r"</?(?:tool_call|function_call|result|response|output|input|system|assistant|user)>|"
    r"<\|/?(?:system|assistant|user|tool)[^>]*\|>",
    re.IGNORECASE,
)
_FENCE_OPEN_RE = re.compile(r"^\s*```(?:json|xml|html|markdown)?\s*", re.MULTILINE)
_FENCE_CLOSE_RE = re.compile(r"\s*```\s*$", re.MULTILINE)
_CDATA_RE = re.compile(r"<!\[CDATA\[.*?\]\]>", re.DOTALL)


def _sanitize_text(value: str) -> str:
    text = value or ""
    text = _ROLE_TAG_RE.sub("", text)
    text = _FENCE_OPEN_RE.sub("", text)
    text = _FENCE_CLOSE_RE.sub("", text)
    text = _CDATA_RE.sub("", text)
    text = CREDENTIAL_VALUE_RE.sub("[REDACTED]", text)
    return text


def _sanitize_json_value(value: Any) -> Any:
    if isinstance(value, str):
        return _sanitize_text(value)
    if isinstance(value, list):
        return [_sanitize_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize_json_value(item) for key, item in value.items()}
    return value


def sanitize_tool_result_for_model(tool_name: str, result: Any) -> Any:
    """Sanitize successful tool output before it is shown to the model.

    Preserves JSON shape when possible so existing handlers/tests that expect
    JSON strings keep working, while neutralizing role-framing tags and obvious
    credential values in external/tool-produced text.
    """
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
        except (TypeError, ValueError):
            return _sanitize_text(result)
        sanitized = _sanitize_json_value(parsed)
        if sanitized == parsed:
            return result
        return json.dumps(sanitized, ensure_ascii=False)
    return _sanitize_json_value(result)
