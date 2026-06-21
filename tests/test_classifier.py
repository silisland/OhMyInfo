"""
Tests for src/processors/classifier.py — 文章分类模块。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.collectors import Article
from src.processors import CATEGORIES, LLMClassifier, RuleClassifier, classify


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _make_article(
    title: str = "Test Title",
    summary: str = "",
    content: str = "",
) -> Article:
    """快速创建 Article 实例。"""
    return Article(
        title=title,
        url="https://example.com/test",
        source="test_source",
        summary=summary,
        content=content,
    )


# ===================================================================
# CATEGORIES 常量测试
# ===================================================================


class TestCategoriesConstant:
    """CATEGORIES 字典应包含全部 5 个固定类别且描述非空。"""

    def test_has_exactly_five_categories(self) -> None:
        assert len(CATEGORIES) == 5

    def test_all_categories_covered(self) -> None:
        expected = {
            "major-release",
            "tools-release",
            "research-frontier",
            "industry-business",
            "policy-regulation",
        }
        assert set(CATEGORIES.keys()) == expected

    def test_all_descriptions_non_empty(self) -> None:
        for slug, desc in CATEGORIES.items():
            assert desc, f"Category {slug!r} has empty description"


# ===================================================================
# RuleClassifier 测试
# ===================================================================


class TestRuleClassifierMajorRelease:
    """major-release 分类测试。"""

    def test_new_model_launch(self) -> None:
        article = _make_article(
            title="OpenAI Launches GPT-5: A New Model for Reasoning",
            summary="OpenAI announces GPT-5 with breakthrough reasoning capabilities.",
        )
        assert RuleClassifier().classify(article) == "major-release"

    def test_claude_announcement(self) -> None:
        article = _make_article(
            title="Anthropic Releases Claude 4",
            content="Anthropic has announced Claude 4, their latest model release.",
        )
        assert RuleClassifier().classify(article) == "major-release"

    def test_gemini_launch(self) -> None:
        article = _make_article(
            title="Google Launches Gemini 2.0",
            summary="Google announces their new model Gemini 2.0.",
        )
        assert RuleClassifier().classify(article) == "major-release"


class TestRuleClassifierToolsRelease:
    """tools-release 分类测试。"""

    def test_open_source_tool(self) -> None:
        article = _make_article(
            title="Announcing PyTorch 3.0: A New Open Source Framework",
            summary="The popular open source framework releases version 3.0.",
        )
        assert RuleClassifier().classify(article) == "tools-release"

    def test_sdk_release(self) -> None:
        article = _make_article(
            title="AWS Releases New SDK for Python Developers",
            content="The new SDK v1.0 includes support for the latest API features.",
        )
        assert RuleClassifier().classify(article) == "tools-release"

    def test_cli_tool(self) -> None:
        article = _make_article(
            title="Introducing OhMyInfo CLI — Your Info Hub",
            summary="A new CLI tool for aggregating technical news.",
        )
        assert RuleClassifier().classify(article) == "tools-release"


class TestRuleClassifierResearchFrontier:
    """research-frontier 分类测试。"""

    def test_arxiv_paper(self) -> None:
        article = _make_article(
            title="Attention Is All You Need — A Landmark Paper",
            summary="This paper introduces the Transformer architecture, now SOTA.",
            content="Published on arXiv, this research paper proposes a new architecture.",
        )
        assert RuleClassifier().classify(article) == "research-frontier"

    def test_benchmark_result(self) -> None:
        article = _make_article(
            title="New Benchmark Shows 40% Improvement on ImageNet",
            summary="Research team achieves SOTA results on the ImageNet benchmark.",
        )
        assert RuleClassifier().classify(article) == "research-frontier"


class TestRuleClassifierIndustryBusiness:
    """industry-business 分类测试。"""

    def test_funding_round(self) -> None:
        article = _make_article(
            title="AI Startup Raises $500 Million in Series C Funding",
            summary="The company secured a funding round led by Sequoia Capital.",
        )
        assert RuleClassifier().classify(article) == "industry-business"

    def test_acquisition(self) -> None:
        article = _make_article(
            title="Microsoft Acquires AI Firm for $10 Billion",
            content="The acquisition marks the largest deal in the industry this year.",
        )
        assert RuleClassifier().classify(article) == "industry-business"

    def test_partnership(self) -> None:
        article = _make_article(
            title="New Partnership Between Google and NVIDIA",
            summary="A strategic partnership to advance AI infrastructure and revenue growth.",
        )
        assert RuleClassifier().classify(article) == "industry-business"


class TestRuleClassifierPolicyRegulation:
    """policy-regulation 分类测试。"""

    def test_eu_ai_act(self) -> None:
        article = _make_article(
            title="EU AI Act: New Regulations for Artificial Intelligence",
            summary="The EU AI Act introduces comprehensive AI compliance requirements.",
        )
        assert RuleClassifier().classify(article) == "policy-regulation"

    def test_safety_governance(self) -> None:
        article = _make_article(
            title="New AI Safety Guidelines Published by Government",
            content="The policy framework establishes governance standards for AI development.",
        )
        assert RuleClassifier().classify(article) == "policy-regulation"


class TestRuleClassifierEdgeCases:
    """边界情况测试。"""

    def test_no_match_returns_general(self) -> None:
        article = _make_article(
            title="Weather Report for San Francisco Today",
            summary="Sunny with a chance of fog in the afternoon.",
        )
        assert RuleClassifier().classify(article) == "general"

    def test_multiple_categories_uses_best_match(self) -> None:
        """文章同时匹配多个类别时应返回关键词命中数最多的类别。"""
        article = _make_article(
            title="Open Source Launch: New Framework v1.0 Released",
            summary="The team announces the open source release and benchmark results.",
        )
        # tools-release 关键词: open source, framework, v1., releases (4 hits)
        # research-frontier 关键词: benchmark (1 hit)
        # major-release: launches, releases (2 hits)
        # => tools-release 应胜出
        result = RuleClassifier().classify(article)
        assert result == "tools-release", f"Expected tools-release, got {result}"

    def test_keywords_case_insensitive(self) -> None:
        """关键词匹配应忽略大小写。"""
        article = _make_article(
            title="BREAKING: OPENAI LAUNCHES NEW MODEL",
            summary="THE CLAUDE KILLER HAS ARRIVED",
        )
        assert RuleClassifier().classify(article) == "major-release"

    def test_uses_title_summary_and_content(self) -> None:
        """分类应使用 title + summary + content 三个字段进行匹配。"""
        article = _make_article(
            title="Unrelated Title",
            summary="Unrelated summary",
            content="This paper on arXiv presents a breakthrough benchmark achieving SOTA architecture results.",
        )
        assert RuleClassifier().classify(article) == "research-frontier"

    def test_empty_fields_ok(self) -> None:
        """所有文本字段为空时不崩溃。"""
        article = _make_article(title="Minimal")
        # Only title "minimal" — no keyword hits
        assert RuleClassifier().classify(article) == "general"

    def test_unicode_content(self) -> None:
        """包含 Unicode 字符时仍能正常匹配。"""
        article = _make_article(
            title="论文: Transformer 架构研究 (Research Paper)",
            content="Published on arXiv, this paper proposes new architecture achieving SOTA benchmark results.",
        )
        # 英文关键词仍可匹配
        assert RuleClassifier().classify(article) == "research-frontier"


# ===================================================================
# LLMClassifier 测试
# ===================================================================


class TestLLMClassifier:
    """LLMClassifier 使用 mock LLM 的测试。"""

    def test_llm_returns_valid_slug(self) -> None:
        mock_llm = MagicMock(return_value="research-frontier")
        article = _make_article(title="Some ambiguous article")
        result = LLMClassifier(mock_llm).classify(article)
        assert result == "research-frontier"
        mock_llm.assert_called_once()

    def test_llm_returns_lowercase_slug(self) -> None:
        mock_llm = MagicMock(return_value="MAJOR-RELEASE")
        article = _make_article(title="Big launch")
        result = LLMClassifier(mock_llm).classify(article)
        assert result == "major-release"

    def test_llm_returns_slug_in_sentence(self) -> None:
        """LLM 返回了包含 slug 的完整句子时应能提取。"""
        mock_llm = MagicMock(return_value="I think this is tools-release because it's a framework.")
        article = _make_article(title="Some framework")
        result = LLMClassifier(mock_llm).classify(article)
        assert result == "tools-release"

    def test_llm_returns_unrecognized_response(self) -> None:
        """LLM 返回完全无法识别的文本时应回退到 general。"""
        mock_llm = MagicMock(return_value="I have no idea what this is about.")
        article = _make_article(title="Mysterious content")
        result = LLMClassifier(mock_llm).classify(article)
        assert result == "general"

    def test_llm_prompt_contains_categories(self) -> None:
        """prompt 中应包含所有类别定义。"""
        mock_llm = MagicMock(return_value="general")
        classifier = LLMClassifier(mock_llm)
        article = _make_article(title="Test")
        classifier.classify(article)
        prompt = mock_llm.call_args[0][0]
        for slug in CATEGORIES:
            assert slug in prompt
        assert article.title in prompt

    def test_llm_classifier_reused(self) -> None:
        """同一个 LLMClassifier 实例应能多次使用。"""
        mock_llm = MagicMock(return_value="industry-business")
        classifier = LLMClassifier(mock_llm)
        articles = [
            _make_article(title="Article A"),
            _make_article(title="Article B"),
        ]
        for a in articles:
            classifier.classify(a)
        assert mock_llm.call_count == 2


# ===================================================================
# classify() 统一入口测试
# ===================================================================


class TestClassifyEntryPoint:
    """classify() 函数作为统一入口的行为测试。"""

    def test_default_strategy_is_rule(self) -> None:
        article = _make_article(
            title="OpenAI Announces GPT-5: New Model Launch",
        )
        assert classify(article) == "major-release"

    def test_rule_strategy_explicit(self) -> None:
        article = _make_article(
            title="OpenAI Announces GPT-5: New Model Launch",
        )
        assert classify(article, strategy="rule") == "major-release"

    def test_llm_strategy(self) -> None:
        mock_llm = MagicMock(return_value="policy-regulation")
        article = _make_article(title="Some ambiguous regulation article")
        result = classify(article, strategy="llm", llm_provider=mock_llm)
        assert result == "policy-regulation"

    def test_llm_strategy_without_provider_raises(self) -> None:
        article = _make_article(title="Test")
        with pytest.raises(ValueError, match="llm_provider is required"):
            classify(article, strategy="llm")

    def test_does_not_mutate_article(self) -> None:
        """classify() 不应修改传入的 Article 对象。"""
        article = _make_article(
            title="OpenAI Announces GPT-5",
            summary="",
            content="",
        )
        original_category = article.category
        result = classify(article)
        assert article.category == original_category  # 未被修改
        assert result == "major-release"
