# Video Assembler for OpenStoryMode
# Composites scene images and narration audio into a single MP4 using FFmpeg.

import asyncio
import logging
from pathlib import Path

from app.models import AspectRatio, SceneAsset

logger = logging.getLogger(__name__)

CROSSFADE_DURATION = 0.5


class VideoAssemblyError(Exception):
    """Raised when FFmpeg video assembly fails."""

    def __init__(self, message: str, stderr: str = ""):
        self.stderr = stderr
        super().__init__(message)


async def _get_audio_duration(audio_path: Path) -> float:
    """Probe audio file duration using ffprobe."""
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise VideoAssemblyError(
            f"ffprobe failed for {audio_path}: {stderr.decode().strip()}",
            stderr=stderr.decode(),
        )

    return float(stdout.decode().strip())


async def _run_ffmpeg(args: list[str]) -> None:
    """Run an FFmpeg command and raise on failure with stderr details."""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        stderr_text = stderr.decode().strip()
        raise VideoAssemblyError(
            f"FFmpeg failed (exit code {proc.returncode}): {stderr_text[-500:]}",
            stderr=stderr_text,
        )


async def assemble_video(
    assets: list[SceneAsset],
    job_id: str,
    aspect_ratio: AspectRatio,
) -> Path:
    """Assemble scene images and audio into a single MP4 video.

    For each scene, creates a video clip from the still image that matches
    the audio duration. Then concatenates all clips with 0.5s crossfade
    transitions. Renders at the user-selected aspect ratio resolution.

    Args:
        assets: List of SceneAsset, each with image_path and audio_path.
        job_id: Unique job identifier for output directory.
        aspect_ratio: Target aspect ratio for the output video.

    Returns:
        Path to the final output MP4 file.

    Raises:
        VideoAssemblyError: If FFmpeg fails at any stage.
        ValueError: If assets list is empty or assets are missing paths.
    """
    if not assets:
        raise ValueError("No scene assets provided for video assembly")

    for asset in assets:
        if asset.image_path is None or asset.audio_path is None:
            raise ValueError(
                f"Scene {asset.scene_index} is missing image or audio path"
            )

    output_dir = Path(f"output/{job_id}")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "output.mp4"

    width, height = aspect_ratio.resolution()

    logger.info(
        "Assembling video for job %s: %d scenes, %dx%d",
        job_id, len(assets), width, height,
    )

    if len(assets) == 1:
        await _assemble_single_scene(assets[0], output_path, width, height)
    else:
        await _assemble_multi_scene(assets, output_path, width, height)

    logger.info("Video assembled: %s", output_path)
    return output_path


async def _assemble_single_scene(
    asset: SceneAsset,
    output_path: Path,
    width: int,
    height: int,
) -> None:
    """Assemble a single-scene video (no crossfade needed)."""
    duration = await _get_audio_duration(asset.audio_path)

    await _run_ffmpeg([
        "-y",
        "-loop", "1",
        "-i", str(asset.image_path),
        "-i", str(asset.audio_path),
        "-t", str(duration),
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
               f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,"
               "format=yuv420p",
        "-c:v", "libx264",
        "-preset", "fast",
        "-c:a", "aac",
        "-shortest",
        str(output_path),
    ])


async def _assemble_multi_scene(
    assets: list[SceneAsset],
    output_path: Path,
    width: int,
    height: int,
) -> None:
    """Assemble multiple scenes with crossfade transitions using a complex filter graph."""
    n = len(assets)
    durations: list[float] = []

    for asset in assets:
        dur = await _get_audio_duration(asset.audio_path)
        durations.append(dur)

    # Build FFmpeg inputs and filter graph
    input_args: list[str] = []
    for asset in assets:
        input_args.extend(["-loop", "1", "-i", str(asset.image_path)])
    for asset in assets:
        input_args.extend(["-i", str(asset.audio_path)])

    scale_filter = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,"
        "format=yuv420p"
    )

    filter_parts: list[str] = []

    # Trim each image input to its audio duration
    for i in range(n):
        filter_parts.append(
            f"[{i}:v]{scale_filter},trim=duration={durations[i]},setpts=PTS-STARTPTS[v{i}]"
        )

    # Chain crossfade transitions between consecutive video streams
    if n == 2:
        filter_parts.append(
            f"[v0][v1]xfade=transition=fade:duration={CROSSFADE_DURATION}"
            f":offset={durations[0] - CROSSFADE_DURATION}[vout]"
        )
    else:
        # First crossfade
        offset = durations[0] - CROSSFADE_DURATION
        filter_parts.append(
            f"[v0][v1]xfade=transition=fade:duration={CROSSFADE_DURATION}"
            f":offset={offset}[vx0]"
        )
        # Intermediate crossfades
        for i in range(2, n - 1):
            offset += durations[i - 1] - CROSSFADE_DURATION
            filter_parts.append(
                f"[vx{i-2}][v{i}]xfade=transition=fade:duration={CROSSFADE_DURATION}"
                f":offset={offset}[vx{i-1}]"
            )
        # Final crossfade
        offset += durations[n - 2] - CROSSFADE_DURATION
        filter_parts.append(
            f"[vx{n-3}][v{n-1}]xfade=transition=fade:duration={CROSSFADE_DURATION}"
            f":offset={offset}[vout]"
        )

    # Concatenate audio streams with crossfade overlap adjustment
    audio_inputs = "".join(f"[{n + i}:a]" for i in range(n))
    filter_parts.append(
        f"{audio_inputs}concat=n={n}:v=0:a=1[aout]"
    )

    filter_graph = ";\n".join(filter_parts)

    await _run_ffmpeg([
        "-y",
        *input_args,
        "-filter_complex", filter_graph,
        "-map", "[vout]",
        "-map", "[aout]",
        "-c:v", "libx264",
        "-preset", "fast",
        "-c:a", "aac",
        str(output_path),
    ])
