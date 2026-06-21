"""
OhMyInfo — Internal LLM provider implementations.

Each provider wraps a specific SDK (OpenAI, Gemini) and translates its
SDK-specific exceptions into the module's ``_ProviderError`` hierarchy
so the caller only needs to catch ``_RateLimitError`` and ``_TimeoutError``.
"""

from __future__ import annotations

import asyncio  # noqa: ANYIO_OK
import logging
from abc import ABC, abstractmethod

import openai

try:
    import google.genai as genai
    import google.genai.errors as genai_errors

    _HAS_GEMINI = True
except ImportError:  # pragma: no cover
    _HAS_GEMINI = False

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal exceptions (provider-agnostic)
# ---------------------------------------------------------------------------


class _ProviderError(Exception):
    """Base exception for all provider errors."""


class _RateLimitError(_ProviderError):
    """Provider returned a rate-limit response."""


class _TimeoutError(_ProviderError):
    """Provider request timed out."""


# ---------------------------------------------------------------------------
# Provider interface
# ---------------------------------------------------------------------------


class _AbstractProvider(ABC):
    """Interface that every provider implements."""

    @abstractmethod
    async def generate(self, prompt: str) -> str:
        """Send *prompt* to the LLM and return the text response."""


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------


class _OpenAIProvider(_AbstractProvider):
    """Wrapper around OpenAI's ``AsyncOpenAI`` client."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        self._client = openai.AsyncOpenAI(api_key=api_key, timeout=30.0)
        self._model = model

    async def generate(self, prompt: str) -> str:
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=500,
            )
        except openai.RateLimitError as exc:
            raise _RateLimitError(str(exc)) from exc
        except (openai.APITimeoutError, asyncio.TimeoutError) as exc:
            raise _TimeoutError(str(exc)) from exc

        msg = response.choices[0].message
        return msg.content or ""


# ---------------------------------------------------------------------------
# OpenRouter — fully OpenAI-compatible, custom base_url
# ---------------------------------------------------------------------------


class _OpenRouterProvider(_AbstractProvider):
    """OpenRouter provider — uses the OpenAI SDK with a custom ``base_url``.

    OpenRouter is a unified API gateway for 100+ LLMs.  Its API is identical
    to OpenAI's chat-completion format, so we reuse ``openai.AsyncOpenAI``
    with ``base_url`` pointed at ``https://openrouter.ai/api/v1``.

    See https://openrouter.ai/docs for available models and pricing.
    """

    OPENROUTER_BASE_URL: Final[str] = "https://openrouter.ai/api/v1"

    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        self._client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=self.OPENROUTER_BASE_URL,
            timeout=30.0,
        )
        self._model = model

    async def generate(self, prompt: str) -> str:
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=500,
                # Recommended by OpenRouter for dashboard attribution
                extra_headers={
                    "HTTP-Referer": "https://github.com/silisland/OhMyInfo",
                    "X-Title": "OhMyInfo",
                },
            )
        except openai.RateLimitError as exc:
            raise _RateLimitError(str(exc)) from exc
        except (openai.APITimeoutError, asyncio.TimeoutError) as exc:
            raise _TimeoutError(str(exc)) from exc

        msg = response.choices[0].message
        return msg.content or ""


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------


class _GeminiProvider(_AbstractProvider):
    """Wrapper around Google's ``google.genai`` client."""

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash") -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model

    async def generate(self, prompt: str) -> str:
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=prompt,
                config={
                    "temperature": 0.3,
                    "max_output_tokens": 500,
                },
            )
        except genai_errors.APIError as exc:
            if getattr(exc, "code", None) == 429:
                raise _RateLimitError(str(exc)) from exc
            raise
        except asyncio.TimeoutError as exc:
            raise _TimeoutError(str(exc)) from exc

        return response.text
