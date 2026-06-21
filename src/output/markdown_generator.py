"""
OhMyInfo — Markdown 日报生成器（Daily Digest Markdown Generator）

将 Article 列表渲染为结构化 Markdown 日报，按分类组织、评分降序排列，
包含热点精选、趋势总结、来源标签等，适合部署到 GitHub Pages。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Final

from src.collectors import Article

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

CATEGORY_ICONS: Final[dict[str, str]] = {
    "major-release": "🚀",
    "tools-release": "📡",
    "research-frontier": "📚",
    "industry-business": "📰",
    "policy-regulation": "🏛️",
}

CATEGORY_NAMES: Final[dict[str, str]] = {
    "major-release": "重大发布",
    "tools-release": "工具发布",
    "research-frontier": "研究前沿",
    "industry-business": "行业动态",
    "policy-regulation": "政策监管",
}

MAX_SUMMARY_LENGTH: Final[int] = 150

HOT_TOP_COUNT: Final[int] = 5

# 分类展示顺序
_CATEGORY_ORDER: Final[list[str]] = [
    "major-release",
    "tools-release",
    "research-frontier",
    "industry-business",
    "policy-regulation",
]

# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------


def generate_daily_digest(articles: list[Article], date: date | None = None) -> str:
    """Generate daily digest markdown from a list of articles.

    Args:
        articles: list of articles to include in the digest.
        date: date for the digest header (defaults to today).

    Returns:
        Complete markdown string ready to write to a file.
    """
    digest_date = date or datetime.now().astimezone().date()
    sections: list[str] = []

    # 标题 + 趋势洞察
    sections.append(f"# 🔭 OhMyInfo 技术日报 — {digest_date.isoformat()}\n")
    sections.append(generate_trend_summary(articles))
    sections.append("---\n")

    # 今日热点（跨分类 Top N，不出现在空摘要中）
    sorted_all = sorted(articles, key=lambda a: a.score, reverse=True)
    hot_articles = sorted_all[:HOT_TOP_COUNT]
    if hot_articles:
        sections.append("## 🔥 今日热点\n")
        for rank, article in enumerate(hot_articles, start=1):
            sections.append(generate_article_entry(article, rank=rank))
        sections.append("")

    # 按分类组织
    categorized = _group_articles_by_category(articles)
    for category in _CATEGORY_ORDER:
        category_articles = categorized.get(category)
        if not category_articles:
            continue
        sections.append(generate_category_section(category, category_articles))

    # 空状态
    if not articles:
        sections.append("> 今日暂无收录内容，看看明天会有什么吧 ✨\n")

    result = "\n".join(sections).rstrip("\n") + "\n"
    return result


def generate_category_section(category: str, articles: list[Article]) -> str:
    """Generate markdown section for a single category.

    Args:
        category: category key (e.g. "major-release").
        articles: articles belonging to this category.

    Returns:
        Markdown section string.
    """
    icon = CATEGORY_ICONS.get(category, "📌")
    name = CATEGORY_NAMES.get(category, category)
    lines: list[str] = [f"## {icon} {name}\n"]

    sorted_articles = sorted(articles, key=lambda a: a.score, reverse=True)
    for rank, article in enumerate(sorted_articles, start=1):
        lines.append(generate_article_entry(article, rank=rank))
    lines.append("")
    return "\n".join(lines)


def generate_article_entry(article: Article, rank: int = 1) -> str:
    """Generate markdown entry for a single article.

    Args:
        article: article to format.
        rank: display rank number (1-based).

    Returns:
        Multi-line markdown entry string.
    """
    score_display = f"{article.score:.1f}"
    summary = _truncate_summary(article.summary)
    tags_display = _format_tags(article.tags)
    source_display = _format_source(article.source)

    parts: list[str] = [
        f"{rank}. ⭐ **{score_display}** [{article.title}]({article.url})",
    ]

    if summary:
        parts.append(f"   — {summary}")

    meta_parts: list[str] = []
    if tags_display:
        meta_parts.append(f"`标签: {tags_display}`")
    if source_display:
        meta_parts.append(f"`来源: {source_display}`")

    if meta_parts:
        parts.append(f"   {' | '.join(meta_parts)}")

    return "\n".join(parts)


def generate_trend_summary(articles: list[Article]) -> str:
    """Generate a rule-based trend summary at the top of the digest.

    Produces a human-readable snapshot of the day's content distribution,
    including article counts per category, score ranges, and categories covered.

    Args:
        articles: list of articles to analyze.

    Returns:
        Markdown blockquote with the summary text.
    """
    if not articles:
        return "> 📭 今日暂无内容更新，静待明日。\n"

    total = len(articles)
    categorized = _group_articles_by_category(articles)
    category_counts: dict[str, int] = {}
    for cat in _CATEGORY_ORDER:
        cat_articles = categorized.get(cat)
        if cat_articles:
            category_counts[cat] = len(cat_articles)

    # 最多文章的类别
    if category_counts:
        top_category = max(category_counts, key=category_counts.get)
        top_count = category_counts[top_category]
        top_category_name = CATEGORY_NAMES.get(top_category, top_category)
    else:
        top_category_name = "未分类"
        top_count = 0

    # 评分统计
    scores = [a.score for a in articles]
    avg_score = sum(scores) / len(scores)
    top_article = max(articles, key=lambda a: a.score)

    # 涵盖领域
    covered_names = [
        CATEGORY_NAMES.get(c, c) for c in _CATEGORY_ORDER if c in categorized
    ]
    covered_str = f"涵盖 {len(covered_names)} 个领域（{'、'.join(covered_names)}）。" if covered_names else "暂无分类信息。"

    summary_parts: list[str] = [
        f"今日共收录 **{total}** 篇技术动态，{covered_str}",
        f"最高评分文章 **{top_article.score:.1f}** 分"
        f" —「{top_article.title}」。",
        f"其中 **{top_category_name}** 最受关注（{top_count} 篇），"
        f"平均评分 **{avg_score:.1f}** 分。",
    ]

    return "> " + "\n> ".join(summary_parts) + "\n"


# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------


def _group_articles_by_category(
    articles: list[Article],
) -> dict[str, list[Article]]:
    """Group articles by their category field."""
    grouped: dict[str, list[Article]] = {}
    for article in articles:
        cat = article.category or "uncategorized"
        if cat not in grouped:
            grouped[cat] = []
        grouped[cat].append(article)
    return grouped


def _truncate_summary(summary: str) -> str:
    """Truncate summary to MAX_SUMMARY_LENGTH characters with ellipsis."""
    if not summary:
        return ""
    if len(summary) <= MAX_SUMMARY_LENGTH:
        return summary
    truncated = summary[:MAX_SUMMARY_LENGTH].rstrip()
    return f"{truncated}…"


def _format_tags(tags: list[str]) -> str:
    """Format tags list as a comma-separated string."""
    if not tags:
        return ""
    return ", ".join(tags)


def _format_source(source: str) -> str:
    """Format source for display."""
    return source if source else ""
