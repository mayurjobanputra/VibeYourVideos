"""Unit tests for video metadata extraction utility."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.metadata import extract_video_metadata, _compute_aspect_ratio


class TestComputeAspectRatio:
    def test_16_9_landscape(self):
        assert _compute_aspect_ratio(1280, 720) == "16:9"

    def test_9_16_vertical(self):
        assert _compute_aspect_ratio(720, 1280) == "9:16"

    def test_1_1_square(self):
        assert _compute_aspect_ratio(1080, 1080) == "1:1"

    def test_4_3_ratio(self):
        assert _compute_aspect_ratio(1024, 768) == "4:3"

    def test_zero_width(self):
        assert _compute_aspect_ratio(0, 720) == "unknown"

    def test_zero_height(self):
        assert _compute_aspect_ratio(1280, 0) == "unknown"

    def test_negative_values(self):
        assert _compute_aspect_ratio(-1, 720) == "unknown"


class TestExtractVideoMetadata:
    def test_file_not_found_raises(self):
        with pytest.raises(FileNotFoundError):
            asyncio.get_event_loop().run_until_complete(
                extract_video_metadata(Path("/nonexistent/video.mp4"))
            )

    @pytest.mark.asyncio
    async def test_ffprobe_failure_raises_runtime_error(self, tmp_path):
        video_file = tmp_path / "test.mp4"
        video_file.write_bytes(b"\x00" * 100)

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"ffprobe error message")
        mock_proc.returncode = 1

        with patch("app.metadata.asyncio.create_subprocess_exec", return_value=mock_proc):
            with pytest.raises(RuntimeError, match="ffprobe failed"):
                await extract_video_metadata(video_file)

    @pytest.mark.asyncio
    async def test_successful_metadata_extraction(self, tmp_path):
        video_file = tmp_path / "test.mp4"
        video_file.write_bytes(b"\x00" * 2048)

        probe_output = {
            "format": {"duration": "12.5"},
            "streams": [
                {
                    "codec_type": "video",
                    "width": 1280,
                    "height": 720,
                },
                {
                    "codec_type": "audio",
                },
            ],
        }

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (json.dumps(probe_output).encode(), b"")
        mock_proc.returncode = 0

        with patch("app.metadata.asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await extract_video_metadata(video_file)

        assert result["duration"] == 12.5
        assert result["aspect_ratio"] == "16:9"
        assert result["file_size"] == 2048
        assert result["width"] == 1280
        assert result["height"] == 720

    @pytest.mark.asyncio
    async def test_vertical_video_metadata(self, tmp_path):
        video_file = tmp_path / "vertical.mp4"
        video_file.write_bytes(b"\x00" * 512)

        probe_output = {
            "format": {"duration": "5.0"},
            "streams": [
                {
                    "codec_type": "video",
                    "width": 720,
                    "height": 1280,
                },
            ],
        }

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (json.dumps(probe_output).encode(), b"")
        mock_proc.returncode = 0

        with patch("app.metadata.asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await extract_video_metadata(video_file)

        assert result["duration"] == 5.0
        assert result["aspect_ratio"] == "9:16"
        assert result["file_size"] == 512
        assert result["width"] == 720
        assert result["height"] == 1280

    @pytest.mark.asyncio
    async def test_invalid_json_from_ffprobe(self, tmp_path):
        video_file = tmp_path / "test.mp4"
        video_file.write_bytes(b"\x00" * 100)

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"not json", b"")
        mock_proc.returncode = 0

        with patch("app.metadata.asyncio.create_subprocess_exec", return_value=mock_proc):
            with pytest.raises(RuntimeError, match="Failed to parse ffprobe output"):
                await extract_video_metadata(video_file)

    @pytest.mark.asyncio
    async def test_no_video_stream_returns_zero_dimensions(self, tmp_path):
        video_file = tmp_path / "audio_only.mp4"
        video_file.write_bytes(b"\x00" * 100)

        probe_output = {
            "format": {"duration": "3.0"},
            "streams": [
                {"codec_type": "audio"},
            ],
        }

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (json.dumps(probe_output).encode(), b"")
        mock_proc.returncode = 0

        with patch("app.metadata.asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await extract_video_metadata(video_file)

        assert result["width"] == 0
        assert result["height"] == 0
        assert result["aspect_ratio"] == "unknown"


