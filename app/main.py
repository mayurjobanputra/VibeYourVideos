"""FastAPI application entry point for OpenStoryMode."""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import config, validate_config
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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Validate configuration on startup."""
    validate_config(config)
    logger.info("OpenStoryMode started on port %d", config.port)
    yield


app = FastAPI(title="OpenStoryMode", lifespan=lifespan)


def _run_pipeline_sync(job: Job) -> None:
    """Run the async pipeline in a new event loop for background execution."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(run_pipeline(job))
    finally:
        loop.close()


@app.post("/api/generate", status_code=202)
async def generate(request: GenerateRequest, background_tasks: BackgroundTasks) -> JSONResponse:
    """Validate request, create a Job, launch pipeline as background task, return 202."""
    result = validate_generation_request(
        prompt=request.prompt,
        video_length=request.video_length,
        aspect_ratio=request.aspect_ratio,
    )

    if not result.is_valid:
        raise HTTPException(status_code=422, detail=result.errors)

    job = Job(request=result.request)
    jobs[job.job_id] = job

    background_tasks.add_task(_run_pipeline_sync, job)

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

    response: dict = {
        "job_id": job.job_id,
        "status": job.stage.value,
        "stage": job.stage.value,
        "progress_pct": progress_pct,
        "error": job.error,
        "error_stage": job.error_stage.value if job.error_stage else None,
        "video_url": f"/api/video/{job.job_id}" if job.stage == JobStage.COMPLETE else None,
        "metadata": None,
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


# Mount static files for serving the web UI
static_dir = Path("static")
if static_dir.exists():
    app.mount("/", StaticFiles(directory="static", html=True), name="static")
