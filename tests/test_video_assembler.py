# Feature: story-mode-mvp, Video Assembler tests
# Tests for video assembly: FFmpeg command construction, single/multi scene, error handling

import asyncio
import subprocess
import uuid
from pathlib import Path

import pytest

from app.models import AspectRatio, SceneAsset
from app.video_assembler import (
    VideoAssemblyError,
    assemble_video,
    _get_audio_duration,
)


@pytest.fixture
def job_id():
    return f"test-{uuid.uuid4().hex[:8]}"


def _create_test_image(path: Path, width: int = 320, height: int = 240) -> None:
    """Create a small test image using FFmpeg."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=c=blue:s={width}x{height}:d=1",
            "-frames:v", "1",
            str(path),
        ],
        capture_output=True,
        check=True,
    )


def _create_test_audio(path: Path, duration: float = 2.0) -> None:
    """Create a small test audio file using FFmpeg."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
            "-c:a", "libmp3lame", "-q:a", "9",
            str(path),
        ],
        capture_output=True,
        check=True,
    )


@pytest.fixture
def single_scene_assets(job_id, tmp_path):
    """Create a single scene with test image and audio."""
    img = tmp_path / "scene_0_image.png"
    aud = tmp_path / "scene_0_audio.mp3"
    _create_test_image(img)
    _create_test_audio(aud, duration=2.0)
    return [SceneAsset(scene_index=0, image_path=img, audio_path=aud)]


@pytest.fixture
def multi_scene_assets(job_id, tmp_path):
    """Create two scenes with test images and audio."""
    assets = []
    for i in range(2):
        img = tmp_path / f"scene_{i}_image.png"
        aud = tmp_path / f"scene_{i}_audio.mp3"
        _create_test_image(img)
        _create_test_audio(aud, duration=2.0)
        assets.append(SceneAsset(scene_index=i, image_path=img, audio_path=aud))
    return assets


@pytest.fixture
def three_scene_assets(job_id, tmp_path):
    """Create three scenes with test images and audio."""
    assets = []
    for i in range(3):
        img = tmp_path / f"scene_{i}_image.png"
        aud = tmp_path / f"scene_{i}_audio.mp3"
        _create_test_image(img)
        _create_test_audio(aud, duration=2.0)
        assets.append(SceneAsset(scene_index=i, image_path=img, audio_path=aud))
    return assets


class TestGetAudioDuration:
    def test_returns_correct_duration(self, tmp_path):
        audio = tmp_path / "test.mp3"
        _create_test_audio(audio, duration=3.0)
        dur = asyncio.get_event_loop().run_until_complete(_get_audio_duration(audio))
        assert abs(dur - 3.0) < 0.2

    def test_raises_on_invalid_file(self, tmp_path):
        bad_file = tmp_path / "bad.mp3"
        bad_file.write_text("not audio")
        with pytest.raises(VideoAssemblyError, match="ffprobe failed"):
            asyncio.get_event_loop().run_until_complete(_get_audio_duration(bad_file))


class TestAssembleVideoValidation:
    def test_raises_on_empty_assets(self, job_id):
        with pytest.raises(ValueError, match="No scene assets"):
            asyncio.get_event_loop().run_until_complete(
                assemble_video([], job_id, AspectRatio.HORIZONTAL)
            )

    def test_raises_on_missing_image_path(self, job_id, tmp_path):
        aud = tmp_path / "audio.mp3"
        _create_test_audio(aud)
        assets = [SceneAsset(scene_index=0, image_path=None, audio_path=aud)]
        with pytest.raises(ValueError, match="missing image or audio"):
            asyncio.get_event_loop().run_until_complete(
                assemble_video(assets, job_id, AspectRatio.HORIZONTAL)
            )

    def test_raises_on_missing_audio_path(self, job_id, tmp_path):
        img = tmp_path / "image.png"
        _create_test_image(img)
        assets = [SceneAsset(scene_index=0, image_path=img, audio_path=None)]
        with pytest.raises(ValueError, match="missing image or audio"):
            asyncio.get_event_loop().run_until_complete(
                assemble_video(assets, job_id, AspectRatio.HORIZONTAL)
            )


class TestSingleSceneAssembly:
    def test_produces_mp4(self, single_scene_assets, job_id):
        result = asyncio.get_event_loop().run_until_complete(
            assemble_video(single_scene_assets, job_id, AspectRatio.HORIZONTAL)
        )
        assert result.exists()
        assert result.suffix == ".mp4"
        assert result == Path(f"output/{job_id}/output.mp4")

    def test_correct_resolution_horizontal(self, single_scene_assets, job_id):
        result = asyncio.get_event_loop().run_until_complete(
            assemble_video(single_scene_assets, job_id, AspectRatio.HORIZONTAL)
        )
        # Probe the output video dimensions
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "csv=p=0:s=x", str(result)],
            capture_output=True, text=True, check=True,
        )
        dims = probe.stdout.strip()
        assert dims == "1280x720"


class TestMultiSceneAssembly:
    def test_two_scenes_produces_mp4(self, multi_scene_assets, job_id):
        result = asyncio.get_event_loop().run_until_complete(
            assemble_video(multi_scene_assets, job_id, AspectRatio.HORIZONTAL)
        )
        assert result.exists()
        assert result.suffix == ".mp4"

    def test_three_scenes_produces_mp4(self, three_scene_assets, job_id):
        result = asyncio.get_event_loop().run_until_complete(
            assemble_video(three_scene_assets, job_id, AspectRatio.VERTICAL)
        )
        assert result.exists()
        assert result.suffix == ".mp4"

    def test_vertical_resolution(self, multi_scene_assets, job_id):
        result = asyncio.get_event_loop().run_until_complete(
            assemble_video(multi_scene_assets, job_id, AspectRatio.VERTICAL)
        )
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "csv=p=0:s=x", str(result)],
            capture_output=True, text=True, check=True,
        )
        dims = probe.stdout.strip()
        assert dims == "720x1280"


class TestVideoAssemblyError:
    def test_error_includes_stderr(self):
        err = VideoAssemblyError("test error", stderr="detailed ffmpeg output")
        assert err.stderr == "detailed ffmpeg output"
        assert "test error" in str(err)
