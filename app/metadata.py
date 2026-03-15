"""Video metadata extraction utility using FFmpeg probe."""

import asyncio
import json
import logging
import math
from pathlib import Path

logger = logging.getLogger(__name__)


def _compute_aspect_ratio(width: int, height: int) -> str:
    """Compute a human-readable aspect ratio string from width and height."""
    if width <= 0 or height <= 0:
        return "unknown"
    divisor = math.gcd(width, height)
    w = width // divisor
    h = height // divisor
    return f"{w}:{h}"


async def extract_video_metadata(video_path: Path) -> dict:
    """Extract duration, aspect ratio, dimensions, and file size from an MP4 file.

    Uses ffprobe to get duration and dimensions, and Path.stat() for file size.

    Args:
        video_path: Path to the MP4 video file.

    Returns:
        A dict with keys: duration (float, seconds), aspect_ratio (str),
        file_size (int, bytes), width (int), height (int).

    Raises:
        FileNotFoundError: If the video file does not exist.
        RuntimeError: If ffprobe fails to extract metadata.
    """
    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    file_size = video_path.stat().st_size

    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(video_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        error_msg = stderr.decode().strip() if stderr else "Unknown ffprobe error"
        raise RuntimeError(f"ffprobe failed: {error_msg}")

    try:
        probe_data = json.loads(stdout.decode())
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse ffprobe output: {e}")

    # Extract duration from format section
    duration = float(probe_data.get("format", {}).get("duration", 0.0))

    # Find the video stream for dimensions
    width = 0
    height = 0
    for stream in probe_data.get("streams", []):
        if stream.get("codec_type") == "video":
            width = int(stream.get("width", 0))
            height = int(stream.get("height", 0))
            break

    aspect_ratio = _compute_aspect_ratio(width, height)

    return {
        "duration": duration,
        "aspect_ratio": aspect_ratio,
        "file_size": file_size,
        "width": width,
        "height": height,
    }
