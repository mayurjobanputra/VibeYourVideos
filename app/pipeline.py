# Pipeline Manager for OpenStoryMode
# Orchestrates the full video generation pipeline: script → visuals + TTS → assembly

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from app.models import Job, JobStage, SceneAsset
from app.openrouter import OpenRouterClient
from app.script_processor import generate_script
from app.tts_engine import synthesize_narration
from app.video_assembler import assemble_video
from app.visual_generator import generate_visual

logger = logging.getLogger(__name__)


async def _process_scene_assets(
    scene_index: int,
    job: Job,
    client: OpenRouterClient,
) -> SceneAsset:
    """Run visual generation and TTS synthesis concurrently for a single scene.

    Returns a SceneAsset with whatever paths succeeded.
    If both fail, the asset will have both paths as None.
    """
    scene = job.scenes[scene_index]
    asset = SceneAsset(scene_index=scene_index)

    async def _generate_visual() -> Optional[Path]:
        try:
            return await generate_visual(
                scene=scene,
                job_id=job.job_id,
                aspect_ratio=job.request.aspect_ratio,
                client=client,
            )
        except Exception as e:
            logger.error("Visual generation failed for scene %d: %s", scene_index, e)
            return None

    async def _synthesize_narration() -> Optional[Path]:
        try:
            return await synthesize_narration(
                scene=scene,
                job_id=job.job_id,
                client=client,
            )
        except Exception as e:
            logger.error("TTS synthesis failed for scene %d: %s", scene_index, e)
            return None

    image_path, audio_path = await asyncio.gather(
        _generate_visual(),
        _synthesize_narration(),
    )

    asset.image_path = image_path
    asset.audio_path = audio_path
    return asset


async def run_pipeline(job: Job) -> None:
    """Orchestrate the full video generation pipeline.

    Mutates the Job object in place, updating stage, scenes, assets,
    video_path, error, and error_stage as the pipeline progresses.

    Pipeline stages:
    1. SCRIPT_GENERATION — generate scene script via LLM, save script.json
    2. VISUAL_GENERATION — concurrent visual + TTS per scene
    3. VIDEO_ASSEMBLY — assemble final MP4
    4. COMPLETE — done

    If any scene fails both visual and TTS after retries, the pipeline
    aborts and sets the ERROR stage.
    """
    client = OpenRouterClient()

    # --- Stage 1: Script Generation ---
    job.stage = JobStage.SCRIPT_GENERATION
    logger.info("Job %s: starting script generation", job.job_id)

    try:
        scenes = await generate_script(
            prompt=job.request.prompt,
            video_length=job.request.video_length,
            aspect_ratio=job.request.aspect_ratio,
            client=client,
        )
        job.scenes = scenes
    except Exception as e:
        logger.error("Job %s: script generation failed: %s", job.job_id, e)
        job.error = str(e)
        job.error_stage = JobStage.SCRIPT_GENERATION
        job.stage = JobStage.ERROR
        return

    # Save script.json
    output_dir = Path(f"output/{job.job_id}")
    output_dir.mkdir(parents=True, exist_ok=True)
    script_data = [
        {
            "index": s.index,
            "narration_text": s.narration_text,
            "visual_description": s.visual_description,
        }
        for s in job.scenes
    ]
    script_path = output_dir / "script.json"
    script_path.write_text(json.dumps(script_data, indent=2))
    logger.info("Job %s: saved script to %s", job.job_id, script_path)

    # --- Stage 2: Visual Generation + TTS (concurrent per scene) ---
    job.stage = JobStage.VISUAL_GENERATION
    logger.info("Job %s: starting visual generation and TTS synthesis", job.job_id)

    scene_tasks = [
        _process_scene_assets(i, job, client)
        for i in range(len(job.scenes))
    ]
    assets = await asyncio.gather(*scene_tasks)
    job.assets = list(assets)

    # Check for scenes where both visual and TTS failed
    for asset in job.assets:
        if asset.image_path is None and asset.audio_path is None:
            error_msg = (
                f"Scene {asset.scene_index} failed both visual generation "
                "and TTS synthesis after retries"
            )
            logger.error("Job %s: %s", job.job_id, error_msg)
            job.error = error_msg
            job.error_stage = JobStage.VISUAL_GENERATION
            job.stage = JobStage.ERROR
            return

    # --- Stage 3: Video Assembly ---
    job.stage = JobStage.VIDEO_ASSEMBLY
    logger.info("Job %s: starting video assembly", job.job_id)

    try:
        video_path = await assemble_video(
            assets=job.assets,
            job_id=job.job_id,
            aspect_ratio=job.request.aspect_ratio,
        )
        job.video_path = video_path
    except Exception as e:
        logger.error("Job %s: video assembly failed: %s", job.job_id, e)
        job.error = str(e)
        job.error_stage = JobStage.VIDEO_ASSEMBLY
        job.stage = JobStage.ERROR
        return

    # --- Stage 4: Complete ---
    job.stage = JobStage.COMPLETE
    logger.info("Job %s: pipeline complete, video at %s", job.job_id, job.video_path)
