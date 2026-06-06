"""Sage ports 层（Protocol 接口定义）。

本层是六边形架构的端口（port）抽象，仅声明接口，**不包含任何实现**。
设计原则：

- **零外部依赖**：除 ``backend.domain`` 之外，不得 import 任何模块
  （禁止 fastapi / httpx / sqlite3 / pydantic 等）。
- **运行时透明**：Protocol 不在执行路径上产生任何开销，仅用于
  类型提示与 ``mypy --strict`` 校验。
- **适配器独立**：每个 port 的具体实现由 ``backend.adapters.*`` 提供
  （HttpxLLMAdapter、SqliteStorageAdapter、PrometheusMetricAdapter …）。
- **可测试性**：单元测试可以声明一个最小 mock 实现来满足 Protocol
  校验，避免依赖真实外部系统。

约定的子模块布局：

| 子模块              | Port(s)                | 说明                                |
|---------------------|------------------------|-------------------------------------|
| ``llm``             | ``LLMPort``            | 大模型调用（聊天 + 流式）           |
| ``tool``            | ``ToolPort``           | 工具注册与执行                      |
| ``skill``           | ``SkillPort``          | 技能发现与执行                      |
| ``storage``         | ``StoragePort``        | 会话/消息/记忆等持久化              |
| ``observability``   | ``MetricPort``         | Prometheus 风格指标                 |
| ``observability``   | ``EventPort``          | 业务事件（审计/调试）               |
"""

from backend.ports.llm import LLMPort
from backend.ports.observability import EventPort, MetricPort
from backend.ports.skill import SkillPort
from backend.ports.storage import StoragePort
from backend.ports.tool import ToolPort

__all__ = [
    "LLMPort",
    "ToolPort",
    "SkillPort",
    "StoragePort",
    "MetricPort",
    "EventPort",
]
