"""Tests for src/collectors/hacker_news.py — Hacker News 采集器。"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import Mock

import httpx
import pytest

from src.collectors import Article, CollectorError
from src.collectors.hacker_news import HackerNewsCollector


# ---------------------------------------------------------------------------
# Helper: build mock httpx responses
# ---------------------------------------------------------------------------


def _mock_response(data, status: int = 200):
    """Create a mock httpx.Response-like object."""
    resp = Mock()
    resp.status_code = status
    resp.json = Mock(return_value=data)
    if status >= 400:
        resp.raise_for_status = Mock(
            side_effect=httpx.HTTPStatusError(
                f"HTTP {status}",
                request=Mock(),
                response=resp,
            ),
        )
    else:
        resp.raise_for_status = Mock(return_value=None)
    return resp


# ---------------------------------------------------------------------------
# Sample HN story payloads
# ---------------------------------------------------------------------------

SAMPLE_STORY: dict = {
    "id": 1,
    "title": "Test HN Story",
    "url": "https://example.com/test",
    "by": "testuser",
    "score": 500,
    "time": 1_700_000_000,
    "descendants": 50,
    "type": "story",
}

ASK_HN_STORY: dict = {
    "id": 2,
    "title": "Ask HN: What are you working on?",
    "by": "askuser",
    "score": 100,
    "time": 1_700_000_001,
    "descendants": 200,
    "type": "story",
    # 无 "url" 字段 —— 典型 Ask HN 特征
}

STORY_NO_TITLE: dict = {
    "id": 3,
    "by": "someuser",
    "score": 10,
    "time": 1_700_000_002,
    "type": "story",
    # 缺少 "title" —— 应被跳过
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHackerNewsCollector:
    """HackerNewsCollector 单元测试。"""

    # ── 基本属性 ──────────────────────────────────────────────

    def test_name(self) -> None:
        """name 应返回 'hacker_news'。"""
        collector = HackerNewsCollector()
        assert collector.name == "hacker_news"

    def test_health(self) -> None:
        """health() 应返回包含 name 和 status 的字典。"""
        collector = HackerNewsCollector()
        health = collector.health()

        assert health["name"] == "hacker_news"
        assert health["status"] == "ok"
        assert health["timeout"] == 30
        assert health["max_retries"] == 3

    def test_class_constants(self) -> None:
        """类常量应有合理的默认值。"""
        assert HackerNewsCollector.MAX_STORIES == 30
        assert HackerNewsCollector.SCORE_CAP == 2000
        assert HackerNewsCollector.BASE_URL == "https://hacker-news.firebaseio.com/v0"

    # ── 采集主流程 ──────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_fetch_top_stories(self, monkeypatch) -> None:
        """应正确获取并解析 Top 热门文章。"""
        story_ids = [1, 2]

        async def mock_get(self, url: str, **kwargs):  # noqa: ARG001
            url_str = str(url)
            if "topstories" in url_str:
                return _mock_response(story_ids)
            if "/item/1.json" in url_str:
                return _mock_response(SAMPLE_STORY)
            if "/item/2.json" in url_str:
                return _mock_response(ASK_HN_STORY)
            return _mock_response(None, 404)

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

        collector = HackerNewsCollector()
        articles = await collector.fetch()

        assert len(articles) == 2

        # —— 第一篇：完整的外部 URL
        a1 = articles[0]
        assert a1.title == "Test HN Story"
        assert a1.url == "https://example.com/test"
        assert a1.source == "hacker_news"
        assert a1.author == "testuser"
        assert a1.score == pytest.approx(25.0)  # 500 / 2000 * 100

        # —— 第二篇：Ask HN —— 应使用 HN 讨论页作为回退 URL
        a2 = articles[1]
        assert a2.title == "Ask HN: What are you working on?"
        assert a2.url == "https://news.ycombinator.com/item?id=2"
        assert a2.author == "askuser"
        assert a2.score == pytest.approx(5.0)  # 100 / 2000 * 100

    # ── 文章解析 ──────────────────────────────────────────────

    def test_parse_story_with_url(self) -> None:
        """有外部 URL 的文章应正确解析。"""
        collector = HackerNewsCollector()
        article = collector._parse_story(SAMPLE_STORY)

        assert article is not None
        assert article.title == "Test HN Story"
        assert article.url == "https://example.com/test"
        assert article.author == "testuser"
        assert article.score == pytest.approx(25.0)

        expected_dt = datetime.fromtimestamp(1_700_000_000, tz=timezone.utc)
        assert article.published_at == expected_dt

    def test_parse_story_without_url(self) -> None:
        """无外部 URL 的文章（Ask HN）应使用 HN 讨论页 URL。"""
        collector = HackerNewsCollector()
        article = collector._parse_story(ASK_HN_STORY)

        assert article is not None
        assert article.title == "Ask HN: What are you working on?"
        assert article.url == "https://news.ycombinator.com/item?id=2"
        assert article.author == "askuser"
        assert article.score == pytest.approx(5.0)  # 100/2000*100

    def test_parse_story_no_title_returns_none(self) -> None:
        """缺少标题的文章应返回 None。"""
        collector = HackerNewsCollector()
        article = collector._parse_story(STORY_NO_TITLE)
        assert article is None

    def test_parse_empty_dict_returns_none(self) -> None:
        """空字典应返回 None。"""
        collector = HackerNewsCollector()
        article = collector._parse_story({})
        assert article is None

    def test_parse_story_score_cap(self) -> None:
        """超高的 HN 分数应被上限截断为 100。"""
        collector = HackerNewsCollector()
        high_score = {
            "id": 999,
            "title": "Very Popular",
            "url": "https://example.com/popular",
            "by": "popular_user",
            "score": 5000,  # > SCORE_CAP (2000)
            "time": 1_700_000_000,
        }
        article = collector._parse_story(high_score)
        assert article is not None
        assert article.score == 100.0

    def test_parse_story_zero_score(self) -> None:
        """零分的文章应映射为 0.0。"""
        collector = HackerNewsCollector()
        zero_score = {
            "id": 1000,
            "title": "Zero Score",
            "url": "https://example.com/zero",
            "by": "nobody",
            "score": 0,
            "time": 1_700_000_000,
        }
        article = collector._parse_story(zero_score)
        assert article is not None
        assert article.score == 0.0

    # ── 空响应 ──────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_fetch_empty_top_stories(self, monkeypatch) -> None:
        """HN 返回空 ID 列表时应返回空文章列表。"""
        async def mock_get(self, url: str, **kwargs):  # noqa: ARG001
            return _mock_response([])

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

        collector = HackerNewsCollector()
        articles = await collector.fetch()
        assert articles == []

    # ── API 错误 ──────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_fetch_top_stories_http_error(self, monkeypatch) -> None:
        """topstories 接口返回 HTTP 错误时应抛出 CollectorError。"""
        async def mock_get(self, url: str, **kwargs):  # noqa: ARG001
            return _mock_response(None, 500)

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

        collector = HackerNewsCollector()
        with pytest.raises(CollectorError) as exc_info:
            await collector.fetch()

        assert exc_info.value.source == "hacker_news"

    @pytest.mark.asyncio
    async def test_fetch_top_stories_non_list_response(self, monkeypatch) -> None:
        """topstories 返回非列表类型时应抛出 CollectorError。"""
        async def mock_get(self, url: str, **kwargs):  # noqa: ARG001
            if "topstories" in str(url):
                return _mock_response({"error": "not a list"})
            return _mock_response(None, 404)

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

        collector = HackerNewsCollector()
        with pytest.raises(CollectorError) as exc_info:
            await collector.fetch()

        assert exc_info.value.source == "hacker_news"

    # ── 重试逻辑 ──────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_retry_on_failure_then_succeed(self, monkeypatch) -> None:
        """首次失败、重试成功后应正常返回数据。"""
        call_count = 0
        story_ids = [1]

        async def mock_get(self, url: str, **kwargs):  # noqa: ARG001
            nonlocal call_count
            call_count += 1
            if "topstories" in str(url):
                if call_count == 1:
                    return _mock_response(None, 503)
                return _mock_response(story_ids)
            if "/item/1.json" in str(url):
                return _mock_response(SAMPLE_STORY)
            return _mock_response(None, 404)

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

        collector = HackerNewsCollector()
        articles = await collector.fetch()

        assert len(articles) == 1
        assert articles[0].title == "Test HN Story"
        assert call_count >= 2  # 至少重试一次

    @pytest.mark.asyncio
    async def test_retry_exhaustion_raises_error(self, monkeypatch) -> None:
        """重试耗尽后应抛出 CollectorError。"""
        async def mock_get(self, url: str, **kwargs):  # noqa: ARG001
            return _mock_response(None, 503)

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

        collector = HackerNewsCollector()
        with pytest.raises(CollectorError) as exc_info:
            await collector.fetch()

        assert exc_info.value.source == "hacker_news"

    # ── 单篇采集失败不影响整体 ──────────────────────────────────

    @pytest.mark.asyncio
    async def test_individual_story_failure_skipped(self, monkeypatch) -> None:
        """单篇故事获取失败应被跳过，不影响其他文章的返回。"""
        story_ids = [1, 2, 3]

        async def mock_get(self, url: str, **kwargs):  # noqa: ARG001
            url_str = str(url)
            if "topstories" in url_str:
                return _mock_response(story_ids)
            if "/item/1.json" in url_str:
                return _mock_response(SAMPLE_STORY)
            if "/item/2.json" in url_str:
                return _mock_response(None, 500)  # 此篇失败
            if "/item/3.json" in url_str:
                return _mock_response(ASK_HN_STORY)
            return _mock_response(None, 404)

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

        collector = HackerNewsCollector()
        articles = await collector.fetch()

        assert len(articles) == 2  # 失败的那篇被跳过
        assert articles[0].title == "Test HN Story"
        assert articles[1].title == "Ask HN: What are you working on?"

    # ── 健康检查 ──────────────────────────────────────────────

    def test_health_includes_custom_values(self) -> None:
        """健康检查应包含自定义属性。"""
        collector = HackerNewsCollector()
        health = collector.health()

        assert health["name"] == "hacker_news"
        assert health["status"] == "ok"
        assert health["timeout"] == 30
        assert health["max_retries"] == 3
