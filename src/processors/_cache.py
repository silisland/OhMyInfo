"""
OhMyInfo — Internal summary cache module.

Provides ``SummaryCache``, a dict + file-persisted cache keyed by
``hashlib.sha256(article.url)`` with 24-hour TTL.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Final

from src.collectors import Article

logger = logging.getLogger(__name__)

_CACHE_TTL: Final[timedelta] = timedelta(hours=24)
_CACHE_FILENAME: Final[str] = "summaries_cache.json"


class _CacheEntry:
    """A single cache entry with value and expiry."""

    __slots__ = ("value", "expires_at")

    def __init__(self, value: str, expires_at: datetime) -> None:
        self.value = value
        self.expires_at = expires_at


def _cache_key(article: Article) -> str:
    """Deterministic cache key from an article's URL."""
    return hashlib.sha256(article.url.encode("utf-8")).hexdigest()


class SummaryCache:
    """In-memory + file-persisted cache for LLM summarization results.

    Keyed by ``hashlib.sha256(article.url)``.  Entries expire after 24 hours.
    When *cache_dir* is provided the cache is persisted to a JSON file
    on every write and reloaded on construction.

    Args:
        cache_dir: Optional directory for the on-disk cache file.
    """

    def __init__(self, cache_dir: str | Path | None = None) -> None:
        self._entries: dict[str, _CacheEntry] = {}
        self._cache_dir = Path(cache_dir).resolve() if cache_dir else None
        self._load()

    def get(self, article: Article) -> str | None:
        """Return cached summary for *article*, or *None* on miss/expiry."""
        key = _cache_key(article)
        entry = self._entries.get(key)
        if entry is not None and entry.expires_at > datetime.now():
            logger.debug("Cache hit for %s", article.url)
            return entry.value
        return None

    def set(self, article: Article, summary: str) -> None:
        """Store *summary* for *article* with a 24-hour TTL."""
        key = _cache_key(article)
        self._entries[key] = _CacheEntry(
            value=summary,
            expires_at=datetime.now() + _CACHE_TTL,
        )
        self._save()

    def _load(self) -> None:
        if self._cache_dir is None:
            return
        cache_file = self._cache_dir / _CACHE_FILENAME
        if not cache_file.exists():
            return
        try:
            with open(cache_file) as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load cache: %s", exc)
            return

        now = datetime.now()
        loaded = 0
        for key_str, entry_raw in raw.items():
            try:
                expires_at = datetime.fromisoformat(entry_raw["expires_at"])
                if expires_at > now:
                    self._entries[key_str] = _CacheEntry(
                        value=entry_raw["value"],
                        expires_at=expires_at,
                    )
                    loaded += 1
            except (KeyError, ValueError, TypeError):
                continue
        logger.debug("Loaded %d valid cache entries from %s", loaded, cache_file)

    def _save(self) -> None:
        if self._cache_dir is None:
            return
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = self._cache_dir / _CACHE_FILENAME
        raw = {
            key: {
                "value": entry.value,
                "expires_at": entry.expires_at.isoformat(),
            }
            for key, entry in self._entries.items()
        }
        try:
            with open(cache_file, "w") as f:
                json.dump(raw, f, ensure_ascii=False)
        except OSError as exc:
            logger.warning("Failed to save cache: %s", exc)

    def clear(self) -> None:
        """Remove all entries (useful in tests)."""
        self._entries.clear()
