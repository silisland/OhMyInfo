"""Tests for ``src.collectors.devto`` — Dev.to API collector."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.collectors import Article, CollectorError
from src.collectors.devto import DevToCollector

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_ARTICLE: dict = {
    "title": "Getting Started with Python",
    "url": "https://dev.to/johndoe/getting-started-with-python-123",
    "canonical_url": "https://example.com/python-guide",
    "description": "A comprehensive guide to Python for beginners.",
    "body_markdown": "# Python Guide\n\nThis is the full content.",
    "tag_list": ["python", "tutorial", "beginners"],
    "user": {"name": "John Doe", "username": "johndoe"},
    "published_at": "2024-01-15T10:30:00Z",
    "positive_reactions_count": 25,
    "comments_count": 8,
    "page_views_count": 1500,
    "reading_time_minutes": 5,
    "cover_image": "https://example.com/cover.png",
}


def _mock_response(
    status_code: int,
    json_data: list[dict],
) -> MagicMock:
    """Build a minimal ``httpx.Response``-like mock."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data

    if status_code >= 400:
        error = httpx.HTTPStatusError(
            f"HTTP {status_code}",
            request=MagicMock(spec=httpx.Request),
            response=resp,
        )
        resp.raise_for_status.side_effect = error

    return resp


@pytest.fixture
def collector() -> DevToCollector:
    return DevToCollector()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDevToCollector:
    """DevToCollector end-to-end behaviour."""

    # -- identity -------------------------------------------------------

    @pytest.mark.asyncio
    async def test_name(self, collector: DevToCollector) -> None:
        assert collector.name == "devto"

    @pytest.mark.asyncio
    async def test_health(self, collector: DevToCollector) -> None:
        health = collector.health()
        assert health["name"] == "devto"
        assert health["status"] == "ok"
        assert health["timeout"] == 30
        assert health["max_retries"] == 3

    # -- parsing --------------------------------------------------------

    @pytest.mark.asyncio
    async def test_fetch_parses_article_fields(self, collector: DevToCollector) -> None:
        """All Article fields are populated correctly from API response."""
        resp = _mock_response(200, [SAMPLE_ARTICLE])
        with patch.object(httpx.AsyncClient, "get", new=AsyncMock(return_value=resp)):
            articles = await collector.fetch()

        assert len(articles) == 1
        a = articles[0]

        assert a.title == "Getting Started with Python"
        assert a.url == "https://example.com/python-guide"  # canonical_url > url
        assert a.source == "devto"
        assert a.summary == "A comprehensive guide to Python for beginners."
        assert a.content == "# Python Guide\n\nThis is the full content."
        assert a.tags == ["python", "tutorial", "beginners"]
        assert a.author == "John Doe"
        assert isinstance(a.published_at, datetime)
        assert a.score > 0

    @pytest.mark.asyncio
    async def test_published_at_parsing(self, collector: DevToCollector) -> None:
        """ISO 8601 timestamp with Z suffix is parsed correctly."""
        resp = _mock_response(200, [SAMPLE_ARTICLE])
        with patch.object(httpx.AsyncClient, "get", new=AsyncMock(return_value=resp)):
            articles = await collector.fetch()

        expected = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        assert articles[0].published_at == expected

    @pytest.mark.asyncio
    async def test_score_derivation(self, collector: DevToCollector) -> None:
        """Score is derived from engagement metrics and capped at 100."""
        high_engagement = {
            **SAMPLE_ARTICLE,
            "positive_reactions_count": 50,
            "comments_count": 20,
            "page_views_count": 2000,
        }
        # raw = 50*2 + 20*3 + min(2000, 1000)*0.05 = 100 + 60 + 50 = 210 → 100
        resp = _mock_response(200, [high_engagement])
        with patch.object(httpx.AsyncClient, "get", new=AsyncMock(return_value=resp)):
            articles = await collector.fetch()

        assert articles[0].score == 100.0

    @pytest.mark.asyncio
    async def test_zero_engagement_score(self, collector: DevToCollector) -> None:
        """Articles with zero engagement get score 0."""
        no_engagement = {
            **SAMPLE_ARTICLE,
            "positive_reactions_count": 0,
            "comments_count": 0,
            "page_views_count": 0,
        }
        resp = _mock_response(200, [no_engagement])
        with patch.object(httpx.AsyncClient, "get", new=AsyncMock(return_value=resp)):
            articles = await collector.fetch()

        assert articles[0].score == 0.0

    # -- fallbacks ------------------------------------------------------

    @pytest.mark.asyncio
    async def test_fallback_to_url_when_canonical_missing(
        self, collector: DevToCollector
    ) -> None:
        """When ``canonical_url`` is absent, ``url`` is used."""
        no_canonical = {**SAMPLE_ARTICLE, "canonical_url": None}
        resp = _mock_response(200, [no_canonical])
        with patch.object(httpx.AsyncClient, "get", new=AsyncMock(return_value=resp)):
            articles = await collector.fetch()

        assert (
            articles[0].url
            == "https://dev.to/johndoe/getting-started-with-python-123"
        )

    @pytest.mark.asyncio
    async def test_missing_user(self, collector: DevToCollector) -> None:
        """Absent ``user`` field does not crash."""
        no_user = {**SAMPLE_ARTICLE, "user": None}
        resp = _mock_response(200, [no_user])
        with patch.object(httpx.AsyncClient, "get", new=AsyncMock(return_value=resp)):
            articles = await collector.fetch()

        assert articles[0].author == ""

    @pytest.mark.asyncio
    async def test_empty_user_dict(self, collector: DevToCollector) -> None:
        """Empty ``user`` dict results in empty author."""
        empty_user = {**SAMPLE_ARTICLE, "user": {}}
        resp = _mock_response(200, [empty_user])
        with patch.object(httpx.AsyncClient, "get", new=AsyncMock(return_value=resp)):
            articles = await collector.fetch()

        assert articles[0].author == ""

    @pytest.mark.asyncio
    async def test_missing_body_markdown(self, collector: DevToCollector) -> None:
        """When ``body_markdown`` is absent, ``description`` becomes content."""
        no_body = {**SAMPLE_ARTICLE, "body_markdown": None}
        resp = _mock_response(200, [no_body])
        with patch.object(httpx.AsyncClient, "get", new=AsyncMock(return_value=resp)):
            articles = await collector.fetch()

        assert articles[0].content == "A comprehensive guide to Python for beginners."

    @pytest.mark.asyncio
    async def test_tags_as_string(self, collector: DevToCollector) -> None:
        """If ``tag_list`` is a comma-separated string, normalise to list."""
        tags_str = {**SAMPLE_ARTICLE, "tag_list": "python, tutorial, beginners"}
        resp = _mock_response(200, [tags_str])
        with patch.object(httpx.AsyncClient, "get", new=AsyncMock(return_value=resp)):
            articles = await collector.fetch()

        assert articles[0].tags == ["python", "tutorial", "beginners"]

    # -- edge cases -----------------------------------------------------

    @pytest.mark.asyncio
    async def test_empty_results(self, collector: DevToCollector) -> None:
        """Empty API response returns empty list."""
        resp = _mock_response(200, [])
        with patch.object(httpx.AsyncClient, "get", new=AsyncMock(return_value=resp)):
            articles = await collector.fetch()

        assert articles == []

    @pytest.mark.asyncio
    async def test_network_error(self, collector: DevToCollector) -> None:
        """Network errors are wrapped in ``CollectorError``."""
        side = httpx.RequestError("Connection refused")

        with patch.object(
            httpx.AsyncClient,
            "get",
            new=AsyncMock(side_effect=side),
        ):
            with pytest.raises(CollectorError) as exc_info:
                await collector.fetch()

        assert exc_info.value.source == "devto"
        assert "Network error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_http_error(self, collector: DevToCollector) -> None:
        """HTTP errors (e.g. 429) are wrapped in ``CollectorError``."""
        resp = _mock_response(429, [])
        with patch.object(httpx.AsyncClient, "get", new=AsyncMock(return_value=resp)):
            with pytest.raises(CollectorError) as exc_info:
                await collector.fetch()

        assert exc_info.value.source == "devto"
        assert "429" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_pagination(self, collector: DevToCollector) -> None:
        """``fetch(max_pages=2)`` returns articles from both pages."""
        page1 = [{**SAMPLE_ARTICLE, "title": f"Article {i}"} for i in range(3)]
        page2 = [{**SAMPLE_ARTICLE, "title": f"Article {i + 3}"} for i in range(2)]

        resp1 = _mock_response(200, page1)
        resp2 = _mock_response(200, page2)

        mock_get = AsyncMock()
        mock_get.side_effect = [resp1, resp2]

        with patch.object(httpx.AsyncClient, "get", mock_get):
            articles = await collector.fetch(max_pages=2)

        assert len(articles) == 5
        assert articles[0].title == "Article 0"
        assert articles[4].title == "Article 4"

    @pytest.mark.asyncio
    async def test_pagination_stops_on_empty(self, collector: DevToCollector) -> None:
        """Pagination stops when an empty page is returned."""
        page1 = [{**SAMPLE_ARTICLE, "title": "Only"}]
        page2: list[dict] = []

        resp1 = _mock_response(200, page1)
        resp2 = _mock_response(200, page2)

        mock_get = AsyncMock()
        mock_get.side_effect = [resp1, resp2]

        with patch.object(httpx.AsyncClient, "get", mock_get):
            articles = await collector.fetch(max_pages=2)

        assert len(articles) == 1

    @pytest.mark.asyncio
    async def test_is_collector_subclass(self) -> None:
        """DevToCollector is a proper Collector subclass."""
        from src.collectors import Collector

        assert issubclass(DevToCollector, Collector)

    @pytest.mark.asyncio
    async def test_return_type(self, collector: DevToCollector) -> None:
        """fetch() returns list of Article instances."""
        resp = _mock_response(200, [SAMPLE_ARTICLE])
        with patch.object(httpx.AsyncClient, "get", new=AsyncMock(return_value=resp)):
            articles = await collector.fetch()

        assert all(isinstance(a, Article) for a in articles)

    @pytest.mark.asyncio
    async def test_top_period_param(self) -> None:
        """When ``top_period=True`` the request includes ``top=1``."""
        top_collector = DevToCollector(top_period=True)

        # Spy on get() to inspect params
        original_get = httpx.AsyncClient.get

        called_with: dict | None = None

        async def spy(self, url, **kwargs):  # noqa: ANN001, ANN401
            nonlocal called_with
            called_with = kwargs.get("params")
            return _mock_response(200, [])

        with patch.object(httpx.AsyncClient, "get", spy):
            await top_collector.fetch()

        assert called_with is not None
        assert called_with.get("top") == 1
