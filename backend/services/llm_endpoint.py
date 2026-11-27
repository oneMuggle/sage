"""LLM 端点装配 —— 各 AI 子系统的公共入口（P2 抽出）。

``todo_ai``（对话→待办）、``worklog_ai``（对话→工作日志）、``report_ai``
（日报/周报）都要「拿到一个配置好的 LLM 客户端」，并且在端点未配置时抛出
**同一个**异常类型 —— 路由层靠这个类型统一映射 503。

装配路径与 ``todo_ai`` 原有实现一致：``build_llm_client_from_settings()``
返回 ``None`` 即代表未配置。

``llm_factory`` 的导入放在函数内（延迟导入）—— 否则模块加载期就会把
``backend.orchestration`` 的依赖链拉进来，测试与 CLI 场景都受影响。
"""
from __future__ import annotations

from typing import Any


class LLMNotConfiguredError(RuntimeError):
    """LLM 端点未配置。"""


def build_ai_client() -> Any:
    """返回配置好的 LLM 客户端。

    Raises:
        LLMNotConfiguredError: 设置里没有可用端点时抛出（路由层映射 503）。
    """
    from backend.orchestration.llm_factory import build_llm_client_from_settings

    client = build_llm_client_from_settings()
    if client is None:
        raise LLMNotConfiguredError("LLM 未配置，请先在 设置 → 模型 中完成配置")
    return client
