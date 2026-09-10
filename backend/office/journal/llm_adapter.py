"""LLM 适配器 — 把 ProviderClient 桥接到 generate_article 期望的接口。

背景：``generate_article`` (Task 5 写的) 期望一个 ``llm_proxy`` 对象，暴露
``async generate(*, system_prompt, user_prompt, output_schema=None, **kwargs)
-> str | dict``。返回值会被 ``_json.loads(result)`` 解析成 dict。

真实世界的 LLM 调用走 ``backend/ports/llm.py:ProviderClient.complete()``，其
签名是 ``async complete(*, model, messages, tools, tool_choice)``，返回
``AssistantTurn(text, tool_calls, ...)``。

这个适配器把 Task 5 的 ``MockLLMProxy`` 风格接口包到 ``ProviderClient`` 上，
让 ``generate_article`` 既能在测试里用 mock，也能在生产里用真实 provider。

模型名：
- 优先用构造时显式传入的 ``model``；
- 否则从当前激活的 chat session / provider config 读取；
- 最后回退 ``"unknown"``。

输出契约：
- 解析 ``AssistantTurn.text`` 为 JSON dict；
- 当 LLM 没有返回合法 JSON 时，把 ``text`` 原样返回（dict(str=text)），让
  ``generate_article`` 在最后一步 ``JournalContent.model_validate`` 失败
  时给用户清晰的错误信息。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from sage_core import Message, Role

from backend.ports.llm import AssistantTurn, ModelCapabilities, ProviderClient

logger = logging.getLogger(__name__)


class JournalLLMAdapter:
    """把 ProviderClient 包装成 generate_article 期望的接口。

    Args:
        provider: ``ProviderClient`` 实例。生产从 ``backend.ports.llm.get_provider()``
                  拿；测试可注入 mock。
        model: 模型名。``None`` 时走 :func:`resolve_default_model`。
    """

    def __init__(
        self,
        provider: ProviderClient,
        model: Optional[str] = None,
    ) -> None:
        self._provider = provider
        self._model = model or resolve_default_model()

    @property
    def model(self) -> str:
        return self._model

    async def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_schema: Any = None,  # noqa: ARG002 — API 契约保留字段
        **kwargs: Any,
    ) -> Any:
        """生成论文内容。

        Args:
            system_prompt: 系统提示（含 JournalSpec JSON）。
            user_prompt: 用户请求 + 章节列表。
            output_schema: 保留字段 — generate_article 当前未消费，仅签名占位。
            **kwargs: 透传到 ``ProviderClient.complete``。

        Returns:
            ``AssistantTurn.text`` 解析后的 dict；解析失败时回退为 ``{"raw": text}``。
        """
        messages = [
            Message(role=Role.SYSTEM, content=system_prompt),
            Message(role=Role.USER, content=user_prompt),
        ]
        turn: AssistantTurn = await self._provider.complete(
            model=self._model,
            messages=messages,
            **kwargs,
        )
        return _parse_turn_text(turn.text)


def resolve_default_model() -> str:
    """从运行配置推断默认模型；无法推断时回退 ``"unknown"``。

    测试场景通常不调用此函数（直接传 ``model``）。生产场景下
    ``backend.llm.config`` 之类的模块持有默认模型；为了避免 journal 子系统
    引入硬依赖，这里采用"读取 + 失败回退"策略。
    """
    try:
        from backend.llm.config import get_default_model  # type: ignore

        value = get_default_model()
        if isinstance(value, str) and value.strip():
            return value.strip()
    except Exception:  # noqa: BLE001 — 推断失败不应破坏工具路径
        pass
    return "unknown"


def _parse_turn_text(text: Optional[str]) -> Any:
    """把 AssistantTurn.text 解析为 dict；失败时回退为 ``{"raw": text}``。

    ``generate_article`` 收到 dict 后会 ``JournalContent.model_validate``，
    解析失败时 Pydantic ValidationError 给清晰的字段级错误信息。
    """
    if text is None:
        return {"raw": ""}
    stripped = text.strip()
    if not stripped:
        return {"raw": ""}
    # 直接 JSON
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    # ```json ... ``` 围栏
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        inner = "\n".join(lines[1:]).rstrip()
        if inner.endswith("```"):
            inner = inner[:-3].rstrip()
        try:
            return json.loads(inner)
        except json.JSONDecodeError:
            pass
    return {"raw": text}


def get_default_journal_llm_adapter() -> JournalLLMAdapter:
    """工厂：构造一个使用生产 ProviderClient 的适配器。

    通过懒加载 ``backend.ports.llm.get_provider()`` 拿 provider（如果存在），
    否则退到一个 noop adapter（仅用于兼容早期尚未接入 ProviderRouter 的场景）。
    """
    try:
        from backend.ports.llm import get_provider  # type: ignore

        provider = get_provider()
    except Exception:  # noqa: BLE001
        provider = _NoopProviderClient()
    return JournalLLMAdapter(provider=provider)


class _NoopProviderClient(ProviderClient):
    """当 ProviderRouter 不可用时的兜底 provider（仅占位，避免 import-time 崩溃）。

    真实环境必须通过 ``backend.ports.llm.get_provider()`` 注入真正的 provider。
    这个 noop 仅在测试 / 早期环境无 LLM 配置时让适配器能正常构造。
    """

    async def complete(
        self,
        *,
        model: str,
        messages: Any,
        tools: Any = None,
        tool_choice: Any = None,
        **settings: Any,
    ) -> AssistantTurn:
        return AssistantTurn(
            text='{"title": "noop", "abstract": "noop stub", '
            '"sections": {"keywords": "k"}, "references": [], "citations": []}',
            finish_reason="stop",
            model=model,
        )

    def capabilities(self, model: str) -> ModelCapabilities:  # type: ignore[override]
        return ModelCapabilities(
            tools=False, vision=False, streaming=False, parallel_tool_calls=False
        )


__all__ = [
    "JournalLLMAdapter",
    "get_default_journal_llm_adapter",
    "resolve_default_model",
]
