"""Google Gemini（generateContent REST API）Provider adapter（A2）。

用 httpx 直连 ``POST /v1beta/models/{model}:generateContent`` REST API
—— **不引入 google-genai SDK**，保持 Sage 的零 SDK 依赖约束
（Win7 LTS / Py3.8 打包矩阵）。API key 走 ``x-goog-api-key`` header。

消息格式翻译要点：

- SYSTEM 消息抽为顶层 ``systemInstruction``。
- TOOL 消息 → user 角色 ``functionResponse`` part（name 从上一条
  assistant 的 tool_calls 按 tool_call_id 反查）。
- ASSISTANT 的 tool_calls → model 角色 ``functionCall`` part。
- 连续同角色消息的 part 合并。

Token 归一化语义（与 OpenWorker ``gemini_provider._usage_from`` 对齐）：
``promptTokenCount`` **包含**缓存命中部分，减去
``cachedContentTokenCount`` 拆入 ``cache_read``；thinking token 按
output 计费，``thoughtsTokenCount`` 折入 ``output``。

流式说明：``stream`` 走 ``:streamGenerateContent?alt=sse``，逐块
yield 文本增量，末尾 yield 携带 usage 的完整 turn（流内 functionCall
组装留给后续集成阶段，非流式 ``complete`` 已完整支持）。
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx
from sage_core import Message, Role, ToolCall

from backend.adapters.out.llm._common import raise_classified_error
from backend.core.errors import LLMError, LLMErrorType
from backend.ports.llm import (
    AssistantTurn,
    ModelCapabilities,
    ProviderClient,
    StreamChunk,
    TokenUsage,
)

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"

#: Gemini finishReason → OpenAI 风格 finish_reason 词汇。
FINISH_REASON_MAP = {
    "STOP": "stop",
    "MAX_TOKENS": "length",
    "SAFETY": "stop",
    "RECITATION": "stop",
    "MALFORMED_FUNCTION_CALL": "stop",
}


def _map_finish(raw_finish: Any) -> Optional[str]:
    """Gemini finishReason → OpenAI 风格词汇；非字符串（None 等）视为无。"""
    if not isinstance(raw_finish, str):
        return None
    return FINISH_REASON_MAP.get(raw_finish, raw_finish)


# ============================================================================
# 双向转换辅助（模块级纯函数，便于单测直接调用）
# ============================================================================


def messages_to_gemini(
    messages: List[Message],
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """domain ``Message`` 列表 → ``(system_instruction, contents)``。

    - SYSTEM 消息合并为 ``systemInstruction``（多条以 ``\\n\\n`` 拼接）。
    - TOOL 消息 → user 角色 ``functionResponse`` part；函数名从上一条
      assistant 消息的 tool_calls 按 ``tool_call_id`` 反查，查不到降级
      为 ``"unknown"``。
    - ASSISTANT 消息 → model 角色 text / ``functionCall`` part。
    - 连续同角色消息的 part 合并。
    """
    system_parts: List[str] = []
    contents: List[Dict[str, Any]] = []
    # 最近一条 assistant 消息的 tool_call id → name（供 TOOL 消息反查）
    pending_tool_names: Dict[str, str] = {}

    for msg in messages:
        role = msg.role if isinstance(msg.role, Role) else Role(str(msg.role))

        if role is Role.SYSTEM:
            if msg.content:
                system_parts.append(msg.content)
            continue

        parts: List[Dict[str, Any]]
        if role is Role.TOOL:
            wire_role = "user"
            name = pending_tool_names.get(msg.tool_call_id or "", "unknown")
            parts = [
                {
                    "functionResponse": {
                        "name": name,
                        "response": {"content": msg.content},
                    }
                }
            ]
        elif role is Role.ASSISTANT:
            wire_role = "model"
            parts = []
            if msg.content:
                parts.append({"text": msg.content})
            if msg.tool_calls:
                pending_tool_names = {}
                for tc in msg.tool_calls:
                    if tc.id:
                        pending_tool_names[tc.id] = tc.name
                    parts.append({"functionCall": {"name": tc.name, "args": tc.args}})
            if not parts:  # 空 assistant 消息兜底
                parts.append({"text": ""})
        else:  # USER
            wire_role = "user"
            parts = [{"text": msg.content}]

        if contents and contents[-1]["role"] == wire_role:
            contents[-1]["parts"].extend(parts)
        else:
            contents.append({"role": wire_role, "parts": parts})

    system_instruction = {"parts": [{"text": "\n\n".join(system_parts)}]} if system_parts else None
    return system_instruction, contents


def tools_to_gemini(tools: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """OpenAI 风格工具 schema → Gemini ``functionDeclarations``。"""
    declarations: List[Dict[str, Any]] = []
    for spec in tools or []:
        fn = spec.get("function") or spec
        declarations.append(
            {
                "name": fn.get("name") or "",
                "description": fn.get("description") or "",
                "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
            }
        )
    return [{"functionDeclarations": declarations}] if declarations else []


def tool_choice_to_gemini(
    tool_choice: Optional[Union[str, Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    """OpenAI 风格 tool_choice → Gemini ``toolConfig.toolChoice``。"""
    if tool_choice is None:
        return None
    if isinstance(tool_choice, dict):
        fn = tool_choice.get("function") or tool_choice
        name = fn.get("name")
        if name:
            return {"mode": "ANY", "allowedFunctionNames": [name]}
        return {"mode": "ANY"}
    return {"mode": {"auto": "AUTO", "required": "ANY", "none": "NONE"}.get(tool_choice, "AUTO")}


def usage_from_gemini(meta: Optional[Dict[str, Any]]) -> Optional[TokenUsage]:
    """``usageMetadata``（REST camelCase）→ 归一化 4 字段。

    ``promptTokenCount`` 包含缓存命中部分：减去
    ``cachedContentTokenCount`` 拆入 ``cache_read``。thinking token 按
    output 计费：``thoughtsTokenCount`` 折入 ``output``。
    """
    if not meta:
        return None
    prompt = int(meta.get("promptTokenCount") or 0)
    cached = int(meta.get("cachedContentTokenCount") or 0)
    return TokenUsage(
        input=max(prompt - cached, 0),
        output=int(meta.get("candidatesTokenCount") or 0)
        + int(meta.get("thoughtsTokenCount") or 0),
        cache_read=cached,
    )


def turn_from_gemini(data: Dict[str, Any], fallback_model: str) -> AssistantTurn:
    """generateContent 响应 JSON → ``AssistantTurn``。"""
    block_reason = (data.get("promptFeedback") or {}).get("blockReason")
    if block_reason:
        raise LLMError(LLMErrorType.UNKNOWN, f"Gemini 请求被安全策略拦截: {block_reason}")

    candidates = data.get("candidates") or []
    if not candidates:
        raise LLMError(LLMErrorType.PARSING, "LLM 返回空响应(无 candidates)")
    candidate = candidates[0]

    text_parts: List[str] = []
    tool_calls: List[ToolCall] = []
    for part in (candidate.get("content") or {}).get("parts") or []:
        if "text" in part:
            text_parts.append(part.get("text") or "")
        elif "functionCall" in part:
            fc = part.get("functionCall") or {}
            tool_calls.append(
                ToolCall(
                    name=fc.get("name") or "",
                    args=fc.get("args") or {},
                    id=None,  # Gemini 原生不返回 id；由运行时按需生成
                )
            )

    finish_reason = _map_finish(candidate.get("finishReason"))
    if tool_calls and finish_reason == "stop":
        finish_reason = "tool_calls"  # Gemini 无独立 tool reason（同 OpenWorker）

    return AssistantTurn(
        text="".join(text_parts),
        tool_calls=tool_calls,
        finish_reason=finish_reason,
        model=data.get("modelVersion") or fallback_model,
        usage=usage_from_gemini(data.get("usageMetadata")),
        raw=data,
    )


# ============================================================================
# Adapter
# ============================================================================


class GeminiProvider(ProviderClient):
    """Gemini generateContent 实现。

    用法::

        provider = GeminiProvider(api_key="AIza...")
        turn = await provider.complete(
            model="gemini-2.5-pro",
            messages=[Message(role=Role.USER, content="hi")],
        )
    """

    #: REST API 版本前缀。
    api_version = "v1beta"

    def __init__(
        self,
        *,
        api_key: str = "",
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 120.0,
        extra_headers: Optional[Dict[str, str]] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._extra_headers = dict(extra_headers or {})
        self._client = client
        self._owns_client = client is None

    def _get_client(self) -> httpx.AsyncClient:
        """惰性创建 httpx client（关闭后可自动重建）。"""
        if self._client is None or self._client.is_closed:
            headers: Dict[str, str] = {"Content-Type": "application/json"}
            if self._api_key:
                headers["x-goog-api-key"] = self._api_key
            headers.update(self._extra_headers)
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers=headers,
                timeout=httpx.Timeout(self._timeout),
            )
            self._owns_client = True
        return self._client

    def _paths(self, model: str) -> Tuple[str, str]:
        """返回 (非流式路径, 流式 SSE 路径)。"""
        prefix = f"/{self.api_version}/models/{model}"
        return f"{prefix}:generateContent", f"{prefix}:streamGenerateContent"

    def _build_body(
        self,
        *,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]],
        tool_choice: Optional[Union[str, Dict[str, Any]]],
        **settings: Any,
    ) -> Dict[str, Any]:
        """组装 generateContent 请求体。"""
        system_instruction, contents = messages_to_gemini(messages)
        body: Dict[str, Any] = {"contents": contents}
        if system_instruction:
            body["systemInstruction"] = system_instruction

        generation_config: Dict[str, Any] = {}
        if settings.get("temperature") is not None:
            generation_config["temperature"] = settings["temperature"]
        if settings.get("max_tokens") is not None:
            generation_config["maxOutputTokens"] = settings["max_tokens"]
        if settings.get("top_p") is not None:
            generation_config["topP"] = settings["top_p"]
        if settings.get("thinking_budget") is not None:
            generation_config["thinkingConfig"] = {"thinkingBudget": settings["thinking_budget"]}
        if generation_config:
            body["generationConfig"] = generation_config

        gemini_tools = tools_to_gemini(tools)
        if gemini_tools:
            body["tools"] = gemini_tools
            choice = tool_choice_to_gemini(tool_choice)
            if choice:
                body["toolConfig"] = {"toolChoice": choice}
        return body

    # -- ProviderClient 实现 ----

    def capabilities(self, model: str) -> ModelCapabilities:
        """Gemini 能力：工具 + 视觉 + 流式 + 推理。"""
        return ModelCapabilities(vision=True, reasoning=True)

    async def complete(
        self,
        *,
        model: str,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        **settings: Any,
    ) -> AssistantTurn:
        """非流式补全。"""
        client = self._get_client()
        path, _ = self._paths(model)
        body = self._build_body(messages=messages, tools=tools, tool_choice=tool_choice, **settings)
        try:
            response = await client.post(path, json=body)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:  # noqa: BLE001 — 统一分类后重抛
            raise_classified_error(exc)
        return turn_from_gemini(data, fallback_model=model)

    async def stream(
        self,
        *,
        model: str,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        **settings: Any,
    ) -> AsyncIterator[StreamChunk]:
        """SSE 流式（``alt=sse``）：逐块 yield 文本增量，末尾 yield 完整 turn。"""
        client = self._get_client()
        _, stream_path = self._paths(model)
        body = self._build_body(messages=messages, tools=tools, tool_choice=tool_choice, **settings)
        usage: Optional[TokenUsage] = None
        text_parts: List[str] = []
        finish_reason: Optional[str] = None
        resp_model = model
        try:
            async with client.stream(
                "POST", stream_path, params={"alt": "sse"}, json=body
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[len("data: ") :].strip()
                    if not payload:
                        continue
                    try:
                        data = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    if data.get("modelVersion"):
                        resp_model = data["modelVersion"]
                    chunk_usage = usage_from_gemini(data.get("usageMetadata"))
                    if chunk_usage is not None:
                        usage = chunk_usage
                    candidates = data.get("candidates") or []
                    if not candidates:
                        continue
                    candidate = candidates[0]
                    for part in (candidate.get("content") or {}).get("parts") or []:
                        piece = part.get("text")
                        if piece:
                            text_parts.append(piece)
                            yield StreamChunk(text_delta=piece)
                    raw_finish = candidate.get("finishReason")
                    if raw_finish:
                        finish_reason = _map_finish(raw_finish)
        except Exception as exc:  # noqa: BLE001 — 统一分类后重抛
            raise_classified_error(exc)
        turn = AssistantTurn(
            text="".join(text_parts),
            finish_reason=finish_reason,
            model=resp_model,
            usage=usage,
        )
        yield StreamChunk(turn=turn)

    async def aclose(self) -> None:
        """关闭自建 httpx client（注入的 client 不动）。"""
        if self._client is not None and self._owns_client and not self._client.is_closed:
            await self._client.aclose()
