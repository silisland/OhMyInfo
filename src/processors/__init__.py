"""
OhMyInfo — 处理器统一接口（Processor Interface）

提供文章分类、评分、摘要等处理模块的基础设施。
"""

from __future__ import annotations

from src.processors.classifier import CATEGORIES, LLMClassifier, RuleClassifier, classify
from src.processors.scorer import (
    LLMEnhancedScorer,
    RuleScorer,
    ScoringConfig,
    calculate_score,
)
from src.processors.summarizer import Summarizer, SummaryCache

__all__ = [
    "CATEGORIES",
    "LLMClassifier",
    "LLMEnhancedScorer",
    "RuleClassifier",
    "RuleScorer",
    "ScoringConfig",
    "Summarizer",
    "SummaryCache",
    "calculate_score",
    "classify",
]
