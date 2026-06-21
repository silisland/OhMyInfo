"""
Tests for src/collectors/reddit.py — Reddit hot posts collector.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
from httpx import MockTransport

from src.collectors import Article, CollectorError
from src.collectors.reddit import RedditCollector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reddit_listing(posts: list[dict]) -> dict:
    """Build a Reddit JSON listing envelope around post dicts."""
    return {
        "data": {
            "children": [{"data": p} for p in posts],
        }
    }


def _post(
    *,
    title: str = "Test Post",
    url: str = "https://example.com/test",
    permalink: str = "/r/test/comments/abc123/",
    score: int = 500,
    author: str = "testuser",
    num_comments: int = 10,
    selftext: str = "Post content here",
    created_utc: int = 1_700_000_000,
    over_18: bool = False,
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
        "over_18": over_18,
    }


def _mock_transport(json_body: dict | None = None, *, status_code: int = 200):
    """Return a MockTransport that always responds with *json_body*."""

    def handler(request: httpx.Request) -> httpx.Response:
        if status_code != 200:
            return httpx.Response(status_code, text="error")
        return httpx.Response(200, json=json_body or _reddit_listing([]))

    return MockTransport(handler)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRedditCollector:
    """RedditCollector — parsing, filtering, error handling."""

    @pytest.mark.asyncio
    async def test_fetch_parses_subreddit_hot_feed(self) -> None:
        """Given subreddit hot feeds, fetch returns parsed Articles."""
        ml_posts = [
            _post(
                title="GPT-5 Released",
                url="https://example.com/gpt5",
                permalink="/r/MachineLearning/comments/xyz/",
                score=1_500,
                author="user1",
                num_comments=42,
                selftext="OpenAI just released GPT-5 with amazing capabilities.",
                created_utc=1_700_000_000,
            ),
        ]
        prog_posts = [
            _post(
                title="Rust in Linux Kernel",
                url="https://example.com/rust-linux",
                permalink="/r/programming/comments/abc/",
                score=800,
                author="user2",
                num_comments=120,
                selftext="",
                created_utc=1_700_000_001,
            ),
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            if "programming" in request.url.path:
                return httpx.Response(200, json=_reddit_listing(prog_posts))
            return httpx.Response(200, json=_reddit_listing(ml_posts))

        transport = MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            collector = RedditCollector(
                subreddits=["MachineLearning", "programming"],
                min_upvotes=0,
                http_client=client,
            )
            articles = await collector.fetch()

        assert len(articles) == 2

        # -- article 0 (MachineLearning)
        assert articles[0].title == "GPT-5 Released"
        assert articles[0].url == "https://example.com/gpt5"
        assert articles[0].source == "reddit"
        assert articles[0].author == "user1"
        assert articles[0].score > 0
        assert "42 comments" in articles[0].summary
        assert "OpenAI just released GPT-5" in articles[0].summary

        # -- article 1 (programming)
        assert articles[1].title == "Rust in Linux Kernel"
        assert articles[1].url == "https://example.com/rust-linux"
        assert articles[1].author == "user2"
        # no selftext → summary is just comment count
        assert articles[1].summary == "120 comments"

    @pytest.mark.asyncio
    async def test_filters_posts_below_min_upvotes(self) -> None:
        """Given a min_upvotes threshold, posts below it are excluded."""
        posts = [
            _post(title="Popular Post", score=500),
            _post(title="Low Vote Post", score=50),
        ]

        transport = _mock_transport(_reddit_listing(posts))
        async with httpx.AsyncClient(transport=transport) as client:
            collector = RedditCollector(
                subreddits=["test"],
                min_upvotes=100,
                http_client=client,
            )
            articles = await collector.fetch()

        assert len(articles) == 1
        assert articles[0].title == "Popular Post"

    @pytest.mark.asyncio
    async def test_skips_deleted_or_removed_posts(self) -> None:
        """Given posts with [deleted] author or null title, they are skipped."""
        posts = [
            _post(title="Valid Post", author="user1"),
            _post(title="", author="user2", score=0),
            _post(title=None, author="[deleted]", score=300),  # type: ignore[call-arg]
            _post(title="Removed by Mods", author="[deleted]", score=150),
        ]

        transport = _mock_transport(_reddit_listing(posts))
        async with httpx.AsyncClient(transport=transport) as client:
            collector = RedditCollector(
                subreddits=["test"],
                min_upvotes=0,
                http_client=client,
            )
            articles = await collector.fetch()

        assert len(articles) == 1
        assert articles[0].title == "Valid Post"

    @pytest.mark.asyncio
    async def test_self_post_uses_permalink_as_url(self) -> None:
        """Given a self post (Reddit-internal URL), use the permalink as URL."""
        posts = [
            _post(
                title="Self Post",
                url=f"https://www.reddit.com/r/test/comments/xyz/",
                permalink="/r/test/comments/xyz/",
            ),
        ]

        transport = _mock_transport(_reddit_listing(posts))
        async with httpx.AsyncClient(transport=transport) as client:
            collector = RedditCollector(
                subreddits=["test"],
                min_upvotes=0,
                http_client=client,
            )
            articles = await collector.fetch()

        assert len(articles) == 1
        # Self-post URLs from Reddit are kept as-is
        assert articles[0].url == "https://www.reddit.com/r/test/comments/xyz/"

    @pytest.mark.asyncio
    async def test_network_error_raises_collector_error(self) -> None:
        """Given a connection error, fetch raises CollectorError."""

        def fail_handler(request: httpx.Request) -> httpx.Response:
            msg = "DNS resolution failed"
            raise httpx.ConnectError(msg)

        transport = MockTransport(fail_handler)
        async with httpx.AsyncClient(transport=transport) as client:
            collector = RedditCollector(
                subreddits=["test"],
                min_upvotes=0,
                http_client=client,
            )
            with pytest.raises(CollectorError) as exc_info:
                await collector.fetch()

        assert exc_info.value.source == "reddit"

    @pytest.mark.asyncio
    async def test_http_error_status_raises_collector_error(self) -> None:
        """Given a non-2xx HTTP response, fetch raises CollectorError."""
        transport = _mock_transport(status_code=429)
        async with httpx.AsyncClient(transport=transport) as client:
            collector = RedditCollector(
                subreddits=["test"],
                min_upvotes=0,
                http_client=client,
            )
            with pytest.raises(CollectorError) as exc_info:
                await collector.fetch()

        assert exc_info.value.source == "reddit"

    @pytest.mark.asyncio
    async def test_selftext_truncated_in_summary(self) -> None:
        """Given a long selftext, summary is truncated to 200 characters."""
        long_text = "A" * 500
        posts = [
            _post(
                title="Long Post",
                selftext=long_text,
                num_comments=5,
            ),
        ]

        transport = _mock_transport(_reddit_listing(posts))
        async with httpx.AsyncClient(transport=transport) as client:
            collector = RedditCollector(
                subreddits=["test"],
                min_upvotes=0,
                http_client=client,
            )
            articles = await collector.fetch()

        assert len(articles) == 1
        summary = articles[0].summary
        # 200 chars + "..." + " | 5 comments"
        assert "A" * 200 in summary
        assert "..." in summary
        assert "5 comments" in summary

    @pytest.mark.asyncio
    async def test_published_at_from_created_utc(self) -> None:
        """Given a created_utc timestamp, published_at is correctly parsed."""
        posts = [
            _post(title="Timely Post", created_utc=1_700_000_000),
        ]

        transport = _mock_transport(_reddit_listing(posts))
        async with httpx.AsyncClient(transport=transport) as client:
            collector = RedditCollector(
                subreddits=["test"],
                min_upvotes=0,
                http_client=client,
            )
            articles = await collector.fetch()

        assert len(articles) == 1
        expected = datetime.fromtimestamp(1_700_000_000, tz=timezone.utc)
        assert articles[0].published_at == expected

    @pytest.mark.asyncio
    async def test_score_normalized_in_zero_to_hundred_range(self) -> None:
        """Given Reddit upvotes, score is normalized to 0-100."""
        posts = [
            _post(title="High Score", score=50_000),
            _post(title="Zero Score", score=0),
        ]

        transport = _mock_transport(_reddit_listing(posts))
        async with httpx.AsyncClient(transport=transport) as client:
            collector = RedditCollector(
                subreddits=["test"],
                min_upvotes=0,
                http_client=client,
            )
            articles = await collector.fetch()

        assert articles[0].score == 100.0  # clamped
        assert articles[1].score == 0.0

    def test_name_property(self) -> None:
        """Given a RedditCollector, name is 'reddit'."""
        collector = RedditCollector()
        assert collector.name == "reddit"

    def test_default_health(self) -> None:
        """Given a RedditCollector, health returns expected defaults."""
        collector = RedditCollector()
        health = collector.health()
        assert health["name"] == "reddit"
        assert health["status"] == "ok"
