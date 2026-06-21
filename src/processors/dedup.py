"""
OhMyInfo — Article deduplication processor (文章去重处理器)

Provides a pipeline for deduplicating a list of Articles:

    1. dedup_by_url   — exact URL match (after normalization)
    2. dedup_by_title — fuzzy title similarity via difflib.SequenceMatcher
    3. merge_duplicates — cross-source merge (combines metadata of same story)

Usage:

    from src.processors.dedup import dedup_pipeline

    cleaned = dedup_pipeline(articles)
"""

from __future__ import annotations

import string
from difflib import SequenceMatcher

from src.collectors import Article

_SOURCE_TAG_PREFIX = "source:"
_TITLE_SIMILARITY_THRESHOLD = 0.85


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normalize_url(url: str) -> str:
    """Strip trailing slash and fragment for URL comparison."""
    if "#" in url:
        url = url[: url.index("#")]
    url = url.rstrip("/")
    return url


def _normalize_url_deep(url: str) -> str:
    """Aggressive URL normalization — strips query params too."""
    if "#" in url:
        url = url[: url.index("#")]
    if "?" in url:
        url = url[: url.index("?")]
    url = url.rstrip("/")
    return url


def _normalize_title(title: str) -> str:
    """Lowercase, remove punctuation, collapse whitespace."""
    title = title.lower()
    title = title.translate(str.maketrans("", "", string.punctuation))
    title = " ".join(title.split())
    return title


def _title_similarity(a: str, b: str) -> float:
    """SequenceMatcher ratio between two normalized titles."""
    return SequenceMatcher(None, _normalize_title(a), _normalize_title(b)).ratio()


def _add_source_tag(article: Article) -> Article:
    """Return a new Article with its own source tag appended (if missing)."""
    tag = f"{_SOURCE_TAG_PREFIX}{article.source}"
    if tag not in article.tags:
        return article.model_copy(update={"tags": article.tags + [tag]})
    return article


def _merge_two(a: Article, b: Article) -> Article:
    """Merge two duplicate articles into one, combining metadata.

    Preserves:
      - longer title / url / summary / content
      - highest score
      - earliest published_at
      - union of source tags
    """
    sources = set()
    for tag in a.tags + b.tags:
        if tag.startswith(_SOURCE_TAG_PREFIX):
            sources.add(tag[len(_SOURCE_TAG_PREFIX) :])
    sources.add(a.source)
    sources.add(b.source)

    combined_tags = sorted(f"{_SOURCE_TAG_PREFIX}{s}" for s in sources)

    return Article(
        title=b.title if len(b.title) > len(a.title) else a.title,
        url=b.url if len(b.url) > len(a.url) else a.url,
        source=",".join(sorted(sources)),
        published_at=min(a.published_at, b.published_at),
        summary=b.summary if len(b.summary) > len(a.summary) else a.summary,
        content=b.content if len(b.content) > len(a.content) else a.content,
        score=max(a.score, b.score),
        category=a.category or b.category,
        tags=combined_tags,
        author=a.author or b.author,
    )


def _is_same_story(a: Article, b: Article) -> bool:
    """Check whether two articles represent the same story.

    Matching strategies (OR):
      1. Normalized URL equality (with query-param stripping)
      2. Fuzzy title similarity >= threshold
    """
    if _normalize_url_deep(a.url) == _normalize_url_deep(b.url):
        return True
    return _title_similarity(a.title, b.title) >= _TITLE_SIMILARITY_THRESHOLD


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def dedup_by_url(articles: list[Article]) -> list[Article]:
    """Deduplicate by exact URL match (after basic normalization: strip trailing slash & fragment).

    Keeps the *first* occurrence.  Each kept article gets its ``source``
    recorded as a ``source:<name>`` tag.  If the same URL appears from a
    **different** source, that source is added to the kept article's tags
    (enabling later cross-source discovery in the pipeline).
    """
    seen: dict[str, int] = {}  # normalized URL → index in result
    result: list[Article] = []
    for article in articles:
        norm = _normalize_url(article.url)
        if norm not in seen:
            seen[norm] = len(result)
            result.append(_add_source_tag(article))
        else:
            # Same URL from a different source → merge source tag into kept article
            idx = seen[norm]
            existing = result[idx]
            new_tag = f"{_SOURCE_TAG_PREFIX}{article.source}"
            if existing.source != article.source and new_tag not in existing.tags:
                result[idx] = existing.model_copy(
                    update={"tags": existing.tags + [new_tag]},
                )
    return result


def dedup_by_title(
    articles: list[Article],
    threshold: float = _TITLE_SIMILARITY_THRESHOLD,
) -> list[Article]:
    """Deduplicate by fuzzy title similarity (``difflib.SequenceMatcher.ratio``).

    Keeps the *first* occurrence.  Articles whose normalised titles have a
    similarity ratio >= *threshold* are considered duplicates.
    """
    result: list[Article] = []
    for article in articles:
        is_dup = any(
            _title_similarity(article.title, existing.title) >= threshold
            for existing in result
        )
        if not is_dup:
            result.append(_add_source_tag(article))
    return result


def merge_duplicates(articles: list[Article]) -> list[Article]:
    """Cross-source merge — merge articles about the **same story** from **different sources**.

    Detection uses the same heuristics as ``dedup_by_url`` / ``dedup_by_title``
    but **merges** the metadata (source tags, score, content) instead of
    discarding the duplicate.
    """
    result: list[Article] = []
    for article in articles:
        tagged = _add_source_tag(article)
        merged = False
        for i, existing in enumerate(result):
            if _is_same_story(existing, tagged):
                result[i] = _merge_two(existing, tagged)
                merged = True
                break
        if not merged:
            result.append(tagged)
    return result


def dedup_pipeline(articles: list[Article]) -> list[Article]:
    """Run the full dedup pipeline in sequence:

    ``URL dedup → Title dedup → Cross-source merge``
    """
    result = dedup_by_url(articles)
    result = dedup_by_title(result)
    result = merge_duplicates(result)
    return result
