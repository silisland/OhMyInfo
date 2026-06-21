"""GitHub Trending collector — scrapes https://github.com/trending HTML page.

Parses the server-rendered HTML from GitHub Trending to extract trending
repository metadata without using any API key or external service.

Supported ``since`` values: ``daily``, ``weekly``, ``monthly``.

When ``search_topic`` is provided, also searches the GitHub Search API
for repositories matching the topic.  Requires ``GITHUB_TOKEN`` env var
for higher rate limits (5000/hr vs 60/hr without).
"""

from __future__ import annotations

import math
import os
import re
from datetime import datetime, timezone
from typing import Any, Final

import httpx

from src.collectors import Article, Collector, CollectorError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GITHUB_TRENDING_URL: Final[str] = "https://github.com/trending"

_USER_AGENT: Final[str] = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_REQUEST_TIMEOUT: Final[int] = 30

# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

_NUMBER_RE = re.compile(r"([\d,.]+)")
_STARS_ONLY_RE = re.compile(r"([\d,.]+)\s*stars?(?!\s*today)", re.IGNORECASE)
_FORKS_RE = re.compile(r"([\d,.]+)\s*forks?", re.IGNORECASE)
_STARS_TODAY_RE = re.compile(r"([\d,.]+)\s*stars?\s*today", re.IGNORECASE)
_ARTICLE_RE = re.compile(
    r'<article[^>]*class="[^"]*Box-row[^"]*"[^>]*>.*?</article>',
    re.DOTALL,
)
_HREF_RE = re.compile(r'<a[^>]*href="/([^"]+?)"[^>]*>')
_P_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.DOTALL)
_LANG_RE = re.compile(
    r'<span[^>]*itemprop="programmingLanguage"[^>]*>(.*?)</span>',
)
_F6_RE = re.compile(r'<div[^>]*class="[^"]*f6[^"]*"[^>]*>(.*?)</div>', re.DOTALL)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _parse_count(raw: str) -> int:
    """Parse a count string like ``1,234`` or ``12.5k`` to an integer.

    Args:
        raw: Count string, possibly with commas or a ``k`` suffix.

    Returns:
        Parsed integer value.
    """
    text = raw.strip().lower()
    if text.endswith("k"):
        try:
            return int(float(text[:-1]) * 1000)
        except ValueError:
            return 0
    try:
        return int(text.replace(",", ""))
    except ValueError:
        return 0


def _clean_html(text: str) -> str:
    """Strip HTML tags and normalise whitespace."""
    text = _HTML_TAG_RE.sub("", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _normalize_score(stars_today: int) -> float:
    """Normalise *stars_today* to a 0--100 score.

    Uses a log scale so that small counts still register meaningfully:
    1 star → ~10, 100 stars → ~66, 1000+ → 100.

    Args:
        stars_today: Number of stars gained today.

    Returns:
        Score between 0.0 and 100.0, rounded to one decimal place.
    """
    if stars_today <= 0:
        return 0.0
    score = min(math.log(stars_today + 1) / math.log(1000) * 100, 100.0)
    return round(score, 1)


# ---------------------------------------------------------------------------
# Page parsing (pure function, no IO)
# ---------------------------------------------------------------------------


def parse_trending_page(html: str) -> list[dict[str, Any]]:
    """Parse GitHub Trending HTML into a list of repo metadata dicts.

    Args:
        html: Raw HTML content from the GitHub Trending page.

    Returns:
        List of dicts with the keys ``name``, ``description``, ``language``,
        ``stars``, ``forks``, ``stars_today``.
    """
    repos: list[dict[str, Any]] = []

    for match in _ARTICLE_RE.finditer(html):
        block = match.group()
        repo: dict[str, Any] = {
            "name": "",
            "description": "",
            "language": "",
            "stars": 0,
            "forks": 0,
            "stars_today": 0,
        }

        # Repository name from h2 > a href="/owner/name"
        if m := _HREF_RE.search(block):
            repo["name"] = m.group(1)
        else:
            continue

        # Skip non-repo entries (sponsors, login, search, etc.)
        name = repo["name"]
        if "/" not in name or "?" in name or name.count("/") != 1:
            continue

        # Description from <p>...</p>
        if m := _P_RE.search(block):
            repo["description"] = _clean_html(m.group(1))

        # Programming language
        if m := _LANG_RE.search(block):
            repo["language"] = _clean_html(m.group(1))

        # Metadata inside the f6 div (stars, forks, stars_today)
        if m := _F6_RE.search(block):
            f6 = m.group(1)

            if sm := _STARS_ONLY_RE.search(f6):
                repo["stars"] = _parse_count(sm.group(1))
            if fm := _FORKS_RE.search(f6):
                repo["forks"] = _parse_count(fm.group(1))
            if tm := _STARS_TODAY_RE.search(f6):
                repo["stars_today"] = _parse_count(tm.group(1))

        repos.append(repo)

    return repos


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


class GithubTrendingCollector(Collector):
    """Collects trending repositories from the GitHub Trending page.

    Scrapes https://github.com/trending to obtain trending repository
    metadata.  Supports daily, weekly, and monthly time ranges.

    When ``search_topic`` is set, additionally queries the GitHub Search
    API for repositories matching the topic.

    Attributes:
        since: Time range to fetch — ``"daily"`` (default), ``"weekly"``, or
            ``"monthly"``.
        search_topic: Optional topic string to search GitHub for (default: ``""``).
    """

    SEARCH_API_URL: Final[str] = "https://api.github.com/search/repositories"

    def __init__(self, since: str = "daily", search_topic: str = "") -> None:
        self.since = since
        self.search_topic = search_topic

    @property
    def name(self) -> str:
        return "github_trending"

    async def fetch(self, client: httpx.AsyncClient | None = None) -> list[Article]:  # noqa: D102,PLR0912
        """Fetch trending repositories from GitHub Trending.

        Args:
            client: An optional ``httpx.AsyncClient`` to reuse.  When
                ``None`` (the default) a new client is created and closed
                automatically.

        Returns:
            List of :class:`Article` objects for trending repositories.
            When ``search_topic`` is set, search results are appended after
            trending results.

        Raises:
            CollectorError: If the HTTP request fails or returns an error
                status code.
        """
        if client is not None:
            articles = await self._do_fetch(client)
            if self.search_topic:
                articles.extend(await self._search_github(client, self.search_topic))
            return articles

        async with httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT},
            timeout=_REQUEST_TIMEOUT,
            follow_redirects=True,
        ) as new_client:
            articles = await self._do_fetch(new_client)
            if self.search_topic:
                articles.extend(
                    await self._search_github(new_client, self.search_topic),
                )
            return articles

    async def _do_fetch(self, client: httpx.AsyncClient) -> list[Article]:
        """Perform the actual fetch with a provided client."""
        url = f"{GITHUB_TRENDING_URL}?since={self.since}"

        try:
            response = await client.get(url)
        except httpx.TimeoutException as exc:
            msg = f"Request to GitHub Trending timed out: {exc}"
            raise CollectorError(msg, source=self.name) from exc
        except httpx.ConnectError as exc:
            msg = f"Failed to connect to GitHub Trending: {exc}"
            raise CollectorError(msg, source=self.name) from exc
        except httpx.HTTPError as exc:
            msg = f"HTTP error fetching GitHub Trending: {exc}"
            raise CollectorError(msg, source=self.name) from exc

        if response.status_code == 429:
            raise CollectorError(
                "Rate limited by GitHub (429). Try again later.",
                source=self.name,
            )
        if response.status_code == 403:
            raise CollectorError(
                "Forbidden by GitHub (403). May need a different User-Agent.",
                source=self.name,
            )
        if response.status_code != 200:
            msg = (
                f"Unexpected status {response.status_code} "
                f"from GitHub Trending"
            )
            raise CollectorError(msg, source=self.name)

        repos = parse_trending_page(response.text)
        return self._repos_to_articles(repos)

    async def _search_github(
        self,
        client: httpx.AsyncClient,
        topic: str,
    ) -> list[Article]:
        """Search GitHub repositories by topic using the Search API.

        Args:
            client: HTTP client to use for the request.
            topic: Search query string.

        Returns:
            List of :class:`Article` objects from search results, or an
            empty list if the request fails or is rate-limited.
        """
        url = f"{self.SEARCH_API_URL}?q={topic}&sort=stars&order=desc&per_page=10"
        headers: dict[str, str] = {}
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            response = await client.get(url, headers=headers)
        except httpx.HTTPError:
            return []

        # Gracefully degrade on rate limit or other errors
        if response.status_code == 429:
            return []
        if response.status_code == 403:
            # Could be rate limiting — degrade gracefully
            return []
        if response.status_code != 200:
            return []

        data: dict[str, Any] = response.json()
        return self._search_results_to_articles(data)

    def _search_results_to_articles(
        self,
        data: dict[str, Any],
    ) -> list[Article]:
        """Convert GitHub Search API response items to Article objects.

        Args:
            data: JSON response from the GitHub Search API.

        Returns:
            List of :class:`Article` objects.
        """
        now = datetime.now(timezone.utc)
        articles: list[Article] = []
        for item in data.get("items", []):
            name: str = item.get("full_name", "")
            if not name:
                continue
            desc: str = item.get("description") or ""
            stars: int = item.get("stargazers_count", 0)
            forks: int = item.get("forks_count", 0)
            lang: str = item.get("language") or ""

            summary_parts: list[str] = [desc] if desc else []
            if lang:
                summary_parts.append(f"Language: {lang}")
            summary_parts.append(f"Stars: {stars:,} | Forks: {forks:,}")

            article = Article(
                title=name,
                url=f"https://github.com/{name}",
                source=self.name,
                published_at=now,
                summary=" | ".join(summary_parts),
                score=_normalize_score(stars),
            )
            articles.append(article)
        return articles

    def _repos_to_articles(
        self,
        repos: list[dict[str, Any]],
    ) -> list[Article]:
        """Convert parsed repo dicts to Article objects.

        Args:
            repos: List of repo metadata dicts from ``parse_trending_page``.

        Returns:
            List of :class:`Article` objects.
        """
        now = datetime.now(timezone.utc)
        articles: list[Article] = []

        for repo in repos:
            name: str = repo["name"]
            desc: str = repo["description"]
            lang: str = repo["language"]
            stars: int = repo["stars"]
            forks: int = repo["forks"]
            stars_today: int = repo["stars_today"]

            summary_parts: list[str] = [desc] if desc else []
            if lang:
                summary_parts.append(f"Language: {lang}")
            summary_parts.append(
                f"Stars: {stars:,} | Forks: {forks:,} | +{stars_today:,} today",
            )

            article = Article(
                title=name,
                url=f"https://github.com/{name}",
                source=self.name,
                published_at=now,
                summary=" | ".join(summary_parts),
                score=_normalize_score(stars_today),
            )
            articles.append(article)

        return articles
