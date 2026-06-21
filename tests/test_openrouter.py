"""
Tests for src/processors/_providers.py — _OpenRouterProvider.

OpenRouter reuses the OpenAI SDK with a custom base_url.  These tests
verify that the provider wraps SDK calls correctly and translates
SDK-specific exceptions into the module's _ProviderError hierarchy.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.processors._providers import (
    _OpenRouterProvider,
    _RateLimitError,
    _TimeoutError,
)
from src.processors.summarizer import Summarizer


# ============================================================================
# _OpenRouterProvider unit tests
# ============================================================================


class TestOpenRouterProviderInit:
    """_OpenRouterProvider construction."""

    def test_uses_correct_base_url(self) -> None:
        """AsyncOpenAI is initialized with the OpenRouter base URL."""
        with patch(
            "src.processors._providers.openai.AsyncOpenAI",
        ) as mock_client_cls:
            _OpenRouterProvider(api_key="test-key", model="gpt-4o-mini")

            mock_client_cls.assert_called_once_with(
                api_key="test-key",
                base_url="https://openrouter.ai/api/v1",
                timeout=30.0,
            )

    def test_default_model(self) -> None:
        """Default model is gpt-4o-mini when not specified."""
        with patch(
            "src.processors._providers.openai.AsyncOpenAI",
        ) as mock_client_cls:
            provider = _OpenRouterProvider(api_key="test-key")
            assert provider._model == "gpt-4o-mini"
            mock_client_cls.assert_called_once()

    def test_custom_model(self) -> None:
        """Custom model is accepted."""
        with patch(
            "src.processors._providers.openai.AsyncOpenAI",
        ) as mock_client_cls:
            provider = _OpenRouterProvider(
                api_key="test-key", model="google/gemma-4-31b"
            )
            assert provider._model == "google/gemma-4-31b"
            mock_client_cls.assert_called_once()


class TestOpenRouterProviderGenerate:
    """_OpenRouterProvider.generate behavior."""

    @pytest.mark.asyncio
    async def test_generate_calls_sdk_with_extra_headers(self) -> None:
        """generate calls AsyncOpenAI with the expected parameters."""
        mock_completion = MagicMock()
        mock_completion.choices = [
            MagicMock(message=MagicMock(content="OpenRouter response"))
        ]

        with patch(
            "src.processors._providers.openai.AsyncOpenAI",
        ) as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value = mock_client
            mock_client.chat.completions.create = AsyncMock(
                return_value=mock_completion
            )

            provider = _OpenRouterProvider(api_key="test-key")
            result = await provider.generate("Test prompt")

            assert result == "OpenRouter response"
            mock_client.chat.completions.create.assert_awaited_once_with(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "Test prompt"}],
                temperature=0.3,
                max_tokens=500,
                extra_headers={
                    "HTTP-Referer": "https://github.com/silisland/OhMyInfo",
                    "X-Title": "OhMyInfo",
                },
            )

    @pytest.mark.asyncio
    async def test_generate_with_custom_model(self) -> None:
        """Custom model is passed through to the SDK."""
        mock_completion = MagicMock()
        mock_completion.choices = [
            MagicMock(message=MagicMock(content="Response"))
        ]

        with patch(
            "src.processors._providers.openai.AsyncOpenAI",
        ) as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value = mock_client
            mock_client.chat.completions.create = AsyncMock(
                return_value=mock_completion
            )

            provider = _OpenRouterProvider(
                api_key="test-key", model="google/gemma-4-31b"
            )
            result = await provider.generate("Test")

            assert result == "Response"
            mock_client.chat.completions.create.assert_awaited_once_with(
                model="google/gemma-4-31b",
                messages=[{"role": "user", "content": "Test"}],
                temperature=0.3,
                max_tokens=500,
                extra_headers={
                    "HTTP-Referer": "https://github.com/silisland/OhMyInfo",
                    "X-Title": "OhMyInfo",
                },
            )

    @pytest.mark.asyncio
    async def test_empty_content_returns_empty_string(self) -> None:
        """When the SDK returns empty content, an empty string is returned."""
        mock_completion = MagicMock()
        mock_completion.choices = [
            MagicMock(message=MagicMock(content=None))
        ]

        with patch(
            "src.processors._providers.openai.AsyncOpenAI",
        ) as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value = mock_client
            mock_client.chat.completions.create = AsyncMock(
                return_value=mock_completion
            )

            provider = _OpenRouterProvider(api_key="test-key")
            result = await provider.generate("Test")

            assert result == ""


class TestOpenRouterProviderErrors:
    """_OpenRouterProvider error wrapping."""

    @pytest.mark.asyncio
    async def test_rate_limit_wraps_sdk_error(self) -> None:
        """openai.RateLimitError is wrapped as _RateLimitError."""
        import openai

        with patch(
            "src.processors._providers.openai.AsyncOpenAI",
        ) as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value = mock_client
            mock_client.chat.completions.create = AsyncMock(
                side_effect=openai.RateLimitError(
                    "rate limited",
                    response=MagicMock(),
                    body=None,
                )
            )

            provider = _OpenRouterProvider(api_key="test-key")
            with pytest.raises(_RateLimitError):
                await provider.generate("Test")

    @pytest.mark.asyncio
    async def test_timeout_wraps_sdk_timeout_error(self) -> None:
        """openai.APITimeoutError is wrapped as _TimeoutError."""
        import openai

        with patch(
            "src.processors._providers.openai.AsyncOpenAI",
        ) as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value = mock_client
            mock_client.chat.completions.create = AsyncMock(
                side_effect=openai.APITimeoutError("timed out")
            )

            provider = _OpenRouterProvider(api_key="test-key")
            with pytest.raises(_TimeoutError):
                await provider.generate("Test")

    @pytest.mark.asyncio
    async def test_timeout_wraps_asyncio_timeout(self) -> None:
        """asyncio.TimeoutError is wrapped as _TimeoutError."""
        with patch(
            "src.processors._providers.openai.AsyncOpenAI",
        ) as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value = mock_client
            mock_client.chat.completions.create = AsyncMock(
                side_effect=TimeoutError("asyncio timeout")
            )

            provider = _OpenRouterProvider(api_key="test-key")
            with pytest.raises(_TimeoutError):
                await provider.generate("Test")

    @pytest.mark.asyncio
    async def test_non_retriable_error_propagates(self) -> None:
        """Non-retriable errors (e.g. auth) propagate without wrapping."""
        import openai

        with patch(
            "src.processors._providers.openai.AsyncOpenAI",
        ) as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value = mock_client
            mock_client.chat.completions.create = AsyncMock(
                side_effect=openai.APIStatusError(
                    "unauthorized",
                    response=MagicMock(),
                    body=None,
                )
            )

            provider = _OpenRouterProvider(api_key="test-key")
            with pytest.raises(openai.APIStatusError):
                await provider.generate("Test")


# ============================================================================
# Summarizer facade integration tests
# ============================================================================


class TestSummarizerWithOpenRouter:
    """Summarizer facade integration with _OpenRouterProvider."""

    def test_openrouter_provider_selection(self) -> None:
        """Summarizer(provider='openrouter') creates _OpenRouterProvider."""
        with patch(
            "src.processors._providers.openai.AsyncOpenAI",
        ):
            s = Summarizer(provider="openrouter", api_key="test-key")
            assert s.provider_name == "openrouter"
            assert isinstance(s._llm, _OpenRouterProvider)

    def test_openrouter_default_model(self) -> None:
        """Default model for OpenRouter is google/gemma-4-31b."""
        with patch(
            "src.processors._providers.openai.AsyncOpenAI",
        ):
            s = Summarizer(provider="openrouter", api_key="test-key")
            assert s._model == "google/gemma-4-31b"

    def test_openrouter_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """OPENROUTER_API_KEY env var is picked up."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "env-key")
        with patch(
            "src.processors._providers.openai.AsyncOpenAI",
        ):
            s = Summarizer(provider="openrouter")
            assert s._llm is not None
            assert isinstance(s._llm, _OpenRouterProvider)

    def test_openrouter_missing_api_key_fallback(self) -> None:
        """Missing OpenRouter API key results in fallback mode."""
        s = Summarizer(provider="openrouter", api_key="")
        assert s._llm is None

    @pytest.mark.asyncio
    async def test_openrouter_provider_works_with_summarize(self) -> None:
        """Summarizer uses _OpenRouterProvider for LLM calls."""
        mock_completion = MagicMock()
        mock_completion.choices = [
            MagicMock(message=MagicMock(content="OpenRouter summary"))
        ]

        with patch(
            "src.processors._providers.openai.AsyncOpenAI",
        ) as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value = mock_client
            mock_client.chat.completions.create = AsyncMock(
                return_value=mock_completion
            )

            s = Summarizer(provider="openrouter", api_key="test-key")
            article = MagicMock()
            article.summary = ""
            article.url = "https://example.com/test"
            article.title = "Test Article"
            article.content = "Some content here"

            result = await s.summarize(article)
            assert result == "OpenRouter summary"
