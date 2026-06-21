"""Dev.to articles collector.

Fetches articles from the Dev.to public API.
No API key required — uses the free public endpoint at ``/api/articles``.

Usage::

    collector = DevToCollector()
    articles = await collector.fetch()
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

import httpx

from src.collectors import Article, Collector, CollectorError


class DevToCollector(Collector):
    """Collector for Dev.to articles using the public API.

    Fetches from ``https://dev.to/api/articles`` with configurable
    page size and optional ``top`` period filtering.

    Attributes:
        BASE_URL: Dev.to API endpoint.
        DEFAULT_PAGE_SIZE: Number of articles per page.
    """

    BASE_URL: ClassVar[str] = "https://dev.to/api/articles"
    DEFAULT_PAGE_SIZE: ClassVar[int] = 20

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        """Unique collector identifier — ``"devto"``."""
        return "devto"

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def __init__(
        self,
        page_size: int = DEFAULT_PAGE_SIZE,
        top_period: bool = False,
        timeout: int = 30,
        max_retries: int = 3,
    ) -> None:
        """Initialise the collector.

        Args:
            page_size: Articles per page (1-100, API max is 100).
            top_period: When True adds ``?top=1`` for top/month articles.
            timeout: HTTP request timeout in seconds.
            max_retries: Maximum retry attempts (unused, reserved).
        """
        self.page_size = page_size
        self.top_period = top_period
        self.DEFAULT_TIMEOUT = timeout
        self.DEFAULT_MAX_RETRIES = max_retries

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def fetch(self, max_pages: int = 1) -> list[Article]:
        """Fetch articles from Dev.to.

        Args:
            max_pages: Number of result pages to fetch (default 1).

        Returns:
            Parsed ``Article`` objects — may be empty.

        Raises:
            CollectorError: On HTTP or network errors.
        """
        articles: list[Article] = []

        async with httpx.AsyncClient(timeout=self.DEFAULT_TIMEOUT) as client:
            for page in range(1, max_pages + 1):
                try:
                    data = await self._fetch_page(client, page)
                    if not data:
                        break  # no more results

                    for item in data:
                        articles.append(self._parse_article(item))

                except httpx.HTTPStatusError as e:
                    raise CollectorError(
                        f"Dev.to API returned status {e.response.status_code}",
                        source=self.name,
                    ) from e
                except httpx.RequestError as e:
                    raise CollectorError(
                        f"Network error while fetching Dev.to articles: {e}",
                        source=self.name,
                    ) from e

        return articles

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_page(
        self,
        client: httpx.AsyncClient,
        page: int,
    ) -> list[dict[str, Any]]:
        """Fetch a single page of articles from Dev.to API."""
        params: dict[str, Any] = {
            "per_page": self.page_size,
            "page": page,
        }
        if self.top_period:
            params["top"] = 1

        response = await client.get(self.BASE_URL, params=params)
        response.raise_for_status()
        return response.json()

    def _parse_article(self, item: dict[str, Any]) -> Article:
        """Transform a Dev.to API response item into an ``Article``."""
        title = item.get("title") or ""
        url = item.get("canonical_url") or item.get("url") or ""
        description = item.get("description") or ""
        body_markdown = item.get("body_markdown") or ""
        tag_list = item.get("tag_list") or []
        user = item.get("user") or {}
        author = user.get("name", "") if isinstance(user, dict) else ""

        # Parse published_at — ISO 8601 with optional trailing Z
        published_at_str = item.get("published_at") or ""
        published_at = (
            datetime.fromisoformat(published_at_str.replace("Z", "+00:00"))
            if published_at_str
            else datetime.now()
        )

        # Score: weighted engagement metrics capped at 100
        reactions = item.get("positive_reactions_count", 0) or 0
        comments = item.get("comments_count", 0) or 0
        page_views = item.get("page_views_count", 0) or 0

        raw_score = reactions * 2 + comments * 3 + min(page_views, 1000) * 0.05
        score = min(raw_score, 100.0)

        # Normalise tags — API may return list or string
        tags: list[str] = []
        if isinstance(tag_list, list):
            tags = [str(t) for t in tag_list]
        elif isinstance(tag_list, str):
            tags = [t.strip() for t in tag_list.split(",") if t.strip()]

        content = body_markdown or description

        return Article(
            title=title,
            url=url,
            source=self.name,
            published_at=published_at,
            summary=description,
            content=content,
            score=score,
            tags=tags,
            author=author,
        )
