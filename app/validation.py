"""Prompt validation for OpenStoryMode generation requests."""

from dataclasses import dataclass, field
from typing import Optional

from app.models import AspectRatio, GenerationRequest, VideoLength

MAX_PROMPT_LENGTH = 5000


@dataclass
class ValidationResult:
    """Result of validating a generation request.

    On success, `request` contains the validated GenerationRequest.
    On failure, `errors` contains a list of human-readable error messages.
    """

    is_valid: bool
    request: Optional[GenerationRequest] = None
    errors: list[str] = field(default_factory=list)


def _get_enum_values(enum_cls: type) -> list[str]:
    return [e.value for e in enum_cls]


def validate_prompt(prompt: str) -> list[str]:
    """Validate the prompt string. Returns a list of error messages (empty if valid)."""
    errors: list[str] = []
    if not isinstance(prompt, str) or not prompt.strip():
        errors.append("Prompt must not be empty or whitespace-only.")
        return errors
    if len(prompt) > MAX_PROMPT_LENGTH:
        errors.append(
            f"Prompt exceeds maximum length of {MAX_PROMPT_LENGTH} characters."
        )
    return errors


def validate_video_length(value: str) -> tuple[Optional[VideoLength], list[str]]:
    """Validate video_length against allowed enum values."""
    try:
        return VideoLength(value), []
    except ValueError:
        allowed = _get_enum_values(VideoLength)
        return None, [f"Invalid video_length '{value}'. Allowed values: {allowed}"]


def validate_aspect_ratio(value: str) -> tuple[Optional[AspectRatio], list[str]]:
    """Validate aspect_ratio against allowed enum values."""
    try:
        return AspectRatio(value), []
    except ValueError:
        allowed = _get_enum_values(AspectRatio)
        return None, [f"Invalid aspect_ratio '{value}'. Allowed values: {allowed}"]


def validate_generation_request(
    prompt: str, video_length: str, aspect_ratio: str
) -> ValidationResult:
    """Validate all inputs for a generation request.

    Returns a ValidationResult with either a valid GenerationRequest or error messages.
    """
    errors: list[str] = []

    errors.extend(validate_prompt(prompt))

    vl, vl_errors = validate_video_length(video_length)
    errors.extend(vl_errors)

    ar, ar_errors = validate_aspect_ratio(aspect_ratio)
    errors.extend(ar_errors)

    if errors:
        return ValidationResult(is_valid=False, errors=errors)

    assert vl is not None and ar is not None
    return ValidationResult(
        is_valid=True,
        request=GenerationRequest(prompt=prompt, video_length=vl, aspect_ratio=ar),
    )
