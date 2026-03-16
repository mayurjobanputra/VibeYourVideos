"""Caption renderer module for video captions.

Supports two backends:
1. ASS subtitle files (preferred) — generates a .ass file with per-word
   rolling-window timing, rendered by FFmpeg's `ass` filter. Efficient
   even for hundreds of words across many scenes.
2. FFmpeg drawtext filters (legacy) — one drawtext per word, used only
   for single-scene videos where the filter graph stays small.
"""

import logging
import unicodedata
from pathlib import Path

logger = logging.getLogger(__name__)

# Characters that require backslash escaping in FFmpeg drawtext filter syntax
_FFMPEG_SPECIAL_CHARS = r""":\'[];="""

# Caption style constants
FONT_FAMILY = "Sans-Bold"
FONT_SIZE_HORIZONTAL = 96
FONT_SIZE_VERTICAL = 84
FONT_COLOR = "white"
BORDER_W = 4  # Black stroke border around each letter
MAX_WIDTH_RATIO = 0.8
LOWER_THIRD_Y_RATIO = 0.75
ROLLING_WINDOW_SECONDS = 1.0  # Show only words from the last ~1 second


def _is_renderable(ch: str) -> bool:
    """Return True if a character is considered renderable by FFmpeg drawtext."""
    if ch == "\n" or ch == "\r" or ch == "\t":
        return True
    cat = unicodedata.category(ch)
    return cat[0] in ("L", "M", "N", "P", "S", "Z")


def escape_ffmpeg_text(text: str) -> str:
    """Escape special characters for FFmpeg drawtext filter."""
    # Normalize curly quotes to straight equivalents before escaping
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    result: list[str] = []
    for ch in text:
        if not _is_renderable(ch):
            result.append(" ")
            continue
        if ch in _FFMPEG_SPECIAL_CHARS:
            result.append("\\" + ch)
        else:
            result.append(ch)
    return "".join(result)


def unescape_ffmpeg_text(escaped: str) -> str:
    """Reverse the escaping performed by escape_ffmpeg_text."""
    result: list[str] = []
    i = 0
    while i < len(escaped):
        if escaped[i] == "\\" and i + 1 < len(escaped) and escaped[i + 1] in _FFMPEG_SPECIAL_CHARS:
            result.append(escaped[i + 1])
            i += 2
        else:
            result.append(escaped[i])
            i += 1
    return "".join(result)


# ---------------------------------------------------------------------------
# ASS subtitle generation (preferred for multi-scene)
# ---------------------------------------------------------------------------

def _format_ass_time(seconds: float) -> str:
    """Format seconds as ASS timestamp: H:MM:SS.cc (centiseconds)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _escape_ass_text(text: str) -> str:
    """Escape text for ASS dialogue lines."""
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def build_ass_file(
    scenes: list,
    durations: list[float],
    video_width: int,
    video_height: int,
    start_times: list[float],
    crossfade_duration: float,
    output_path: Path,
) -> Path:
    """Generate an ASS subtitle file with rolling-window per-word captions.

    Args:
        scenes: List of Scene objects with narration_text.
        durations: Audio duration per scene in seconds.
        video_width: Output video width in pixels.
        video_height: Output video height in pixels.
        start_times: Cumulative start time of each scene in the final video.
        crossfade_duration: Duration of crossfade overlap in seconds.
        output_path: Directory to write the .ass file into.

    Returns:
        Path to the generated .ass file.
    """
    is_vertical = video_height > video_width
    font_size = FONT_SIZE_VERTICAL if is_vertical else FONT_SIZE_HORIZONTAL
    avg_char_width = font_size * 0.55
    max_text_width = int(video_width * MAX_WIDTH_RATIO)

    # ASS margin from edges (in pixels)
    margin_h = int(video_width * (1 - MAX_WIDTH_RATIO) / 2)
    # Vertical position: ASS MarginV is distance from bottom
    margin_v = int(video_height * (1 - LOWER_THIRD_Y_RATIO))

    # ASS header
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {video_width}",
        f"PlayResY: {video_height}",
        "WrapStyle: 0",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,{FONT_FAMILY},{font_size},"
        f"&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
        f"-1,0,0,0,100,100,0,0,1,{BORDER_W},0,"
        f"2,{margin_h},{margin_h},{margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    n = len(scenes)
    for i in range(n):
        scene = scenes[i]
        if not scene.narration_text or not scene.narration_text.strip():
            continue

        words = scene.narration_text.split()
        if not words:
            continue

        n_words = len(words)
        crossfade_dur = crossfade_duration if i > 0 else 0.0
        caption_start = start_times[i] + crossfade_dur
        scene_end = start_times[i] + durations[i]
        caption_duration = scene_end - caption_start
        if caption_duration <= 0:
            caption_duration = durations[i]

        # Per-word reveal times proportional to character count
        total_chars = sum(len(w) for w in words)
        if total_chars == 0:
            continue

        word_times: list[float] = []
        cumulative = 0
        for w in words:
            t = caption_start + (cumulative / total_chars) * caption_duration
            word_times.append(t)
            cumulative += len(w)

        # Build rolling window dialogue events
        for wi in range(n_words):
            reveal_time = word_times[wi]
            end_time = word_times[wi + 1] if wi + 1 < n_words else scene_end

            # Rolling window: include words from last ROLLING_WINDOW_SECONDS
            window_start_time = reveal_time - ROLLING_WINDOW_SECONDS
            window_start_idx = wi
            for j in range(wi, -1, -1):
                if word_times[j] >= window_start_time:
                    window_start_idx = j
                else:
                    break

            window_words = words[window_start_idx: wi + 1]

            # Line-wrap
            text_lines: list[str] = []
            current_line: list[str] = []
            current_width = 0.0
            for w in window_words:
                w_width = len(w) * avg_char_width
                space_width = avg_char_width if current_line else 0
                if current_line and (current_width + space_width + w_width) > max_text_width:
                    text_lines.append(" ".join(current_line))
                    current_line = [w]
                    current_width = w_width
                else:
                    current_line.append(w)
                    current_width += space_width + w_width
            if current_line:
                text_lines.append(" ".join(current_line))

            # ASS uses \N for line breaks
            display_text = "\\N".join(_escape_ass_text(line) for line in text_lines)

            start_ts = _format_ass_time(reveal_time)
            end_ts = _format_ass_time(end_time)
            lines.append(
                f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,{display_text}"
            )

    ass_path = output_path / "captions.ass"
    ass_path.write_text("\n".join(lines), encoding="utf-8")
    return ass_path


# ---------------------------------------------------------------------------
# Drawtext filter generation (legacy, used for single-scene only)
# ---------------------------------------------------------------------------

def build_drawtext_filter(
    text: str,
    duration: float,
    video_width: int,
    video_height: int,
    start_time: float = 0.0,
    crossfade_duration: float = 0.0,
) -> str:
    """Generate FFmpeg drawtext filter expressions for rolling-window captions.

    Returns a comma-separated chain of drawtext filter strings, or empty
    string for empty text. Suitable for single-scene videos only.
    """
    if duration <= 0:
        raise ValueError(f"Duration must be positive, got {duration}")

    if not text or not text.strip():
        logger.warning("Empty caption text, skipping drawtext filter")
        return ""

    words = text.split()
    if not words:
        return ""

    n_words = len(words)
    is_vertical = video_height > video_width
    font_size = FONT_SIZE_VERTICAL if is_vertical else FONT_SIZE_HORIZONTAL
    max_text_width = int(video_width * MAX_WIDTH_RATIO)
    avg_char_width = font_size * 0.55
    y_pos = int(video_height * LOWER_THIRD_Y_RATIO)

    caption_start = start_time + crossfade_duration
    scene_end = start_time + duration
    caption_duration = scene_end - caption_start
    if caption_duration <= 0:
        caption_duration = duration

    total_chars = sum(len(w) for w in words)
    if total_chars == 0:
        return ""

    word_times: list[float] = []
    cumulative = 0
    for w in words:
        t = caption_start + (cumulative / total_chars) * caption_duration
        word_times.append(t)
        cumulative += len(w)

    filters: list[str] = []
    for i in range(n_words):
        reveal_time = word_times[i]
        end_time = word_times[i + 1] if i + 1 < n_words else scene_end

        window_start_time = reveal_time - ROLLING_WINDOW_SECONDS
        window_start_idx = i
        for j in range(i, -1, -1):
            if word_times[j] >= window_start_time:
                window_start_idx = j
            else:
                break

        window_words = words[window_start_idx: i + 1]

        lines: list[str] = []
        current_line: list[str] = []
        current_width = 0.0
        for w in window_words:
            w_width = len(w) * avg_char_width
            space_width = avg_char_width if current_line else 0
            if current_line and (current_width + space_width + w_width) > max_text_width:
                lines.append(" ".join(current_line))
                current_line = [w]
                current_width = w_width
            else:
                current_line.append(w)
                current_width += space_width + w_width
        if current_line:
            lines.append(" ".join(current_line))

        # Escape each line individually, then join with FFmpeg's drawtext
        # line-break sequence (literal backslash + n).  We must escape first
        # so that the backslash in the join separator isn't double-escaped.
        escaped_lines = [escape_ffmpeg_text(line) for line in lines]
        escaped_text = "\x5cn".join(escaped_lines)
        x_margin = int(video_width * (1 - MAX_WIDTH_RATIO) / 2)

        dt_filter = (
            f"drawtext=text='{escaped_text}'"
            f":font='{FONT_FAMILY}'"
            f":fontsize={font_size}"
            f":fontcolor={FONT_COLOR}"
            f":borderw={BORDER_W}:bordercolor=black"
            f":x=max({x_margin}\\,(w-text_w)/2)"
            f":y={y_pos}"
            f":enable='between(t,{reveal_time:.4f},{end_time:.4f})'"
        )
        filters.append(dt_filter)

    return ",".join(filters)
