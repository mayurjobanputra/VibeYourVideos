"""FastAPI application entry point for Vibe Your Videos."""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import config
from app.job_persistence import restore_jobs_from_disk
from app.metadata import extract_video_metadata
from app.models import Job, JobStage
from app.pipeline import run_pipeline
from app.validation import validate_generation_request

logger = logging.getLogger(__name__)

# In-memory job store
jobs: dict[str, Job] = {}

# Progress percentage mapping by stage
STAGE_PROGRESS: dict[JobStage, int] = {
    JobStage.QUEUED: 0,
    JobStage.SCRIPT_GENERATION: 10,
    JobStage.VISUAL_GENERATION: 40,
    JobStage.TTS_SYNTHESIS: 60,
    JobStage.VIDEO_ASSEMBLY: 80,
    JobStage.COMPLETE: 100,
}


class GenerateRequest(BaseModel):
    prompt: str
    video_length: str
    aspect_ratio: str
    caption_mode: str = "yes"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Check configuration on startup and restore persisted jobs."""
    if not config.api_key_configured:
        logger.warning(
            "OPENROUTER_API_KEY is not set. Video generation is disabled. "
            "Set the OPENROUTER_API_KEY environment variable and restart."
        )
    restore_jobs_from_disk(jobs)
    logger.info("Restored %d job(s) from disk", len(jobs))
    logger.info("Vibe Your Videos started on port %d", config.port)
    yield


app = FastAPI(title="Vibe Your Videos", lifespan=lifespan)


async def _run_pipeline_background(job: Job) -> None:
    """Run the pipeline as a background coroutine, catching exceptions to avoid unhandled task errors."""
    try:
        await run_pipeline(job)
    except Exception as e:
        logger.error("Job %s: unhandled pipeline error: %s", job.job_id, e)
        job.error = str(e)
        job.stage = JobStage.ERROR


@app.post("/api/generate", status_code=202)
async def generate(request: GenerateRequest) -> JSONResponse:
    """Validate request, create a Job, launch pipeline as background task, return 202."""
    if not config.api_key_configured:
        return JSONResponse(
            status_code=503,
            content={
                "detail": "API key not configured. Set the OPENROUTER_API_KEY environment variable and restart the server."
            },
        )

    result = validate_generation_request(
        prompt=request.prompt,
        video_length=request.video_length,
        aspect_ratio=request.aspect_ratio,
        caption_mode=request.caption_mode,
    )

    if not result.is_valid:
        raise HTTPException(status_code=422, detail=result.errors)

    job = Job(request=result.request)
    jobs[job.job_id] = job

    asyncio.create_task(_run_pipeline_background(job))

    return JSONResponse(
        status_code=202,
        content={"job_id": job.job_id},
    )


@app.get("/api/status/{job_id}")
async def get_status(job_id: str) -> JSONResponse:
    """Return job status including stage, progress, error, metadata, and video_url when complete."""
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    # Calculate progress percentage
    if job.stage == JobStage.ERROR:
        progress_pct = STAGE_PROGRESS.get(job.error_stage, 0)
    else:
        progress_pct = STAGE_PROGRESS.get(job.stage, 0)

    # Serialize script scenes
    script = None
    if job.scenes:
        script = [
            {
                "index": s.index,
                "narration_text": s.narration_text,
                "visual_description": s.visual_description,
            }
            for s in job.scenes
        ]

    # Build video_urls list for BOTH mode
    video_urls = None
    if job.stage == JobStage.COMPLETE and job.video_paths is not None:
        video_urls = [
            f"/api/video/{job.job_id}/{p.name}" for p in job.video_paths
        ]

    response: dict = {
        "job_id": job.job_id,
        "status": job.stage.value,
        "stage": job.stage.value,
        "progress_pct": progress_pct,
        "error": job.error,
        "error_stage": job.error_stage.value if job.error_stage else None,
        "script": script,
        "video_url": f"/api/video/{job.job_id}" if job.stage == JobStage.COMPLETE else None,
        "video_urls": video_urls,
        "metadata": None,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "prompt": job.request.prompt if job.request else None,
        "video_length": job.request.video_length.value if job.request else None,
        "aspect_ratio": job.request.aspect_ratio.value if job.request else None,
        "caption_mode": job.request.caption_mode.value if job.request else None,
    }

    # Include video metadata when job is complete and video exists
    if job.stage == JobStage.COMPLETE and job.video_path is not None:
        video_path = Path(job.video_path)
        if video_path.exists():
            try:
                metadata = await extract_video_metadata(video_path)
                response["metadata"] = metadata
            except Exception as e:
                logger.warning("Failed to extract video metadata for job %s: %s", job_id, e)

    return JSONResponse(content=response)

@app.get("/api/jobs")
async def list_jobs() -> JSONResponse:
    """Return all jobs sorted by created_at descending."""
    job_list = []
    for job in jobs.values():
        # Calculate progress percentage
        if job.stage == JobStage.ERROR:
            progress_pct = STAGE_PROGRESS.get(job.error_stage, 0)
        else:
            progress_pct = STAGE_PROGRESS.get(job.stage, 0)

        # Serialize script scenes
        script = None
        if job.scenes:
            script = [
                {
                    "index": s.index,
                    "narration_text": s.narration_text,
                    "visual_description": s.visual_description,
                }
                for s in job.scenes
            ]

        job_list.append({
            "job_id": job.job_id,
            "prompt": job.request.prompt if job.request else None,
            "video_length": job.request.video_length.value if job.request else None,
            "aspect_ratio": job.request.aspect_ratio.value if job.request else None,
            "caption_mode": job.request.caption_mode.value if job.request else None,
            "status": job.stage.value,
            "stage": job.stage.value,
            "progress_pct": progress_pct,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
            "error": job.error,
            "error_stage": job.error_stage.value if job.error_stage else None,
            "script": script,
            "video_url": f"/api/video/{job.job_id}" if job.stage == JobStage.COMPLETE else None,
        })

    # Sort by created_at descending (newest first)
    job_list.sort(key=lambda j: j["created_at"], reverse=True)

    return JSONResponse(content=job_list)



@app.get("/api/video/{job_id}")
async def get_video(job_id: str) -> FileResponse:
    """Stream the MP4 file from the output directory."""
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.stage != JobStage.COMPLETE or job.video_path is None:
        raise HTTPException(status_code=404, detail="Video not available")

    video_path = Path(job.video_path)
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video file not found")

    return FileResponse(
        path=str(video_path),
        media_type="video/mp4",
        filename=f"{job_id}.mp4",
    )


@app.get("/api/video/{job_id}/{filename}")
async def get_video_by_filename(job_id: str, filename: str) -> FileResponse:
    """Serve an individual video file by filename (for BOTH mode)."""
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.stage != JobStage.COMPLETE:
        raise HTTPException(status_code=404, detail="Video not available")

    if job.video_paths is None:
        raise HTTPException(status_code=404, detail="No video files available for this job")

    # Find the matching path by filename
    for p in job.video_paths:
        if p.name == filename:
            if not p.exists():
                raise HTTPException(status_code=404, detail="Video file not found")
            return FileResponse(
                path=str(p),
                media_type="video/mp4",
                filename=filename,
            )

    raise HTTPException(status_code=404, detail="Video file not found")


@app.get("/api/health")
async def health() -> JSONResponse:
    """Return configuration status for frontend health checks."""
    return JSONResponse(content={"api_key_configured": config.api_key_configured})


# SPA catch-all routes — serve index.html for client-side routing paths.
# These must be registered before the static files mount so they take priority.
_index_html = Path("static/index.html")


@app.get("/")
async def serve_spa_root() -> FileResponse:
    return FileResponse(_index_html, media_type="text/html")


@app.get("/jobs")
async def serve_spa_jobs() -> FileResponse:
    return FileResponse(_index_html, media_type="text/html")


@app.get("/job/{job_id}")
async def serve_spa_job_detail(job_id: str) -> FileResponse:
    return FileResponse(_index_html, media_type="text/html")


# Mount static files for serving the web UI
static_dir = Path("static")
if static_dir.exists():
    app.mount("/", StaticFiles(directory="static", html=True), name="static")
