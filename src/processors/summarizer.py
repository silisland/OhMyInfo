"""
OhMyInfo — AI-powered summarization and translation module.

Generates Chinese summaries for English articles via configurable LLM providers
(OpenAI, Gemini), with content caching and graceful fallback when the LLM
is unavailable.

Usage::

    summarizer = Summarizer(api_key="...")
    article = Article(title="...", url="...", content="...", source="test")
    summary = await summarizer.summarize(article)
    translated = await summarizer.translate("Hello world")
    updated = await summarizer.summarize_and_translate(article)
"""

from __future__ import annotations

import asyncio  # noqa: ANYIO_OK
import logging
import os
from pathlib import Path
from typing import Final

from src.collectors import Article
from src.processors._cache import SummaryCache
from src.processors._providers import (
    _AbstractProvider,
    _GeminiProvider,
    _OpenAIProvider,
    _ProviderError,
    _RateLimitError,
    _TimeoutError,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_MODELS: Final[dict[str, str]] = {
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.0-flash",
}
_ENV_VAR_MAP: Final[dict[str, str]] = {
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
}
_MAX_RETRIES: Final[int] = 3
_FALLBACK_MAX_CHARS: Final[int] = 200

_SUMMARIZE_PROMPT: Final[str] = (
    "用中文总结以下技术文章的要点（2-3句话）：\n{title}\n\n{content}"
)
_TRANSLATE_PROMPT: Final[str] = "将以下英文技术内容翻译为中文：\n{content}"


# ---------------------------------------------------------------------------
# Summarizer
# ---------------------------------------------------------------------------


class Summarizer:
    """AI-powered summarization and translation for articles.

    Args:
        provider: LLM provider name — ``"gemini"`` (default) or ``"openai"``.
        model:   Model name override.  Falls back to the per-provider default
                 (gemini-2.0-flash / gpt-4o-mini) when *None*.
        api_key: API key for the chosen provider.  Falls back to the
                 ``OPENAI_API_KEY`` / ``GEMINI_API_KEY`` environment variable
                 when *None*.  When both are empty/missing the summarizer
                 operates in **fallback mode** and truncates content instead
                 of calling an LLM.
        cache_dir: Optional directory for persistent summary cache.

    Raises:
        ValueError: When *provider* is not ``"openai"`` or ``"gemini"``.
    """

    def __init__(
        self,
        provider: str = "gemini",
        model: str | None = None,
        api_key: str | None = None,
        cache_dir: str | Path | None = None,
    ) -> None:
        supported = {"openai", "gemini"}
        if provider not in supported:
            msg = f"Unsupported provider: {provider!r}. Choose from {sorted(supported)}."
            raise ValueError(msg)

        self._provider_name = provider
        self._model = model or _DEFAULT_MODELS[provider]
        self._cache = SummaryCache(cache_dir=cache_dir)

        resolved_key = api_key or os.environ.get(_ENV_VAR_MAP[provider])
        if resolved_key:
            match provider:
                case "openai":
                    self._llm: _AbstractProvider = _OpenAIProvider(
                        api_key=resolved_key, model=self._model
                    )
                case "gemini":
                    self._llm = _GeminiProvider(
                        api_key=resolved_key, model=self._model
                    )
                case unreachable:  # pragma: no cover
                    from typing import assert_never

                    assert_never(unreachable)
        else:
            self._llm = None
            logger.info(
                "No API key for %s — operating in fallback mode",
                provider,
            )

    # -- public API ----------------------------------------------------------

    async def summarize(self, article: Article) -> str:
        """Generate a 2--3 sentence Chinese summary of *article*.

        Results are cached by article URL.  When the article already has
        a non-empty summary it is returned immediately.
        """
        if article.summary:
            return article.summary

        cached = self._cache.get(article)
        if cached is not None:
            return cached

        if self._llm is None:
            summary = self._truncate(article.content)
            self._cache.set(article, summary)
            return summary

        prompt = _SUMMARIZE_PROMPT.format(
            title=article.title,
            content=article.content,
        )
        summary = await self._call_with_retry(prompt, article)
        self._cache.set(article, summary)
        return summary

    async def translate(self, text: str, target_lang: str = "zh") -> str:
        """Translate *text* to Chinese (``target_lang="zh"``).

        Falls back to truncation when the LLM is unavailable.
        The *target_lang* parameter is reserved for future multi-language
        support; currently only ``"zh"`` is implemented.
        """
        if self._llm is None:
            return self._truncate(text)

        prompt = _TRANSLATE_PROMPT.format(content=text)
        return await self._call_with_retry(prompt, None)

    async def summarize_and_translate(self, article: Article) -> Article:
        """Full pipeline: summarise *article* in Chinese and return the result.

        The returned ``Article`` has its ``summary`` field set to the
        generated Chinese summary.  The original article is not mutated.
        """
        summary = await self.summarize(article)
        return article.model_copy(update={"summary": summary})

    # -- internals -----------------------------------------------------------

    async def _call_with_retry(
        self,
        prompt: str,
        article: Article | None,
    ) -> str:
        """Call the LLM with exponential-backoff retry on rate limits.

        On timeout or when all retries are exhausted the method falls back
        to truncation.
        """
        assert self._llm is not None

        last_error: _ProviderError | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                return await self._llm.generate(prompt)
            except _RateLimitError as exc:
                last_error = exc
                if attempt < _MAX_RETRIES - 1:
                    wait = 2**attempt
                    logger.info(
                        "Rate limited (attempt %d/%d), retrying in %ds",
                        attempt + 1,
                        _MAX_RETRIES,
                        wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                logger.warning(
                    "Rate limit exhausted after %d retries",
                    _MAX_RETRIES,
                )
            except _TimeoutError as exc:
                last_error = exc
                logger.warning("LLM call timed out, falling back")
                break

        if article is not None:
            return self._truncate(article.content)
        return self._truncate(prompt)

    @staticmethod
    def _truncate(text: str) -> str:
        """Truncate *text* to ``_FALLBACK_MAX_CHARS`` characters."""
        if len(text) <= _FALLBACK_MAX_CHARS:
            return text
        return text[:_FALLBACK_MAX_CHARS] + "..."

    # -- properties ----------------------------------------------------------

    @property
    def provider_name(self) -> str:
        """The name of the configured LLM provider."""
        return self._provider_name


__all__ = [
    "Summarizer",
    "SummaryCache",
]
