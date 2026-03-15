# Tests for app/script_processor.py
# Covers: scene count heuristic, prompt building, JSON parsing/validation

import json
import pytest

from app.models import AspectRatio, Scene, VideoLength
from app.script_processor import (
    _build_prompt,
    _calculate_scene_count,
    _parse_and_validate,
    generate_script,
)


class TestCalculateSceneCount:
    """Test scene count heuristic: ~1 scene per 7 seconds."""

    def test_10s_video(self):
        count = _calculate_scene_count(VideoLength.TEN)
        assert count >= 1

    def test_30s_video(self):
        count = _calculate_scene_count(VideoLength.THIRTY)
        assert count >= 1
        assert count >= _calculate_scene_count(VideoLength.TEN)

    def test_60s_video(self):
        count = _calculate_scene_count(VideoLength.SIXTY)
        assert count >= _calculate_scene_count(VideoLength.THIRTY)

    def test_90s_video(self):
        count = _calculate_scene_count(VideoLength.NINETY)
        assert count >= _calculate_scene_count(VideoLength.SIXTY)

    def test_minimum_one_scene(self):
        for vl in VideoLength:
            assert _calculate_scene_count(vl) >= 1


class TestBuildPrompt:
    """Test LLM prompt template construction."""

    def test_contains_user_prompt(self):
        prompt = _build_prompt("A cat in space", VideoLength.THIRTY, AspectRatio.HORIZONTAL, 4)
        assert "A cat in space" in prompt

    def test_contains_scene_count(self):
        prompt = _build_prompt("test", VideoLength.THIRTY, AspectRatio.VERTICAL, 4)
        assert "4" in prompt

    def test_contains_video_length(self):
        prompt = _build_prompt("test", VideoLength.SIXTY, AspectRatio.HORIZONTAL, 8)
        assert "60" in prompt

    def test_contains_aspect_ratio(self):
        prompt = _build_prompt("test", VideoLength.TEN, AspectRatio.VERTICAL, 1)
        assert "9:16" in prompt

    def test_mentions_json(self):
        prompt = _build_prompt("test", VideoLength.TEN, AspectRatio.HORIZONTAL, 1)
        assert "JSON" in prompt


class TestParseAndValidate:
    """Test JSON parsing and validation of LLM responses."""

    def test_valid_single_scene(self):
        raw = json.dumps([{"narration_text": "Hello world", "visual_description": "A sunny day"}])
        scenes = _parse_and_validate(raw, 1)
        assert len(scenes) == 1
        assert scenes[0].index == 0
        assert scenes[0].narration_text == "Hello world"
        assert scenes[0].visual_description == "A sunny day"

    def test_valid_multiple_scenes(self):
        data = [
            {"narration_text": f"Scene {i} narration", "visual_description": f"Scene {i} visual"}
            for i in range(3)
        ]
        scenes = _parse_and_validate(json.dumps(data), 3)
        assert len(scenes) == 3
        for i, scene in enumerate(scenes):
            assert scene.index == i

    def test_strips_markdown_fences(self):
        raw = '```json\n[{"narration_text": "Hi", "visual_description": "Bye"}]\n```'
        scenes = _parse_and_validate(raw, 1)
        assert len(scenes) == 1

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError, match="invalid JSON"):
            _parse_and_validate("not json at all", 1)

    def test_not_array_raises(self):
        with pytest.raises(ValueError, match="Expected JSON array"):
            _parse_and_validate('{"key": "value"}', 1)

    def test_empty_array_raises(self):
        with pytest.raises(ValueError, match="empty scene list"):
            _parse_and_validate("[]", 0)

    def test_missing_narration_raises(self):
        raw = json.dumps([{"visual_description": "A visual"}])
        with pytest.raises(ValueError, match="narration_text"):
            _parse_and_validate(raw, 1)

    def test_missing_visual_raises(self):
        raw = json.dumps([{"narration_text": "Some text"}])
        with pytest.raises(ValueError, match="visual_description"):
            _parse_and_validate(raw, 1)

    def test_empty_narration_raises(self):
        raw = json.dumps([{"narration_text": "  ", "visual_description": "A visual"}])
        with pytest.raises(ValueError, match="narration_text"):
            _parse_and_validate(raw, 1)

    def test_empty_visual_raises(self):
        raw = json.dumps([{"narration_text": "Text", "visual_description": ""}])
        with pytest.raises(ValueError, match="visual_description"):
            _parse_and_validate(raw, 1)

    def test_scene_not_dict_raises(self):
        raw = json.dumps(["not a dict"])
        with pytest.raises(ValueError, match="not a JSON object"):
            _parse_and_validate(raw, 1)

    def test_strips_whitespace_from_fields(self):
        raw = json.dumps([{"narration_text": "  Hello  ", "visual_description": "  World  "}])
        scenes = _parse_and_validate(raw, 1)
        assert scenes[0].narration_text == "Hello"
        assert scenes[0].visual_description == "World"


class TestGenerateScript:
    """Test the full generate_script async function with a mock client."""

    @pytest.mark.asyncio
    async def test_success_with_mock_client(self):
        """Test generate_script with a mock OpenRouterClient."""
        scene_data = [
            {"narration_text": "Once upon a time", "visual_description": "A dark forest"},
            {"narration_text": "The hero appeared", "visual_description": "A knight in armor"},
        ]

        class MockClient:
            async def llm_completion(self, prompt, **kwargs):
                return {"choices": [{"message": {"content": json.dumps(scene_data)}}]}

        scenes = await generate_script(
            prompt="A hero's journey",
            video_length=VideoLength.TEN,
            aspect_ratio=AspectRatio.HORIZONTAL,
            client=MockClient(),
        )
        assert len(scenes) == 2
        assert all(isinstance(s, Scene) for s in scenes)

    @pytest.mark.asyncio
    async def test_bad_response_structure_raises(self):
        """Test that unexpected LLM response structure raises ValueError."""

        class MockClient:
            async def llm_completion(self, prompt, **kwargs):
                return {"unexpected": "structure"}

        with pytest.raises(ValueError, match="Unexpected LLM response"):
            await generate_script(
                prompt="test",
                video_length=VideoLength.TEN,
                aspect_ratio=AspectRatio.HORIZONTAL,
                client=MockClient(),
            )

    @pytest.mark.asyncio
    async def test_invalid_json_from_llm_raises(self):
        """Test that invalid JSON from LLM raises ValueError."""

        class MockClient:
            async def llm_completion(self, prompt, **kwargs):
                return {"choices": [{"message": {"content": "not valid json"}}]}

        with pytest.raises(ValueError, match="invalid JSON"):
            await generate_script(
                prompt="test",
                video_length=VideoLength.TEN,
                aspect_ratio=AspectRatio.HORIZONTAL,
                client=MockClient(),
            )
