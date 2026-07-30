"""Ollama（本地推理）Provider adapter（A2）。

Ollama 暴露 OpenAI 兼容端点 ``/v1/chat/completions``，因此
``OllamaProvider`` 直接继承 ``OpenAIProvider``，仅调整默认配置与
能力标志：

- 默认 ``base_url`` 指向本机 ``http://localhost:11434/v1``
- 默认不带 API key（本地推理无需鉴权）
- usage 无缓存分片 → ``cache_read`` / ``cache_write`` 恒 0
  （``usage_from_openai`` 在缺少 ``prompt_tokens_details`` 时天然置 0）
- 本地模型并行工具调用支持参差，默认保守关闭
"""

from __future__ import annotations

from typing import Any

from backend.adapters.out.llm.openai import OpenAIProvider
from backend.ports.llm import ModelCapabilities

__all__ = ["OllamaProvider", "DEFAULT_BASE_URL"]

DEFAULT_BASE_URL = "http://localhost:11434/v1"


class OllamaProvider(OpenAIProvider):
    """Ollama 本地推理实现（OpenAI 兼容端点）。

    用法::

        provider = OllamaProvider()  # 默认连本机 11434
        turn = await provider.complete(
            model="llama3.3",
            messages=[Message(role=Role.USER, content="hi")],
        )
    """

    #: 本地模型并行工具调用支持参差，保守默认关闭。
    default_capabilities = ModelCapabilities(parallel_tool_calls=False)

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str = "",
        timeout: float = 300.0,  # 本地推理（CPU / 小显存）可能很慢
        **kwargs: Any,
    ) -> None:
        super().__init__(api_key=api_key, base_url=base_url, timeout=timeout, **kwargs)

    def capabilities(self, model: str) -> ModelCapabilities:
        """Ollama 能力：无并行工具调用；视觉取决于具体模型，默认关闭。"""
        return self.default_capabilities
