"""Guard helpers for image-generation prompts and inputs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from tools.tool_input_packet import PacketLimits, validate_text_packet


_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]{8,}", re.IGNORECASE),
    re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_\-]{8,}\b", re.IGNORECASE),
    re.compile(r"\b[A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD)\s*=\s*[^\s]+", re.IGNORECASE),
    re.compile(r"\*\*\*"),
)

_EXTERNAL_PROVIDERS = {"openai", "openai-codex", "fal", "replicate", "custom"}


@dataclass(frozen=True)
class ImagePromptRequest:
    prompt: str
    aspect_ratio: str | None = None
    provider: str | None = None
    model: str | None = None
    input_files: list[str] = field(default_factory=list)
    max_prompt_chars: int = 4_000
    real_person: bool = False
    person_consent: bool = False
    require_existing_input_files: bool = True
    require_cost_ack: bool = False
    cost_acknowledged: bool = False


def _contains_secret_marker(text: str) -> bool:
    return any(pattern.search(text or "") for pattern in _SECRET_PATTERNS)


def _provider_family(provider: str | None) -> str:
    value = (provider or "").strip().lower()
    return value.split(":", 1)[0]


def validate_image_prompt_request(request: ImagePromptRequest) -> list[str]:
    violations: list[str] = []
    prompt = request.prompt or ""
    if not prompt.strip():
        violations.append("missing_image_prompt")
    text_violations = validate_text_packet(
        prompt,
        limits=PacketLimits(max_chars=request.max_prompt_chars, max_lines=120),
        too_large_code="image_prompt_too_large",
        too_many_lines_code="image_prompt_too_many_lines",
    )
    if "image_prompt_too_large" in text_violations:
        violations.append("image_prompt_too_large")
    if "hermes_or_session_transcript_marker" in text_violations:
        violations.append("image_prompt_contains_hermes_context")
    if "raw_diff_or_patch_marker" in text_violations or "raw_log_marker" in text_violations:
        violations.append("image_prompt_contains_raw_diff_or_log")
    if "secret_marker" in text_violations or _contains_secret_marker(prompt):
        violations.append("image_prompt_contains_secret_marker")
    if request.require_existing_input_files:
        for raw in request.input_files:
            if raw and not Path(raw).exists():
                violations.append("image_input_file_missing")
                break
    if request.real_person and not request.person_consent:
        violations.append("real_person_requires_consent")
    if (
        request.require_cost_ack
        and not request.cost_acknowledged
        and _provider_family(request.provider) in _EXTERNAL_PROVIDERS
    ):
        violations.append("external_image_cost_not_acknowledged")
    return sorted(set(violations))


def redact_debug_prompt(prompt: str) -> str:
    redacted = prompt or ""
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED_SECRET]", redacted)
    return redacted
