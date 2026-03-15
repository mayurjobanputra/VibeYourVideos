from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional
import uuid


class VideoLength(str, Enum):
    TEN = "10s"
    THIRTY = "30s"
    SIXTY = "60s"
    NINETY = "90s"

    def to_seconds(self) -> int:
        return int(self.value.replace("s", ""))


class AspectRatio(str, Enum):
    VERTICAL = "9:16"
    HORIZONTAL = "16:9"

    def resolution(self) -> tuple[int, int]:
        if self == AspectRatio.VERTICAL:
            return (720, 1280)
        return (1280, 720)


class JobStage(str, Enum):
    QUEUED = "queued"
    SCRIPT_GENERATION = "script_generation"
    VISUAL_GENERATION = "visual_generation"
    TTS_SYNTHESIS = "tts_synthesis"
    VIDEO_ASSEMBLY = "video_assembly"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class Scene:
    index: int
    narration_text: str
    visual_description: str


@dataclass
class SceneAsset:
    scene_index: int
    image_path: Optional[Path] = None
    audio_path: Optional[Path] = None


@dataclass
class GenerationRequest:
    prompt: str
    video_length: VideoLength
    aspect_ratio: AspectRatio


@dataclass
class Job:
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    request: Optional[GenerationRequest] = None
    stage: JobStage = JobStage.QUEUED
    scenes: list[Scene] = field(default_factory=list)
    assets: list[SceneAsset] = field(default_factory=list)
    video_path: Optional[Path] = None
    error: Optional[str] = None
    error_stage: Optional[JobStage] = None
