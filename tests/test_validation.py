"""Unit tests for prompt validation logic."""

import pytest

from app.models import AspectRatio, VideoLength
from app.validation import (
    MAX_PROMPT_LENGTH,
    ValidationResult,
    validate_aspect_ratio,
    validate_generation_request,
    validate_prompt,
    validate_video_length,
)


class TestValidatePrompt:
    def test_empty_string_rejected(self):
        errors = validate_prompt("")
        assert len(errors) == 1
        assert "empty" in errors[0].lower()

    def test_whitespace_only_rejected(self):
        errors = validate_prompt("   \t\n  ")
        assert len(errors) == 1
        assert "empty" in errors[0].lower()

    def test_valid_prompt_accepted(self):
        errors = validate_prompt("Make a video about cats")
        assert errors == []

    def test_max_length_accepted(self):
        prompt = "a" * MAX_PROMPT_LENGTH
        errors = validate_prompt(prompt)
        assert errors == []

    def test_over_max_length_rejected(self):
        prompt = "a" * (MAX_PROMPT_LENGTH + 1)
        errors = validate_prompt(prompt)
        assert len(errors) == 1
        assert "maximum length" in errors[0].lower()


class TestValidateVideoLength:
    @pytest.mark.parametrize("value", ["10s", "30s", "60s", "90s"])
    def test_valid_values(self, value):
        vl, errors = validate_video_length(value)
        assert vl is not None
        assert errors == []

    def test_invalid_value(self):
        vl, errors = validate_video_length("45s")
        assert vl is None
        assert len(errors) == 1


class TestValidateAspectRatio:
    @pytest.mark.parametrize("value", ["9:16", "16:9"])
    def test_valid_values(self, value):
        ar, errors = validate_aspect_ratio(value)
        assert ar is not None
        assert errors == []

    def test_invalid_value(self):
        ar, errors = validate_aspect_ratio("4:3")
        assert ar is None
        assert len(errors) == 1


class TestValidateGenerationRequest:
    def test_valid_request(self):
        result = validate_generation_request("A cat story", "30s", "16:9")
        assert result.is_valid is True
        assert result.request is not None
        assert result.request.prompt == "A cat story"
        assert result.request.video_length == VideoLength.THIRTY
        assert result.request.aspect_ratio == AspectRatio.HORIZONTAL
        assert result.errors == []

    def test_empty_prompt_returns_error(self):
        result = validate_generation_request("", "30s", "16:9")
        assert result.is_valid is False
        assert result.request is None
        assert len(result.errors) >= 1

    def test_multiple_errors_collected(self):
        result = validate_generation_request("", "bad", "bad")
        assert result.is_valid is False
        assert len(result.errors) == 3  # prompt + video_length + aspect_ratio

    def test_whitespace_prompt_with_valid_options(self):
        result = validate_generation_request("   ", "10s", "9:16")
        assert result.is_valid is False
        assert any("empty" in e.lower() for e in result.errors)
