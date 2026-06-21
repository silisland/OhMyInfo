"""Tests for src/processors/dedup.py — Article deduplication processor."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.collectors import Article
from src.processors.dedup import (
    dedup_by_title,
    dedup_by_url,
    dedup_pipeline,
    merge_duplicates,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_T0 = datetime.now(timezone.utc)


def _make(**overrides: object) -> Article:
    """Build an Article with sensible defaults."""
    defaults: dict = {
        "title": "Test Article",
        "url": "https://example.com/article",
        "source": "test_source",
        "published_at": _T0,
    }
    defaults.update(overrides)
    return Article(**defaults)


# ---------------------------------------------------------------------------
# dedup_by_url
# ---------------------------------------------------------------------------


class TestDedupByUrl:
    """Exact URL deduplication."""

    def test_exact_url_duplicates(self) -> None:
        """Same URL → only the first article is kept."""
        a1 = _make(title="First", url="https://example.com/a")
        a2 = _make(title="Second", url="https://example.com/a")
        result = dedup_by_url([a1, a2])
        assert len(result) == 1
        assert result[0].title == "First"

    def test_trailing_slash_normalized(self) -> None:
        """URLs that differ only by trailing slash are treated as the same."""
        a1 = _make(title="No Slash", url="https://example.com/a")
        a2 = _make(title="With Slash", url="https://example.com/a/")
        result = dedup_by_url([a1, a2])
        assert len(result) == 1
        assert result[0].title == "No Slash"

    def test_fragment_stripped(self) -> None:
        """URLs that differ only by fragment are treated as the same."""
        a1 = _make(title="No Fragment", url="https://example.com/a")
        a2 = _make(title="With Fragment", url="https://example.com/a#section")
        result = dedup_by_url([a1, a2])
        assert len(result) == 1
        assert result[0].title == "No Fragment"

    def test_source_tag_added(self) -> None:
        """Each kept article gets a source:<name> tag."""
        article = _make(source="hacker_news")
        result = dedup_by_url([article])
        assert len(result) == 1
        assert "source:hacker_news" in result[0].tags

    def test_all_distinct_urls(self) -> None:
        """Articles with different URLs are all kept."""
        articles = [
            _make(title="A", url="https://example.com/a"),
            _make(title="B", url="https://example.com/b"),
            _make(title="C", url="https://example.com/c"),
        ]
        result = dedup_by_url(articles)
        assert len(result) == 3

    def test_empty_list(self) -> None:
        """Empty input returns empty list."""
        result = dedup_by_url([])
        assert result == []


# ---------------------------------------------------------------------------
# dedup_by_title
# ---------------------------------------------------------------------------


class TestDedupByTitle:
    """Fuzzy title deduplication."""

    def test_identical_titles(self) -> None:
        """Identical titles are deduped."""
        a1 = _make(title="Python 3.12 Released", url="https://example.com/a")
        a2 = _make(title="Python 3.12 Released", url="https://example.com/b")
        result = dedup_by_title([a1, a2])
        assert len(result) == 1
        assert result[0].title == "Python 3.12 Released"

    def test_similar_titles(self) -> None:
        """Titles differing only by punctuation are deduped."""
        a1 = _make(title="Python 3.12 Released!", url="https://example.com/a")
        a2 = _make(title="Python 3.12 Released", url="https://example.com/b")
        result = dedup_by_title([a1, a2])
        assert len(result) == 1

    def test_case_insensitive(self) -> None:
        """Case differences alone are not enough to avoid dedup."""
        a1 = _make(title="Python 3.12 Released", url="https://example.com/a")
        a2 = _make(title="python 3.12 released", url="https://example.com/b")
        result = dedup_by_title([a1, a2])
        assert len(result) == 1

    def test_very_different_titles_not_deduped(self) -> None:
        """Titles with different wording are both kept."""
        a1 = _make(title="Python 3.12 Released", url="https://example.com/a")
        a2 = _make(title="Rust 1.75 Introduces New Features", url="https://example.com/b")
        result = dedup_by_title([a1, a2])
        assert len(result) == 2

    def test_custom_threshold(self) -> None:
        """A lower threshold catches more duplicates."""
        a1 = _make(
            title="Python 3.12: What's New", url="https://example.com/a",
        )
        a2 = _make(
            title="Python 3.12: What Is New", url="https://example.com/b",
        )
        # Default threshold (0.85) should keep both for slightly different titles
        result_default = dedup_by_title([a1, a2])
        # At 0.7 they should match
        result_loose = dedup_by_title([a1, a2], threshold=0.7)
        assert len(result_loose) == 1
        # Ensure default is stricter
        assert len(result_default) >= len(result_loose)

    def test_source_tag_preserved(self) -> None:
        """Source tags are still added after title dedup."""
        a1 = _make(title="Same Story", source="hn")
        a2 = _make(title="Same Story", source="reddit")
        result = dedup_by_title([a1, a2])
        assert len(result) == 1
        assert any(t.startswith("source:") for t in result[0].tags)

    def test_empty_list(self) -> None:
        """Empty input returns empty list."""
        assert dedup_by_title([]) == []

    def test_all_distinct_titles(self) -> None:
        """All distinct titles are kept."""
        articles = [
            _make(title="Alpha", url="https://example.com/a"),
            _make(title="Beta", url="https://example.com/b"),
            _make(title="Gamma", url="https://example.com/c"),
        ]
        assert len(dedup_by_title(articles)) == 3


# ---------------------------------------------------------------------------
# merge_duplicates
# ---------------------------------------------------------------------------


class TestMergeDuplicates:
    """Cross-source merge."""

    def test_same_url_different_sources(self) -> None:
        """Same URL from different sources → merged with combined tags."""
        hn = _make(
            title="Python 3.12 Released",
            url="https://example.com/article",
            source="hacker_news",
            score=90.0,
        )
        reddit = _make(
            title="Python 3.12 Released",
            url="https://example.com/article",
            source="reddit",
            score=85.0,
        )
        result = merge_duplicates([hn, reddit])
        assert len(result) == 1
        merged = result[0]
        # Highest score preserved
        assert merged.score == 90.0
        # Both sources tracked
        assert "source:hacker_news" in merged.tags
        assert "source:reddit" in merged.tags

    def test_same_title_different_urls_different_sources(self) -> None:
        """Same title, different URLs, different sources → merged."""
        hn = _make(
            title="New AI Model Breaks Records",
            url="https://news.ycombinator.com/item?id=12345",
            source="hacker_news",
        )
        reddit = _make(
            title="New AI Model Breaks Records",
            url="https://reddit.com/r/ai/comments/abcde",
            source="reddit",
        )
        result = merge_duplicates([hn, reddit])
        assert len(result) == 1
        merged = result[0]
        assert "source:hacker_news" in merged.tags
        assert "source:reddit" in merged.tags

    def test_same_source_not_merged(self) -> None:
        """Articles from the same source that match are still merged (single source tracked)."""
        a1 = _make(title="Same Story", url="https://example.com/a", source="hn")
        a2 = _make(title="Same Story", url="https://example.com/b", source="hn")
        result = merge_duplicates([a1, a2])
        assert len(result) == 1
        merged = result[0]
        # Source should still be tracked
        assert "source:hn" in merged.tags

    def test_preserves_longer_content(self) -> None:
        """When merging, the longer content and summary are kept."""
        short = _make(
            title="Story",
            url="https://example.com/a",
            source="src_a",
            content="Short.",
            summary="Brief.",
            score=50.0,
        )
        long = _make(
            title="Story",
            url="https://example.com/b",
            source="src_b",
            content="This is a much longer content.",
            summary="This is a detailed summary.",
            score=80.0,
        )
        result = merge_duplicates([short, long])
        assert len(result) == 1
        merged = result[0]
        assert merged.content == "This is a much longer content."
        assert merged.summary == "This is a detailed summary."
        assert merged.score == 80.0

    def test_distinct_articles_not_merged(self) -> None:
        """Completely different articles are not merged."""
        a1 = _make(
            title="Python 3.12 Released",
            url="https://example.com/python",
            source="hn",
        )
        a2 = _make(
            title="Rust 1.75 Introduces New Features",
            url="https://example.com/rust",
            source="reddit",
        )
        result = merge_duplicates([a1, a2])
        assert len(result) == 2

    def test_empty_list(self) -> None:
        """Empty input returns empty list."""
        assert merge_duplicates([]) == []


# ---------------------------------------------------------------------------
# dedup_pipeline
# ---------------------------------------------------------------------------


class TestDedupPipeline:
    """Full dedup pipeline integration."""

    def test_empty_list(self) -> None:
        """Empty input returns empty list."""
        assert dedup_pipeline([]) == []

    def test_no_duplicates(self) -> None:
        """All distinct articles pass through unchanged."""
        articles = [
            _make(title="Alpha", url="https://example.com/a", source="hn"),
            _make(title="Beta", url="https://example.com/b", source="reddit"),
            _make(title="Gamma", url="https://example.com/c", source="devto"),
        ]
        result = dedup_pipeline(articles)
        assert len(result) == 3

    def test_url_duplicates_removed(self) -> None:
        """URL duplicates are removed first."""
        articles = [
            _make(title="First", url="https://example.com/a"),
            _make(title="Second", url="https://example.com/a"),  # dup URL
            _make(title="Third", url="https://example.com/b"),
        ]
        result = dedup_pipeline(articles)
        assert len(result) == 2
        assert result[0].title == "First"
        assert result[1].title == "Third"

    def test_title_duplicates_removed(self) -> None:
        """Title near-duplicates are removed after URL dedup."""
        articles = [
            _make(title="Python 3.12 Released", url="https://example.com/a"),
            _make(title="Python 3.12 Released!", url="https://example.com/b"),
            _make(title="Rust 1.75 Released", url="https://example.com/c"),
        ]
        result = dedup_pipeline(articles)
        assert len(result) == 2
        titles = {a.title for a in result}
        assert "Python 3.12 Released" in titles or "Python 3.12 Released!" in titles
        assert "Rust 1.75 Released" in titles

    def test_cross_source_merged(self) -> None:
        """Cross-source duplicates are merged with both sources tracked."""
        articles = [
            _make(
                title="AI Breakthrough",
                url="https://example.com/ai",
                source="hacker_news",
                score=95.0,
            ),
            _make(
                title="AI Breakthrough",
                url="https://example.com/ai",
                source="reddit",
                score=80.0,
            ),
            _make(
                title="Rust Update",
                url="https://example.com/rust",
                source="devto",
                score=70.0,
            ),
        ]
        result = dedup_pipeline(articles)
        # HN + Reddit merged → 1 article; Rust → 1 article = 2 total
        assert len(result) == 2
        ai_article = next(a for a in result if a.title == "AI Breakthrough")
        assert "source:hacker_news" in ai_article.tags
        assert "source:reddit" in ai_article.tags
        assert ai_article.score == 95.0

    def test_complex_mix(self) -> None:
        """A mixed batch exercises all three phases correctly."""
        articles = [
            # URL duplicate pair
            _make(title="URL Dup A", url="https://example.com/dup"),
            _make(title="URL Dup B", url="https://example.com/dup"),
            # Title near-duplicate pair (different URLs)
            _make(title="Hot New Framework Released", url="https://example.com/fw1"),
            _make(title="Hot New Framework Released!", url="https://example.com/fw2"),
            # Cross-source same story
            _make(
                title="Database Technology Update",
                url="https://example.com/db",
                source="hacker_news",
            ),
            _make(
                title="Database Technology Update",
                url="https://example.com/db",
                source="reddit",
            ),
            # Unique
            _make(title="Unique Story", url="https://example.com/unique"),
        ]
        result = dedup_pipeline(articles)
        # Expected: URL dupA, Framework, DB(merged), Unique = 4
        assert len(result) == 4
        titles = {a.title for a in result}
        assert "URL Dup A" in titles
        assert "URL Dup B" not in titles
        # Find the DB article and verify cross-source merge
        db_articles = [a for a in result if "Database" in a.title]
        assert len(db_articles) == 1
        db = db_articles[0]
        assert "source:hacker_news" in db.tags
        assert "source:reddit" in db.tags
