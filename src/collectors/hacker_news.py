"""Hacker News collector — fetches top stories from the HN Firebase API.

使用 Hacker News 公开 Firebase API:

    GET /v0/topstories.json  → 当前热门文章 ID 列表
    GET /v0/item/{id}.json   → 单篇文章详情

无需 API Key，无需注册，完全免费开放。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx

from src.collectors import Article, Collector, CollectorError


class HackerNewsCollector(Collector):
    """Hacker News 采集器 —— 通过 Firebase API 获取 HN 热门文章。

    API 地址: https://hacker-news.firebaseio.com/v0/
    每次采集取前 30 篇热门文章，逐篇获取详情后转换为标准 Article 模型。

    When ``filter_keywords`` is set, after fetching stories the results are
    filtered to only those whose title matches at least one keyword.  If
    fewer than 5 stories match, the top 5 are kept regardless.

    Attributes:
        BASE_URL: Firebase API 基础地址。
        MAX_STORIES: 每次采集最多获取的文章数。
        SCORE_CAP: HN 点赞数归一化的上限（2000 分 → Article.score 100）。
    """

    BASE_URL = "https://hacker-news.firebaseio.com/v0"
    TOP_STORIES_ENDPOINT = "/topstories.json"
    ITEM_ENDPOINT = "/item/{item_id}.json"
    MAX_STORIES = 30
    SCORE_CAP = 2000
    _MIN_FALLBACK = 5

    def __init__(self, filter_keywords: list[str] | None = None) -> None:
        self._filter_keywords = [kw.lower() for kw in (filter_keywords or [])]

    @property
    def name(self) -> str:
        return "hacker_news"

    async def fetch(self) -> list[Article]:
        """执行采集：获取 HN 当前 Top 30 热门文章。

        Returns:
            采集到的文章列表（网络正常但 HN 无数据时返回空列表）。
            当设置了 filter_keywords 时仅保留匹配的文章。

        Raises:
            CollectorError: 重试耗尽后仍无法获取热门文章列表。
        """
        async with httpx.AsyncClient(timeout=self.DEFAULT_TIMEOUT) as client:
            story_ids = await self._fetch_top_story_ids(client)

            if not story_ids:
                return []

            story_ids = story_ids[: self.MAX_STORIES]

            tasks = [self._fetch_story_detail(client, sid) for sid in story_ids]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            articles: list[Article] = []
            for result in results:
                if isinstance(result, Exception):
                    # 单篇采集失败不阻塞全局，静默跳过
                    continue
                if result is not None:
                    articles.append(result)

            return await self._filter_by_interests(articles)

    async def _fetch_top_story_ids(self, client: httpx.AsyncClient) -> list[int]:
        """获取 HN 热门文章 ID 列表，含指数退避重试。

        Args:
            client: 共享的 httpx 异步客户端。

        Returns:
            文章 ID 列表。

        Raises:
            CollectorError: 所有重试均失败或响应格式异常。
        """
        url = f"{self.BASE_URL}{self.TOP_STORIES_ENDPOINT}"
        last_exc: Exception | None = None

        for attempt in range(self.DEFAULT_MAX_RETRIES):
            try:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, list):
                    msg = f"响应格式异常：期望 list，实际 {type(data).__name__}"
                    raise CollectorError(msg, source=self.name)
                return [int(i) for i in data]
            except httpx.HTTPError as e:
                last_exc = e
                if attempt < self.DEFAULT_MAX_RETRIES - 1:
                    await asyncio.sleep(2**attempt)
                continue

        msg = f"重试 {self.DEFAULT_MAX_RETRIES} 次后仍无法获取热门文章: {last_exc}"
        raise CollectorError(msg, source=self.name) from last_exc

    async def _fetch_story_detail(
        self,
        client: httpx.AsyncClient,
        item_id: int,
    ) -> Article | None:
        """获取并解析单篇 HN 文章详情。

        Args:
            client: 共享的 httpx 异步客户端。
            item_id: HN 文章 ID。

        Returns:
            解析成功的 Article，或 None（网络错误 / 数据异常 / 无标题）。
        """
        url = f"{self.BASE_URL}{self.ITEM_ENDPOINT.format(item_id=item_id)}"

        try:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError:
            return None

        if not data or not isinstance(data, dict):
            return None

        return self._parse_story(data)

    def _parse_story(self, data: dict[str, Any]) -> Article | None:
        """将 HN API 返回的文章 JSON 转换为 Article 模型。

        Args:
            data: HN /v0/item/{id} 接口返回的 JSON 字典。

        Returns:
            Article 对象，若缺少标题则返回 None。
        """
        title = data.get("title")
        if not title:
            return None

        item_id = data.get("id")
        # 没有外部 URL（如 Ask HN / Show HN 类）则回退到 HN 讨论页
        url = data.get("url") or f"https://news.ycombinator.com/item?id={item_id}"
        author = data.get("by", "")
        score = data.get("score", 0)
        timestamp = data.get("time", 0)

        if timestamp:
            published_at = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        else:
            published_at = datetime.now(timezone.utc)

        # HN score 通常在 0~2000+ 范围内，映射到 0~100
        normalized_score = min(score / self.SCORE_CAP * 100, 100.0)

        return Article(
            title=title,
            url=url,
            source=self.name,
            published_at=published_at,
            author=author,
            score=normalized_score,
        )

    async def _filter_by_interests(
        self,
        articles: list[Article],
    ) -> list[Article]:
        """Filter articles by keyword interests, with a minimum fallback.

        Args:
            articles: List of articles to filter.

        Returns:
            Filtered list.  When ``_filter_keywords`` is empty returns all
            articles unchanged.  When fewer than ``_MIN_FALLBACK`` articles
            match, the top ``_MIN_FALLBACK`` are kept to avoid empty results.
        """
        if not self._filter_keywords:
            return articles

        matched = [
            a
            for a in articles
            if any(kw in a.title.lower() for kw in self._filter_keywords)
        ]

        if len(matched) < self._MIN_FALLBACK and articles:
            return articles[: self._MIN_FALLBACK]
        return matched
