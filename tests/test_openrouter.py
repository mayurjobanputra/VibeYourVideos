# Tests for app/openrouter.py — retry logic and OpenRouter client

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from app.openrouter import OpenRouterError, with_retries, OpenRouterClient


# --- Tests for with_retries ---


@pytest.mark.asyncio
async def test_with_retries_succeeds_first_try():
    """Succeeds on the first attempt without retrying."""
    fn = AsyncMock(return_value="ok")
    result = await with_retries(fn, scene_id=0)
    assert result == "ok"
    assert fn.call_count == 1


@pytest.mark.asyncio
async def test_with_retries_succeeds_after_one_failure():
    """Fails once, then succeeds on the second attempt."""
    fn = AsyncMock(side_effect=[RuntimeError("fail"), "ok"])
    result = await with_retries(fn, scene_id=1, max_retries=2)
    assert result == "ok"
    assert fn.call_count == 2


@pytest.mark.asyncio
async def test_with_retries_succeeds_after_two_failures():
    """Fails twice, then succeeds on the third (final) attempt."""
    fn = AsyncMock(side_effect=[RuntimeError("fail1"), RuntimeError("fail2"), "ok"])
    result = await with_retries(fn, scene_id=2, max_retries=2)
    assert result == "ok"
    assert fn.call_count == 3


@pytest.mark.asyncio
async def test_with_retries_raises_after_all_retries_exhausted():
    """Fails all 3 attempts and raises OpenRouterError with scene_id."""
    fn = AsyncMock(side_effect=RuntimeError("always fails"))
    with pytest.raises(OpenRouterError) as exc_info:
        await with_retries(fn, scene_id=5, max_retries=2)
    assert fn.call_count == 3
    assert exc_info.value.scene_id == 5
    assert "3 attempts" in str(exc_info.value)


@pytest.mark.asyncio
async def test_with_retries_no_scene_id():
    """scene_id defaults to None when not provided."""
    fn = AsyncMock(side_effect=RuntimeError("fail"))
    with pytest.raises(OpenRouterError) as exc_info:
        await with_retries(fn, max_retries=0)
    assert exc_info.value.scene_id is None


@pytest.mark.asyncio
async def test_with_retries_exponential_backoff():
    """Verify that sleep is called with exponential delays (1s, 2s)."""
    fn = AsyncMock(side_effect=[RuntimeError("f1"), RuntimeError("f2"), "ok"])
    with patch("app.openrouter.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await with_retries(fn, scene_id=0, max_retries=2)
    assert result == "ok"
    assert mock_sleep.call_count == 2
    mock_sleep.assert_any_call(1)  # 2^0
    mock_sleep.assert_any_call(2)  # 2^1


# --- Tests for OpenRouterClient ---


@pytest.mark.asyncio
async def test_llm_completion_calls_correct_endpoint():
    """llm_completion posts to /chat/completions with correct payload."""
    client = OpenRouterClient(api_key="test-key", base_url="https://fake.api")

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"choices": [{"message": {"content": "hi"}}]}

    with patch("app.openrouter.httpx.AsyncClient") as MockClient:
        mock_ctx = AsyncMock()
        mock_ctx.post = AsyncMock(return_value=mock_response)
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await client.llm_completion("test prompt", scene_id=0)

    assert result == {"choices": [{"message": {"content": "hi"}}]}
    mock_ctx.post.assert_called_once()
    call_args = mock_ctx.post.call_args
    assert "/chat/completions" in call_args[0][0]


@pytest.mark.asyncio
async def test_text_to_speech_returns_bytes():
    """text_to_speech returns raw audio bytes."""
    client = OpenRouterClient(api_key="test-key", base_url="https://fake.api")

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.content = b"fake-audio-data"

    with patch("app.openrouter.httpx.AsyncClient") as MockClient:
        mock_ctx = AsyncMock()
        mock_ctx.post = AsyncMock(return_value=mock_response)
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await client.text_to_speech("Hello world", scene_id=1)

    assert result == b"fake-audio-data"
