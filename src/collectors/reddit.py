"""
RedditCollector — Reddit hot posts collector via public JSON API.

Uses Reddit's public JSON endpoint (no OAuth required for reading public
subreddits).  Fetches hot posts from configurable subreddits, filters by
minimum upvotes, and normalizes Reddit scores to the 0-100 Article scale.

Rate limiting: 1 request/second between subreddit fetches (well within
Reddit's 60 requests/minute limit).
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone
from typing import Any, ClassVar

import httpx

from src.collectors import Article, Collector, CollectorError

_USER_AGENT = "OhMyInfo/1.0 (https://github.com/ohmyinfo)"


class RedditCollector(Collector):
    """Collect hot posts from Reddit subreddits via the public JSON API.

    Parameters
    ----------
    subreddits :
        List of subreddit names to collect from.
        Defaults to ``["MachineLearning", "programming", "artificial", "LocalLLaMA"]``.
    min_upvotes :
        Minimum score (upvotes) a post must have to be included.
    top_count :
        Number of posts to fetch per subreddit (passed as ``?limit=``).
    http_client :
        Optional shared ``httpx.AsyncClient``.  When provided the caller
        owns its lifecycle; when omitted the collector creates and closes
        one per ``fetch()`` call.
    """

    BASE_URL: ClassVar[str] = "https://www.reddit.com"

    DEFAULT_SUBREDDITS: ClassVar[list[str]] = [
        "MachineLearning",
        "programming",
        "artificial",
        "LocalLLaMA",
    ]
    DEFAULT_MIN_UPVOTES: ClassVar[int] = 100
    DEFAULT_TOP_COUNT: ClassVar[int] = 10

    # 1 second between requests keeps us well under 60 req/min
    _RATE_LIMIT_DELAY: ClassVar[float] = 1.0

    def __init__(
        self,
        subreddits: list[str] | None = None,
        min_upvotes: int = DEFAULT_MIN_UPVOTES,
        top_count: int = DEFAULT_TOP_COUNT,
        http_client: httpx.AsyncClient | None = None,
        search_topics: list[str] | None = None,
    ) -> None:
        self._subreddits = subreddits or list(self.DEFAULT_SUBREDDITS)
        self._min_upvotes = min_upvotes
        self._top_count = top_count
        self._http_client = http_client
        self._search_topics = search_topics or []

    # ------------------------------------------------------------------
    # Collector interface
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "reddit"

    async def fetch(self) -> list[Article]:
        client: httpx.AsyncClient
        use_own_client: bool
        if self._http_client is not None:
            client = self._http_client
            use_own_client = False
        else:
            client = self._build_client()
            use_own_client = True

        try:
            articles: list[Article] = []
            for i, subreddit in enumerate(self._subreddits):
                if i > 0:
                    await asyncio.sleep(self._RATE_LIMIT_DELAY)
                batch = await self._fetch_subreddit(client, subreddit)
                articles.extend(batch)

            if self._search_topics:
                articles = await self._add_search_results(client, articles)

            return articles
        except httpx.HTTPError as exc:
            msg = f"Reddit API request failed: {exc}"
            raise CollectorError(msg, source=self.name) from exc
        finally:
            if use_own_client:
                await client.aclose()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT},
            timeout=httpx.Timeout(self.DEFAULT_TIMEOUT),
        )

    async def _fetch_subreddit(
        self,
        client: httpx.AsyncClient,
        subreddit: str,
    ) -> list[Article]:
        """Fetch one subreddit's hot listing and parse articles."""
        url = f"{self.BASE_URL}/r/{subreddit}/hot.json?limit={self._top_count}"
        response = await client.get(url)
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return self._parse_listing(data, subreddit)

    async def _search_subreddit(
        self,
        client: httpx.AsyncClient,
        subreddit: str,
        topic: str,
    ) -> list[Article]:
        """Search a subreddit for topic-specific posts.

        Args:
            client: HTTP client for the request.
            subreddit: Subreddit name to search within.
            topic: Topic search query.

        Returns:
            List of :class:`Article` objects matching the topic.
        """
        url = (
            f"{self.BASE_URL}/r/{subreddit}/search.json"
            f"?q={topic}&restrict_sr=1&sort=top&t=week&limit=5"
        )
        try:
            response = await client.get(url)
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            return self._parse_listing(data, subreddit)
        except httpx.HTTPError:
            return []

    async def _add_search_results(
        self,
        client: httpx.AsyncClient,
        existing: list[Article],
    ) -> list[Article]:
        """Augment existing articles with topic search results, deduped by URL."""
        seen: set[str] = {a.url for a in existing}
        all_articles: list[Article] = list(existing)

        for topic in self._search_topics:
            for subreddit in self._subreddits:
                await asyncio.sleep(self._RATE_LIMIT_DELAY)
                batch = await self._search_subreddit(client, subreddit, topic)
                for article in batch:
                    if article.url not in seen:
                        seen.add(article.url)
                        all_articles.append(article)

        return all_articles

    def _parse_listing(
        self,
        data: dict[str, Any],
        subreddit: str,
    ) -> list[Article]:
        """Parse a Reddit JSON listing envelope into Article objects."""
        articles: list[Article] = []
        children: list[dict[str, Any]] = (
            data.get("data", {}).get("children", [])
        )
        for child in children:
            post: dict[str, Any] = child.get("data", {})
            article = self._post_to_article(post, subreddit)
            if article is not None:
                articles.append(article)
        return articles

    def _post_to_article(
        self,
        post: dict[str, Any],
        subreddit: str,  # noqa: ARG002
    ) -> Article | None:
        """Convert a single Reddit post dict to an Article (or skip)."""
        # --- Skip deleted / removed posts ---
        title: str | None = post.get("title")
        author: str | None = post.get("author")
        if not title or author in ("[deleted]", None):
            return None

        # --- Score filter ---
        score: int = post.get("score") or 0
        if score < self._min_upvotes:
            return None

        # --- URL ---
        url: str = post.get("url") or ""
        permalink: str = post.get("permalink") or ""
        if not url:
            # Fallback: construct from permalink
            url = f"{self.BASE_URL}{permalink}"

        # --- Summary ---
        selftext: str = post.get("selftext") or ""
        num_comments: int = post.get("num_comments") or 0
        summary = self._build_summary(selftext, num_comments)

        # --- Published timestamp ---
        created_utc: int = post.get("created_utc") or 0
        published_at = (
            datetime.fromtimestamp(created_utc, tz=timezone.utc)
            if created_utc
            else datetime.now(timezone.utc)
        )

        return Article(
            title=title,
            url=url,
            source=self.name,
            published_at=published_at,
            summary=summary,
            score=self._normalize_score(score),
            author=author,
        )

    # ------------------------------------------------------------------
    # Score normalization
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_score(score: int) -> float:
        """Normalize Reddit upvotes (0-50k+) to Article score (0-100).

        Uses logarithmic scaling so high-variance Reddit scores map to a
        sensible 0-100 range: a score of 10 → ~33, 100 → ~50, 1000 → ~66,
        10000 → ~83, 50000 → 100.
        """
        if score <= 0:
            return 0.0
        # log10(50001) ≈ 4.699
        max_log = math.log10(50_001)
        normalized = math.log10(score + 1) / max_log * 100.0
        return round(min(normalized, 100.0), 1)

    # ------------------------------------------------------------------
    # Summary builder
    # ------------------------------------------------------------------

    @staticmethod
    def _build_summary(selftext: str, num_comments: int) -> str:
        """Build an Article summary from selftext and comment count."""
        parts: list[str] = []
        if selftext:
            truncated = selftext[:200]
            if len(selftext) > 200:
                truncated += "..."
            parts.append(truncated)
        parts.append(f"{num_comments} comments")
        return " | ".join(parts)
