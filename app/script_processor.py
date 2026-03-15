# Script Processor for OpenStoryMode
# Generates scene-by-scene scripts from user prompts via LLM

import json
import logging
from typing import Optional

from app.models import AspectRatio, Scene, VideoLength
from app.openrouter import OpenRouterClient

logger = logging.getLogger(__name__)

# ~150 words per minute speaking rate
WORDS_PER_MINUTE = 150


def _calculate_scene_count(video_length: VideoLength) -> int:
    """Determine number of scenes based on video length.

    Heuristic: roughly 1 scene per 5-10 seconds, using ~7 seconds as midpoint.
    Minimum 1 scene for any length.
    """
    seconds = video_length.to_seconds()
    count = max(1, round(seconds / 7))
    return count


def _build_prompt(user_prompt: str, video_length: VideoLength, aspect_ratio: AspectRatio, scene_count: int) -> str:
    """Build the LLM prompt that instructs the model to produce scene JSON."""
    total_seconds = video_length.to_seconds()
    # Target word count: 150 wpm * (seconds / 60)
    total_words = round(WORDS_PER_MINUTE * total_seconds / 60)
    words_per_scene = round(total_words / scene_count)

    return f"""You are a video script writer. Given a user's video idea, produce a scene-by-scene script as a JSON array.

User's video idea: {user_prompt}

Target video length: {total_seconds} seconds
Aspect ratio: {aspect_ratio.value}
Number of scenes: {scene_count}

Requirements:
- Output ONLY a valid JSON array with exactly {scene_count} scene objects.
- Each scene object must have exactly two fields: "narration_text" and "visual_description".
- "narration_text": The spoken narration for this scene. Each scene should have approximately {words_per_scene} words of narration (total across all scenes should be approximately {total_words} words to fit a {total_seconds}-second video at ~150 words per minute).
- "visual_description": A detailed description of the visual/image to generate for this scene, suitable as an image generation prompt. Include style, mood, colors, and composition details. Reference the aspect ratio ({aspect_ratio.value}) in framing.
- Distribute the story evenly across scenes.
- Do NOT include any text outside the JSON array. No markdown, no explanation, just the JSON.

Example format:
[
  {{"narration_text": "...", "visual_description": "..."}},
  {{"narration_text": "...", "visual_description": "..."}}
]"""


def _parse_and_validate(raw_response: str, expected_scene_count: int) -> list[Scene]:
    """Parse LLM JSON response and validate against expected schema.

    Each scene must have non-empty narration_text and visual_description.
    Returns list[Scene] on success, raises ValueError on validation failure.
    """
    # Strip any markdown code fences the LLM might wrap around the JSON
    text = raw_response.strip()
    if text.startswith("```"):
        # Remove opening fence (with optional language tag)
        first_newline = text.index("\n")
        text = text[first_newline + 1:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM returned invalid JSON: {e}") from e

    if not isinstance(data, list):
        raise ValueError(f"Expected JSON array, got {type(data).__name__}")

    if len(data) == 0:
        raise ValueError("LLM returned empty scene list")

    scenes: list[Scene] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"Scene {i} is not a JSON object")

        narration = item.get("narration_text", "")
        visual = item.get("visual_description", "")

        if not isinstance(narration, str) or not narration.strip():
            raise ValueError(f"Scene {i} has empty or missing narration_text")

        if not isinstance(visual, str) or not visual.strip():
            raise ValueError(f"Scene {i} has empty or missing visual_description")

        scenes.append(Scene(index=i, narration_text=narration.strip(), visual_description=visual.strip()))

    return scenes


async def generate_script(
    prompt: str,
    video_length: VideoLength,
    aspect_ratio: AspectRatio,
    client: Optional[OpenRouterClient] = None,
) -> list[Scene]:
    """Generate a scene-by-scene script from a user prompt via LLM.

    Args:
        prompt: The user's video idea text.
        video_length: Target video duration.
        aspect_ratio: Target aspect ratio.
        client: Optional OpenRouterClient instance (creates default if None).

    Returns:
        list[Scene] with narration_text and visual_description per scene.

    Raises:
        OpenRouterError: If the LLM API call fails after retries.
        ValueError: If the LLM response cannot be parsed or validated.
    """
    if client is None:
        client = OpenRouterClient()

    scene_count = _calculate_scene_count(video_length)
    llm_prompt = _build_prompt(prompt, video_length, aspect_ratio, scene_count)

    # Call LLM — retries are handled inside the client
    response = await client.llm_completion(llm_prompt)

    # Extract the text content from the chat completion response
    try:
        raw_text = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise ValueError(f"Unexpected LLM response structure: {e}") from e

    return _parse_and_validate(raw_text, scene_count)
