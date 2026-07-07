"""
LLM Client - 大语言模型客户端
支持 OpenAI-compatible API 协议，兼容多种提供商
"""

from __future__ import annotations
from typing import Dict, List, Optional, Tuple

import json
import logging
import os
import re
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

import httpx

from backend.core.errors import LLMError, LLMErrorType

logger = logging.getLogger(__name__)

# 预编译：提取 LLM 输出中的 <think>...</think> 推理块。
# 部分 provider（如 DeepSeek）把推理内容用此标签包裹在 content 字段中。
THINK_TAG_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL)


@dataclass
class LLMMessage:
    """单条对话消息"""

    role: str  # "system" | "user" | "assistant" | "tool"
    content: str
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None


@dataclass
class LLMToolCall:
    """工具调用"""

    id: str
    name: str
    arguments: str  # JSON string


@dataclass
class LLMChoice:
    """单条回复选项"""

    message: LLMMessage
    finish_reason: Optional[str] = None
    tool_calls: Optional[List[LLMToolCall]] = None


@dataclass
class LLMResponse:
    """LLM 回复"""

    content: str = ""
    reasoning_content: Optional[str] = (
        None  # LLM 思考/推理过程（Claude extended thinking, o1 reasoning 等）
    )
    model: str = ""
    finish_reason: Optional[str] = None
    tool_calls: List[LLMToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    raw: Optional[Dict[str, Any]] = None


@dataclass
class LLMConfig:
    """LLM 连接配置"""

    provider: str = "openai"  # openai, claude, gemini, deepseek, ollama, custom
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-3.5-turbo"
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: int = 60
    # 推理参数（覆盖 commit #38 之前的硬编码 "custom" provider 路径，
    # 让用户在前端选的真实 provider 透传到 LLMClient，并启用 thinking 输出）
    reasoning_effort: Optional[str] = None  # OpenAI o1/o3/5: "low" | "medium" | "high"
    thinking_budget: Optional[int] = None  # Gemini 2.5: 思考 token 上限,0 关闭,-1 动态
    extra_headers: Dict[str, str] = field(default_factory=dict)
    # === v2: LLM proxy 路由 ===
    # 为统一「测试连接」与「chat」两条路径的 baseUrl 解析规则（避免 baseUrl 是否
    # 包含 `/v1` 后缀的二义性），所有 LLM HTTP 调用现在走本机 FastAPI 上的
    # `/api/v1/llm/*` 反向代理。`base_url` 仍然是用户填的真实上游 URL（用于
    # 构造 `X-LLM-Provider-Url` header），`backend_url` 是本机后端地址（默认
    # 从环境变量 `BACKEND_URL` 读取，否则 `http://127.0.0.1:8765`）。
    # 当 `use_proxy=False` 时，绕过 proxy 直连上游 — 仅用于单测（respx mock
    # 直接拦截上游调用，简化 fixture）。
    backend_url: str = field(
        default_factory=lambda: os.environ.get("BACKEND_URL", "http://127.0.0.1:8765")
    )
    use_proxy: bool = True


class LLMClient:
    """
    LLM 客户端，支持 OpenAI-compatible API

    用法:
        config = LLMConfig(
            provider="openai",
            api_key="sk-xxx",
            model="gpt-4"
        )
        client = LLMClient(config)
        response = await client.chat(messages)
    """

    def __init__(self, config: LLMConfig):
        self.config = config
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端

        v2: 默认走本机 LLM proxy (`<backend_url>/api/v1/llm`),把真实上游 URL
        通过 `X-LLM-Provider-Url` header 注入,与前端"测试连接"走同一通路。
        单测场景下 `LLMConfig(use_proxy=False)` 切回直连上游,保持 fixture 简洁。
        """
        if self._client is None or self._client.is_closed:
            headers: Dict[str, str] = {"Content-Type": "application/json"}

            if self.config.use_proxy:
                backend = (self.config.backend_url or "http://127.0.0.1:8765").rstrip("/")
                client_base_url = f"{backend}/api/v1/llm"
                headers["X-LLM-Provider-Url"] = self.config.base_url
            else:
                client_base_url = self.config.base_url

            if self.config.api_key:
                headers["Authorization"] = f"Bearer {self.config.api_key}"
            headers.update(self.config.extra_headers)

            self._client = httpx.AsyncClient(
                base_url=client_base_url,
                headers=headers,
                timeout=httpx.Timeout(self.config.timeout),
            )
        return self._client

    async def close(self):
        """关闭 HTTP 客户端"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    @staticmethod
    def _convert_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """转换消息格式"""
        result = []
        for msg in messages:
            entry = {"role": msg["role"], "content": msg["content"]}
            if "tool_calls" in msg:
                entry["tool_calls"] = msg["tool_calls"]
            if "tool_call_id" in msg:
                entry["tool_call_id"] = msg["tool_call_id"]
            result.append(entry)
        return result

    @staticmethod
    def _parse_tool_calls(raw_tool_calls: list) -> List[LLMToolCall]:
        """解析工具调用"""
        result = []
        for tc in raw_tool_calls:
            result.append(
                LLMToolCall(
                    id=tc.get("id", ""),
                    name=tc["function"]["name"],
                    arguments=tc["function"].get("arguments", "{}"),
                )
            )
        return result

    @staticmethod
    def _extract_think_tags(content: str) -> Tuple[Optional[str], str]:
        """
        从 content 中提取 <think>...</think> 标签内容。

        Args:
            content: LLM 输出的原始内容

        Returns:
            (reasoning_content, clean_content) 元组
            - reasoning_content: 提取的思考内容，无标签则为 None
            - clean_content: 移除 <think> 标签后的内容
        """
        matches = THINK_TAG_RE.findall(content)

        if not matches:
            # 没有 <think> 标签
            return None, content

        # 合并所有思考内容
        reasoning = "".join(matches)

        # 从 content 中移除所有 <think> 标签
        clean_content = THINK_TAG_RE.sub("", content)

        return reasoning, clean_content

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
    ) -> LLMResponse:
        """
        发送聊天请求（非流式）

        Args:
            messages: 消息列表，每条包含 role 和 content
            tools: OpenAI 格式工具 schema 列表（可选）
            tool_choice: "auto" | "none" | "required"（默认 "auto"，仅当 tools 非空时写入请求体）

        Returns:
            LLM 回复
        """
        client = self._get_client()

        body = {
            "model": self.config.model,
            "messages": self._convert_messages(messages),
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }

        if tools:
            body["tools"] = tools
            body["tool_choice"] = tool_choice or "auto"

        if self.config.provider == "claude":
            body["max_tokens"] = self.config.max_tokens

        # 推理参数透传: provider 决定哪种 key 会被上游接受
        # - OpenAI o1/o3/5 + DeepSeek + 多数 OpenAI 兼容代理: reasoning_effort
        # - Gemini 2.5 (OpenAI 兼容模式): thinking_budget
        # 同时存在时,让上游自己挑(不同 provider 接受不同 key)
        if self.config.reasoning_effort is not None:
            body["reasoning_effort"] = self.config.reasoning_effort
        if self.config.thinking_budget is not None:
            body["thinking_budget"] = self.config.thinking_budget

        start_time = time.time()

        try:
            response = await client.post("/v1/chat/completions", json=body)
            response.raise_for_status()
            data = response.json()
        except httpx.TimeoutException as e:
            logger.error(f"LLM 请求超时: {e}")
            raise LLMError(LLMErrorType.TIMEOUT, f"请求 LLM 超时: {e}")
        except httpx.ConnectError as e:
            logger.error(f"LLM 连接失败: {e}")
            raise LLMError(LLMErrorType.NETWORK, f"无法连接 LLM: {e}")
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status == 401:
                raise LLMError(LLMErrorType.AUTH_FAILED, "API Key 无效或过期", status_code=401)
            elif status == 429:
                retry_after = None
                try:
                    retry_after = int(e.response.headers.get("retry-after", "0")) or None
                except (ValueError, TypeError):
                    retry_after = None
                raise LLMError(
                    LLMErrorType.RATE_LIMITED, "请求过于频繁，请稍后再试", retry_after=retry_after
                )
            elif 500 <= status < 600:
                raise LLMError(
                    LLMErrorType.SERVER_ERROR, f"LLM 服务端错误 (HTTP {status})", status_code=status
                )
            else:
                raise LLMError(LLMErrorType.UNKNOWN, f"LLM HTTP 错误: {status}", status_code=status)
        except (ValueError, KeyError) as e:
            logger.error(f"LLM 响应解析失败: {e}")
            raise LLMError(LLMErrorType.PARSING, f"LLM 响应格式异常: {e}")
        except Exception as e:
            logger.error(f"LLM 请求未知失败: {e}")
            raise LLMError(LLMErrorType.UNKNOWN, f"LLM 请求失败: {e}")

        elapsed = time.time() - start_time
        logger.debug(f"LLM 响应耗时: {elapsed:.2f}s")

        choices = data.get("choices", [])
        if not choices:
            raise LLMError(LLMErrorType.PARSING, "LLM 返回空响应(无 choices)")

        choice = choices[0]
        msg_data = choice.get("message", {})
        content = msg_data.get("content", "")

        # 提取 reasoning_content（多提供商兼容）
        # Anthropic Claude 使用 reasoning_content 字段
        # OpenAI o1/o3 使用 reasoning 或 reasoning_content 字段
        # DeepSeek 使用 reasoning_content 字段
        # 优先使用 reasoning_content，其次 reasoning
        reasoning_content = msg_data.get("reasoning_content") or msg_data.get("reasoning")

        # 某些 LLM 提供商（如 DeepSeek）会把思考内容用 <think> 标签包裹在 content 中
        # 始终清理 content 中的 <think> 标签，无论 reasoning_content 字段是否存在
        if content:
            parsed_reasoning, parsed_content = self._extract_think_tags(content)
            # 如果 reasoning_content 字段为空，使用解析出的思考内容
            if not reasoning_content and parsed_reasoning is not None:
                reasoning_content = parsed_reasoning
            # 更新 content（移除 <think> 标签）
            content = parsed_content

        tool_calls = []
        if msg_data.get("tool_calls"):
            tool_calls = self._parse_tool_calls(msg_data["tool_calls"])

        usage = data.get("usage", {})

        return LLMResponse(
            content=content,
            reasoning_content=reasoning_content,
            model=data.get("model", self.config.model),
            finish_reason=choice.get("finish_reason"),
            tool_calls=tool_calls,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            raw=data,
        )

    async def chat_stream(self, messages: List[Dict[str, Any]]) -> AsyncGenerator[str, None]:
        """
        发送聊天请求（流式）

        Note: 流式响应暂抛出 RuntimeError，Task 11 将统一改为 LLMError 分类。

        Args:
            messages: 消息列表

        Yields:
            每个 chunk 的文本内容
        """
        client = self._get_client()

        body = {
            "model": self.config.model,
            "messages": self._convert_messages(messages),
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "stream": True,
        }

        if self.config.reasoning_effort is not None:
            body["reasoning_effort"] = self.config.reasoning_effort
        if self.config.thinking_budget is not None:
            body["thinking_budget"] = self.config.thinking_budget

        try:
            async with client.stream("POST", "/v1/chat/completions", json=body) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue

                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break

                    try:
                        data = json.loads(data_str)
                        choices = data.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                    except json.JSONDecodeError:
                        continue

        except httpx.HTTPStatusError as e:
            logger.error(f"LLM 流式请求 HTTP 错误: {e.response.status_code}")
            raise RuntimeError(f"LLM 流式请求错误: {e.response.status_code}")
        except Exception as e:
            logger.error(f"LLM 流式请求失败: {e}")
            raise RuntimeError(f"LLM 流式请求失败: {e}")

    async def complete(self, prompt: str) -> str:
        """
        简单补全接口

        Args:
            prompt: 提示文本

        Returns:
            补全结果文本
        """
        messages = [{"role": "user", "content": prompt}]
        response = await self.chat(messages)
        return response.content

    def to_dict(self) -> Dict[str, Any]:
        """导出配置信息"""
        return {
            "provider": self.config.provider,
            "model": self.config.model,
            "base_url": self.config.base_url,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
