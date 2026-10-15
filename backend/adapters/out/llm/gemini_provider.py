"""Google Gemini Provider 适配器（A2）。

实现 ``ProviderClient`` ABC，直连 Gemini ``generateContent`` 端点。

设计要点

- **零 SDK 依赖**：只用 ``httpx``，不引入 ``google-generativeai`` 包。
- **认证**：API key 通过 query param ``?key=`` 传递（Gemini 惯例）。
- **消息格式**：Gemini 用 ``contents[]`` + ``parts[]``，role 为 ``user``/``model``
  （无 ``assistant``），工具调用用 ``functionCall`` 字段。
- **Usage**：``usageMetadata`` 中 ``promptTokenCount`` / ``candidatesTokenCount`` /
  ``cachedContentTokenCount``（→ ``cache_read``）/
  ``thoughtsTokenCount``（→ ``output``，与正常 output 合并）。
- **流式**：``streamGenerateContent?alt=sse`` 返回 SSE，每块含一个完整 candidate。
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional, Union

import httpx
from sage_core import Message, Role, ToolCall

from backend.ports.llm import (
    AssistantTurn,
    ModelCapabilities,
    ProviderClient,
    StreamChunk,
    TokenUsage,
)

logger = logging.getLogger(__name__)

# Gemini finishReason → 统一词汇
_FINISH_REASON_MAP = {
    "STOP": "stop",
    "MAX_TOKENS": "length",
    "SAFETY": "stop",
    "RECITATION": "stop",
    "OTHER": "stop",
    "FUNCTION_CALL": "tool_calls",  # 旧版；新版用 tool_use
}


class GeminiProvider(ProviderClient):
    """Google Gemini provider。

    Args:
        base_url: API 基础 URL（默认 ``https://generativelanguage.googleapis.com/v1beta``）。
        api_key:  API key（通过 ``?key=`` 传递）。
        timeout:  请求超时秒数（默认 120）。
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout: float = 120.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = httpx.AsyncClient(timeout=timeout)

    def _model_url(self, model: str, *, stream: bool = False) -> str:
        """构造 model-specific URL。"""
        action = "streamGenerateContent" if stream else "generateContent"
        return f"{self._base_url}/models/{model}:{action}"

    def _auth_params(self) -> Dict[str, str]:
        return {"key": self._api_key}

    # ------------------------------------------------------------------ #
    # ProviderClient 抽象方法实现
    # ------------------------------------------------------------------ #

    async def complete(
        self,
        *,
        model: str,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        **settings: Any,
    ) -> AssistantTurn:
        body = self._build_body(
            messages=messages, tools=tools, tool_choice=tool_choice, **settings
        )
        response = await self._client.post(
            self._model_url(model),
            json=body,
            params=self._auth_params(),
        )
        response.raise_for_status()
        data = response.json()
        return self._parse_response(data, model=model)

    async def stream(
        self,
        *,
        model: str,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        **settings: Any,
    ) -> AsyncIterator[StreamChunk]:
        body = self._build_body(
            messages=messages, tools=tools, tool_choice=tool_choice, **settings
        )
        async with self._client.stream(
            "POST",
            self._model_url(model, stream=True),
            json=body,
            params={**self._auth_params(), "alt": "sse"},
        ) as response:
            response.raise_for_status()
            async for chunk in self._iter_sse(response, model=model):
                yield chunk

    def capabilities(self, model: str) -> ModelCapabilities:
        lower = model.lower()
        # Gemini 2.5+ 支持 vision / reasoning / tools
        vision = "gemini" in lower  # 所有 Gemini 模型都支持 vision
        reasoning = "2.5" in lower or "flash-thinking" in lower
        return ModelCapabilities(
            tools=True,
            vision=vision,
            streaming=True,
            parallel_tool_calls=True,
            reasoning=reasoning,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ #
    # 内部辅助
    # ------------------------------------------------------------------ #

    def _build_body(
        self,
        *,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]],
        tool_choice: Optional[Union[str, Dict[str, Any]]],
        **settings: Any,
    ) -> Dict[str, Any]:
        # 分离 system instruction 与对话内容
        system_instruction: Optional[str] = None
        contents: List[Dict[str, Any]] = []
        for msg in messages:
            role = msg.role.value if isinstance(msg.role, Role) else str(msg.role)
            if role == "system":
                system_instruction = msg.content
                continue
            contents.append(_serialize_message(msg))

        body: Dict[str, Any] = {"contents": contents}
        if system_instruction is not None:
            body["systemInstruction"] = {
                "parts": [{"text": system_instruction}],
            }
        # 生成配置
        generation_config: Dict[str, Any] = {}
        if "temperature" in settings:
            generation_config["temperature"] = settings["temperature"]
        if "max_tokens" in settings:
            generation_config["maxOutputTokens"] = settings["max_tokens"]
        if "top_p" in settings:
            generation_config["topP"] = settings["top_p"]
        if "thinking_budget" in settings:
            generation_config["thinkingConfig"] = {
                "thinkingBudget": settings["thinking_budget"],
            }
        if generation_config:
            body["generationConfig"] = generation_config
        # 工具
        if tools:
            body["tools"] = [
                {
                    "functionDeclarations": [
                        _convert_tool_to_gemini(t) for t in tools
                    ]
                }
            ]
        return body

    def _parse_response(self, data: Dict[str, Any], *, model: str) -> AssistantTurn:
        candidates = data.get("candidates", [])
        if not candidates:
            return AssistantTurn(model=model, raw=data)

        candidate = candidates[0]
        content = candidate.get("content", {})
        parts = content.get("parts", [])

        text_parts: List[str] = []
        tool_calls: List[ToolCall] = []
        reasoning_parts: List[str] = []

        for part in parts:
            if "text" in part:
                # 思考内容在 thought: true 的 part 里
                if part.get("thought"):
                    reasoning_parts.append(part["text"])
                else:
                    text_parts.append(part["text"])
            elif "functionCall" in part:
                fc = part["functionCall"]
                tool_calls.append(
                    ToolCall(
                        name=fc.get("name", ""),
                        args=fc.get("args", {}),
                        id=None,  # Gemini functionCall 无原生 id
                    )
                )

        text = "".join(text_parts) or None
        reasoning = "".join(reasoning_parts) or None
        raw_reason = candidate.get("finishReason", "")
        finish_reason = _FINISH_REASON_MAP.get(
            raw_reason, raw_reason.lower() if raw_reason else None
        )
        usage = _parse_usage(data.get("usageMetadata"))

        return AssistantTurn(
            text=text,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            reasoning=reasoning,
            model=model,
            usage=usage,
            raw=data,
        )

    async def _iter_sse(
        self, response: httpx.Response, *, model: str
    ) -> AsyncIterator[StreamChunk]:
        """解析 Gemini SSE 流。"""
        buf = b""
        async for raw_chunk in response.aiter_bytes():
            buf += raw_chunk
            while b"\n\n" in buf:
                event_bytes, buf = buf.split(b"\n\n", 1)
                event_text = event_bytes.decode("utf-8", errors="replace")
                for line in event_text.splitlines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[len("data:"):].strip()
                    if not payload:
                        continue
                    try:
                        data = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    chunk = self._parse_stream_chunk(data, model=model)
                    if chunk is not None:
                        yield chunk

    def _parse_stream_chunk(
        self, data: Dict[str, Any], *, model: str
    ) -> Optional[StreamChunk]:
        candidates = data.get("candidates", [])
        if not candidates:
            return None
        candidate = candidates[0]
        parts = candidate.get("content", {}).get("parts", [])

        text_delta: Optional[str] = None
        reasoning_delta: Optional[str] = None
        for part in parts:
            if "text" in part:
                if part.get("thought"):
                    reasoning_delta = part["text"]
                else:
                    text_delta = part["text"]

        finish_reason_raw = candidate.get("finishReason")
        turn: Optional[AssistantTurn] = None
        if finish_reason_raw is not None:
            usage = _parse_usage(data.get("usageMetadata"))
            finish_reason = _FINISH_REASON_MAP.get(
                finish_reason_raw,
                finish_reason_raw.lower() if finish_reason_raw else None,
            )
            turn = AssistantTurn(
                finish_reason=finish_reason,
                model=model,
                usage=usage,
                raw=data,
            )

        return StreamChunk(
            text_delta=text_delta,
            reasoning_delta=reasoning_delta,
            turn=turn,
        )


# ============================================================================
# 模块级辅助
# ============================================================================


def _serialize_message(msg: Message) -> Dict[str, Any]:
    """``domain.Message`` → Gemini contents[] 元素。

    Gemini role 映射：``user`` → ``user``、``assistant`` → ``model``、
    ``tool`` → ``function`` (functionResponse part)。
    """
    role = msg.role.value if isinstance(msg.role, Role) else str(msg.role)

    if role == "tool" or msg.tool_call_id is not None:
        # functionResponse：name 是工具名，response 是 dict
        return {
            "role": "function",
            "parts": [
                {
                    "functionResponse": {
                        "name": msg.tool_call_id or "unknown",
                        "response": {"result": msg.content},
                    }
                }
            ],
        }

    gemini_role = "model" if role == "assistant" else "user"
    parts: List[Dict[str, Any]] = []
    if msg.content:
        parts.append({"text": msg.content})
    if msg.tool_calls:
        for tc in msg.tool_calls:
            parts.append(
                {
                    "functionCall": {
                        "name": tc.name,
                        "args": tc.args,
                    }
                }
            )
    return {"role": gemini_role, "parts": parts}


def _convert_tool_to_gemini(tool: Dict[str, Any]) -> Dict[str, Any]:
    """OpenAI 风格 tool schema → Gemini functionDeclaration。"""
    fn = tool.get("function", tool)
    return {
        "name": fn.get("name", ""),
        "description": fn.get("description", ""),
        "parameters": fn.get("parameters", {"type": "object", "properties": {}}),
    }


def _parse_usage(raw: Optional[Dict[str, Any]]) -> Optional[TokenUsage]:
    """Gemini usageMetadata → TokenUsage。

    字段映射：
    - ``promptTokenCount`` → input
    - ``candidatesTokenCount`` → output（基础）
    - ``thoughtsTokenCount`` → 累加到 output（Gemini 把 thinking token 按 output 计费）
    - ``cachedContentTokenCount`` → cache_read
    """
    if not raw:
        return None
    output = raw.get("candidatesTokenCount", 0)
    # Gemini 2.5 起 thoughtsTokenCount 单独报告
    thoughts = raw.get("thoughtsTokenCount", 0)
    return TokenUsage(
        input=raw.get("promptTokenCount", 0),
        output=output + thoughts,
        cache_read=raw.get("cachedContentTokenCount", 0),
    )
