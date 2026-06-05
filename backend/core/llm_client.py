"""
LLM Client - 大语言模型客户端
支持 OpenAI-compatible API 协议，兼容多种提供商
"""
import json
import time
import logging
from typing import List, Dict, Any, Optional, AsyncGenerator
from dataclasses import dataclass, field

import httpx

from backend.core.errors import LLMError, LLMErrorType

logger = logging.getLogger(__name__)


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
    provider: str = "openai"  # openai, claude, ollama, custom
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-3.5-turbo"
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: int = 60
    extra_headers: Dict[str, str] = field(default_factory=dict)


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
        """获取或创建 HTTP 客户端"""
        if self._client is None or self._client.is_closed:
            headers = {
                "Content-Type": "application/json",
            }
            if self.config.api_key:
                headers["Authorization"] = f"Bearer {self.config.api_key}"
            headers.update(self.config.extra_headers)

            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
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
            result.append(LLMToolCall(
                id=tc.get("id", ""),
                name=tc["function"]["name"],
                arguments=tc["function"].get("arguments", "{}"),
            ))
        return result

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

        start_time = time.time()

        try:
            response = await client.post("/chat/completions", json=body)
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
                raise LLMError(LLMErrorType.RATE_LIMITED, "请求过于频繁，请稍后再试", retry_after=retry_after)
            elif 500 <= status < 600:
                raise LLMError(LLMErrorType.SERVER_ERROR, f"LLM 服务端错误 (HTTP {status})", status_code=status)
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

        tool_calls = []
        if msg_data.get("tool_calls"):
            tool_calls = self._parse_tool_calls(msg_data["tool_calls"])

        usage = data.get("usage", {})

        return LLMResponse(
            content=content,
            model=data.get("model", self.config.model),
            finish_reason=choice.get("finish_reason"),
            tool_calls=tool_calls,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            raw=data,
        )

    async def chat_stream(
        self, messages: List[Dict[str, Any]]
    ) -> AsyncGenerator[str, None]:
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

        try:
            async with client.stream("POST", "/chat/completions", json=body) as response:
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
