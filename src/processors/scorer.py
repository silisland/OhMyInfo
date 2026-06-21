"""
OhMyInfo — Article scoring module (Article Scorer)

Multi-dimensional scoring: rules-based + optional LLM enhancement.
Scores articles 0-100 based on recency, source authority, engagement,
novelty, and impact. The final score is a weighted combination of
all dimensions.

Usage::

    # Rule-based scoring (no external dependencies)
    score = calculate_score(article)

    # With LLM enhancement
    def my_llm(prompt: str) -> str:
        return "85"

    score = calculate_score(article, strategy="llm", llm_provider=my_llm)

    # With custom weights and novelty cache
    score = calculate_score(article, recent_titles={"seen title", "old title"})
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from src.collectors import Article

# ---------------------------------------------------------------------------
# Dimension maximums (raw point ceilings)
# ---------------------------------------------------------------------------

RECENCY_MAX: float = 30.0
SOURCE_MAX: float = 20.0
ENGAGEMENT_MAX: float = 25.0
NOVELTY_MAX: float = 15.0
IMPACT_MAX: float = 10.0

# ---------------------------------------------------------------------------
# Source authority scores
# ---------------------------------------------------------------------------

SOURCE_SCORES: dict[str, float] = {
    "hacker_news": 18.0,
    "github_trending": 16.0,
    "reddit": 10.0,
    "arxiv": 14.0,
    "devto": 12.0,
}

DEFAULT_SOURCE_SCORE: float = 8.0

# ---------------------------------------------------------------------------
# Impact / business keywords
# ---------------------------------------------------------------------------

IMPACT_KEYWORDS: list[str] = [
    "funding",
    "ipo",
    "acquisition",
    "billion",
    "regulation",
    "breakthrough",
]

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class ScoringConfig:
    """Configuration for article scoring weights.

    Each weight controls the relative importance of a scoring dimension.
    All weights must sum to **1.0**.

    Defaults (matching the project's recommended YAML config)::

        recency_weight:    0.30
        source_weight:     0.20
        engagement_weight: 0.25
        novelty_weight:    0.15
        impact_weight:     0.10
    """

    recency_weight: float = 0.30
    source_weight: float = 0.20
    engagement_weight: float = 0.25
    novelty_weight: float = 0.15
    impact_weight: float = 0.10

    def __post_init__(self) -> None:
        total = (
            self.recency_weight
            + self.source_weight
            + self.engagement_weight
            + self.novelty_weight
            + self.impact_weight
        )
        if abs(total - 1.0) > 1e-6:
            msg = f"Weights must sum to 1.0 (got {total})"
            raise ValueError(msg)


# ---------------------------------------------------------------------------
# Rule-based scorer
# ---------------------------------------------------------------------------


class RuleScorer:
    """Five-dimensional rule-based article scorer.

    Each dimension is scored independently using deterministic rules,
    normalised to a 0.0-1.0 scale, then blended via ``ScoringConfig``
    weights.  The final score is scaled to 0-100.
    """

    def __init__(self, config: ScoringConfig | None = None) -> None:
        self._config = config or ScoringConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score(
        self,
        article: Article,
        recent_titles: set[str] | None = None,
    ) -> float:
        """Compute a 0-100 rule-based score for *article*.

        Args:
            article:      The article to score.
            recent_titles: Optional set of recently-seen titles used for
                           novelty detection.

        Returns:
            A float between 0.0 and 100.0.
        """
        recency_raw = self._recency_score(article)
        source_raw = self._source_score(article)
        engagement_raw = self._engagement_score(article)
        novelty_raw = self._novelty_score(article, recent_titles)
        impact_raw = self._impact_score(article)

        # Normalise each dimension to 0.0-1.0
        recency_norm = recency_raw / RECENCY_MAX
        source_norm = source_raw / SOURCE_MAX
        engagement_norm = engagement_raw / ENGAGEMENT_MAX
        novelty_norm = novelty_raw / NOVELTY_MAX
        impact_norm = impact_raw / IMPACT_MAX

        weighted = (
            recency_norm * self._config.recency_weight
            + source_norm * self._config.source_weight
            + engagement_norm * self._config.engagement_weight
            + novelty_norm * self._config.novelty_weight
            + impact_norm * self._config.impact_weight
        )

        return round(weighted * 100.0, 2)

    # ------------------------------------------------------------------
    # Dimension scorers
    # ------------------------------------------------------------------

    @staticmethod
    def _recency_score(article: Article) -> float:
        """Score based on how recently the article was published (max 30)."""
        age = datetime.now(timezone.utc) - article.published_at
        hours = age.total_seconds() / 3600.0

        if hours < 6:
            return 30.0
        if hours < 24:
            return 22.0
        if hours < 72:
            return 8.0
        return 2.0

    @staticmethod
    def _source_score(article: Article) -> float:
        """Score based on source authority (max 20)."""
        return SOURCE_SCORES.get(article.source.lower(), DEFAULT_SOURCE_SCORE)

    @staticmethod
    def _engagement_score(article: Article) -> float:
        """Score based on original engagement signals (max 25).

        Uses ``article.score`` which represents the source's native
        engagement metric (HN points, Reddit upvotes, etc.).
        """
        return min(article.score / 100.0, 1.0) * ENGAGEMENT_MAX

    @staticmethod
    def _novelty_score(
        article: Article,
        recent_titles: set[str] | None,
    ) -> float:
        """Score based on title uniqueness vs. recently-seen titles (max 15)."""
        if recent_titles is None:
            return NOVELTY_MAX  # No context → assume unique

        lower_title = article.title.lower().strip()

        if not lower_title:
            return 0.0

        lower_seen = {t.lower().strip() for t in recent_titles if t.strip()}

        # Exact duplicate
        if lower_title in lower_seen:
            return 0.0

        # Fuzzy overlap check
        title_words = set(lower_title.split())
        if not title_words:
            return 0.0

        for seen in lower_seen:
            seen_words = set(seen.split())
            if not seen_words:
                continue
            intersection = title_words & seen_words
            overlap = len(intersection) / min(len(title_words), len(seen_words))
            if overlap >= 0.5:
                return 5.0  # Similar to a recent title

        return 15.0  # Unique

    @staticmethod
    def _impact_score(article: Article) -> float:
        """Score based on business-impact keywords in the title (max 10)."""
        text = article.title.lower()
        score = sum(2.0 for kw in IMPACT_KEYWORDS if kw in text)
        return min(score, IMPACT_MAX)


# ---------------------------------------------------------------------------
# LLM-enhanced scorer (optional)
# ---------------------------------------------------------------------------


class LLMEnhancedScorer:
    """Optional LLM-enhanced scorer that blends rule and LLM scores.

    The LLM is asked to rate relevance on a 0-100 scale.  If the LLM
    is unavailable or raises, the scorer gracefully degrades to the
    rule-based score alone.

    Args:
        llm_provider: A callable that accepts a prompt string and returns
                      a response string (typically a numeric rating).
        config:       Optional scoring weights (passed to internal
                      ``RuleScorer``).
    """

    def __init__(
        self,
        llm_provider: Callable[[str], str] | None = None,
        config: ScoringConfig | None = None,
    ) -> None:
        self._llm = llm_provider
        self._rule_scorer = RuleScorer(config)

    def score(
        self,
        article: Article,
        recent_titles: set[str] | None = None,
    ) -> float:
        """Compute an LLM-enhanced score (0-100).

        Formula: ``final = rule_score * 0.7 + llm_score * 0.3``

        Degrades gracefully to ``rule_score`` when the LLM is unavailable
        or raises an exception.
        """
        rule_score = self._rule_scorer.score(article, recent_titles)

        if self._llm is None:
            return rule_score

        try:
            raw = self._llm(self._build_prompt(article))
            llm_score = self._parse_score(raw)
        except Exception:
            return rule_score

        return round(rule_score * 0.7 + llm_score * 0.3, 2)

    @staticmethod
    def _build_prompt(article: Article) -> str:
        """Build the LLM prompt for relevance scoring."""
        return (
            f"Rate the relevance of this article on a scale of 0-100. "
            f"Respond with ONLY a number between 0 and 100, no explanation.\n\n"
            f"Title: {article.title}\n"
            f"Summary: {article.summary}"
        )

    @staticmethod
    def _parse_score(response: str) -> float:
        """Extract a numeric 0-100 score from the LLM response."""
        cleaned = response.strip()
        try:
            value = float(cleaned)
        except ValueError:
            # Try to find a number in the response
            for token in cleaned.split():
                try:
                    value = float(token.strip(",.!?"))
                    break
                except ValueError:
                    continue
            else:
                return 50.0  # Sensible default

        return max(0.0, min(100.0, value))


# ---------------------------------------------------------------------------
# Unified entry point
# ---------------------------------------------------------------------------


def calculate_score(
    article: Article,
    recent_titles: set[str] | None = None,
    strategy: str = "rule",
    config: ScoringConfig | None = None,
    llm_provider: Callable[[str], str] | None = None,
) -> float:
    """Score an article using the selected strategy.

    Args:
        article:       The article to score.
        recent_titles: Optional set of recently-seen titles (for novelty).
        strategy:      ``"rule"`` (default) or ``"llm"``.
        config:        Optional ``ScoringConfig`` with custom weights.
        llm_provider:  LLM callable (required when ``strategy="llm"``).

    Returns:
        A float between 0.0 and 100.0.

    Raises:
        ValueError: When ``strategy="llm"`` but no ``llm_provider`` is given.

    Examples::

        >>> calculate_score(article)
        67.5

        >>> calculate_score(article, strategy="llm", llm_provider=my_llm)
        71.2
    """
    if strategy == "llm":
        if llm_provider is None:
            msg = "llm_provider is required when strategy='llm'"
            raise ValueError(msg)
        return LLMEnhancedScorer(
            llm_provider=llm_provider,
            config=config,
        ).score(article, recent_titles)

    return RuleScorer(config).score(article, recent_titles)


# ---------------------------------------------------------------------------
# Interest-based score boosting
# ---------------------------------------------------------------------------


class InterestBooster:
    """Boosts article scores based on interest keyword matching.

    Looks for interest keywords in the article's title, summary, tags,
    and category.  Each match contributes a fixed bonus:

    * Title match   — +5
    * Summary match — +3
    * Tag match     — +3
    * Category match — +3

    The total boost is capped at +20.

    Args:
        interests: List of interest keywords (case-insensitive matching).
    """

    BOOST_TITLE: float = 5.0
    BOOST_SUMMARY: float = 3.0
    BOOST_TAG: float = 3.0
    BOOST_CATEGORY: float = 3.0
    BOOST_MAX: float = 20.0

    def __init__(self, interests: list[str]) -> None:
        self._keywords: list[str] = [kw.lower() for kw in interests if kw.strip()]

    def calculate_boost(self, article: Article) -> float:
        """Calculate a 0-20 score boost for an article based on interest keywords.

        Args:
            article: The article to evaluate.

        Returns:
            A float between 0.0 and 20.0.
        """
        if not self._keywords:
            return 0.0

        boost: float = 0.0
        title_lower = article.title.lower()
        summary_lower = article.summary.lower()
        category_lower = article.category.lower()
        tags_lower = [t.lower() for t in article.tags]

        for kw in self._keywords:
            if kw in title_lower:
                boost += self.BOOST_TITLE
            if kw in summary_lower:
                boost += self.BOOST_SUMMARY
            if any(kw == t for t in tags_lower):
                boost += self.BOOST_TAG
            if kw == category_lower:
                boost += self.BOOST_CATEGORY

        return min(boost, self.BOOST_MAX)


def calculate_score_with_interests(
    article: Article,
    interests: list[str] | None = None,
    recent_titles: set[str] | None = None,
    strategy: str = "rule",
    config: ScoringConfig | None = None,
    llm_provider: Callable[[str], str] | None = None,
) -> float:
    """Calculate an article's score with interest-based boosting.

    The base score is computed first using the selected strategy (``"rule"``
    or ``"llm"``), then an interest boost (0-20) is added.  The final score
    is capped at 100.

    Args:
        article:       The article to score.
        interests:     Optional list of interest keywords for boosting.
        recent_titles: Optional set of recently-seen titles (for novelty).
        strategy:      ``"rule"`` (default) or ``"llm"``.
        config:        Optional ``ScoringConfig`` with custom weights.
        llm_provider:  LLM callable (required when ``strategy="llm"``).

    Returns:
        A float between 0.0 and 100.0.

    Raises:
        ValueError: When ``strategy="llm"`` but no ``llm_provider`` is given.
    """
    base = calculate_score(
        article,
        recent_titles=recent_titles,
        strategy=strategy,
        config=config,
        llm_provider=llm_provider,
    )

    if not interests:
        return base

    boost = InterestBooster(interests).calculate_boost(article)
    return min(base + boost, 100.0)
