"""
Tests for src/collectors/__init__.py — 采集器核心接口与数据模型。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.collectors import (
    Article,
    ArticleStatus,
    Collector,
    CollectorError,
    SourceConfig,
)


class TestArticle:
    """Article 数据模型测试。"""

    def test_create_with_all_fields(self) -> None:
        """可以用所有字段创建 Article 实例。"""
        published = datetime.now(timezone.utc)
        article = Article(
            title="Test Article",
            url="https://example.com/test",
            source="test_source",
            published_at=published,
            summary="A brief summary",
            content="Full content here",
            score=85.5,
            category="tools-release",
            tags=["python", "testing"],
            author="Tester",
        )

        assert article.title == "Test Article"
        assert article.url == "https://example.com/test"
        assert article.source == "test_source"
        assert article.published_at == published
        assert article.summary == "A brief summary"
        assert article.content == "Full content here"
        assert article.score == 85.5
        assert article.category == "tools-release"
        assert article.tags == ["python", "testing"]
        assert article.author == "Tester"

    def test_create_with_minimal_fields(self) -> None:
        """仅用必填字段创建 Article，其余字段应有合理默认值。"""
        article = Article(
            title="Minimal",
            url="https://example.com/minimal",
            source="minimal_source",
        )

        assert article.title == "Minimal"
        assert article.url == "https://example.com/minimal"
        assert article.source == "minimal_source"
        # 默认值检查
        assert isinstance(article.published_at, datetime)
        assert article.summary == ""
        assert article.content == ""
        assert article.score == 0.0
        assert article.category == ""
        assert article.tags == []
        assert article.author == ""

    def test_missing_title_raises(self) -> None:
        """缺少必填字段 title 应触发 ValidationError。"""
        with pytest.raises(Exception):  # pydantic.ValidationError
            Article(url="https://example.com", source="test")  # type: ignore[call-arg]

    def test_missing_url_raises(self) -> None:
        """缺少必填字段 url 应触发 ValidationError。"""
        with pytest.raises(Exception):
            Article(title="No URL", source="test")  # type: ignore[call-arg]

    def test_missing_source_raises(self) -> None:
        """缺少必填字段 source 应触发 ValidationError。"""
        with pytest.raises(Exception):
            Article(title="No Source", url="https://example.com")  # type: ignore[call-arg]

    def test_empty_title_raises(self) -> None:
        """空标题应触发验证错误（min_length=1）。"""
        with pytest.raises(Exception):
            Article(title="", url="https://example.com", source="test")

    def test_score_out_of_range_raises(self) -> None:
        """评分超出 0-100 范围应触发验证错误。"""
        with pytest.raises(Exception):
            Article(
                title="Bad Score",
                url="https://example.com",
                source="test",
                score=150.0,
            )

    def test_negative_score_raises(self) -> None:
        """负分应触发验证错误。"""
        with pytest.raises(Exception):
            Article(
                title="Negative Score",
                url="https://example.com",
                source="test",
                score=-10.0,
            )

    def test_validate_assignment_rejects_bad_score(self) -> None:
        """赋值时验证也应触发（validate_assignment=True）。"""
        article = Article(
            title="Valid",
            url="https://example.com",
            source="test",
        )
        with pytest.raises(Exception):
            article.score = 200.0


class TestArticleStatus:
    """ArticleStatus 枚举测试。"""

    def test_enum_values(self) -> None:
        """枚举值应与预期字符串一致。"""
        assert ArticleStatus.NEW.value == "new"
        assert ArticleStatus.SEEN.value == "seen"
        assert ArticleStatus.STARRED.value == "starred"
        assert ArticleStatus.ARCHIVED.value == "archived"

    def test_enum_members(self) -> None:
        """枚举应包含全部 4 个成员。"""
        members = set(ArticleStatus)
        assert members == {
            ArticleStatus.NEW,
            ArticleStatus.SEEN,
            ArticleStatus.STARRED,
            ArticleStatus.ARCHIVED,
        }

    def test_from_string(self) -> None:
        """应支持通过字符串值构造枚举。"""
        assert ArticleStatus("new") == ArticleStatus.NEW
        assert ArticleStatus("seen") == ArticleStatus.SEEN
        assert ArticleStatus("starred") == ArticleStatus.STARRED
        assert ArticleStatus("archived") == ArticleStatus.ARCHIVED

    def test_invalid_string_raises(self) -> None:
        """无效字符串应触发 ValueError。"""
        with pytest.raises(ValueError):
            ArticleStatus("unknown")


class TestCollectorABC:
    """Collector 抽象基类测试。"""

    def test_cannot_instantiate_directly(self) -> None:
        """抽象基类不可直接实例化。"""
        with pytest.raises(TypeError):
            Collector()  # type: ignore[abstract]

    def test_must_implement_abstract_methods(self) -> None:
        """未实现抽象方法的子类不可实例化。"""
        # 只实现了 name，缺少 fetch
        class IncompleteCollector(Collector):
            @property
            def name(self) -> str:
                return "incomplete"

        with pytest.raises(TypeError):
            IncompleteCollector()

    def test_must_implement_name(self) -> None:
        """未实现 name 属性的子类不可实例化。"""
        # 只实现了 fetch，缺少 name
        class NoNameCollector(Collector):
            async def fetch(self) -> list[Article]:
                return []

        with pytest.raises(TypeError):
            NoNameCollector()


class TestConcreteCollector:
    """具体采集器实现测试。"""

    def test_concrete_collector_works(self) -> None:
        """实现了全部抽象方法的子类可正常实例化并调用方法。"""

        class MyCollector(Collector):
            @property
            def name(self) -> str:
                return "my_collector"

            async def fetch(self) -> list[Article]:
                return [
                    Article(
                        title="Collected Article",
                        url="https://example.com/collected",
                        source=self.name,
                    ),
                ]

        collector = MyCollector()
        assert collector.name == "my_collector"
        assert callable(collector.fetch)

    def test_default_health(self) -> None:
        """health() 默认实现应返回包含 name 和 status 的字典。"""

        class HealthyCollector(Collector):
            @property
            def name(self) -> str:
                return "healthy"

            async def fetch(self) -> list[Article]:
                return []

        collector = HealthyCollector()
        health = collector.health()

        assert health["name"] == "healthy"
        assert health["status"] == "ok"
        assert health["timeout"] == 30
        assert health["max_retries"] == 3

    @pytest.mark.asyncio
    async def test_fetch_returns_articles(self) -> None:
        """fetch() 应正确返回 Article 列表。"""

        class FetchCollector(Collector):
            @property
            def name(self) -> str:
                return "fetch_test"

            async def fetch(self) -> list[Article]:
                return [
                    Article(title=f"Article {i}", url=f"https://example.com/{i}", source=self.name)
                    for i in range(3)
                ]

        collector = FetchCollector()
        articles = await collector.fetch()

        assert len(articles) == 3
        for a in articles:
            assert isinstance(a, Article)
            assert a.source == "fetch_test"

    @pytest.mark.asyncio
    async def test_fetch_error_wrapping(self) -> None:
        """采集器应在出错时抛出 CollectorError。"""

        class FailingCollector(Collector):
            @property
            def name(self) -> str:
                return "failing"

            async def fetch(self) -> list[Article]:
                msg = "Connection refused"
                raise CollectorError(msg, source=self.name)

        collector = FailingCollector()
        with pytest.raises(CollectorError) as exc_info:
            await collector.fetch()

        assert exc_info.value.source == "failing"


class TestSourceConfig:
    """SourceConfig 配置模型测试。"""

    def test_valid_config(self) -> None:
        """有效配置应正常创建。"""
        config = SourceConfig(
            name="hacker_news",
            type="api",
        )
        assert config.name == "hacker_news"
        assert config.type == "api"
        assert config.enabled is True
        assert config.interval_minutes == 360
        assert config.priority == 5

    def test_custom_values(self) -> None:
        """自定义值应正确覆盖默认值。"""
        config = SourceConfig(
            name="custom_rss",
            type="rss",
            enabled=False,
            interval_minutes=60,
            priority=1,
        )
        assert config.name == "custom_rss"
        assert config.type == "rss"
        assert config.enabled is False
        assert config.interval_minutes == 60
        assert config.priority == 1

    def test_invalid_type_raises(self) -> None:
        """无效的 type 应触发验证错误。"""
        with pytest.raises(Exception):
            SourceConfig(name="bad", type="invalid_type")

    def test_interval_too_small_raises(self) -> None:
        """interval_minutes < 1 应触发验证错误。"""
        with pytest.raises(Exception):
            SourceConfig(name="bad", type="api", interval_minutes=0)

    def test_priority_out_of_range_raises(self) -> None:
        """priority 超出 1-10 范围应触发验证错误。"""
        with pytest.raises(Exception):
            SourceConfig(name="bad", type="api", priority=11)


class TestCollectorError:
    """CollectorError 异常测试。"""

    def test_error_with_source(self) -> None:
        """带 source 的异常应保留 source 信息。"""
        err = CollectorError("API timeout", source="hacker_news")
        assert str(err) == "API timeout"
        assert err.source == "hacker_news"

    def test_error_without_source(self) -> None:
        """不带 source 的异常，source 应为 None。"""
        err = CollectorError("Generic error")
        assert str(err) == "Generic error"
        assert err.source is None

    def test_error_is_exception(self) -> None:
        """CollectorError 应是 Exception 的子类。"""
        assert issubclass(CollectorError, Exception)


class TestModuleExports:
    """模块导出测试。"""

    def test_all_symbols_importable(self) -> None:
        """__all__ 中的所有符号均可导入。"""
        from src.collectors import __all__ as exported

        expected = {"Article", "ArticleStatus", "Collector", "CollectorError", "SourceConfig"}
        assert set(exported) == expected
