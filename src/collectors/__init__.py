"""
OhMyInfo — 采集器统一接口与数据模型（Collector Interface & Data Model）

定义数据采集模块的核心契约，所有具体采集器必须遵循此接口：

    Article       — 通用文章数据模型（数据管线的通用传输对象）
    Collector     — 采集器抽象基类（async fetch / health / name）
    CollectorError— 采集流程自定义异常
    ArticleStatus — 文章生命周期状态枚举
    SourceConfig  — 数据源配置模型（支持 YAML/JSON 反序列化）

使用方式:

    class MyCollector(Collector):
        @property
        def name(self) -> str:
            return "my_source"

        async def fetch(self) -> list[Article]:
            ...
            return [Article(title=..., url=..., source=self.name)]
"""

from __future__ import annotations

import abc
import enum
from datetime import datetime
from typing import Any, ClassVar

from pydantic import BaseModel, Field, field_validator

__all__ = [
    "Article",
    "ArticleStatus",
    "Collector",
    "CollectorError",
    "SourceConfig",
]


# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------


class CollectorError(Exception):
    """采集器相关异常的基类。

    Attributes:
        message: 人类可读的错误描述。
        source:  引发异常的数据源名称（可选）。
    """

    def __init__(self, message: str, source: str | None = None) -> None:
        self.source = source
        super().__init__(message)


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------


class ArticleStatus(str, enum.Enum):
    """文章在系统中的生命周期状态。

    状态流转: NEW → SEEN → ARCHIVED
                   ↘ STARRED
    """

    NEW = "new"
    SEEN = "seen"
    STARRED = "starred"
    ARCHIVED = "archived"


# ---------------------------------------------------------------------------
# 配置模型
# ---------------------------------------------------------------------------


class SourceConfig(BaseModel):
    """数据源配置模型，支持从 YAML/JSON 直接反序列化。"""

    name: str = Field(..., description="数据源名称（唯一标识）")
    type: str = Field(
        ...,
        description="数据源类型: rss / api / scrape / search",
    )
    enabled: bool = Field(default=True, description="是否启用")
    interval_minutes: int = Field(
        default=360,
        ge=1,
        le=43200,
        description="采集周期（分钟），默认 6 小时",
    )
    priority: int = Field(
        default=5,
        ge=1,
        le=10,
        description="优先级 1（最高）~ 10（最低）",
    )

    @field_validator("type")
    @classmethod
    def _validate_type(cls, v: str) -> str:
        allowed = {"rss", "api", "scrape", "search"}
        if v not in allowed:
            msg = f"type 必须是 {allowed} 之一，当前值：'{v}'"
            raise ValueError(msg)
        return v


# ---------------------------------------------------------------------------
# 文章数据模型
# ---------------------------------------------------------------------------


class Article(BaseModel):
    """通用文章数据模型。

    作为整个数据管线的通用传输对象（DTO），采集 → 处理 → 输出
    各阶段均使用此模型传递数据。
    """

    title: str = Field(..., min_length=1, description="文章标题")
    url: str = Field(..., description="文章链接")
    source: str = Field(..., min_length=1, description="数据源名称")
    published_at: datetime = Field(
        default_factory=datetime.now,
        description="发布时间",
    )
    summary: str = Field(default="", description="文章摘要")
    content: str = Field(default="", description="文章全文")
    score: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="综合评分 0-100",
    )
    category: str = Field(default="", description="文章分类")
    tags: list[str] = Field(default_factory=list, description="标签列表")
    author: str = Field(default="", description="作者")

    model_config: ClassVar[dict] = {
        "from_attributes": True,
        "validate_assignment": True,
    }


# ---------------------------------------------------------------------------
# 采集器抽象基类
# ---------------------------------------------------------------------------


class Collector(abc.ABC):
    """采集器抽象基类。

    所有具体采集器必须继承此类并实现以下接口：

        name    — 采集器唯一名称（只读属性）
        fetch() — 异步采集方法，返回 Article 列表
        health()— 健康检查（已提供默认实现）

    约定：
        - 子类应定义 URL / 超时 / 重试等常量为类变量
        - 所有网络请求使用 httpx.AsyncClient
        - 采集过程中的异常应包装为 CollectorError 抛出
    """

    # 默认 HTTP 超时（秒）
    DEFAULT_TIMEOUT: ClassVar[int] = 30
    # 默认最大重试次数
    DEFAULT_MAX_RETRIES: ClassVar[int] = 3

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """采集器唯一名称，用于标识和配置匹配。"""
        ...

    @abc.abstractmethod
    async def fetch(self) -> list[Article]:
        """执行异步采集。

        Returns:
            采集到的文章列表（可能为空列表）。

        Raises:
            CollectorError: 采集过程中发生可恢复或不可恢复的错误。
        """
        ...

    def health(self) -> dict[str, Any]:
        """返回采集器健康状态。

        默认实现返回基础状态；子类可覆盖以添加自定义指标
        （如最后采集时间、失败次数等）。

        Returns:
            包含健康信息的字典，至少包含 name 和 status 字段。
        """
        return {
            "name": self.name,
            "status": "ok",
            "timeout": self.DEFAULT_TIMEOUT,
            "max_retries": self.DEFAULT_MAX_RETRIES,
        }
