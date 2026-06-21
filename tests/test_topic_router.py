"""
Tests for src/processors/topic_router.py and interest integration in scorer.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.collectors import Article
from src.processors.scorer import (
    InterestBooster,
    RuleScorer,
    ScoringConfig,
    calculate_score,
    calculate_score_with_interests,
)
from src.processors.topic_router import (
    InterestRouter,
    TopicStrategy,
    boost_score,
)


# ===================================================================
# Helpers
# ===================================================================


def _article(
    *,
    title: str = "Test Article",
    source: str = "hacker_news",
    score: float = 50.0,
    hours_ago: float = 1.0,
    summary: str = "",
    content: str = "",
    tags: list[str] | None = None,
    category: str = "",
) -> Article:
    """Create an Article with sensible defaults for interest-boost tests."""
    return Article(
        title=title,
        url="https://example.com/test",
        source=source,
        published_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
        score=score,
        summary=summary,
        content=content,
        tags=tags or [],
        category=category,
    )


def _llm_ok(prompt: str) -> str:
    """A mock LLM provider that returns a valid score."""
    return "85"


# ===================================================================
# InterestRouter — get_strategy
# ===================================================================


class TestGetStrategy:
    """InterestRouter.get_strategy() tests."""

    def test_single_keyword(self) -> None:
        """单个关键词应在各源生成对应的搜索策略。"""
        router = InterestRouter(["obsidian"])
        strategy = router.get_strategy()

        assert strategy.github_search_query == "obsidian"
        assert strategy.reddit_search_queries == ["obsidian"]
        assert strategy.hn_filter_keywords == ["obsidian"]
        assert strategy.arxiv_search_query == "obsidian"
        assert strategy.devto_tags == ["obsidian"]

    def test_multiple_keywords(self) -> None:
        """多个关键词应组合或分列到各源策略中。"""
        router = InterestRouter(["obsidian", "knowledge management"])
        strategy = router.get_strategy()

        assert strategy.github_search_query == "obsidian knowledge management"
        assert strategy.reddit_search_queries == ["obsidian", "knowledge management"]
        assert strategy.hn_filter_keywords == ["obsidian", "knowledge management"]
        assert strategy.arxiv_search_query == "obsidian knowledge management"
        assert strategy.devto_tags == ["obsidian", "knowledge management"]

    def test_empty_interests(self) -> None:
        """空兴趣列表应返回全空的 TopicStrategy。"""
        router = InterestRouter([])
        strategy = router.get_strategy()

        assert strategy.github_search_query == ""
        assert strategy.reddit_search_queries == []
        assert strategy.hn_filter_keywords == []
        assert strategy.arxiv_search_query == ""
        assert strategy.devto_tags == []

    def test_all_whitespace_interests(self) -> None:
        """全空白字符的兴趣词应被过滤掉，返回空策略。"""
        router = InterestRouter(["   ", "  "])
        strategy = router.get_strategy()

        assert strategy.github_search_query == ""
        assert strategy.reddit_search_queries == []
        assert strategy.hn_filter_keywords == []

    def test_mixed_empty_and_valid(self) -> None:
        """混有空字符串和有效关键词时，只保留有效关键词。"""
        router = InterestRouter(["", "rust", "  ", "wasm"])
        strategy = router.get_strategy()

        assert strategy.github_search_query == "rust wasm"
        assert strategy.reddit_search_queries == ["rust", "wasm"]
        assert strategy.hn_filter_keywords == ["rust", "wasm"]
        assert strategy.arxiv_search_query == "rust wasm"
        assert strategy.devto_tags == ["rust", "wasm"]


# ===================================================================
# InterestRouter — boost_score
# ===================================================================


class TestBoostScore:
    """InterestRouter.boost_score() tests."""

    def test_title_match(self) -> None:
        """标题包含兴趣关键词应得 +5 分。"""
        router = InterestRouter(["obsidian"])
        article = _article(title="Obsidian plugin for knowledge management")
        assert router.boost_score(article) == 5.0

    def test_summary_match(self) -> None:
        """摘要包含兴趣关键词应得 +3 分。"""
        router = InterestRouter(["obsidian"])
        article = _article(title="No match", summary="Using obsidian for notes")
        assert router.boost_score(article) == 3.0

    def test_tag_match(self) -> None:
        """标签包含兴趣关键词应得 +3 分。"""
        router = InterestRouter(["obsidian"])
        article = _article(title="No match", tags=["obsidian", "productivity"])
        assert router.boost_score(article) == 3.0

    def test_category_match(self) -> None:
        """分类匹配兴趣关键词应得 +3 分。"""
        router = InterestRouter(["obsidian"])
        article = _article(title="No match", category="obsidian")
        assert router.boost_score(article) == 3.0

    def test_multiple_matches(self) -> None:
        """多个维度匹配应累加。"""
        router = InterestRouter(["obsidian"])
        article = _article(
            title="Obsidian plugin released",
            summary="New obsidian features",
            tags=["obsidian"],
            category="obsidian",
        )
        # title(+5) + summary(+3) + tag(+3) + category(+3) = 14
        assert router.boost_score(article) == 14.0

    def test_max_boost_capped(self) -> None:
        """总加分不应超过 20。"""
        router = InterestRouter(["obsidian", "plugin"])
        article = _article(
            title="Obsidian plugin for knowledge management",
            summary="Obsidian plugin with great features",
            tags=["obsidian", "plugin"],
            category="plugin",
        )
        # obsidian: title(+5) + summary(+3) + tag(+3) = 11
        # plugin:   title(+5) + summary(+3) + tag(+3) + category(+3) = 14
        # total raw: 25, capped at 20
        boost = router.boost_score(article)
        assert boost == 20.0

    def test_no_match_returns_zero(self) -> None:
        """无任何匹配时应返回 0。"""
        router = InterestRouter(["obsidian"])
        article = _article(title="Completely unrelated topic")
        assert router.boost_score(article) == 0.0

    def test_empty_interests_returns_zero(self) -> None:
        """空兴趣列表应返回 0 加分。"""
        router = InterestRouter([])
        article = _article(title="Anything at all")
        assert router.boost_score(article) == 0.0

    def test_case_insensitive_title(self) -> None:
        """标题匹配应大小写不敏感。"""
        router = InterestRouter(["OBSIDIAN"])
        article = _article(title="obsidian plugin is great")
        assert router.boost_score(article) == 5.0

        router2 = InterestRouter(["obsidian"])
        article2 = _article(title="OBSIDIAN PLUGIN")
        assert router2.boost_score(article2) == 5.0

    def test_keyword_as_substring(self) -> None:
        """关键词作为标题子串时应匹配。"""
        router = InterestRouter(["obsidian"])
        article = _article(title="ObsidianMD vs Notion")
        # "obsidian" is a substring of "obsidianMD" (lowercased)
        assert router.boost_score(article) == 5.0

    def test_multi_word_keyword(self) -> None:
        """多词兴趣关键词应作为一个整体匹配。"""
        router = InterestRouter(["knowledge management"])
        article = _article(title="Knowledge Management with Obsidian")
        assert router.boost_score(article) == 5.0

    def test_keyword_split_across_words(self) -> None:
        """多词关键词不应匹配拆分的词（子串匹配在整个文本上）。"""
        # "knowledge management" is checked via `in` on the whole lowercased text
        # so "knowledge" and "management" appearing separately would NOT match.
        router = InterestRouter(["knowledge management"])
        article = _article(title="Knowledge base for management teams")
        # "knowledge management" is not in "knowledge base for management teams"
        assert router.boost_score(article) == 0.0


# ===================================================================
# boost_score convenience function
# ===================================================================


class TestBoostScoreFunction:
    """boost_score() convenience function tests."""

    def test_convenience_matches_router(self) -> None:
        """boost_score() 便利函数应与 InterestRouter.boost_score() 结果一致。"""
        article = _article(title="Obsidian plugin")
        router_boost = InterestRouter(["obsidian"]).boost_score(article)
        func_boost = boost_score(article, ["obsidian"])
        assert func_boost == router_boost

    def test_convenience_with_empty_interests(self) -> None:
        """带空兴趣列表时便利函数应返回 0。"""
        article = _article(title="Anything")
        assert boost_score(article, []) == 0.0


# ===================================================================
# InterestBooster (scorer.py)
# ===================================================================


class TestInterestBooster:
    """InterestBooster class tests (from scorer.py)."""

    def test_boost_title(self) -> None:
        """InterestBooster 的标题匹配应正确加分。"""
        booster = InterestBooster(["obsidian"])
        article = _article(title="Obsidian plugin released")
        assert booster.calculate_boost(article) == 5.0

    def test_boost_summary(self) -> None:
        """InterestBooster 的摘要匹配应正确加分。"""
        booster = InterestBooster(["obsidian"])
        article = _article(title="No match", summary="obsidian notes")
        assert booster.calculate_boost(article) == 3.0

    def test_boost_tag(self) -> None:
        """InterestBooster 的标签匹配应正确加分。"""
        booster = InterestBooster(["obsidian"])
        article = _article(title="No match", tags=["obsidian"])
        assert booster.calculate_boost(article) == 3.0

    def test_boost_category(self) -> None:
        """InterestBooster 的分类匹配应正确加分。"""
        booster = InterestBooster(["obsidian"])
        article = _article(title="No match", category="obsidian")
        assert booster.calculate_boost(article) == 3.0

    def test_max_boost(self) -> None:
        """InterestBooster 总加分不应超过 20。"""
        booster = InterestBooster(["obsidian"])
        article = _article(
            title="Obsidian plugin",
            summary="Obsidian is great",
            tags=["obsidian"],
            category="obsidian",
        )
        # 5 + 3 + 3 + 3 = 14
        assert booster.calculate_boost(article) == 14.0

        # Multiple keywords
        booster2 = InterestBooster(["obsidian", "plugin", "knowledge"])
        article2 = _article(
            title="Obsidian plugin knowledge",
            summary="Obsidian plugin",
            tags=["obsidian", "plugin", "knowledge"],
            category="knowledge",
        )
        # obsidian: title(5) + summary(3) + tag(3) = 11
        # plugin:   title(5) + summary(3) + tag(3) = 11
        # knowledge: title(5) + tag(3) + category(3) = 11
        # raw: 33, capped: 20
        assert booster2.calculate_boost(article2) == 20.0

    def test_empty_interests(self) -> None:
        """空兴趣列表应返回 0。"""
        booster = InterestBooster([])
        article = _article(title="Anything")
        assert booster.calculate_boost(article) == 0.0

    def test_no_match(self) -> None:
        """无匹配时应返回 0。"""
        booster = InterestBooster(["rust"])
        article = _article(title="Python tips and tricks")
        assert booster.calculate_boost(article) == 0.0

    def test_tag_exact_match_only(self) -> None:
        """标签匹配要求精确匹配（不是子串）。"""
        booster = InterestBooster(["obsidian"])
        article = _article(title="No match", tags=["obsidian-plugin"])
        # "obsidian" != "obsidian-plugin" exactly
        assert booster.calculate_boost(article) == 0.0


# ===================================================================
# calculate_score_with_interests
# ===================================================================


class TestCalculateScoreWithInterests:
    """calculate_score_with_interests() integration tests."""

    def test_adds_boost_to_rule_score(self) -> None:
        """兴趣加分应累加到规则分数之上。"""
        article = _article(
            title="Obsidian plugin for PKM",
            source="reddit",
            score=20,
            hours_ago=12,
        )
        base = calculate_score(article, strategy="rule")
        boosted = calculate_score_with_interests(article, interests=["obsidian"])
        # base + 5 (title match)
        assert boosted == pytest.approx(base + 5.0, rel=1e-3)

    def test_capped_at_100(self) -> None:
        """最终分数不应超过 100。"""
        # Create an article that already scores near 100
        article = _article(
            title="Obsidian plugin with funding breakthrough",
            source="hacker_news",
            score=100,
            hours_ago=0.1,
        )
        boosted = calculate_score_with_interests(article, interests=["obsidian"])
        assert boosted <= 100.0

    def test_no_interests_returns_base(self) -> None:
        """无兴趣列表时应返回与 calculate_score 相同的结果。"""
        article = _article(title="Generic article")
        base = calculate_score(article)
        result = calculate_score_with_interests(article, interests=None)
        assert result == base

    def test_empty_interests_returns_base(self) -> None:
        """空兴趣列表时应返回基础分数。"""
        article = _article(title="Generic article")
        base = calculate_score(article)
        result = calculate_score_with_interests(article, interests=[])
        assert result == base

    def test_with_llm_strategy(self) -> None:
        """使用 LLM 策略时兴趣加分应同样生效。"""
        article = _article(title="Obsidian AI features")
        base = calculate_score(article, strategy="llm", llm_provider=_llm_ok)
        boosted = calculate_score_with_interests(
            article,
            interests=["obsidian"],
            strategy="llm",
            llm_provider=_llm_ok,
        )
        assert boosted > base

    def test_passes_config_through(self) -> None:
        """config 参数应正确传递给底层 scorer。"""
        article = _article(title="Obsidian article")
        config = ScoringConfig(
            recency_weight=0.5,
            source_weight=0.2,
            engagement_weight=0.1,
            novelty_weight=0.1,
            impact_weight=0.1,
        )
        # Should not raise
        result = calculate_score_with_interests(
            article,
            interests=["obsidian"],
            config=config,
        )
        assert 0.0 <= result <= 100.0

    def test_passes_recent_titles_through(self) -> None:
        """recent_titles 参数应正确传递给底层 scorer。"""
        article = _article(title="Duplicate Title")
        recent = {"Duplicate Title"}
        # Without recent_titles, novelty is high → higher score
        # With recent_titles (duplicate), novelty is 0 → lower score
        boosted_without = calculate_score_with_interests(
            article, interests=["test"]
        )
        boosted_with = calculate_score_with_interests(
            article, interests=["test"], recent_titles=recent
        )
        # Duplicate title → novelty = 0 → lower overall
        assert boosted_with < boosted_without
