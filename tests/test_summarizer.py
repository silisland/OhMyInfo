"""
Tests for src/processors/summarizer.py — AI-powered summarization and translation.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.collectors import Article
from src.processors._cache import SummaryCache, _cache_key
from src.processors._providers import (
    _GeminiProvider,
    _OpenAIProvider,
    _RateLimitError,
    _TimeoutError,
)
from src.processors.summarizer import Summarizer

# Each async test method uses @pytest.mark.asyncio individually.

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_article() -> Article:
    return Article(
        title="Introduction to Transformer Models",
        url="https://example.com/transformer",
        content=(
            "Transformer models have revolutionized natural language processing. "
            "They use self-attention mechanisms to process sequential data. "
            "This article explains the architecture and its applications. "
            "We also cover multi-head attention, positional encoding, "
            "and how transformers enable parallel computation."
        ),
        source="test",
    )


@pytest.fixture
def long_article() -> Article:
    return Article(
        title="Very Long Article",
        url="https://example.com/long",
        content="Hello world. " * 100,  # ~1200 chars
        source="test",
    )


# ============================================================================
# SummaryCache tests
# ============================================================================


class TestSummaryCache:
    """SummaryCache behavior: hit, miss, expiry, persistence."""

    def test_cache_miss_returns_none(self, sample_article: Article) -> None:
        """A never-cached article returns None."""
        cache = SummaryCache()
        assert cache.get(sample_article) is None

    def test_cache_hit_returns_value(self, sample_article: Article) -> None:
        """A cached article returns its stored summary."""
        cache = SummaryCache()
        cache.set(sample_article, "中文摘要")
        assert cache.get(sample_article) == "中文摘要"

    def test_cache_miss_different_url(self) -> None:
        """Different URLs produce different cache keys."""
        cache = SummaryCache()
        a1 = Article(title="A", url="https://x.com/1", content="c1", source="t")
        a2 = Article(title="B", url="https://x.com/2", content="c2", source="t")

        cache.set(a1, "摘要A")
        assert cache.get(a2) is None

    def test_cache_expires(self, sample_article: Article) -> None:
        """An expired entry returns None."""
        cache = SummaryCache()
        cache.set(sample_article, "旧摘要")

        # Manually set the entry's expiry to the past
        key = _cache_key(sample_article)
        past = datetime.now() - timedelta(hours=1)
        entry = MagicMock()
        entry.value = "旧摘要"
        entry.expires_at = past
        cache._entries[key] = entry  # type: ignore[attr-defined]

        assert cache.get(sample_article) is None

    def test_cache_file_persistence(self, tmp_path: Path, sample_article: Article) -> None:
        """Cache saved to disk is loadable."""
        cache1 = SummaryCache(cache_dir=tmp_path)
        cache1.set(sample_article, "磁盘缓存")

        # Fresh cache instance should load from disk
        cache2 = SummaryCache(cache_dir=tmp_path)
        assert cache2.get(sample_article) == "磁盘缓存"

    def test_cache_clear(self, sample_article: Article) -> None:
        """Clearing the cache removes all entries."""
        cache = SummaryCache()
        cache.set(sample_article, "摘要")
        cache.clear()
        assert cache.get(sample_article) is None


# ============================================================================
# Summarizer initialization tests
# ============================================================================


class TestSummarizerInit:
    """Summarizer construction and provider selection."""

    def test_default_provider_is_gemini(self) -> None:
        """Default provider is gemini."""
        s = Summarizer(api_key="fake-key")
        assert s.provider_name == "gemini"

    def test_openai_provider_selection(self) -> None:
        """Explicit 'openai' provider is accepted."""
        s = Summarizer(provider="openai", api_key="fake-key")
        assert s.provider_name == "openai"

    def test_gemini_provider_selection(self) -> None:
        """Explicit 'gemini' provider is accepted."""
        s = Summarizer(provider="gemini", api_key="fake-key")
        assert s.provider_name == "gemini"

    def test_invalid_provider_raises(self) -> None:
        """An unknown provider name raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported provider"):
            Summarizer(provider="anthropic", api_key="key")  # type: ignore[arg-type]

    def test_missing_api_key_uses_fallback(self) -> None:
        """Missing API key results in fallback mode (no LLM)."""
        s = Summarizer(api_key="")
        assert s._llm is None

    def test_env_var_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """API key from environment variable is picked up."""
        monkeypatch.setenv("GEMINI_API_KEY", "env-key")
        s = Summarizer(provider="gemini")
        assert s._llm is not None


# ============================================================================
# Summarizer fallback tests
# ============================================================================


class TestFallbackBehavior:
    """Fallback mode when no LLM is available."""

    @pytest.mark.asyncio
    async def test_fallback_truncates_long_content(self, long_article: Article) -> None:
        """Content longer than 200 chars is truncated with '...'."""
        s = Summarizer(api_key="")
        summary = await s.summarize(long_article)
        assert len(summary) == 203  # 200 chars + "..."
        assert summary.endswith("...")

    @pytest.mark.asyncio
    async def test_fallback_short_content(self) -> None:
        """Content shorter than 200 chars is kept as-is."""
        article = Article(
            title="Short",
            url="https://x.com/short",
            content="Short content.",
            source="test",
        )
        s = Summarizer(api_key="")
        summary = await s.summarize(article)
        assert summary == "Short content."

    @pytest.mark.asyncio
    async def test_fallback_empty_content(self) -> None:
        """Empty content returns empty string."""
        article = Article(
            title="Empty",
            url="https://x.com/empty",
            content="",
            source="test",
        )
        s = Summarizer(api_key="")
        summary = await s.summarize(article)
        assert summary == ""

    @pytest.mark.asyncio
    async def test_fallback_translate(self) -> None:
        """Translate in fallback mode truncates the input."""
        s = Summarizer(api_key="")
        result = await s.translate("Hello world. " * 100)
        assert result.endswith("...")


# ============================================================================
# Cache integration tests
# ============================================================================


class TestCacheIntegration:
    """Summarizer cache interaction."""

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached(self, sample_article: Article) -> None:
        """Second call with same URL returns cached summary."""
        s = Summarizer(api_key="fake-key")
        s._llm = MagicMock()
        s._llm.generate = AsyncMock(return_value="Chinese summary")

        first = await s.summarize(sample_article)
        assert first == "Chinese summary"
        assert s._llm.generate.call_count == 1  # Called once

        # Change mock — cache should prevent a second call
        s._llm.generate = AsyncMock(return_value="Different summary")
        second = await s.summarize(sample_article)
        assert second == "Chinese summary"  # Cached value
        assert s._llm.generate.call_count == 0  # Not called again

    @pytest.mark.asyncio
    async def test_cache_miss_different_url(self) -> None:
        """Different URLs each trigger an LLM call."""
        s = Summarizer(api_key="fake-key")
        s._llm = MagicMock()
        s._llm.generate = AsyncMock(return_value="摘要")

        a1 = Article(title="A", url="https://x.com/1", content="c1", source="t")
        a2 = Article(title="B", url="https://x.com/2", content="c2", source="t")

        await s.summarize(a1)
        await s.summarize(a2)
        assert s._llm.generate.call_count == 2

    @pytest.mark.asyncio
    async def test_skip_cache_when_article_has_summary(self) -> None:
        """When article.summary is non-empty, it is returned immediately."""
        s = Summarizer(api_key="fake-key")
        s._llm = MagicMock()
        s._llm.generate = AsyncMock(return_value="LLM summary")

        article = Article(
            title="Test",
            url="https://x.com/test",
            content="Some content",
            summary="Existing summary",
            source="test",
        )

        result = await s.summarize(article)
        assert result == "Existing summary"
        s._llm.generate.assert_not_called()


# ============================================================================
# Pipeline tests
# ============================================================================


class TestPipeline:
    """summarize_and_translate pipeline."""

    @pytest.mark.asyncio
    async def test_summarize_and_translate_returns_article(
        self, sample_article: Article
    ) -> None:
        """summarize_and_translate returns an Article with summary set."""
        s = Summarizer(api_key="fake-key")
        s._llm = MagicMock()
        s._llm.generate = AsyncMock(return_value="Transformers 模型的介绍")

        result = await s.summarize_and_translate(sample_article)

        assert isinstance(result, Article)
        assert result.summary == "Transformers 模型的介绍"
        # Original content is preserved
        assert result.content == sample_article.content
        # Original article is not mutated
        assert sample_article.summary == ""


# ============================================================================
# Error handling tests
# ============================================================================


class TestErrorHandling:
    """Summarizer resilience to LLM errors."""

    @pytest.mark.asyncio
    async def test_rate_limit_retry_then_success(self, sample_article: Article) -> None:
        """Rate limit triggers retry; eventual success returns the summary."""
        s = Summarizer(api_key="fake-key")
        s._llm = MagicMock()
        s._llm.generate = AsyncMock(
            side_effect=[
                _RateLimitError("too fast"),
                _RateLimitError("too fast"),
                "最终摘要",
            ]
        )

        summary = await s.summarize(sample_article)
        assert summary == "最终摘要"
        assert s._llm.generate.call_count == 3

    @pytest.mark.asyncio
    async def test_rate_limit_exhausted_falls_back(
        self, sample_article: Article
    ) -> None:
        """All rate-limit retries exhausted → fallback truncation."""
        s = Summarizer(api_key="fake-key")
        s._llm = MagicMock()
        s._llm.generate = AsyncMock(side_effect=_RateLimitError("always limited"))

        summary = await s.summarize(sample_article)
        # Falls back to truncated content
        assert len(summary) > 0
        assert summary.endswith("...")

    @pytest.mark.asyncio
    async def test_timeout_falls_back_immediately(
        self, sample_article: Article
    ) -> None:
        """Timeout falls back to truncation without retry."""
        s = Summarizer(api_key="fake-key")
        s._llm = MagicMock()
        s._llm.generate = AsyncMock(side_effect=_TimeoutError("timed out"))

        summary = await s.summarize(sample_article)
        assert summary.endswith("...")
        # Should only have been called once (no retry on timeout)
        assert s._llm.generate.call_count == 1

    @pytest.mark.asyncio
    async def test_translate_timeout_falls_back(self) -> None:
        """translate() also falls back on timeout."""
        s = Summarizer(api_key="fake-key")
        s._llm = MagicMock()
        s._llm.generate = AsyncMock(side_effect=_TimeoutError("timed out"))

        result = await s.translate("Hello world. " * 50)
        assert result.endswith("...")

    @pytest.mark.asyncio
    async def test_non_retriable_error_propagates(
        self, sample_article: Article
    ) -> None:
        """Non-retriable errors (e.g. auth) propagate to the caller."""
        s = Summarizer(api_key="fake-key")
        s._llm = MagicMock()
        s._llm.generate = AsyncMock(side_effect=ValueError("invalid key"))

        with pytest.raises(ValueError, match="invalid key"):
            await s.summarize(sample_article)


# ============================================================================
# Provider-level tests (mock SDK calls)
# ============================================================================


class TestOpenAIProvider:
    """_OpenAIProvider wraps the openai SDK correctly."""

    @pytest.mark.asyncio
    async def test_generate_calls_sdk(self) -> None:
        """_OpenAIProvider.generate calls AsyncOpenAI.chat.completions.create."""
        mock_completion = MagicMock()
        mock_completion.choices = [
            MagicMock(message=MagicMock(content="SDK response"))
        ]

        with patch(
            "src.processors._providers.openai.AsyncOpenAI",
        ) as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value = mock_client
            mock_client.chat.completions.create = AsyncMock(
                return_value=mock_completion
            )

            provider = _OpenAIProvider(api_key="test-key")
            result = await provider.generate("Test prompt")

            assert result == "SDK response"
            mock_client.chat.completions.create.assert_awaited_once_with(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "Test prompt"}],
                temperature=0.3,
                max_tokens=500,
            )

    @pytest.mark.asyncio
    async def test_rate_limit_wraps_sdk_error(self) -> None:
        """openai.RateLimitError is wrapped as _RateLimitError."""
        import openai

        with patch(
            "src.processors._providers.openai.AsyncOpenAI",
            autospec=True,
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

            provider = _OpenAIProvider(api_key="test-key")
            with pytest.raises(_RateLimitError):
                await provider.generate("Test")


class TestGeminiProvider:
    """_GeminiProvider wraps the google.genai SDK correctly."""

    @pytest.mark.asyncio
    async def test_generate_calls_sdk(self) -> None:
        """_GeminiProvider.generate calls Client.aio.models.generate_content."""
        mock_response = MagicMock()
        mock_response.text = "Gemini response"

        with patch(
            "src.processors._providers.genai.Client",
        ) as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value = mock_client
            mock_client.aio.models.generate_content = AsyncMock(
                return_value=mock_response
            )

            provider = _GeminiProvider(api_key="test-key")
            result = await provider.generate("Test prompt")

            assert result == "Gemini response"
            mock_client.aio.models.generate_content.assert_awaited_once_with(
                model="gemini-2.0-flash",
                contents="Test prompt",
                config={"temperature": 0.3, "max_output_tokens": 500},
            )

    @pytest.mark.asyncio
    async def test_rate_limit_wraps_sdk_error(self) -> None:
        """Gemini API 429 error is wrapped as _RateLimitError."""
        import google.genai.errors as genai_errors

        api_error = genai_errors.APIError(
            code=429,
            response_json={"error": "rate limit"},
        )

        with patch(
            "src.processors._providers.genai.Client",
        ) as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value = mock_client
            mock_client.aio.models.generate_content = AsyncMock(
                side_effect=api_error
            )

            provider = _GeminiProvider(api_key="test-key")
            with pytest.raises(_RateLimitError):
                await provider.generate("Test")
