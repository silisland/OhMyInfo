"""Tests for src/collectors/github_trending.py — GitHub Trending collector."""

from __future__ import annotations

from unittest import mock

import httpx
import pytest

from src.collectors import Article, CollectorError
from src.collectors.github_trending import (
    GithubTrendingCollector,
    _normalize_score,
    parse_trending_page,
)

# ---------------------------------------------------------------------------
# Sample HTML fixtures
# ---------------------------------------------------------------------------

SAMPLE_HTML = """\
<!DOCTYPE html>
<html>
<body>
  <article class="Box-row">
    <h2><a href="/owner/repo">owner / <strong>repo</strong></a></h2>
    <p>Description text</p>
    <div class="f6 color-fg-muted mt-2">
      <span class="d-inline-block mr-3">
        <span itemprop="programmingLanguage">Python</span>
      </span>
      <a href="/owner/repo/stargazers">1,234 stars</a>
      <a href="/owner/repo/forks">567 forks</a>
      <span class="d-inline-block float-sm-right">89 stars today</span>
    </div>
  </article>
</body>
</html>
"""

SAMPLE_MULTI = """\
<!DOCTYPE html>
<html>
<body>
  <article class="Box-row">
    <h2><a href="/owner/repo">owner / <strong>repo</strong></a></h2>
    <p>First repo description</p>
    <div class="f6 color-fg-muted mt-2">
      <span class="d-inline-block mr-3">
        <span itemprop="programmingLanguage">Python</span>
      </span>
      <a href="/owner/repo/stargazers">1,234 stars</a>
      <a href="/owner/repo/forks">567 forks</a>
      <span class="d-inline-block float-sm-right">89 stars today</span>
    </div>
  </article>
  <article class="Box-row">
    <h2><a href="/another/project">another / <strong>project</strong></a></h2>
    <p>Second repo description</p>
    <div class="f6 color-fg-muted mt-2">
      <span class="d-inline-block mr-3">
        <span itemprop="programmingLanguage">Rust</span>
      </span>
      <a href="/another/project/stargazers">500 stars</a>
      <a href="/another/project/forks">100 forks</a>
      <span class="d-inline-block float-sm-right">25 stars today</span>
    </div>
  </article>
</body>
</html>
"""

NO_REPO_HTML = """\
<!DOCTYPE html>
<html>
<body>
  <div class="application-main">
    <main>
      <div class="position-relative container-lg p-responsive pt-6">
        <h2 class="h2">No repositories found</h2>
      </div>
    </main>
  </div>
</body>
</html>
"""

NO_LANG_HTML = """\
<article class="Box-row">
  <h2><a href="/no/lang">no / <strong>lang</strong></a></h2>
  <p>No language repo</p>
  <div class="f6 color-fg-muted mt-2">
    <a href="/no/lang/stargazers">100 stars</a>
    <a href="/no/lang/forks">50 forks</a>
    <span class="d-inline-block float-sm-right">10 stars today</span>
  </div>
</article>
"""

NO_DESC_HTML = """\
<article class="Box-row">
  <h2><a href="/no/desc">no / <strong>desc</strong></a></h2>
  <div class="f6 color-fg-muted mt-2">
    <span class="d-inline-block mr-3">
      <span itemprop="programmingLanguage">Go</span>
    </span>
    <a href="/no/desc/stargazers">50 stars</a>
    <a href="/no/desc/forks">25 forks</a>
    <span class="d-inline-block float-sm-right">5 stars today</span>
  </div>
</article>
"""

NO_HREF_HTML = """\
<article class="Box-row">
  <h2><a>no href</a></h2>
  <p>Malformed entry</p>
</article>
"""


# ---------------------------------------------------------------------------
# Mock helper
# ---------------------------------------------------------------------------


def _mock_get(status: int = 200, text: str = "") -> mock.AsyncMock:
    """Return an async mock for ``httpx.AsyncClient.get``."""

    async def get_response(self: object, url: str, **kwargs: object) -> httpx.Response:  # noqa: ARG001
        return httpx.Response(status, text=text)

    return get_response


def _mock_get_error(exc: type[httpx.HTTPError], message: str = "error") -> mock.AsyncMock:
    """Return an async mock that raises an HTTP error."""

    async def get_error(self: object, url: str, **kwargs: object) -> httpx.Response:  # noqa: ARG001
        raise exc(message)

    return get_error


# ===================================================================
# parse_trending_page
# ===================================================================


class TestParseTrendingPage:
    """Unit tests for ``parse_trending_page()`` (pure function, no IO)."""

    def test_parse_single_repo(self) -> None:
        """Should extract all metadata from a single repo article."""
        repos = parse_trending_page(SAMPLE_HTML)
        assert len(repos) == 1
        repo = repos[0]
        assert repo["name"] == "owner/repo"
        assert repo["description"] == "Description text"
        assert repo["language"] == "Python"
        assert repo["stars"] == 1234
        assert repo["forks"] == 567
        assert repo["stars_today"] == 89

    def test_parse_multiple_repos(self) -> None:
        """Should parse multiple repo articles from a single page."""
        repos = parse_trending_page(SAMPLE_MULTI)
        assert len(repos) == 2
        assert repos[0]["name"] == "owner/repo"
        assert repos[0]["language"] == "Python"
        assert repos[1]["name"] == "another/project"
        assert repos[1]["language"] == "Rust"
        assert repos[1]["stars"] == 500

    def test_parse_empty_html(self) -> None:
        """Should return empty list when no repo articles exist."""
        repos = parse_trending_page(NO_REPO_HTML)
        assert repos == []

    def test_parse_no_articles(self) -> None:
        """Should handle HTML with zero article tags."""
        repos = parse_trending_page("<html><body></body></html>")
        assert repos == []

    def test_parse_empty_string(self) -> None:
        """Should handle an empty string gracefully."""
        repos = parse_trending_page("")
        assert repos == []

    def test_skip_article_without_href(self) -> None:
        """Should skip articles missing a valid repo link."""
        repos = parse_trending_page(NO_HREF_HTML)
        assert repos == []

    def test_parse_no_language(self) -> None:
        """Should default to empty string when language is absent."""
        repos = parse_trending_page(NO_LANG_HTML)
        assert repos[0]["language"] == ""

    def test_parse_no_description(self) -> None:
        """Should default to empty string when description is absent."""
        repos = parse_trending_page(NO_DESC_HTML)
        assert repos[0]["description"] == ""
        assert repos[0]["language"] == "Go"


# ===================================================================
# _normalize_score
# ===================================================================


class TestNormalizeScore:
    """Tests for the score normalisation helper."""

    def test_zero_stars(self) -> None:
        """Zero stars today yields zero score."""
        assert _normalize_score(0) == 0.0

    def test_negative_stars(self) -> None:
        """Negative values should be clamped to zero."""
        assert _normalize_score(-5) == 0.0

    def test_one_star(self) -> None:
        """One star today yields a small positive score (~10)."""
        assert _normalize_score(1) > 0

    def test_large_stars_capped(self) -> None:
        """Very large counts should cap at 100.0."""
        assert _normalize_score(5000) == 100.0
        assert _normalize_score(10000) == 100.0

    def test_monotonic(self) -> None:
        """Score should be monotonically non-decreasing with stars_today."""
        scores = [_normalize_score(n) for n in range(0, 110, 10)]
        for i in range(len(scores) - 1):
            assert scores[i] <= scores[i + 1]


# ===================================================================
# GithubTrendingCollector
# ===================================================================


class TestGithubTrendingCollector:
    """Integration-level tests for ``GithubTrendingCollector``."""

    @pytest.mark.asyncio
    async def test_fetch_returns_articles(self) -> None:
        """``fetch()`` should return ``Article`` objects from HTML."""
        mock_get = _mock_get(200, SAMPLE_HTML)
        with mock.patch.object(httpx.AsyncClient, "get", mock_get):
            collector = GithubTrendingCollector()
            articles = await collector.fetch()

        assert len(articles) == 1
        article = articles[0]
        assert article.title == "owner/repo"
        assert article.url == "https://github.com/owner/repo"
        assert article.source == "github_trending"
        assert article.score > 0
        assert "Description text" in article.summary
        assert "Python" in article.summary

    @pytest.mark.asyncio
    async def test_fetch_empty_html(self) -> None:
        """``fetch()`` should return empty list for pages with no repos."""
        mock_get = _mock_get(200, NO_REPO_HTML)
        with mock.patch.object(httpx.AsyncClient, "get", mock_get):
            collector = GithubTrendingCollector()
            articles = await collector.fetch()

        assert articles == []

    @pytest.mark.asyncio
    async def test_fetch_with_client(self) -> None:
        """``fetch(client=...)`` should use the provided client."""
        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, text=SAMPLE_HTML),
        )
        async with httpx.AsyncClient(transport=transport) as client:
            collector = GithubTrendingCollector()
            articles = await collector.fetch(client=client)

        assert len(articles) == 1

    @pytest.mark.asyncio
    async def test_fetch_timeout(self) -> None:
        """Should raise ``CollectorError`` on timeout."""
        mock_get = _mock_get_error(httpx.TimeoutException, "timed out")
        with mock.patch.object(httpx.AsyncClient, "get", mock_get):
            collector = GithubTrendingCollector()
            with pytest.raises(CollectorError) as exc_info:
                await collector.fetch()

        assert exc_info.value.source == "github_trending"
        assert "timed out" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_fetch_connect_error(self) -> None:
        """Should raise ``CollectorError`` on connection failure."""
        mock_get = _mock_get_error(httpx.ConnectError, "connection refused")
        with mock.patch.object(httpx.AsyncClient, "get", mock_get):
            collector = GithubTrendingCollector()
            with pytest.raises(CollectorError) as exc_info:
                await collector.fetch()

        assert exc_info.value.source == "github_trending"

    @pytest.mark.asyncio
    async def test_fetch_rate_limited(self) -> None:
        """Should raise ``CollectorError`` on HTTP 429."""
        mock_get = _mock_get(429, "Rate limited")
        with mock.patch.object(httpx.AsyncClient, "get", mock_get):
            collector = GithubTrendingCollector()
            with pytest.raises(CollectorError) as exc_info:
                await collector.fetch()

        assert "Rate limited" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_fetch_forbidden(self) -> None:
        """Should raise ``CollectorError`` on HTTP 403."""
        mock_get = _mock_get(403, "Forbidden")
        with mock.patch.object(httpx.AsyncClient, "get", mock_get):
            collector = GithubTrendingCollector()
            with pytest.raises(CollectorError) as exc_info:
                await collector.fetch()

        assert "Forbidden" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_fetch_http_error(self) -> None:
        """Should raise ``CollectorError`` on other HTTP errors."""
        mock_get = _mock_get_error(httpx.RequestError, "500 error")
        with mock.patch.object(httpx.AsyncClient, "get", mock_get):
            collector = GithubTrendingCollector()
            with pytest.raises(CollectorError) as exc_info:
                await collector.fetch()

        assert exc_info.value.source == "github_trending"

    @pytest.mark.asyncio
    async def test_fetch_unexpected_status(self) -> None:
        """Should raise ``CollectorError`` on unexpected status codes."""
        mock_get = _mock_get(500, "Internal Server Error")
        with mock.patch.object(httpx.AsyncClient, "get", mock_get):
            collector = GithubTrendingCollector()
            with pytest.raises(CollectorError) as exc_info:
                await collector.fetch()

        assert "500" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_default_since_is_daily(self) -> None:
        """Default ``since`` parameter should be ``\"daily\"``."""
        collector = GithubTrendingCollector()
        assert collector.since == "daily"

    @pytest.mark.asyncio
    async def test_custom_since(self) -> None:
        """``since`` parameter should propagate to the URL."""
        seen_urls: list[str] = []

        async def capture_get(self: object, url: str, **kwargs: object) -> httpx.Response:  # noqa: ARG001
            seen_urls.append(url)
            return httpx.Response(200, text=NO_REPO_HTML)

        with mock.patch.object(httpx.AsyncClient, "get", capture_get):
            collector = GithubTrendingCollector(since="weekly")
            await collector.fetch()

        assert len(seen_urls) == 1
        assert "since=weekly" in seen_urls[0]

    def test_name_property(self) -> None:
        """``name`` should return ``\"github_trending\"``."""
        collector = GithubTrendingCollector()
        assert collector.name == "github_trending"

    def test_health(self) -> None:
        """Health check should include base fields and custom info."""
        collector = GithubTrendingCollector()
        health = collector.health()
        assert health["name"] == "github_trending"
        assert health["status"] == "ok"

    @pytest.mark.asyncio
    async def test_fetch_multiple_articles(self) -> None:
        """``fetch()`` should return all repos from page."""
        mock_get = _mock_get(200, SAMPLE_MULTI)
        with mock.patch.object(httpx.AsyncClient, "get", mock_get):
            collector = GithubTrendingCollector()
            articles = await collector.fetch()

        assert len(articles) == 2
        assert articles[0].title == "owner/repo"
        assert articles[1].title == "another/project"
        assert articles[1].score > 0
