# OpenRouter unified API client for OpenStoryMode

import asyncio
import logging
from typing import Any, Callable, Optional

import httpx

from app.config import config

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterError(Exception):
    """Raised when an OpenRouter API call fails after all retries."""

    def __init__(self, message: str, scene_id: Optional[int] = None):
        self.scene_id = scene_id
        super().__init__(message)


async def with_retries(
    fn: Callable[..., Any],
    *args: Any,
    max_retries: int = 2,
    scene_id: Optional[int] = None,
    **kwargs: Any,
) -> Any:
    """Retry an async callable up to `max_retries` additional times with exponential backoff.

    Total attempts = 1 initial + max_retries.
    Delays: 1s after first failure, 2s after second failure.
    On final failure, raises OpenRouterError with scene identifier and error details.
    """
    last_error: Optional[Exception] = None
    for attempt in range(1 + max_retries):
        try:
            return await fn(*args, **kwargs)
        except Exception as exc:
            last_error = exc
            if attempt < max_retries:
                delay = 2**attempt  # 1s, 2s
                logger.warning(
                    "OpenRouter call failed (attempt %d/%d, scene=%s): %s. Retrying in %ds...",
                    attempt + 1,
                    1 + max_retries,
                    scene_id,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "OpenRouter call failed after %d attempts (scene=%s): %s",
                    1 + max_retries,
                    scene_id,
                    exc,
                )

    raise OpenRouterError(
        f"API call failed after {1 + max_retries} attempts: {last_error}",
        scene_id=scene_id,
    )


class OpenRouterClient:
    """Async client for calling OpenRouter API endpoints."""

    def __init__(self, api_key: Optional[str] = None, base_url: str = OPENROUTER_BASE_URL):
        self.api_key = api_key or config.openrouter_api_key
        self.base_url = base_url

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def llm_completion(
        self,
        prompt: str,
        model: str = "openai/gpt-4o-mini",
        scene_id: Optional[int] = None,
    ) -> dict:
        """Call the OpenRouter chat completion endpoint.

        Returns the parsed JSON response dict.
        """

        async def _call() -> dict:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                    timeout=60.0,
                )
                response.raise_for_status()
                return response.json()

        return await with_retries(_call, scene_id=scene_id)

    async def generate_image(
        self,
        prompt: str,
        width: int,
        height: int,
        model: str = "google/gemini-2.5-flash-image",
        scene_id: Optional[int] = None,
    ) -> bytes:
        """Generate an image via OpenRouter chat completions with modalities: ["image", "text"].

        Uses the chat/completions endpoint with image output modality.
        Returns the raw image bytes decoded from the base64 response.
        """
        import base64

        async def _call() -> bytes:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "modalities": ["image", "text"],
                    },
                    timeout=120.0,
                )
                response.raise_for_status()
                data = response.json()

                choices = data.get("choices", [])
                if not choices:
                    raise ValueError("No choices in image generation response")

                message = choices[0].get("message", {})

                # Images come as: images: [{"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}]
                images = message.get("images", [])
                if images:
                    img_entry = images[0]
                    if isinstance(img_entry, dict):
                        url = img_entry.get("image_url", {}).get("url", "")
                    else:
                        url = str(img_entry)
                    if "," in url:
                        url = url.split(",", 1)[1]
                    return base64.b64decode(url)

                raise ValueError("No image data found in response")

        return await with_retries(_call, scene_id=scene_id)

    async def text_to_speech(
        self,
        text: str,
        model: str = "openai/gpt-audio-mini",
        voice: str = "alloy",
        scene_id: Optional[int] = None,
    ) -> bytes:
        """Generate speech audio via OpenRouter chat completions with streaming audio output.

        OpenRouter requires stream=True for audio output, with pcm16 format.
        Collects streamed base64 PCM chunks, then converts to MP3 via FFmpeg.
        Returns MP3 audio bytes.
        """
        import asyncio
        import base64
        import json as _json

        async def _call() -> bytes:
            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": f"Read the following text aloud exactly as written, with natural narration pacing:\n\n{text}"}],
                        "modalities": ["text", "audio"],
                        "audio": {"voice": voice, "format": "pcm16"},
                        "stream": True,
                    },
                    timeout=120.0,
                ) as response:
                    response.raise_for_status()
                    audio_chunks: list[str] = []
                    async for line in response.aiter_lines():
                        if line.startswith("data: ") and line.strip() != "data: [DONE]":
                            try:
                                chunk = _json.loads(line[6:])
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                audio = delta.get("audio", {})
                                if audio and "data" in audio:
                                    audio_chunks.append(audio["data"])
                            except (_json.JSONDecodeError, IndexError, KeyError):
                                pass

                    if not audio_chunks:
                        raise ValueError("No audio data received from TTS stream")

                    pcm_bytes = base64.b64decode("".join(audio_chunks))

            # Convert PCM16 to MP3 via FFmpeg
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y",
                "-f", "s16le", "-ar", "24000", "-ac", "1",
                "-i", "pipe:0",
                "-c:a", "libmp3lame", "-q:a", "4",
                "-f", "mp3", "pipe:1",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            mp3_bytes, stderr = await proc.communicate(input=pcm_bytes)
            if proc.returncode != 0:
                raise RuntimeError(f"FFmpeg PCM-to-MP3 conversion failed: {stderr.decode()[:200]}")

            return mp3_bytes

        return await with_retries(_call, scene_id=scene_id)
