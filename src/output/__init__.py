"""OhMyInfo — Output module."""

from src.output.markdown_generator import (
    generate_article_entry,
    generate_category_section,
    generate_daily_digest,
    generate_trend_summary,
)

__all__ = [
    "generate_daily_digest",
    "generate_category_section",
    "generate_article_entry",
    "generate_trend_summary",
]
