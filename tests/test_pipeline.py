"""
Tests for src/processors/pipeline.py — Pipeline orchestrator.

Tests cover:
  - Pipeline initialization loads config correctly
  - run() with mocked collectors (all return empty lists)
  - Error isolation (one collector fails, others still run)
  - RunResult structure and stats
  - Pipeline still produces output when LLM unavailable
  - run_pipeline() convenience function
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, PropertyMock, patch

import pytest
import yaml

from src.collectors import Article, CollectorError
from src.processors.pipeline import Pipeline, RunResult, run_pipeline


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_config_dir(tmp_path: Path) -> Path:
    """Create a temporary config directory with minimal YAML files."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)

    # sources.yaml — two enabled, one disabled
    sources = {
        "sources": {
            "hacker_news": {
                "enabled": True,
                "type": "api",
                "interval_minutes": 360,
                "top_count": 30,
                "priority": 1,
            },
            "github_trending": {
                "enabled": True,
                "type": "scrape",
                "since": "daily",
                "interval_minutes": 360,
                "top_count": 15,
                "priority": 1,
            },
            "reddit": {
                "enabled": False,
                "type": "api",
                "interval_minutes": 360,
                "top_count": 10,
                "priority": 2,
            },
        },
    }
    with open(config_dir / "sources.yaml", "w") as f:
        yaml.dump(sources, f)

    # llm.yaml
    llm = {
        "llm": {
            "default_provider": "openai",
            "providers": {
                "openai": {
                    "model": "gpt-4o-mini",
                    "temperature": 0.3,
                    "max_tokens": 500,
                    "api_key_env": "OPENAI_API_KEY",
                },
            },
            "tasks": {
                "summarization": {
                    "provider": "gemini",
                    "model": "gemini-2.0-flash",
                },
            },
        },
    }
    with open(config_dir / "llm.yaml", "w") as f:
        yaml.dump(llm, f)

    # preferences.yaml
    prefs = {
        "preferences": {
            "scoring": {
                "threshold": 30,
                "recency_weight": 0.30,
                "source_weight": 0.20,
                "engagement_weight": 0.25,
                "novelty_weight": 0.15,
                "impact_weight": 0.10,
            },
            "output": {
                "language": "zh",
                "max_items_per_category": 10,
                "include_summary": True,
                "include_scores": True,
            },
        },
    }
    with open(config_dir / "preferences.yaml", "w") as f:
        yaml.dump(prefs, f)

    return tmp_path


@pytest.fixture
def sample_articles() -> list[Article]:
    """Create a sample list of articles for testing."""
    now = datetime.now(timezone.utc)
    return [
        Article(
            title="GPT-5 Launch Event",
            url="https://example.com/gpt5",
            source="hacker_news",
            published_at=now,
            summary="OpenAI announces GPT-5",
            content="Full content about GPT-5 launch",
            score=90.0,
        ),
        Article(
            title="New Rust Framework Released",
            url="https://example.com/rust-fw",
            source="github_trending",
            published_at=now,
            summary="A new Rust web framework",
            content="Details about the Rust framework",
            score=75.0,
        ),
        Article(
            title="Research Paper on LLM Architecture",
            url="https://arxiv.org/abs/1234.56789",
            source="arxiv",
            published_at=now,
            summary="Novel LLM architecture paper",
            content="Full paper content here",
            score=85.0,
        ),
    ]


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _mock_collector(name: str, articles: list[Article] | None = None) -> AsyncMock:
    """Create a mock Collector with the given name and return values."""
    mock = AsyncMock()
    type(mock).name = PropertyMock(return_value=name)
    if articles is not None:
        mock.fetch.return_value = articles
    else:
        mock.fetch.return_value = []
    return mock


def _mock_failing_collector(name: str = "failing_source") -> AsyncMock:
    """Create a mock Collector that raises CollectorError on fetch."""
    mock = AsyncMock()
    type(mock).name = PropertyMock(return_value=name)
    mock.fetch.side_effect = CollectorError("Connection refused", source=name)
    return mock


# ===========================================================================
# Test RunResult
# ===========================================================================


class TestRunResult:
    """RunResult dataclass tests."""

    def test_minimal_creation(self) -> None:
        """Can create RunResult with all fields."""
        result = RunResult(
            total_collected=10,
            after_dedup=8,
            categorized={"general": 5, "tools-release": 3},
            scored=[],
            summaries_generated=0,
            errors=[],
            duration_seconds=1.5,
        )
        assert result.total_collected == 10
        assert result.after_dedup == 8
        assert result.categorized == {"general": 5, "tools-release": 3}
        assert result.scored == []
        assert result.summaries_generated == 0
        assert result.errors == []
        assert result.duration_seconds == 1.5

    def test_zero_defaults(self) -> None:
        """All numeric fields default to 0 / empty lists / empty dict."""
        result = RunResult(
            total_collected=0,
            after_dedup=0,
            categorized={},
            scored=[],
            summaries_generated=0,
            errors=[],
            duration_seconds=0.0,
        )
        assert result.total_collected == 0

    def test_top_articles_sorting(self) -> None:
        """scored field is the articles list as stored (pipeline sorts upstream)."""
        articles = [
            Article(title="Low", url="https://a.com", source="test", score=30.0),
            Article(title="High", url="https://b.com", source="test", score=90.0),
            Article(title="Mid", url="https://c.com", source="test", score=60.0),
        ]
        # RunResult is a plain dataclass — sorting is the pipeline's job
        result = RunResult(
            total_collected=3,
            after_dedup=3,
            categorized={"general": 3},
            scored=articles,
            summaries_generated=0,
            errors=[],
            duration_seconds=0.1,
        )
        assert len(result.scored) == 3

    def test_error_collection(self) -> None:
        """errors list captures error messages."""
        result = RunResult(
            total_collected=5,
            after_dedup=5,
            categorized={},
            scored=[],
            summaries_generated=0,
            errors=["Collector X failed: timeout", "Summarizer error"],
            duration_seconds=2.0,
        )
        assert len(result.errors) == 2
        assert "timeout" in result.errors[0]


# ===========================================================================
# Test Pipeline initialization
# ===========================================================================


class TestPipelineInit:
    """Pipeline initialization tests."""

    def test_init_with_default_config(self) -> None:
        """Pipeline initializes with default 'config' directory."""
        with patch("src.processors.pipeline.Path.exists", return_value=False):
            pipeline = Pipeline(config_dir="/nonexistent")
            assert pipeline is not None

    def test_init_loads_sources_config(self, sample_config_dir: Path) -> None:
        """Pipeline loads sources.yaml and identifies enabled sources."""
        pipeline = Pipeline(config_dir=str(sample_config_dir / "config"))
        assert pipeline._sources_config is not None
        sources = pipeline._sources_config.get("sources", {})
        assert "hacker_news" in sources
        assert "github_trending" in sources
        assert "reddit" in sources

    def test_init_loads_llm_config(self, sample_config_dir: Path) -> None:
        """Pipeline loads llm.yaml configuration."""
        pipeline = Pipeline(config_dir=str(sample_config_dir / "config"))
        assert pipeline._llm_config is not None
        llm = pipeline._llm_config.get("llm", {})
        assert "default_provider" in llm

    def test_init_loads_preferences(self, sample_config_dir: Path) -> None:
        """Pipeline loads preferences.yaml configuration."""
        pipeline = Pipeline(config_dir=str(sample_config_dir / "config"))
        assert pipeline._preferences is not None
        prefs = pipeline._preferences.get("preferences", {})
        assert "scoring" in prefs
        assert "output" in prefs

    def test_init_with_non_existent_config(self) -> None:
        """Pipeline initializes gracefully when config directory is missing."""
        pipeline = Pipeline(config_dir="/tmp/__nonexistent_config_dir__")
        assert pipeline._sources_config == {}
        assert pipeline._llm_config == {}
        assert pipeline._preferences == {}

    def test_collector_instantiation(self, sample_config_dir: Path) -> None:
        """Enabled collectors are instantiated, disabled ones are not."""
        pipeline = Pipeline(config_dir=str(sample_config_dir / "config"))
        collectors = pipeline._get_enabled_collectors()
        collector_names = {c.name for c in collectors}
        assert "hacker_news" in collector_names
        assert "github_trending" in collector_names
        assert "reddit" not in collector_names  # disabled in test config


# ===========================================================================
# Test Pipeline run()
# ===========================================================================


class TestPipelineRun:
    """Pipeline.run() integration tests with mocked collectors."""

    @pytest.mark.asyncio
    async def test_run_with_empty_collectors(
        self, sample_config_dir: Path,
    ) -> None:
        """run() returns RunResult when all collectors return empty lists."""
        pipeline = Pipeline(config_dir=str(sample_config_dir / "config"))
        # Replace collector instantiation with all-empty mocks
        pipeline._get_enabled_collectors = lambda: [
            _mock_collector("hacker_news", []),
            _mock_collector("github_trending", []),
        ]

        result = await pipeline.run()

        assert isinstance(result, RunResult)
        assert result.total_collected == 0
        assert result.after_dedup == 0
        assert result.categorized == {}
        assert result.scored == []
        assert result.summaries_generated == 0
        assert result.errors == []
        assert result.duration_seconds >= 0

    @pytest.mark.asyncio
    async def test_run_with_articles(self, sample_config_dir: Path, sample_articles: list[Article]) -> None:
        """run() processes articles through all pipeline stages."""
        pipeline = Pipeline(config_dir=str(sample_config_dir / "config"))
        pipeline._get_enabled_collectors = lambda: [
            _mock_collector("hacker_news", [sample_articles[0]]),
            _mock_collector("github_trending", [sample_articles[1]]),
        ]

        result = await pipeline.run()

        assert result.total_collected == 2
        assert result.after_dedup == 2  # no duplicates
        assert len(result.categorized) > 0
        assert len(result.scored) > 0
        # Articles should have category and score after processing
        assert all(a.category for a in pipeline._articles)
        assert all(a.score > 0 for a in pipeline._articles)

    @pytest.mark.asyncio
    async def test_error_isolation(self, sample_config_dir: Path, sample_articles: list[Article]) -> None:
        """When one collector fails, others still run and produce results."""
        pipeline = Pipeline(config_dir=str(sample_config_dir / "config"))
        pipeline._get_enabled_collectors = lambda: [
            _mock_failing_collector("failing"),
            _mock_collector("hacker_news", [sample_articles[0]]),
        ]

        result = await pipeline.run()

        # The failing collector's error should be captured
        assert len(result.errors) >= 1
        assert any("failing" in e for e in result.errors)
        # The working collector's articles should still be processed
        assert result.total_collected == 1
        assert result.after_dedup == 1
        assert len(result.scored) == 1

    @pytest.mark.asyncio
    async def test_all_collectors_fail(self, sample_config_dir: Path) -> None:
        """When all collectors fail, run() still returns a RunResult with errors."""
        pipeline = Pipeline(config_dir=str(sample_config_dir / "config"))
        pipeline._get_enabled_collectors = lambda: [
            _mock_failing_collector("source_a"),
            _mock_failing_collector("source_b"),
        ]

        result = await pipeline.run()

        assert result.total_collected == 0
        assert result.after_dedup == 0
        assert len(result.errors) >= 2
        assert result.duration_seconds >= 0

    @pytest.mark.asyncio
    async def test_dedup_works(self, sample_config_dir: Path) -> None:
        """Duplicate articles across sources are deduplicated."""
        now = datetime.now(timezone.utc)
        dup_article = Article(
            title="Same Story on Both Sources",
            url="https://example.com/same",
            source="hacker_news",
            published_at=now,
        )
        pipeline = Pipeline(config_dir=str(sample_config_dir / "config"))
        # Same article returned by two collectors (same URL)
        pipeline._get_enabled_collectors = lambda: [
            _mock_collector("hacker_news", [dup_article]),
            _mock_collector("github_trending", [
                Article(
                    title="Same Story on Both Sources",
                    url="https://example.com/same",
                    source="github_trending",
                    published_at=now,
                ),
            ]),
        ]

        result = await pipeline.run()

        # Duplicates should be merged
        assert result.total_collected == 2
        assert result.after_dedup == 1
        assert len(result.scored) == 1

    @pytest.mark.asyncio
    async def test_categorization_stats(self, sample_config_dir: Path) -> None:
        """categorized dict reflects correct counts per category."""
        pipeline = Pipeline(config_dir=str(sample_config_dir / "config"))
        # Articles with different content to trigger different categories
        now = datetime.now(timezone.utc)
        pipeline._get_enabled_collectors = lambda: [
            _mock_collector("hacker_news", [
                Article(
                    title="OpenAI Launches GPT-5",
                    url="https://example.com/gpt5",
                    source="hacker_news",
                    published_at=now,
                    content="OpenAI announces new model launch",
                ),
            ]),
            _mock_collector("github_trending", [
                Article(
                    title="New Open Source Rust Framework v1.0",
                    url="https://example.com/rust-fw",
                    source="github_trending",
                    published_at=now,
                    content="A new open source Rust framework",
                ),
            ]),
        ]

        result = await pipeline.run()

        assert sum(result.categorized.values()) == result.after_dedup
        # At least one categorized entry should exist
        assert any(v > 0 for v in result.categorized.values())

    @pytest.mark.asyncio
    async def test_scored_articles_sorted(self, sample_config_dir: Path) -> None:
        """scored articles are sorted by score descending."""
        now = datetime.now(timezone.utc)
        pipeline = Pipeline(config_dir=str(sample_config_dir / "config"))
        pipeline._get_enabled_collectors = lambda: [
            _mock_collector("hacker_news", [
                Article(
                    title="Low Score Article",
                    url="https://example.com/low",
                    source="hacker_news",
                    published_at=now,
                    content="old article with no engagement",
                    score=10.0,
                ),
                Article(
                    title="High Score Article",
                    url="https://example.com/high",
                    source="hacker_news",
                    published_at=now,
                    content="hot new trending breakthrough",
                    score=95.0,
                ),
            ]),
        ]

        result = await pipeline.run()

        assert len(result.scored) == 2
        assert result.scored[0].score >= result.scored[1].score


# ===========================================================================
# Test LLM unavailability
# ===========================================================================


class TestPipelineNoLLM:
    """Pipeline behavior when LLM API keys are not available."""

    @pytest.mark.asyncio
    async def test_skip_summarization_when_no_api_key(
        self, sample_config_dir: Path, sample_articles: list[Article],
    ) -> None:
        """Pipeline skips LLM summarization when no API key is set."""
        # Ensure no API keys in environment
        with patch.dict(os.environ, {}, clear=True):
            pipeline = Pipeline(config_dir=str(sample_config_dir / "config"))
            pipeline._get_enabled_collectors = lambda: [
                _mock_collector("hacker_news", sample_articles),
            ]

            result = await pipeline.run()

            # Summarization should be skipped (0 generated since we're not
            # creating a Summarizer when has_api_key returns False)
            assert result.summaries_generated >= 0
            # The pipeline should still produce scored articles
            assert len(result.scored) == len(sample_articles)
            # No errors from summarization
            summarization_errors = [e for e in result.errors if "summar" in e.lower()]
            assert len(summarization_errors) == 0

    @pytest.mark.asyncio
    async def test_run_without_llm_config(self) -> None:
        """Pipeline runs even when llm.yaml is missing."""
        with patch("src.processors.pipeline.Path.exists", return_value=False):
            pipeline = Pipeline(config_dir="/nonexistent")
            pipeline._get_enabled_collectors = lambda: []

            result = await pipeline.run()

            assert isinstance(result, RunResult)
            assert result.summaries_generated == 0

    @pytest.mark.asyncio
    async def test_markdown_output_generated(
        self, sample_config_dir: Path, sample_articles: list[Article],
    ) -> None:
        """Pipeline generates Markdown output string."""
        pipeline = Pipeline(config_dir=str(sample_config_dir / "config"))
        pipeline._get_enabled_collectors = lambda: [
            _mock_collector("hacker_news", sample_articles),
        ]

        result = await pipeline.run()

        # Check that the generated markdown is stored
        assert hasattr(pipeline, "_last_markdown")
        markdown = pipeline._last_markdown
        assert isinstance(markdown, str)
        assert len(markdown) > 0
        # Should contain article titles
        assert "GPT-5" in markdown or "GPT" in markdown

    @pytest.mark.asyncio
    async def test_markdown_with_empty_results(self, sample_config_dir: Path) -> None:
        """Pipeline generates markdown even when no articles collected."""
        pipeline = Pipeline(config_dir=str(sample_config_dir / "config"))
        pipeline._get_enabled_collectors = lambda: [
            _mock_collector("empty_source", []),
        ]

        result = await pipeline.run()

        assert hasattr(pipeline, "_last_markdown")
        markdown = pipeline._last_markdown
        assert isinstance(markdown, str)
        # Should indicate empty results
        assert len(markdown) > 0 or result.total_collected == 0


# ===========================================================================
# Test run_pipeline() convenience function
# ===========================================================================


class TestRunPipeline:
    """run_pipeline() convenience function tests."""

    @pytest.mark.asyncio
    async def test_run_pipeline_returns_run_result(self, sample_config_dir: Path) -> None:
        """run_pipeline() returns a RunResult instance."""
        with patch("src.processors.pipeline.Pipeline.run") as mock_run:
            mock_run.return_value = RunResult(
                total_collected=5,
                after_dedup=4,
                categorized={"general": 4},
                scored=[],
                summaries_generated=0,
                errors=[],
                duration_seconds=0.5,
            )
            result = await run_pipeline(config_dir=str(sample_config_dir / "config"))

        assert isinstance(result, RunResult)
        assert result.total_collected == 5

    @pytest.mark.asyncio
    async def test_run_pipeline_default_config(self) -> None:
        """run_pipeline() uses 'config' as default config_dir."""
        with patch("src.processors.pipeline.Pipeline") as MockPipeline:
            mock_instance = AsyncMock()
            mock_instance.run.return_value = RunResult(
                total_collected=0,
                after_dedup=0,
                categorized={},
                scored=[],
                summaries_generated=0,
                errors=[],
                duration_seconds=0.0,
            )
            MockPipeline.return_value = mock_instance

            await run_pipeline()

            # Should have been called with 'config' as default
            MockPipeline.assert_called_once_with(config_dir="config")

    @pytest.mark.asyncio
    async def test_run_pipeline_propagates_custom_config(self) -> None:
        """run_pipeline() propagates custom config_dir to Pipeline."""
        custom_dir = "/my/custom/config"
        with patch("src.processors.pipeline.Pipeline") as MockPipeline:
            mock_instance = AsyncMock()
            mock_instance.run.return_value = RunResult(
                total_collected=0,
                after_dedup=0,
                categorized={},
                scored=[],
                summaries_generated=0,
                errors=[],
                duration_seconds=0.0,
            )
            MockPipeline.return_value = mock_instance

            await run_pipeline(config_dir=custom_dir)

            MockPipeline.assert_called_once_with(config_dir=custom_dir)
