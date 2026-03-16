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
    """Create a test client for the FastAPI app with API key configured."""
    with patch("app.main.config") as mock_config, \
         patch("app.main.restore_jobs_from_disk"):
        mock_config.api_key_configured = True
        mock_config.port = 8000
        mock_config.openrouter_api_key = "test-key"
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


class TestGenerateEndpoint:
    def test_valid_request_returns_202(self, client):
        with patch("app.main.run_pipeline"):
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
        with patch("app.main.run_pipeline"):
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

    def test_status_includes_timestamps_and_request_fields(self, client):
        job = self._make_job(stage=JobStage.QUEUED)
        resp = client.get(f"/api/status/{job.job_id}")
        data = resp.json()
        assert data["created_at"] == job.created_at
        assert data["updated_at"] is None
        assert data["prompt"] == "test"
        assert data["video_length"] == "30s"
        assert data["aspect_ratio"] == "16:9"


class TestListJobsEndpoint:
    """Tests for Task 5.1: GET /api/jobs endpoint."""

    def _make_job(self, stage=JobStage.QUEUED, created_at=None, **kwargs) -> Job:
        job = Job(
            request=GenerationRequest(
                prompt="test prompt",
                video_length=VideoLength.THIRTY,
                aspect_ratio=AspectRatio.HORIZONTAL,
            ),
            stage=stage,
            **kwargs,
        )
        if created_at is not None:
            job.created_at = created_at
        jobs[job.job_id] = job
        return job

    def test_empty_store_returns_empty_array(self, client):
        resp = client.get("/api/jobs")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_single_job_returns_all_required_fields(self, client):
        from app.models import Scene
        job = self._make_job(
            stage=JobStage.COMPLETE,
            scenes=[Scene(index=0, narration_text="Hello", visual_description="A cat")],
            updated_at="2025-01-15T10:35:00Z",
        )
        resp = client.get("/api/jobs")
        data = resp.json()
        assert len(data) == 1
        entry = data[0]
        assert entry["job_id"] == job.job_id
        assert entry["prompt"] == "test prompt"
        assert entry["video_length"] == "30s"
        assert entry["aspect_ratio"] == "16:9"
        assert entry["status"] == "complete"
        assert entry["stage"] == "complete"
        assert entry["progress_pct"] == 100
        assert entry["created_at"] == job.created_at
        assert entry["updated_at"] == "2025-01-15T10:35:00Z"
        assert entry["error"] is None
        assert entry["error_stage"] is None
        assert entry["script"] == [{"index": 0, "narration_text": "Hello", "visual_description": "A cat"}]
        assert entry["video_url"] == f"/api/video/{job.job_id}"

    def test_incomplete_job_has_null_video_url(self, client):
        self._make_job(stage=JobStage.VISUAL_GENERATION)
        resp = client.get("/api/jobs")
        entry = resp.json()[0]
        assert entry["video_url"] is None

    def test_job_without_scenes_has_null_script(self, client):
        self._make_job(stage=JobStage.QUEUED)
        resp = client.get("/api/jobs")
        entry = resp.json()[0]
        assert entry["script"] is None

    def test_error_job_includes_error_fields(self, client):
        self._make_job(
            stage=JobStage.ERROR,
            error="LLM timeout",
            error_stage=JobStage.SCRIPT_GENERATION,
        )
        resp = client.get("/api/jobs")
        entry = resp.json()[0]
        assert entry["status"] == "error"
        assert entry["error"] == "LLM timeout"
        assert entry["error_stage"] == "script_generation"
        assert entry["progress_pct"] == STAGE_PROGRESS[JobStage.SCRIPT_GENERATION]

    def test_multiple_jobs_sorted_by_created_at_descending(self, client):
        self._make_job(created_at="2025-01-10T00:00:00Z")
        self._make_job(created_at="2025-01-15T00:00:00Z")
        self._make_job(created_at="2025-01-12T00:00:00Z")
        resp = client.get("/api/jobs")
        data = resp.json()
        assert len(data) == 3
        timestamps = [j["created_at"] for j in data]
        assert timestamps == sorted(timestamps, reverse=True)
        assert timestamps == ["2025-01-15T00:00:00Z", "2025-01-12T00:00:00Z", "2025-01-10T00:00:00Z"]




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


class TestStartupRestoration:
    """Tests for Task 3.2: startup restoration in lifespan."""

    def test_lifespan_restores_jobs_from_disk(self, tmp_path):
        """Verify restore_jobs_from_disk is called during startup and populates the store."""
        import json

        restored_jobs = {}

        def fake_restore(store):
            # Simulate restoring a job
            job = Job(
                job_id="restored-123",
                request=GenerationRequest(
                    prompt="restored prompt",
                    video_length=VideoLength.THIRTY,
                    aspect_ratio=AspectRatio.HORIZONTAL,
                ),
                stage=JobStage.COMPLETE,
            )
            store[job.job_id] = job

        with patch("app.main.restore_jobs_from_disk", side_effect=fake_restore):
            with TestClient(app, raise_server_exceptions=False) as c:
                # After startup, the restored job should be accessible
                resp = c.get("/api/status/restored-123")
                assert resp.status_code == 200
                data = resp.json()
                assert data["job_id"] == "restored-123"
                assert data["prompt"] == "restored prompt"

        # Clean up
        jobs.clear()

    def test_lifespan_calls_restore_before_yield(self):
        """Verify restore_jobs_from_disk is called during startup."""
        with patch("app.main.restore_jobs_from_disk") as mock_restore:
            with TestClient(app, raise_server_exceptions=False):
                pass
            mock_restore.assert_called_once_with(jobs)


class TestJobCreatedAt:
    """Tests for Task 3.3: created_at is set on Job creation in generate()."""

    def test_generate_sets_created_at(self, client):
        """Verify that created_at is set when a Job is created via POST /api/generate."""
        from datetime import datetime

        with patch("app.main.run_pipeline"):
            resp = client.post("/api/generate", json={
                "prompt": "A story about timestamps",
                "video_length": "30s",
                "aspect_ratio": "16:9",
            })
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]
        job = jobs[job_id]

        # created_at should be set and be a valid ISO 8601 string
        assert job.created_at is not None
        assert job.created_at.endswith("Z")
        # Should parse without error
        parsed = datetime.fromisoformat(job.created_at.replace("Z", "+00:00"))
        assert parsed is not None

    def test_generate_created_at_returned_in_status(self, client):
        """Verify created_at is returned in the status endpoint response."""
        with patch("app.main.run_pipeline"):
            resp = client.post("/api/generate", json={
                "prompt": "Timestamp test",
                "video_length": "10s",
                "aspect_ratio": "9:16",
            })
        job_id = resp.json()["job_id"]

        status_resp = client.get(f"/api/status/{job_id}")
        data = status_resp.json()
        assert data["created_at"] is not None
        assert data["created_at"] == jobs[job_id].created_at
