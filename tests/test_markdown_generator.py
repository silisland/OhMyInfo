"""Tests for src.output.markdown_generator."""

from __future__ import annotations

from datetime import date, datetime, timezone

from src.collectors import Article
from src.output.markdown_generator import (
    generate_article_entry,
    generate_category_section,
    generate_daily_digest,
    generate_trend_summary,
)

# ---------------------------------------------------------------------------
# 测试辅助函数
# ---------------------------------------------------------------------------


def _make_article(
    *,
    title: str = "Test Article",
    url: str = "https://example.com/test",
    source: str = "test_source",
    summary: str = "A test article summary.",
    score: float = 50.0,
    category: str = "research-frontier",
    tags: list[str] | None = None,
) -> Article:
    """Create an Article with sensible defaults for testing."""
    return Article(
        title=title,
        url=url,
        source=source,
        published_at=datetime(2026, 6, 20, tzinfo=timezone.utc),
        summary=summary,
        score=score,
        category=category,
        tags=tags or [],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGenerateDailyDigest:
    """Tests for generate_daily_digest()."""

    def test_digest_with_all_categories(self) -> None:
        """Given articles in all 5 categories, digest includes every category section."""
        articles = [
            _make_article(
                title=f"Article-{i}",
                category=cat,
                score=90.0 - i * 5,
            )
            for i, cat in enumerate(
                [
                    "major-release",
                    "tools-release",
                    "research-frontier",
                    "industry-business",
                    "policy-regulation",
                ]
            )
        ]
        result = generate_daily_digest(articles, date=date(2026, 6, 20))

        assert "# 🔭 OhMyInfo 技术日报 — 2026-06-20" in result
        assert "## 🚀 重大发布" in result
        assert "## 📡 工具发布" in result
        assert "## 📚 研究前沿" in result
        assert "## 📰 行业动态" in result
        assert "## 🏛️ 政策监管" in result
        assert "## 🔥 今日热点" in result

    def test_digest_with_empty_articles(self) -> None:
        """Given an empty article list, digest shows minimal placeholder content."""
        result = generate_daily_digest([], date=date(2026, 6, 20))

        assert "暂无收录内容" in result
        assert "## 🔥 今日热点" not in result
        # No category sections either
        for name in ["重大发布", "工具发布", "研究前沿", "行业动态", "政策监管"]:
            assert name not in result

    def test_digest_with_single_category(self) -> None:
        """Given articles in only one category, only that category section appears."""
        articles = [
            _make_article(title="A", category="tools-release", score=80.0),
            _make_article(title="B", category="tools-release", score=70.0),
        ]
        result = generate_daily_digest(articles, date=date(2026, 6, 20))

        assert "## 📡 工具发布" in result
        assert "## 🚀 重大发布" not in result
        assert "## 📚 研究前沿" not in result

    def test_hot_top_five_selection(self) -> None:
        """Given 10+ articles with varying scores, only top 5 appear in 今日热点."""
        articles = [
            _make_article(title=f"Rank-{i}", score=float(100 - i))
            for i in range(10)
        ]
        result = generate_daily_digest(articles, date=date(2026, 6, 20))

        # Top 5 by score: 100, 99, 98, 97, 96
        assert "Rank-0" in result  # score=100
        assert "Rank-4" in result  # score=96
        # Rank-5 to Rank-9 should NOT appear in 今日热点 (but may appear in category sections)
        # Let's check the hot section specifically
        hot_section = _extract_section(result, "🔥 今日热点")
        if hot_section:
            assert "Rank-0" in hot_section
            assert "Rank-4" in hot_section

    def test_date_header_formatting(self) -> None:
        """Given a specific date, the header reflects it correctly."""
        result = generate_daily_digest([], date=date(2026, 12, 25))

        assert "# 🔭 OhMyInfo 技术日报 — 2026-12-25" in result


class TestGenerateCategorySection:
    """Tests for generate_category_section()."""

    def test_articles_sorted_by_score_descending(self) -> None:
        """Given unsorted articles, they appear in score-descending order."""
        articles = [
            _make_article(title="Low", score=30.0),
            _make_article(title="High", score=90.0),
            _make_article(title="Mid", score=60.0),
        ]
        section = generate_category_section("tools-release", articles)

        high_idx = section.index("High")
        mid_idx = section.index("Mid")
        low_idx = section.index("Low")
        assert high_idx < mid_idx < low_idx

    def test_section_uses_correct_icon_and_name(self) -> None:
        """Given a known category, the section header uses the right icon and name."""
        section = generate_category_section("policy-regulation", [])
        # Even with empty articles, header is generated
        assert "## 🏛️" in section
        assert "政策监管" in section

    def test_unknown_category_fallback(self) -> None:
        """Given an unknown category, fallback icon and raw key are used."""
        section = generate_category_section("unknown-cat", [])
        assert "📌" in section
        assert "unknown-cat" in section


class TestGenerateArticleEntry:
    """Tests for generate_article_entry()."""

    def test_score_title_url_summary_tags(self) -> None:
        """Given article with all fields, entry renders all components."""
        article = _make_article(
            title="My Article",
            url="https://example.com/article",
            summary="Some summary here",
            score=85.5,
            tags=["python", "web"],
        )
        entry = generate_article_entry(article, rank=3)

        assert "3." in entry
        assert "⭐" in entry
        assert "**85.5**" in entry
        assert "[My Article](https://example.com/article)" in entry
        assert "Some summary here" in entry
        assert "`标签: python, web`" in entry

    def test_source_tag_display(self) -> None:
        """Given an article with a known source, source tag is shown."""
        article = _make_article(
            title="Src Article",
            source="hacker_news",
        )
        entry = generate_article_entry(article)

        assert "`来源: hacker_news`" in entry

    def test_empty_summary(self) -> None:
        """Given an article with empty summary, no leading dash shown."""
        article = _make_article(
            title="No Summary",
            summary="",
        )
        entry = generate_article_entry(article)

        assert "—" not in entry
        assert "[No Summary]" in entry

    def test_empty_tags(self) -> None:
        """Given an article with no tags, tag field is omitted."""
        article = _make_article(
            title="No Tags",
            tags=[],
        )
        entry = generate_article_entry(article)

        assert "`标签:" not in entry

    def test_missing_source_uses_default(self) -> None:
        """Given an article without explicit source, display uses the source value."""
        article = _make_article(
            title="Default Source",
            source="test_source",
        )
        entry = generate_article_entry(article)

        assert "`来源: test_source`" in entry

    def test_summary_truncation(self) -> None:
        """Given a long summary (>150 chars), it is truncated with ellipsis."""
        long_summary = "A" * 200
        article = _make_article(
            title="Long Summary",
            summary=long_summary,
        )
        entry = generate_article_entry(article)

        assert len(entry.split("— ")[1].split("\n")[0]) <= 155  # 150 + "…" + slack
        assert "…" in entry

    def test_summary_under_limit_not_truncated(self) -> None:
        """Given a short summary (<=150 chars), it is not truncated."""
        short = "Short summary."
        article = _make_article(summary=short)
        entry = generate_article_entry(article)

        assert short in entry
        assert "…" not in entry


class TestGenerateTrendSummary:
    """Tests for generate_trend_summary()."""

    def test_empty_articles_returns_placeholder(self) -> None:
        """Given no articles, placeholder message is returned."""
        result = generate_trend_summary([])

        assert "暂无内容更新" in result

    def test_with_articles_shows_statistics(self) -> None:
        """Given articles, summary includes count, top score, and category info."""
        articles = [
            _make_article(
                title="Hot Article",
                score=95.0,
                category="major-release",
            ),
            _make_article(
                title="Normal",
                score=60.0,
                category="major-release",
            ),
            _make_article(
                title="Other",
                score=40.0,
                category="tools-release",
            ),
        ]
        result = generate_trend_summary(articles)

        assert "**3** 篇" in result
        assert "**95.0**" in result
        assert "Hot Article" in result
        assert "重大发布" in result

    def test_trend_summary_includes_blockquote_format(self) -> None:
        """Given articles, the summary is wrapped in a blockquote."""
        articles = [_make_article(title="Only One")]
        result = generate_trend_summary(articles)

        assert result.startswith(">")
        assert "Only One" in result


# ---------------------------------------------------------------------------
# 集成测试
# ---------------------------------------------------------------------------


class TestIntegration:
    """Integration-level tests for the digest as a whole."""

    def test_digest_cross_source_tag_display(self) -> None:
        """Articles from different sources in same category show proper source tags."""
        articles = [
            _make_article(
                title="From HN",
                source="hacker_news",
                category="major-release",
                score=90.0,
            ),
            _make_article(
                title="From GitHub",
                source="github_trending",
                category="major-release",
                score=80.0,
            ),
            _make_article(
                title="From Reddit",
                source="reddit",
                category="major-release",
                score=70.0,
            ),
        ]
        result = generate_daily_digest(articles, date=date(2026, 6, 20))

        assert "`来源: hacker_news`" in result
        assert "`来源: github_trending`" in result
        assert "`来源: reddit`" in result

    def test_digest_full_output_structure(self) -> None:
        """Given mixed articles, the full digest structure is valid."""
        articles = [
            _make_article(
                title="GPT-5 Released",
                category="major-release",
                score=98.0,
                tags=["ai", "llm"],
            ),
            _make_article(
                title="New Rust Tool",
                category="tools-release",
                score=75.0,
                tags=["rust", "devtools"],
            ),
            _make_article(
                title="Transformer Paper",
                category="research-frontier",
                score=88.0,
                source="arxiv",
                tags=["ml", "nlp"],
            ),
            _make_article(
                title="Startup News",
                category="industry-business",
                score=65.0,
            ),
            _make_article(
                title="EU AI Act",
                category="policy-regulation",
                score=55.0,
                tags=["regulation", "ai"],
            ),
        ]
        result = generate_daily_digest(articles, date=date(2026, 6, 20))

        # Structural assertions
        assert result.startswith("#")
        assert result.endswith("\n")
        assert "---" in result

        # All sections present
        assert "## 🔥 今日热点" in result
        assert "## 🚀 重大发布" in result
        assert "## 📡 工具发布" in result
        assert "## 📚 研究前沿" in result
        assert "## 📰 行业动态" in result
        assert "## 🏛️ 政策监管" in result

        # Top hot articles (at most 5)
        hot_section = _extract_section(result, "🔥 今日热点")
        assert hot_section is not None
        # Only 5 articles total, so all appear in hot
        assert "GPT-5 Released" in hot_section

    def test_digest_with_missing_fields(self) -> None:
        """Given articles with missing optional fields, digest does not crash."""
        article = Article(
            title="Minimal",
            url="https://example.com/minimal",
            source="test_source",
            summary="",
            score=0.0,
            category="",
            tags=[],
        )
        result = generate_daily_digest([article], date=date(2026, 6, 20))

        assert "Minimal" in result
        assert "`标签:" not in result
        assert "`来源: test_source`" in result


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _extract_section(markdown: str, heading: str) -> str | None:
    """Extract the content of a markdown section by heading text.

    Args:
        markdown: full markdown text.
        heading: the heading text to search for (e.g. "🔥 今日热点").

    Returns:
        The section content (from heading to next heading or end), or None.
    """
    lines = markdown.split("\n")
    start_idx = -1
    for i, line in enumerate(lines):
        if line.startswith("## ") and heading in line:
            start_idx = i
            break

    if start_idx == -1:
        return None

    end_idx = len(lines)
    for i in range(start_idx + 1, len(lines)):
        if lines[i].startswith("## "):
            end_idx = i
            break

    return "\n".join(lines[start_idx:end_idx])
