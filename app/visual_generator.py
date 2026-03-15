# Visual Generator for OpenStoryMode
# Generates AI images for each scene via OpenRouter's image generation endpoint.

import logging
from pathlib import Path
from typing import Optional

from app.models import AspectRatio, Scene
from app.openrouter import OpenRouterClient

logger = logging.getLogger(__name__)


async def generate_visual(
    scene: Scene,
    job_id: str,
    aspect_ratio: AspectRatio,
    client: Optional[OpenRouterClient] = None,
) -> Path:
    """Generate an image for a scene and save it to disk.

    Calls OpenRouter's image generation endpoint with the scene's visual_description
    at the resolution determined by the aspect ratio. The image is saved to
    output/{job_id}/scenes/scene_{index}_image.png.

    Returns the Path to the saved image file.
    Raises OpenRouterError on failure after retries.
    """
    if client is None:
        client = OpenRouterClient()

    width, height = aspect_ratio.resolution()

    logger.info(
        "Generating visual for scene %d (job=%s, %dx%d)",
        scene.index,
        job_id,
        width,
        height,
    )

    image_bytes = await client.generate_image(
        prompt=scene.visual_description,
        width=width,
        height=height,
        scene_id=scene.index,
    )

    output_path = Path(f"output/{job_id}/scenes/scene_{scene.index}_image.png")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(image_bytes)

    logger.info("Saved visual for scene %d to %s", scene.index, output_path)
    return output_path
