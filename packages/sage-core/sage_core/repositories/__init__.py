"""仓库接口（Repository Interfaces）。

定义 sage 核心领域所需的持久化与外部服务端口抽象。
所有接口基于 ``typing.Protocol``，零外部依赖；实现侧
由 backend / 其他适配包提供。
"""

from __future__ import annotations

from sage_core.repositories.compute import ComputePort
from sage_core.repositories.llm import LLMPort
from sage_core.repositories.observability import EventPort, MetricPort
from sage_core.repositories.skill import SkillPort
from sage_core.repositories.storage import StoragePort
from sage_core.repositories.tool import ToolPort

__all__ = [
    "ComputePort",
    "EventPort",
    "LLMPort",
    "MetricPort",
    "SkillPort",
    "StoragePort",
    "ToolPort",
]
