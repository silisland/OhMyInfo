"""Tests for topic-aware search modes in collectors.

Tests cover:
  - GithubTrendingCollector(search_topic=...)
  - RedditCollector(search_topics=...)
  - HackerNewsCollector(filter_keywords=...)
  - Graceful degradation when APIs are rate-limited
  - Default parameter backward compatibility
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from unittest import mock

import httpx
import pytest
from httpx import MockTransport

from src.collectors import Article
from src.collectors.github_trending import GithubTrendingCollector
from src.collectors.hacker_news import HackerNewsCollector
from src.collectors.reddit import RedditCollector

# ===========================================================================
# Helpers
# ===========================================================================

SAMPLE_GH_HTML = """\
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

EMPTY_GH_HTML = """\
<!DOCTYPE html>
<html><body></body></html>
"""


def _github_search_response(items: list[dict]) -> dict:
    return {"items": items}


def _github_search_item(
    full_name: str = "topic/repo",
    description: str = "A topic repo",
    stargazers_count: int = 500,
    forks_count: int = 50,
    language: str = "Rust",
) -> dict:
    return {
        "full_name": full_name,
        "description": description,
        "stargazers_count": stargazers_count,
        "forks_count": forks_count,
        "language": language,
    }


def _reddit_listing(posts: list[dict]) -> dict:
    return {
        "data": {
            "children": [{"data": p} for p in posts],
        }
    }


def _reddit_post(
    *,
    title: str = "Test Post",
    url: str = "https://example.com/test",
    permalink: str = "/r/test/comments/abc123/",
    score: int = 500,
    author: str = "testuser",
    num_comments: int = 10,
    selftext: str = "Post content here",
    created_utc: int = 1_700_000_000,
) -> dict:
    return {
        "title": title,
        "url": url,
        "permalink": permalink,
        "score": score,
        "author": author,
        "num_comments": num_comments,
        "selftext": selftext,
        "created_utc": created_utc,
    }


def _hn_story(
    *,
    item_id: int = 1,
    title: str = "HN Story",
    url: str = "https://example.com/story",
    by: str = "user",
    score: int = 500,
    time: int = 1_700_000_000,
) -> dict:
    return {
        "id": item_id,
        "title": title,
        "url": url,
        "by": by,
        "score": score,
        "time": time,
        "type": "story",
    }


# ===========================================================================
# GithubTrendingCollector — search_topic
# ===========================================================================


class TestGithubTrendingSearchTopic:
    """Tests for GithubTrendingCollector with search_topic parameter."""

    @pytest.mark.asyncio
    async def test_default_no_search(self) -> None:
        """Default search_topic="" should not trigger search API."""
        mock_get = mock.AsyncMock(
            return_value=httpx.Response(200, text=SAMPLE_GH_HTML),
        )
        with mock.patch.object(httpx.AsyncClient, "get", mock_get):
            collector = GithubTrendingCollector()
            articles = await collector.fetch()

        assert len(articles) == 1
        assert articles[0].title == "owner/repo"
        # Only one call — the trending page
        mock_get.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_topic_appends_search_results(self) -> None:
        """When search_topic is set, search results are appended to trending."""
        call_count = 0

        async def mock_get(self: object, url: str, **kwargs: object) -> httpx.Response:  # noqa: ARG001
            nonlocal call_count
            call_count += 1
            if "github.com/trending" in str(url):
                return httpx.Response(200, text=SAMPLE_GH_HTML)
            # Search API call
            data = _github_search_response([
                _github_search_item(
                    full_name="obsidian/obsidian",
                    description="Obsidian notes app",
                    stargazers_count=50000,
                    language="TypeScript",
                ),
            ])
            return httpx.Response(200, json=data)

        with mock.patch.object(httpx.AsyncClient, "get", mock_get):
            collector = GithubTrendingCollector(search_topic="obsidian")
            articles = await collector.fetch()

        assert len(articles) == 2
        assert call_count == 2

        # First is trending
        assert articles[0].url == "https://github.com/owner/repo"
        # Second is search result
        assert articles[1].title == "obsidian/obsidian"
        assert articles[1].source == "github_trending"
        assert articles[1].score > 0

    @pytest.mark.asyncio
    async def test_search_topic_rate_limited_429(self) -> None:
        """When search API returns 429, only trending results are returned."""
        call_count = 0

        async def mock_get(self: object, url: str, **kwargs: object) -> httpx.Response:  # noqa: ARG001
            nonlocal call_count
            call_count += 1
            if "github.com/trending" in str(url):
                return httpx.Response(200, text=SAMPLE_GH_HTML)
            return httpx.Response(429, text="rate limit")

        with mock.patch.object(httpx.AsyncClient, "get", mock_get):
            collector = GithubTrendingCollector(search_topic="obsidian")
            articles = await collector.fetch()

        assert len(articles) == 1  # Only trending
        assert articles[0].title == "owner/repo"

    @pytest.mark.asyncio
    async def test_search_topic_rate_limited_403(self) -> None:
        """When search API returns 403, only trending results are returned."""
        call_count = 0

        async def mock_get(self: object, url: str, **kwargs: object) -> httpx.Response:  # noqa: ARG001
            nonlocal call_count
            call_count += 1
            if "github.com/trending" in str(url):
                return httpx.Response(200, text=SAMPLE_GH_HTML)
            return httpx.Response(403, text="rate limit exceeded")

        with mock.patch.object(httpx.AsyncClient, "get", mock_get):
            collector = GithubTrendingCollector(search_topic="obsidian")
            articles = await collector.fetch()

        assert len(articles) == 1  # Only trending

    @pytest.mark.asyncio
    async def test_search_topic_http_error(self) -> None:
        """When search API raises HTTP error, only trending results."""
        call_count = 0

        async def mock_get(self: object, url: str, **kwargs: object) -> httpx.Response:  # noqa: ARG001
            nonlocal call_count
            call_count += 1
            if "github.com/trending" in str(url):
                return httpx.Response(200, text=SAMPLE_GH_HTML)
            raise httpx.ConnectError("connection failed")

        with mock.patch.object(httpx.AsyncClient, "get", mock_get):
            collector = GithubTrendingCollector(search_topic="obsidian")
            articles = await collector.fetch()

        assert len(articles) == 1  # Only trending

    # ------------------------------------------------------------------
    # Behavior with provided client
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_search_topic_with_existing_client(self) -> None:
        """search_topic works when a client is passed to fetch()."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if "github.com/trending" in str(request.url):
                return httpx.Response(200, text=SAMPLE_GH_HTML)
            data = _github_search_response([
                _github_search_item(full_name="obsidian/obsidian"),
            ])
            return httpx.Response(200, json=data)

        transport = MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport,
        ) as client:
            collector = GithubTrendingCollector(search_topic="obsidian")
            articles = await collector.fetch(client=client)

        assert len(articles) == 2
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_search_with_token_header(self) -> None:
        """When GITHUB_TOKEN is set, Authorization header is included."""
        os.environ["GITHUB_TOKEN"] = "test_token_123"

        seen_headers: list[dict] = []

        async def mock_get(self: object, url: str, **kwargs: object) -> httpx.Response:  # noqa: ARG001
            if "search" in str(url):
                seen_headers.append(kwargs.get("headers", {}))
                return httpx.Response(200, json=_github_search_response([]))
            return httpx.Response(200, text=EMPTY_GH_HTML)

        with mock.patch.object(httpx.AsyncClient, "get", mock_get):
            collector = GithubTrendingCollector(search_topic="test")
            await collector.fetch()

        assert len(seen_headers) == 1
        auth = seen_headers[0].get("Authorization", "")
        assert auth == "Bearer test_token_123"

        del os.environ["GITHUB_TOKEN"]


# ===========================================================================
# RedditCollector — search_topics
# ===========================================================================


class TestRedditSearchTopics:
    """Tests for RedditCollector with search_topics parameter."""

    @pytest.mark.asyncio
    async def test_default_no_search(self) -> None:
        """Default search_topics=None should not trigger search."""
        transport = _mock_transport(_reddit_listing([]))
        async with httpx.AsyncClient(transport=transport) as client:
            collector = RedditCollector(
                subreddits=["test"],
                min_upvotes=0,
                http_client=client,
            )
            articles = await collector.fetch()

        assert articles == []

    @pytest.mark.asyncio
    async def test_search_topics_appends_results(self) -> None:
        """When search_topics is set, topic matches are appended to hot feed."""
        hot_posts = [
            _reddit_post(title="Hot Post", url="https://example.com/hot"),
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            if "/search.json" in str(request.url):
                search_posts = [
                    _reddit_post(
                        title="Obsidian Plugin",
                        url="https://example.com/obsidian-plugin",
                    ),
                ]
                return httpx.Response(200, json=_reddit_listing(search_posts))
            # Hot feed
            return httpx.Response(200, json=_reddit_listing(hot_posts))

        transport = MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            collector = RedditCollector(
                subreddits=["test"],
                min_upvotes=0,
                http_client=client,
                search_topics=["obsidian"],
            )
            articles = await collector.fetch()

        # 1 hot + 1 search
        assert len(articles) == 2
        assert articles[0].url == "https://example.com/hot"
        assert articles[1].url == "https://example.com/obsidian-plugin"
        assert articles[1].source == "reddit"

    @pytest.mark.asyncio
    async def test_search_dedup_by_url(self) -> None:
        """When search finds same URL as hot feed, it should be deduped."""
        common_url = "https://example.com/common"

        hot_posts = [
            _reddit_post(title="Common Post", url=common_url),
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            search_posts = [
                _reddit_post(title="Common Post", url=common_url),
            ]
            return httpx.Response(200, json=_reddit_listing(search_posts))

        transport = MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            collector = RedditCollector(
                subreddits=["test"],
                min_upvotes=0,
                http_client=client,
                search_topics=["obsidian"],
            )
            articles = await collector.fetch()

        # Only 1 (deduped)
        assert len(articles) == 1

    @pytest.mark.asyncio
    async def test_multiple_topics_multiple_subreddits(self) -> None:
        """Multiple search_topics x multiple subreddits should work."""
        call_paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            call_paths.append(str(request.url))
            return httpx.Response(200, json=_reddit_listing([]))

        transport = MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            collector = RedditCollector(
                subreddits=["subA", "subB"],
                min_upvotes=0,
                http_client=client,
                search_topics=["topic1", "topic2"],
            )
            await collector.fetch()

        # 2 hot feed calls + 4 search calls (2 topics * 2 subreddits)
        search_calls = [p for p in call_paths if "/search.json" in p]
        assert len(search_calls) == 4

    @pytest.mark.asyncio
    async def test_search_http_error_graceful(self) -> None:
        """When search API fails, hot feed results are still returned."""
        hot_posts = [
            _reddit_post(title="Hot Post", url="https://example.com/hot"),
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            if "/search.json" in str(request.url):
                raise httpx.ConnectError("DNS failed")
            return httpx.Response(200, json=_reddit_listing(hot_posts))

        transport = MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            collector = RedditCollector(
                subreddits=["test"],
                min_upvotes=0,
                http_client=client,
                search_topics=["obsidian"],
            )
            articles = await collector.fetch()

        assert len(articles) == 1  # Only hot feed
        assert articles[0].title == "Hot Post"


# ===========================================================================
# HackerNewsCollector — filter_keywords
# ===========================================================================


class TestHackerNewsFilterKeywords:
    """Tests for HackerNewsCollector with filter_keywords parameter."""

    @pytest.mark.asyncio
    async def test_default_no_filter(self, monkeypatch) -> None:
        """Default filter_keywords=None should return all articles."""
        story_ids = [1, 2]

        async def mock_get(self: object, url: str, **kwargs: object) -> mock.Mock:  # noqa: ARG001
            url_str = str(url)
            if "topstories" in url_str:
                return _mock_hn_response(story_ids)
            if "/item/1.json" in url_str:
                return _mock_hn_response(
                    _hn_story(item_id=1, title="AI News"),
                )
            if "/item/2.json" in url_str:
                return _mock_hn_response(
                    _hn_story(item_id=2, title="Rust Update"),
                )
            return _mock_hn_response(None, 404)

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

        collector = HackerNewsCollector()
        articles = await collector.fetch()
        assert len(articles) == 2

    @pytest.mark.asyncio
    async def test_filter_matches_some(self, monkeypatch) -> None:
        """When keywords match some articles, only those are returned (≥5)."""
        story_ids = [1, 2, 3, 4, 5, 6, 7]

        async def mock_get(self: object, url: str, **kwargs: object) -> mock.Mock:  # noqa: ARG001
            url_str = str(url)
            if "topstories" in url_str:
                return _mock_hn_response(story_ids)
            stories = {
                1: _hn_story(item_id=1, title="OpenAI Releases New Model"),
                2: _hn_story(item_id=2, title="Rust in Linux Kernel"),
                3: _hn_story(item_id=3, title="TypeScript 5.5 Released"),
                4: _hn_story(item_id=4, title="Python 3.14 Alpha"),
                5: _hn_story(item_id=5, title="React 19 Features"),
                6: _hn_story(item_id=6, title="Docker Update"),
                7: _hn_story(item_id=7, title="Kubernetes 2.0"),
            }
            for sid, story in stories.items():
                if f"/item/{sid}.json" in url_str:
                    return _mock_hn_response(story)
            return _mock_hn_response(None, 404)

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

        collector = HackerNewsCollector(filter_keywords=["openai", "rust"])
        articles = await collector.fetch()

        # 2 match + fallback keeps top 5
        assert len(articles) == 5
        assert "OpenAI" in articles[0].title
        assert "Rust" in articles[1].title

    @pytest.mark.asyncio
    async def test_filter_case_insensitive(self, monkeypatch) -> None:
        """Filter keywords should match case-insensitively."""
        story_ids = [1]

        async def mock_get(self: object, url: str, **kwargs: object) -> mock.Mock:  # noqa: ARG001
            url_str = str(url)
            if "topstories" in url_str:
                return _mock_hn_response(story_ids)
            if "/item/1.json" in url_str:
                return _mock_hn_response(
                    _hn_story(item_id=1, title="OPENAI BREAKTHROUGH"),
                )
            return _mock_hn_response(None, 404)

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

        collector = HackerNewsCollector(filter_keywords=["openai"])
        articles = await collector.fetch()
        assert len(articles) == 1

    @pytest.mark.asyncio
    async def test_filter_too_few_matches_keeps_top_5(self, monkeypatch) -> None:
        """When fewer than 5 articles match, top 5 are kept as fallback."""
        story_ids = list(range(1, 8))  # 7 articles

        stories_map: dict[int, dict] = {}
        for i in range(1, 8):
            stories_map[i] = _hn_story(
                item_id=i,
                title=f"Article {i}",
            )

        async def mock_get(self: object, url: str, **kwargs: object) -> mock.Mock:  # noqa: ARG001
            url_str = str(url)
            if "topstories" in url_str:
                return _mock_hn_response(story_ids)
            for sid in story_ids:
                if f"/item/{sid}.json" in url_str:
                    return _mock_hn_response(stories_map[sid])
            return _mock_hn_response(None, 404)

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

        # No article matches "nonexistent"
        collector = HackerNewsCollector(filter_keywords=["nonexistent"])
        articles = await collector.fetch()

        # Should keep top 5 as fallback
        assert len(articles) == 5
        assert articles[0].title == "Article 1"

    @pytest.mark.asyncio
    async def test_filter_no_articles_returns_empty(self, monkeypatch) -> None:
        """When there are no articles at all, return empty list."""
        async def mock_get(self: object, url: str, **kwargs: object) -> mock.Mock:  # noqa: ARG001
            return _mock_hn_response([])

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

        collector = HackerNewsCollector(filter_keywords=["openai"])
        articles = await collector.fetch()
        assert articles == []

    @pytest.mark.asyncio
    async def test_filter_matches_all(self, monkeypatch) -> None:
        """When all articles match, the full list is returned."""
        story_ids = [1, 2, 3]

        async def mock_get(self: object, url: str, **kwargs: object) -> mock.Mock:  # noqa: ARG001
            url_str = str(url)
            if "topstories" in url_str:
                return _mock_hn_response(story_ids)
            stories = {
                1: _hn_story(item_id=1, title="AI News Today"),
                2: _hn_story(item_id=2, title="AI in Healthcare"),
                3: _hn_story(item_id=3, title="AI Robotics"),
            }
            for sid, story in stories.items():
                if f"/item/{sid}.json" in url_str:
                    return _mock_hn_response(story)
            return _mock_hn_response(None, 404)

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

        collector = HackerNewsCollector(filter_keywords=["ai"])
        articles = await collector.fetch()
        assert len(articles) == 3


# ===========================================================================
# Default parameter backward compatibility
# ===========================================================================


class TestDefaultParameterBackwardCompatibility:
    """Ensuring all new parameters default to topic-unaware behavior."""

    def test_github_default_has_no_search_topic(self) -> None:
        """GithubTrendingCollector default should have empty search_topic."""
        collector = GithubTrendingCollector()
        assert collector.search_topic == ""

    def test_github_explicit_empty_topic(self) -> None:
        """GithubTrendingCollector with explicit search_topic=\"\"."""
        collector = GithubTrendingCollector(search_topic="")
        assert collector.search_topic == ""
        assert collector.since == "daily"

    def test_reddit_default_has_no_search_topics(self) -> None:
        """RedditCollector default should have empty search_topics."""
        collector = RedditCollector()
        assert collector._search_topics == []

    def test_reddit_explicit_empty_topics(self) -> None:
        """RedditCollector with explicit search_topics=[]."""
        collector = RedditCollector(search_topics=[])
        assert collector._search_topics == []

    def test_hn_default_has_no_keywords(self) -> None:
        """HackerNewsCollector default should have empty filter_keywords."""
        collector = HackerNewsCollector()
        assert collector._filter_keywords == []

    def test_hn_explicit_empty_keywords(self) -> None:
        """HackerNewsCollector with explicit filter_keywords=[]."""
        collector = HackerNewsCollector(filter_keywords=[])
        assert collector._filter_keywords == []


# ===========================================================================
# Internal test helpers
# ===========================================================================


def _mock_hn_response(data, status: int = 200):
    """Create a mock httpx.Response-like object (matches test_hacker_news.py pattern)."""
    resp = mock.Mock()
    resp.status_code = status
    resp.json = mock.Mock(return_value=data)
    if status >= 400:
        resp.raise_for_status = mock.Mock(
            side_effect=httpx.HTTPStatusError(
                f"HTTP {status}",
                request=mock.Mock(),
                response=resp,
            ),
        )
    else:
        resp.raise_for_status = mock.Mock(return_value=None)
    return resp


def _mock_transport(json_body: dict | None = None, *, status_code: int = 200):
    """Return a MockTransport that always responds with *json_body*."""

    def handler(request: httpx.Request) -> httpx.Response:
        if status_code != 200:
            return httpx.Response(status_code, text="error")
        return httpx.Response(200, json=json_body or _reddit_listing([]))

    return MockTransport(handler)
