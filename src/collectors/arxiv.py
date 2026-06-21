"""
OhMyInfo — arXiv paper collector.

Fetches recent papers from arXiv via the arXiv API (Atom/XML).
No API key required — uses the public arXiv API.

    http://export.arxiv.org/api/query?search_query=cat:{category}&max_results=N&sortBy=submittedDate&sortOrder=descending

Usage:
    collector = ArxivCollector()
    articles = await collector.fetch()
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import ClassVar

import feedparser
import httpx

from src.collectors import Article, Collector, CollectorError

_ARXIV_API = "https://export.arxiv.org/api/query"
_DEFAULT_CATEGORIES = ("cs.AI", "cs.LG", "cs.CL")


class ArxivCollector(Collector):
    """arXiv paper collector.

    Iterates over configured arXiv categories, fetches the most recent papers
    from each, and returns them as a flat list of Article objects.

    Default categories: cs.AI, cs.LG, cs.CL
    Rate limit: 1 request per 3 seconds (per arXiv's terms of service).
    """

    DEFAULT_CATEGORIES: ClassVar[tuple[str, ...]] = _DEFAULT_CATEGORIES
    DEFAULT_MAX_RESULTS: ClassVar[int] = 10
    RATE_LIMIT_DELAY: ClassVar[float] = 3.0  # seconds between category requests

    def __init__(
        self,
        categories: tuple[str, ...] | list[str] | None = None,
        max_results: int = 10,
    ) -> None:
        """Initialize the collector.

        Args:
            categories: arXiv category identifiers (default: cs.AI, cs.LG, cs.CL).
            max_results: Max papers per category (default: 10).
        """
        self._categories = tuple(categories) if categories is not None else _DEFAULT_CATEGORIES
        self._max_results = max_results

    # ------------------------------------------------------------------
    # Collector ABC
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "arxiv"

    async def fetch(self) -> list[Article]:
        """Fetch recent papers from all configured categories.

        Returns:
            Flat list of Article objects across all categories.

        Raises:
            CollectorError: If HTTP or parsing errors occur.
        """
        if not self._categories:
            return []

        articles: list[Article] = []
        errors: list[str] = []

        async with httpx.AsyncClient(timeout=self.DEFAULT_TIMEOUT) as client:
            for i, category in enumerate(self._categories):
                # Rate limit: wait between categories (skip wait for first)
                if i > 0:
                    await asyncio.sleep(self.RATE_LIMIT_DELAY)

                try:
                    entry_list = await self._fetch_category(client, category)
                    articles.extend(entry_list)
                except Exception as exc:
                    errors.append(f"{category}: {exc}")

        if errors and not articles:
            raise CollectorError(
                f"All categories failed: {'; '.join(errors)}",
                source=self.name,
            )

        return articles

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_url(self, category: str) -> str:
        """Build the arXiv API URL for a given category."""
        params = (
            f"search_query=cat:{category}"
            f"&max_results={self._max_results}"
            f"&sortBy=submittedDate"
            f"&sortOrder=descending"
        )
        return f"{_ARXIV_API}?{params}"

    async def _fetch_category(
        self,
        client: httpx.AsyncClient,
        category: str,
    ) -> list[Article]:
        """Fetch and parse papers for a single arXiv category."""
        url = self._build_url(category)
        response = await client.get(url)

        if response.status_code != 200:
            raise CollectorError(
                f"arXiv API returned HTTP {response.status_code} for {category}",
                source=self.name,
            )

        articles = self._parse_response(response.text, category)
        return articles

    @staticmethod
    def _parse_response(xml_text: str, category: str) -> list[Article]:
        """Parse Atom XML response from arXiv API into Article objects."""
        feed = feedparser.parse(xml_text)

        if feed.bozo and not feed.entries:
            raise CollectorError(
                f"Failed to parse arXiv XML for {category}: {feed.bozo_exception}",
            )

        articles: list[Article] = []
        for entry in feed.entries:
            try:
                article = _entry_to_article(entry, category)
                articles.append(article)
            except (KeyError, ValueError, AttributeError) as exc:
                # Skip malformed entries
                continue

        return articles


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

# arXiv ID patterns:
#   New format (2007+):   1234.56789 or 1234.123456  (4 digits . 5+ digits)
#   Old format (pre-2007): cs/0702115                 (subject / 7 digits)
_ARXIV_ID_RE = re.compile(
    r"(?:https?://arxiv\.org/(?:abs|pdf)/)?"
    r"(?:(\w+(?:-\w+)?/)?(\d{7})(?:v\d+)?"
    r"|(\d{4}\.\d{5,})(?:v\d+)?)",
)


def _extract_arxiv_id(raw_id: str) -> str:
    """Extract a clean arXiv ID from various URL/ID formats.

    Handles:
        - http://arxiv.org/abs/1234.56789v1       (new format)
        - http://arxiv.org/pdf/1234.56789v1
        - http://arxiv.org/abs/cs/0702115v1        (old format)
        - 1234.56789v1
        - cs/0702115
    """
    match = _ARXIV_ID_RE.search(raw_id)
    if match:
        # Group 1+2: old format (category/1234567)
        if match.group(2):
            # Group 1 already includes trailing slash (e.g. "cs/")
            prefix = match.group(1) or ""
            return f"{prefix}{match.group(2)}"
        # Group 3: new format (1234.56789)
        if match.group(3):
            return match.group(3)
    # Fallback: take the last path component, strip version
    return raw_id.strip().split("/")[-1].split("v")[0]


def _entry_to_article(entry: feedparser.FeedParserDict, category: str) -> Article:
    """Convert a feedparser entry dict into an Article model."""
    # arXiv Atom <id> looks like: http://arxiv.org/abs/1234.56789v1
    raw_id = entry.get("id", "")
    arxiv_id = _extract_arxiv_id(raw_id)
    abstract_url = f"https://arxiv.org/abs/{arxiv_id}"

    # Title — arXiv API sometimes wraps in newlines
    title = entry.get("title", "").replace("\n", " ").replace("\r", " ").strip()

    # Summary / abstract
    summary_raw = entry.get("summary", "")
    summary = summary_raw.replace("\n", " ").strip()
    summary_short = summary[:300]

    # Authors
    authors = [author.get("name", "") for author in entry.get("authors", [])]
    author_str = ", ".join(a for a in authors if a)

    # Published date
    published_raw = entry.get("published", "")
    published_at = _parse_arxiv_date(published_raw)

    # Primary category
    arxiv_category = ""
    if hasattr(entry, "arxiv_primary_category"):
        arxiv_category = entry.arxiv_primary_category.get("term", "")
    if not arxiv_category:
        # Fallback: use the first category tag
        tags = entry.get("tags", [])
        if tags:
            arxiv_category = tags[0].get("term", "")

    # Tags: all categories + author names
    tags: list[str] = [arxiv_category] if arxiv_category else []
    tags.extend(authors)

    # Build article
    article = Article(
        title=title,
        url=abstract_url,
        source="arxiv",
        published_at=published_at,
        summary=summary_short,
        content=summary,
        category=arxiv_category,
        tags=tags,
        author=author_str,
    )
    return article


def _parse_arxiv_date(date_str: str) -> datetime:
    """Parse arXiv date string (ISO 8601) to datetime.

    arXiv dates look like: 2024-01-15T18:30:00Z
    """
    if not date_str:
        return datetime.now(timezone.utc)

    try:
        # Handle 'Z' suffix for UTC
        clean = date_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)
