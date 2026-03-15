"""Unit tests for the FastAPI REST API endpoints."""

import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import STAGE_PROGRESS, app, jobs
from app.models import GenerationRequest, Job, JobStage, AspectRatio, VideoLength


@pytest.fixture(autouse=True)
def clear_jobs():
    """Clear the in-memory job store before each test."""
    jobs.clear()
    yield
    jobs.clear()


@pytest.fixture
def client():
    """Create a test client that skips the startup validation."""
    with patch("app.main.validate_config"):
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


class TestGenerateEndpoint:
    def test_valid_request_returns_202(self, client):
        with patch("app.main._run_pipeline_sync"):
            resp = client.post("/api/generate", json={
                "prompt": "A story about a cat",
                "video_length": "30s",
                "aspect_ratio": "16:9",
            })
        assert resp.status_code == 202
        data = resp.json()
        assert "job_id" in data
        assert data["job_id"] in jobs

    def test_empty_prompt_returns_422(self, client):
        resp = client.post("/api/generate", json={
            "prompt": "",
            "video_length": "30s",
            "aspect_ratio": "16:9",
        })
        assert resp.status_code == 422

    def test_invalid_video_length_returns_422(self, client):
        resp = client.post("/api/generate", json={
            "prompt": "A story",
            "video_length": "45s",
            "aspect_ratio": "16:9",
        })
        assert resp.status_code == 422

    def test_invalid_aspect_ratio_returns_422(self, client):
        resp = client.post("/api/generate", json={
            "prompt": "A story",
            "video_length": "30s",
            "aspect_ratio": "4:3",
        })
        assert resp.status_code == 422

    def test_job_stored_in_memory(self, client):
        with patch("app.main._run_pipeline_sync"):
            resp = client.post("/api/generate", json={
                "prompt": "Test prompt",
                "video_length": "10s",
                "aspect_ratio": "9:16",
            })
        job_id = resp.json()["job_id"]
        job = jobs[job_id]
        assert job.request.prompt == "Test prompt"
        assert job.request.video_length == VideoLength.TEN
        assert job.request.aspect_ratio == AspectRatio.VERTICAL
        assert job.stage == JobStage.QUEUED


class TestStatusEndpoint:
    def _make_job(self, stage=JobStage.QUEUED, **kwargs) -> Job:
        job = Job(
            request=GenerationRequest(
                prompt="test", video_length=VideoLength.THIRTY, aspect_ratio=AspectRatio.HORIZONTAL
            ),
            stage=stage,
            **kwargs,
        )
        jobs[job.job_id] = job
        return job

    def test_queued_job_status(self, client):
        job = self._make_job(stage=JobStage.QUEUED)
        resp = client.get(f"/api/status/{job.job_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["stage"] == "queued"
        assert data["progress_pct"] == 0
        assert data["video_url"] is None
        assert data["error"] is None

    def test_complete_job_has_video_url(self, client):
        job = self._make_job(stage=JobStage.COMPLETE)
        resp = client.get(f"/api/status/{job.job_id}")
        data = resp.json()
        assert data["stage"] == "complete"
        assert data["progress_pct"] == 100
        assert data["video_url"] == f"/api/video/{job.job_id}"

    def test_error_job_includes_error_info(self, client):
        job = self._make_job(
            stage=JobStage.ERROR,
            error="LLM call failed",
            error_stage=JobStage.SCRIPT_GENERATION,
        )
        resp = client.get(f"/api/status/{job.job_id}")
        data = resp.json()
        assert data["stage"] == "error"
        assert data["error"] == "LLM call failed"
        assert data["error_stage"] == "script_generation"
        assert data["progress_pct"] == STAGE_PROGRESS[JobStage.SCRIPT_GENERATION]

    def test_not_found_returns_404(self, client):
        resp = client.get(f"/api/status/{uuid.uuid4()}")
        assert resp.status_code == 404

    @pytest.mark.parametrize("stage,expected_pct", [
        (JobStage.QUEUED, 0),
        (JobStage.SCRIPT_GENERATION, 10),
        (JobStage.VISUAL_GENERATION, 40),
        (JobStage.TTS_SYNTHESIS, 60),
        (JobStage.VIDEO_ASSEMBLY, 80),
        (JobStage.COMPLETE, 100),
    ])
    def test_progress_pct_by_stage(self, client, stage, expected_pct):
        job = self._make_job(stage=stage)
        resp = client.get(f"/api/status/{job.job_id}")
        assert resp.json()["progress_pct"] == expected_pct

    def test_complete_job_includes_metadata(self, client, tmp_path):
        video_file = tmp_path / "output.mp4"
        video_file.write_bytes(b"\x00" * 1024)

        job = self._make_job(stage=JobStage.COMPLETE, video_path=video_file)

        fake_metadata = {
            "duration": 30.0,
            "aspect_ratio": "16:9",
            "file_size": 1024,
            "width": 1280,
            "height": 720,
        }

        with patch("app.main.extract_video_metadata", return_value=fake_metadata):
            resp = client.get(f"/api/status/{job.job_id}")

        data = resp.json()
        assert data["metadata"] == fake_metadata

    def test_incomplete_job_has_null_metadata(self, client):
        job = self._make_job(stage=JobStage.VISUAL_GENERATION)
        resp = client.get(f"/api/status/{job.job_id}")
        data = resp.json()
        assert data["metadata"] is None


class TestVideoEndpoint:
    def test_not_found_returns_404(self, client):
        resp = client.get(f"/api/video/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_incomplete_job_returns_404(self, client):
        job = Job(stage=JobStage.VISUAL_GENERATION)
        jobs[job.job_id] = job
        resp = client.get(f"/api/video/{job.job_id}")
        assert resp.status_code == 404

    def test_complete_job_streams_video(self, client, tmp_path):
        video_file = tmp_path / "output.mp4"
        video_file.write_bytes(b"\x00\x00\x00\x1cftypisom")  # minimal MP4 header bytes

        job = Job(stage=JobStage.COMPLETE, video_path=video_file)
        jobs[job.job_id] = job

        resp = client.get(f"/api/video/{job.job_id}")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "video/mp4"

    def test_missing_video_file_returns_404(self, client):
        job = Job(stage=JobStage.COMPLETE, video_path=Path("/nonexistent/video.mp4"))
        jobs[job.job_id] = job
        resp = client.get(f"/api/video/{job.job_id}")
        assert resp.status_code == 404
