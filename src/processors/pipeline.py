"""Pipeline orchestrator — connect collectors + processors into one data flow.

collect → dedup → classify → score → summarize → output
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

import yaml

from src.collectors import Article, Collector
from src.collectors.arxiv import ArxivCollector
from src.collectors.devto import DevToCollector
from src.collectors.github_trending import GithubTrendingCollector
from src.collectors.hacker_news import HackerNewsCollector
from src.collectors.reddit import RedditCollector
from src.processors.classifier import RuleClassifier
from src.processors.dedup import dedup_pipeline
from src.processors.scorer import RuleScorer, ScoringConfig, calculate_score_with_interests
from src.processors.summarizer import Summarizer
from src.processors.topic_router import InterestRouter

logger = logging.getLogger(__name__)

_COLLECTOR_REGISTRY: dict[str, type[Collector]] = {
    "hacker_news": HackerNewsCollector,
    "github_trending": GithubTrendingCollector,
    "reddit": RedditCollector,
    "arxiv": ArxivCollector,
    "devto": DevToCollector,
}



@dataclass
class RunResult:
    """Summary of a single pipeline run — stats, scored articles, errors."""

    total_collected: int = 0
    after_dedup: int = 0
    categorized: dict[str, int] = field(default_factory=dict)
    scored: list[Article] = field(default_factory=list)
    summaries_generated: int = 0
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Pipeline orchestrator
# ---------------------------------------------------------------------------


class Pipeline:
    """Orchestrate the full OhMyInfo data pipeline (collect → dedup → classify → score → summarize → output)."""

    _CONSTRUCTOR_KWARGS: ClassVar[dict[str, set[str]]] = {
        "github_trending": {"since", "search_topic"},
        "reddit": {"subreddits", "min_upvotes", "top_count", "search_topics"},
        "arxiv": {"categories", "max_results"},
        "devto": {"page_size", "top_period"},
        "hacker_news": {"filter_keywords"},
    }

    def __init__(self, config_dir: str | Path = "config") -> None:
        self._config_dir = Path(config_dir)
        self._sources_config: dict[str, Any] = {}
        self._llm_config: dict[str, Any] = {}
        self._preferences: dict[str, Any] = {}
        self._articles: list[Article] = []
        self._last_markdown: str = ""
        self._load_all_configs()

    def _load_all_configs(self) -> None:
        self._sources_config = self._load_yaml("sources.yaml", {})
        self._llm_config = self._load_yaml("llm.yaml", {})
        self._preferences = self._load_yaml("preferences.yaml", {})

    def _load_yaml(self, filename: str, default: Any = None) -> Any:
        path = self._config_dir / filename
        if not path.exists():
            logger.info("Config file %s not found, skipping", path)
            return default if default is not None else {}
        try:
            with open(path) as f:
                return yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError) as exc:
            logger.warning("Failed to load %s: %s", path, exc)
            return default if default is not None else {}

    def _get_enabled_collectors(self) -> list[Collector]:
        sources = self._sources_config.get("sources", {})
        interests = self._get_interest_keywords()
        router = InterestRouter(interests) if interests else None
        strategy = router.get_strategy() if router else None

        collectors: list[Collector] = []

        for source_name, source_cfg in sources.items():
            if not source_cfg.get("enabled", True):
                logger.debug("Source %s is disabled, skipping", source_name)
                continue

            collector_cls = _COLLECTOR_REGISTRY.get(source_name)
            if collector_cls is None:
                logger.warning("Unknown source %s, skipping", source_name)
                continue

            # Build constructor kwargs from config keys that match
            allowed_keys = self._CONSTRUCTOR_KWARGS.get(source_name, set())
            kwargs = {
                k: v for k, v in source_cfg.items() if k in allowed_keys
            }

            # Inject topic-aware parameters if strategy available
            if strategy is not None:
                if source_name == "github_trending" and strategy.github_search_query:
                    kwargs["search_topic"] = strategy.github_search_query
                if source_name == "reddit" and strategy.reddit_search_queries:
                    kwargs["search_topics"] = strategy.reddit_search_queries
                if source_name == "hacker_news" and strategy.hn_filter_keywords:
                    kwargs["filter_keywords"] = strategy.hn_filter_keywords

            collectors.append(collector_cls(**kwargs))

        return collectors

    def _get_interest_keywords(self) -> list[str]:
        """Extract interest keywords from loaded preferences."""
        return (
            self._preferences
            .get("preferences", {})
            .get("interests", {})
            .get("include_keywords", [])
        )

    def _has_api_key(self) -> bool:
        providers = (
            self._llm_config.get("llm", {}).get("providers", {})
        )
        for provider_cfg in providers.values():
            env_var = provider_cfg.get("api_key_env", "")
            if env_var and os.environ.get(env_var):
                return True
        return False

    def _generate_markdown(self, articles: list[Article], categorized: dict[str, int]) -> str:
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        threshold = (
            self._preferences.get("preferences", {})
            .get("scoring", {})
            .get("threshold", 0)
        )

        lines: list[str] = [
            f"# OhMyInfo Daily Report — {now_str}",
            "",
            "## Summary",
            f"- Total articles collected: {len(articles)}",
            f"- Categories: {len(categorized)}",
            "",
        ]

        if categorized:
            lines.append("### Per-category breakdown")
            for cat, count in sorted(categorized.items(), key=lambda x: -x[1]):
                lines.append(f"- **{cat}**: {count}")
            lines.append("")

        if not articles:
            lines.append("*No articles were collected in this run.*")
            lines.append("")
            return "\n".join(lines)

        by_category: dict[str, list[Article]] = {}
        for article in articles:
            cat = article.category or "uncategorized"
            by_category.setdefault(cat, []).append(article)

        lines.append("---")
        lines.append("")

        for category, cat_articles in sorted(by_category.items()):
            if threshold > 0:
                cat_articles = [a for a in cat_articles if a.score >= threshold]
            if not cat_articles:
                continue

            lines.append(f"## {category}")
            lines.append("")

            for article in cat_articles:
                score_str = f"`{article.score:.1f}`" if article.score else ""
                source_str = f"*{article.source}*"
                lines.append(f"### [{article.title}]({article.url})")
                lines.append(f"{score_str} — {source_str}")
                if article.summary:
                    lines.append(f"> {article.summary}")
                if article.author:
                    lines.append(f"By {article.author}")
                lines.append("")

        return "\n".join(lines)

    async def run(self) -> RunResult:
        start = time.monotonic()
        errors: list[str] = []

        # Step 1: Collect
        collectors = self._get_enabled_collectors()
        all_articles: list[Article] = []

        async def _safe_fetch(collector: Collector) -> list[Article]:
            try:
                return await collector.fetch()
            except Exception as exc:
                msg = f"{collector.name}: {exc}"
                errors.append(msg)
                logger.warning(msg)
                return []

        if collectors:
            results = await asyncio.gather(*[_safe_fetch(c) for c in collectors])
            for batch in results:
                all_articles.extend(batch)

        total_collected = len(all_articles)

        # Step 2: Dedup
        deduped = dedup_pipeline(all_articles)
        after_dedup = len(deduped)
        self._articles = deduped

        # Step 3: Classify
        classifier = RuleClassifier()
        categorized: dict[str, int] = {}
        for article in deduped:
            cat = classifier.classify(article)
            article.category = cat
            categorized[cat] = categorized.get(cat, 0) + 1

        # Step 4: Score (with interest boost)
        scoring_cfg = self._preferences.get("preferences", {}).get("scoring", {})
        try:
            scorer_cfg = ScoringConfig(
                recency_weight=scoring_cfg.get("recency_weight", 0.30),
                source_weight=scoring_cfg.get("source_weight", 0.20),
                engagement_weight=scoring_cfg.get("engagement_weight", 0.25),
                novelty_weight=scoring_cfg.get("novelty_weight", 0.15),
                impact_weight=scoring_cfg.get("impact_weight", 0.10),
            )
        except ValueError as exc:
            errors.append(f"Invalid scoring config: {exc}")
            scorer_cfg = ScoringConfig()

        interests = self._get_interest_keywords()
        scorer = RuleScorer(config=scorer_cfg)
        for article in deduped:
            article.score = calculate_score_with_interests(
                article,
                interests=interests or None,
                config=scorer_cfg,
            )

        deduped.sort(key=lambda a: a.score, reverse=True)
        scored = list(deduped)

        # Step 5: Summarize
        summaries_generated = 0
        if self._has_api_key():
            try:
                llm = self._llm_config.get("llm", {})
                task = llm.get("tasks", {}).get("summarization", {})
                provider = task.get("provider", llm.get("default_provider", "openai"))
                summarizer = Summarizer(provider=provider)
                for article in deduped:
                    try:
                        updated = await summarizer.summarize_and_translate(article)
                        article.summary = updated.summary
                        summaries_generated += 1
                    except Exception as exc:
                        logger.warning("Summarization failed for %s: %s", article.title, exc)
            except Exception as exc:
                errors.append(f"Summarizer init failed: {exc}")

        # Step 6: Output
        self._last_markdown = self._generate_markdown(deduped, categorized)

        duration = time.monotonic() - start

        return RunResult(
            total_collected=total_collected,
            after_dedup=after_dedup,
            categorized=categorized,
            scored=scored,
            summaries_generated=summaries_generated,
            errors=errors,
            duration_seconds=round(duration, 3),
        )


async def run_pipeline(config_dir: str | Path = "config") -> RunResult:
    pipeline = Pipeline(config_dir=config_dir)
    return await pipeline.run()
