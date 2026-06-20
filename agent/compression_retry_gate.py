"""Manual retry gate helpers for failed context compression summaries."""

from __future__ import annotations

import re
from typing import Literal

ManualCompressionChoice = Literal["retry", "fallback", "stop"]

DEFAULT_MAX_MANUAL_COMPRESSION_RETRIES = 3  # Back-compat only; manual retries are unlimited.

_RESET_COUNTDOWN_FIELD_RE = re.compile(
    r"(?P<prefix>[,;\s{\[]*)"
    r"(?P<quote>['\"]?)reset_(?:seconds|time)(?P=quote)"
    r"\s*[:=]\s*"
    r"(?:'[^']*'|\"[^\"]*\"|[^,;{}\]\s]+)"
    r"\s*,?",
    re.IGNORECASE,
)

_RETRY_WORDS = {
    "重试",
    "再试",
    "再试一次",
    "重新压缩",
    "retry",
    "try again",
}
_FALLBACK_WORDS = {
    "不重试",
    "降级",
    "降级压缩",
    "fallback",
    "用fallback",
    "本地fallback",
    "local fallback",
}
_STOP_WORDS = {
    "停止",
    "停",
    "算了",
    "先不处理",
    "stop",
    "cancel",
    "abort",
}


def _normalize_choice_text(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


def sanitize_manual_compression_error(error: str | None) -> str:
    """Remove provider cooldown countdown fields from user-facing errors.

    Providers often include ``reset_seconds``/``reset_time`` in 429 payloads.
    Those values are volatile and misleading for Hermes' manual retry gate:
    the user can choose to retry immediately, switch/fix credentials, or fall
    back locally. Keep the actual provider error code/message, but hide the
    countdown fields so QQ/WebUI prompts do not look like a hard wait timer.
    """
    text = str(error or "unknown error").strip() or "unknown error"
    text = _RESET_COUNTDOWN_FIELD_RE.sub(lambda match: match.group("prefix") or "", text)
    text = re.sub(r",\s*,", ", ", text)
    text = re.sub(r"\{\s*,\s*", "{", text)
    text = re.sub(r",\s*([}\]])", r"\1", text)
    return text.strip() or "unknown error"


def parse_manual_compression_retry_choice(text: str) -> ManualCompressionChoice | None:
    """Parse the user's response to a pending compression retry gate."""
    normalized = _normalize_choice_text(text)
    if not normalized:
        return None
    compact = normalized.replace(" ", "")
    for word in _RETRY_WORDS:
        if compact == word.replace(" ", "") or normalized == word:
            return "retry"
    for word in _FALLBACK_WORDS:
        if compact == word.replace(" ", "") or normalized == word:
            return "fallback"
    for word in _STOP_WORDS:
        if compact == word.replace(" ", "") or normalized == word:
            return "stop"
    return None


def format_manual_compression_retry_prompt(
    error: str | None,
    *,
    attempts: int = 0,
    max_attempts: int = DEFAULT_MAX_MANUAL_COMPRESSION_RETRIES,
) -> str:
    """Return the user-facing prompt for a failed compression summary."""
    err = sanitize_manual_compression_error(error)
    if len(err) > 500:
        err = err[:497].rstrip() + "..."
    attempts = max(0, int(attempts or 0))

    lines = [
        f"压缩摘要失败：{err}",
        "当前未降级压缩，未继续发送大上下文请求。",
        "",
        "回复：",
        "- 重试 = 再试一次摘要压缩（可重复重试，无次数上限；不会自动无限循环）",
        "- 不重试 / 降级 = 使用本地 fallback 压缩后继续",
        "- 停止 = 不压缩，结束当前轮，建议 /new 或修 auth 后再试",
    ]
    if attempts:
        lines.append(f"已手动重试：{attempts} 次。")
    err_lower = err.lower()
    if any(s in err_lower for s in ("401", "auth", "token invalidated", "unauthorized")):
        lines.append("提示：这类 auth/token 错误重试大概率没用，建议先修 auth/认证。")
    elif any(s in err_lower for s in ("429", "cooldown", "cooling down", "rate limit")):
        lines.append("提示：这类限流/冷却错误可以等一会儿再重试。")
    elif any(s in err_lower for s in ("blocked", "content_filter", "content filter", "content policy", "safety")):
        lines.append("提示：这类 provider block/content_filter 错误继续重试可能无效，建议降级走本地 fallback。")
    elif any(s in err_lower for s in ("timeout", "timed out", "connection", "broken pipe", "eof", "stream exceeded")):
        lines.append("提示：这类超时/连接错误通常可重试一次；如果连续失败再降级。")
    return "\n".join(lines)


def make_pending_manual_compression_retry(
    error: str | None,
    *,
    attempts: int = 0,
    max_attempts: int = DEFAULT_MAX_MANUAL_COMPRESSION_RETRIES,
) -> dict[str, object]:
    """Build a small JSON-serializable pending-state payload."""
    return {
        "error": sanitize_manual_compression_error(error),
        "attempts": max(0, int(attempts or 0)),
    }
