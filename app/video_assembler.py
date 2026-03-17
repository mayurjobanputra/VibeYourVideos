# Video Assembler for Vibe Your Videos
# Composites scene images and narration audio into a single MP4 using FFmpeg.

import asyncio
import logging
from pathlib import Path

from app.caption_renderer import build_ass_file, build_drawtext_filter
from app.models import AspectRatio, CaptionMode, Scene, SceneAsset

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
    scenes: list[Scene] | None = None,
    caption_mode: CaptionMode = CaptionMode.YES,
) -> Path | tuple[Path, Path]:
    """Assemble scene images and audio into a single MP4 video.

    For each scene, creates a video clip from the still image that matches
    the audio duration. Then concatenates all clips with 0.5s crossfade
    transitions. Renders at the user-selected aspect ratio resolution.

    Args:
        assets: List of SceneAsset, each with image_path and audio_path.
        job_id: Unique job identifier for output directory.
        aspect_ratio: Target aspect ratio for the output video.
        scenes: Optional list of Scene objects providing narration text
                for caption generation.
        caption_mode: Controls caption behavior — YES (captioned output),
                      NO (no captions), or BOTH (two output files).

    Returns:
        Path to the final output MP4 file, or a tuple of
        (captioned_path, no_captions_path) when caption_mode is BOTH.

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
        "Assembling video for job %s: %d scenes, %dx%d, caption_mode=%s",
        job_id, len(assets), width, height, caption_mode.value,
    )

    if caption_mode == CaptionMode.BOTH and scenes is not None:
        # BOTH mode: produce two output files
        no_captions_path = output_dir / "output.mp4"
        captioned_path = output_dir / "output_captioned.mp4"

        # First pass: assemble without captions
        if len(assets) == 1:
            await _assemble_single_scene(
                assets[0], no_captions_path, width, height, narration_text=None,
            )
        else:
            await _assemble_multi_scene(
                assets, no_captions_path, width, height, scenes=None,
            )
        logger.info("Video assembled (no captions): %s", no_captions_path)

        # Second pass: assemble with captions
        if len(assets) == 1:
            narration = scenes[0].narration_text if scenes else None
            await _assemble_single_scene(
                assets[0], captioned_path, width, height, narration_text=narration,
            )
        else:
            await _assemble_multi_scene(
                assets, captioned_path, width, height, scenes=scenes,
            )
        logger.info("Video assembled (captioned): %s", captioned_path)

        return (captioned_path, no_captions_path)

    # YES or NO mode: single output
    captions_enabled = (
        caption_mode == CaptionMode.YES and scenes is not None
    )

    if len(assets) == 1:
        narration = (
            scenes[0].narration_text
            if captions_enabled and scenes and len(scenes) > 0
            else None
        )
        await _assemble_single_scene(
            assets[0], output_path, width, height, narration_text=narration,
        )
    else:
        await _assemble_multi_scene(
            assets, output_path, width, height,
            scenes=scenes if captions_enabled else None,
        )

    logger.info("Video assembled: %s", output_path)
    return output_path


async def _assemble_single_scene(
    asset: SceneAsset,
    output_path: Path,
    width: int,
    height: int,
    narration_text: str | None = None,
) -> None:
    """Assemble a single-scene video (no crossfade needed).

    Uses ASS subtitles for captions instead of drawtext filters to avoid
    FFmpeg filter-quoting issues with apostrophes and special characters.
    """
    duration = await _get_audio_duration(asset.audio_path)

    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,"
        "format=yuv420p"
    )

    ass_path: Path | None = None
    if narration_text:
        try:
            # Build a single-element scene list for the ASS generator
            dummy_scene = Scene(
                index=0,
                narration_text=narration_text,
                visual_description="",
            )
            ass_path = build_ass_file(
                scenes=[dummy_scene],
                durations=[duration],
                video_width=width,
                video_height=height,
                start_times=[0.0],
                crossfade_duration=0.0,
                output_path=output_path.parent,
            )
            escaped_ass = str(ass_path).replace("\\", "\\\\").replace(":", "\\:")
            vf = vf + f",ass={escaped_ass}"
        except Exception:
            logger.warning(
                "Caption generation failed for scene %d, proceeding without captions",
                asset.scene_index,
                exc_info=True,
            )

    try:
        await _run_ffmpeg([
            "-y",
            "-framerate", "25",
            "-loop", "1",
            "-t", str(duration),
            "-i", str(asset.image_path),
            "-i", str(asset.audio_path),
            "-vf", vf,
            "-af", "aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo",
            "-c:v", "libx264",
            "-preset", "fast",
            "-c:a", "aac",
            "-r", "25",
            str(output_path),
        ])
    finally:
        if ass_path and ass_path.exists():
            ass_path.unlink(missing_ok=True)



async def _assemble_multi_scene(
    assets: list[SceneAsset],
    output_path: Path,
    width: int,
    height: int,
    scenes: list[Scene] | None = None,
) -> None:
    """Assemble multiple scenes with crossfade transitions using a complex filter graph."""
    n = len(assets)
    durations: list[float] = []

    for asset in assets:
        dur = await _get_audio_duration(asset.audio_path)
        durations.append(dur)

    # Build FFmpeg inputs: use -framerate 25 -loop 1 -t <duration> for each
    # image to produce constant-fps video streams (required by xfade filter)
    input_args: list[str] = []
    for i, asset in enumerate(assets):
        input_args.extend([
            "-framerate", "25",
            "-loop", "1",
            "-t", str(durations[i]),
            "-i", str(asset.image_path),
        ])
    for asset in assets:
        input_args.extend(["-i", str(asset.audio_path)])

    scale_filter = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,"
        "format=yuv420p"
    )

    filter_parts: list[str] = []

    # Scale each image input (no trim/setpts needed — duration set at input level)
    for i in range(n):
        filter_parts.append(
            f"[{i}:v]{scale_filter}[v{i}]"
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

    # Inject captions via ASS subtitle file (single `ass` filter instead of
    # hundreds of drawtext filters that blow up the filter graph size)
    ass_path: Path | None = None
    if scenes is not None and len(scenes) >= n:
        start_times: list[float] = [0.0]
        for i in range(1, n):
            start_times.append(
                start_times[i - 1] + durations[i - 1] - CROSSFADE_DURATION
            )

        try:
            ass_path = build_ass_file(
                scenes=scenes,
                durations=durations,
                video_width=width,
                video_height=height,
                start_times=start_times,
                crossfade_duration=CROSSFADE_DURATION,
                output_path=output_path.parent,
            )
            # Rename [vout] to [vbase], apply ass filter, produce final [vout]
            for idx in range(len(filter_parts) - 1, -1, -1):
                if filter_parts[idx].endswith("[vout]"):
                    filter_parts[idx] = filter_parts[idx][:-6] + "[vbase]"
                    break

            # Escape colons in the path for FFmpeg filter syntax
            escaped_ass = str(ass_path).replace("\\", "\\\\").replace(":", "\\:")
            filter_parts.append(f"[vbase]ass={escaped_ass}[vout]")
        except Exception:
            logger.warning(
                "ASS caption generation failed, proceeding without captions",
                exc_info=True,
            )

    # Normalize and concatenate audio streams
    for i in range(n):
        filter_parts.append(
            f"[{n + i}:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[a{i}]"
        )
    audio_inputs = "".join(f"[a{i}]" for i in range(n))
    filter_parts.append(
        f"{audio_inputs}concat=n={n}:v=0:a=1[aout]"
    )

    filter_graph = ";\n".join(filter_parts)

    try:
        await _run_ffmpeg([
            "-y",
            *input_args,
            "-filter_complex", filter_graph,
            "-map", "[vout]",
            "-map", "[aout]",
            "-c:v", "libx264",
            "-preset", "fast",
            "-c:a", "aac",
            "-r", "25",
            str(output_path),
        ])
    finally:
        # Clean up ASS file after encoding
        if ass_path and ass_path.exists():
            ass_path.unlink(missing_ok=True)

