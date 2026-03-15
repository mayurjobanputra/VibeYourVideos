# TTS Engine for OpenStoryMode
# Synthesizes narration audio for each scene via OpenRouter's TTS endpoint.

import logging
from pathlib import Path
from typing import Optional

from app.models import Scene
from app.openrouter import OpenRouterClient

logger = logging.getLogger(__name__)


async def synthesize_narration(
    scene: Scene,
    job_id: str,
    client: Optional[OpenRouterClient] = None,
) -> Path:
    """Synthesize narration audio for a scene and save it to disk.

    Calls OpenRouter's TTS endpoint with the scene's narration_text.
    The audio is saved as MP3 to output/{job_id}/scenes/scene_{index}_audio.mp3.

    Returns the Path to the saved audio file.
    Raises OpenRouterError on failure after retries.
    """
    if client is None:
        client = OpenRouterClient()

    logger.info(
        "Synthesizing narration for scene %d (job=%s)",
        scene.index,
        job_id,
    )

    audio_bytes = await client.text_to_speech(
        text=scene.narration_text,
        scene_id=scene.index,
    )

    output_path = Path(f"output/{job_id}/scenes/scene_{scene.index}_audio.mp3")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(audio_bytes)

    logger.info("Saved narration for scene %d to %s", scene.index, output_path)
    return output_path
