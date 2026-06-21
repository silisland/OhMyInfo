"""
OhMyInfo — 文章分类模块（Article Classifier）

将文章分为 5 个固定类别，支持规则匹配与 LLM 回退两种策略。
分类器在去重（dedup）之后、日报排版（layout）之前使用。

类别定义参照 Horizon 与 Signal 的 5 类分类体系：

    1. major-release    — 新模型发布、重大产品上线、里程碑公告
    2. tools-release    — 开源工具、SDK、框架、CLI、库
    3. research-frontier— 论文、基准测试、新架构、研究突破
    4. industry-business — 融资、并购、营收、企业合作、监管动态
    5. policy-regulation — 法律法规、合规、安全、治理
"""

from __future__ import annotations

from typing import Callable

from src.collectors import Article

# ---------------------------------------------------------------------------
# 类别定义
# ---------------------------------------------------------------------------

CATEGORIES: dict[str, str] = {
    "major-release": "New model launches, major product releases, milestone announcements",
    "tools-release": "Open source tools, SDKs, frameworks, CLIs, libraries",
    "research-frontier": "Papers, benchmarks, new architectures, research breakthroughs",
    "industry-business": "Funding, M&A, revenue, enterprise deals, regulation",
    "policy-regulation": "Laws, regulations, compliance, safety, governance",
}

# ---------------------------------------------------------------------------
# 基于规则的分类器
# ---------------------------------------------------------------------------


class RuleClassifier:
    """基于关键词匹配的规则分类器。

    对文章的 title + summary + content 进行大小写不敏感的关键词扫描，
    返回命中关键词数量最多的类别。若无任何关键词命中则返回 ``"general"``。
    """

    # 关键词 → 类别映射（关键词均为小写，匹配时忽略大小写）
    KEYWORD_MAP: dict[str, list[str]] = {
        "major-release": [
            "launch",
            "releases",
            "announces",
            "gpt-",
            "claude",
            "gemini",
            "new model",
        ],
        "tools-release": [
            "open source",
            "framework",
            "sdk",
            "cli",
            "library",
            "tool",
            "v0.",
            "v1.",
        ],
        "research-frontier": [
            "paper",
            "arxiv",
            "benchmark",
            "research",
            "architecture",
            "sota",
        ],
        "industry-business": [
            "funding",
            "acquisition",
            "revenue",
            "million",
            "billion",
            "partnership",
        ],
        "policy-regulation": [
            "regulation",
            "policy",
            "compliance",
            "law",
            "governance",
            "safety",
            "eu ai act",
        ],
    }

    def classify(self, article: Article) -> str:
        """对单篇文章执行规则分类。

        Args:
            article: 待分类的文章对象。

        Returns:
            命中关键词最多的类别 slug，若无匹配则返回 ``"general"``。
        """
        text = self._build_text(article)

        best_category = "general"
        best_score = 0

        for category, keywords in self.KEYWORD_MAP.items():
            score = sum(1 for kw in keywords if kw in text)
            if score > best_score:
                best_score = score
                best_category = category

        return best_category

    @staticmethod
    def _build_text(article: Article) -> str:
        """将文章的可分类字段拼接为小写文本。"""
        parts = [article.title, article.summary, article.content]
        return " ".join(parts).lower()


# ---------------------------------------------------------------------------
# 基于 LLM 的分类器（可选回退）
# ---------------------------------------------------------------------------


class LLMClassifier:
    """基于 LLM 的文章分类器。

    当规则分类器的置信度不足时，可选用此分类器进行语义理解。

    Args:
        llm_provider: 接受 prompt 字符串并返回分类结果的 callable。

    Usage::

        def mock_llm(prompt: str) -> str:
            return "research-frontier"

        classifier = LLMClassifier(llm_provider=mock_llm)
        category = classifier.classify(article)
    """

    def __init__(self, llm_provider: Callable[[str], str]) -> None:
        self._llm = llm_provider

    def classify(self, article: Article) -> str:
        """通过 LLM 对文章进行分类。

        Args:
            article: 待分类的文章对象。

        Returns:
            LLM 返回的类别 slug，若无法解析则返回 ``"general"``。
        """
        prompt = self._build_prompt(article)
        response = self._llm(prompt)
        return self._parse_response(response)

    def _build_prompt(self, article: Article) -> str:
        categories_desc = "\n".join(f"- {k}: {v}" for k, v in CATEGORIES.items())
        return (
            f"Classify this article into exactly one of the following categories:\n"
            f"{categories_desc}\n\n"
            f"Title: {article.title}\n"
            f"Summary: {article.summary}\n\n"
            f"Respond with ONLY the category slug."
        )

    @staticmethod
    def _parse_response(response: str) -> str:
        """从 LLM 输出中提取有效的类别 slug。"""
        cleaned = response.strip().lower()
        valid_slugs = set(CATEGORIES.keys())

        if cleaned in valid_slugs:
            return cleaned

        for slug in valid_slugs:
            if slug in cleaned:
                return slug

        return "general"


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------


def classify(
    article: Article,
    strategy: str = "rule",
    llm_provider: Callable[[str], str] | None = None,
) -> str:
    """文章分类的统一入口函数。

    根据 **strategy** 参数选择不同的分类策略：

    - ``"rule"``（默认）: 使用基于关键词的 ``RuleClassifier``，无需网络请求。
    - ``"llm"``: 使用 ``LLMClassifier``，需要提供 **llm_provider**。

    Args:
        article: 待分类的文章。
        strategy: 分类策略，可选 ``"rule"`` 或 ``"llm"``。
        llm_provider: LLM 调用函数（仅 ``"llm"`` 策略需要）。

    Returns:
        类别 slug（如 ``"major-release"``），未匹配时返回 ``"general"``。

    Raises:
        ValueError: 当 ``strategy="llm"`` 但未提供 ``llm_provider`` 时。

    Examples::

        >>> classify(article)
        "research-frontier"

        >>> classify(article, strategy="llm", llm_provider=my_llm)
        "tools-release"
    """
    if strategy == "llm":
        if llm_provider is None:
            raise ValueError("llm_provider is required when strategy='llm'")
        return LLMClassifier(llm_provider).classify(article)

    return RuleClassifier().classify(article)
