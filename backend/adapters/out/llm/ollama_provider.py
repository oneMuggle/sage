"""Ollama Provider 适配器（A2）。

实现 ``ProviderClient`` ABC，使用 Ollama 的 OpenAI 兼容端点
``/v1/chat/completions``。

设计要点

- **继承 OpenAIProvider**：Ollama 的聊天端点与 OpenAI 协议兼容，
  继承 OpenAIProvider 并覆盖差异部分（认证、usage 字段名）。
- **无 API key**：Ollama 默认无认证，但支持可选的 ``Authorization`` 头
  （用于反向代理场景）。
- **Usage 字段**：Ollama 原生用 ``prompt_eval_count``/``eval_count``；
  通过 OpenAI 兼容端点时返回 ``usage.prompt_tokens``/``completion_tokens``。
- **discover_models()**：额外提供 ``/api/tags`` 端点查询本地模型列表。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

import httpx

from backend.adapters.out.llm.openai_provider import OpenAIProvider
from backend.ports.llm import ModelCapabilities

logger = logging.getLogger(__name__)


@dataclass
class DiscoveredModel:
    """discover_models() 返回的模型信息。"""

    id: str
    name: str
    # 粗略能力标志（Ollama /api/tags 不直接报告，需要解析 model details）
    supports_tools: bool = False
    size: Optional[int] = None  # 模型文件大小（bytes）


# Ollama 上的 embedding / rerank 类模型——不接受 image input，需先排除。
_OLLAMA_NON_VISION_MARKERS = ("embed", "rerank", "minilm")

# 已知支持 image input 的 Ollama 模型族：
#   llava* / bakllava / moondream  —— 经典视觉模型
#   *vision* / llama3.2-vision    —— Llama 视觉变体
#   qwen2.5-vl / minicpm-v         —— VL 后缀族
#   glm-4v / internvl              —— GLM / InternVL 视觉模型
#   gemma3 / phi4                  —— Gemma 3 起、Phi 4 多模态
_OLLAMA_VISION_MARKERS = (
    "llava",
    "vision",
    "vl",
    "4v",
    "internvl",
    "moondream",
    "minicpm-v",
    "gemma3",
    "phi4",
)

# 支持 tools 的 Ollama 模型族（llama3/4、mistral、qwen2/3、command-r、hermes）
_OLLAMA_TOOL_MARKERS = (
    "llama3",
    "llama4",
    "mistral",
    "qwen2",
    "qwen3",
    "command-r",
    "hermes",
)


def model_capabilities(model: str) -> ModelCapabilities:
    """推断 Ollama 模型的能力（纯函数，不构造 HTTP 客户端）。

    Ollama 的 ``/api/tags`` 不上报能力元数据，只能按模型名启发式判定；
    未命中的模型按不支持处理，调用方据此走降级而非直接注入图片。

    Args:
        model: Ollama 模型名，如 ``"qwen2.5-vl:7b"`` / ``"llama3.1:8b"``。

    Returns:
        ModelCapabilities：``vision`` 为启发式判定，非权威声明。
    """
    lower = (model or "").lower()
    is_non_vision = any(marker in lower for marker in _OLLAMA_NON_VISION_MARKERS)
    supports_tools = any(marker in lower for marker in _OLLAMA_TOOL_MARKERS)
    vision = not is_non_vision and any(marker in lower for marker in _OLLAMA_VISION_MARKERS)
    return ModelCapabilities(
        tools=supports_tools,
        vision=vision,
        streaming=True,
        parallel_tool_calls=supports_tools,
        reasoning=False,  # Ollama 暂不支持原生 reasoning
    )


class OllamaProvider(OpenAIProvider):
    """Ollama 本地推理 provider。

    继承 ``OpenAIProvider``（Ollama 兼容 OpenAI 聊天端点），
    覆盖认证与 usage 解析的差异。

    Args:
        base_url: Ollama 基础 URL（默认 ``http://localhost:11434/v1``）。
        api_key:  可选 API key（用于反向代理场景；Ollama 原生无需）。
        timeout:  请求超时秒数（默认 300 —— 本地推理可能较慢）。
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str = "",
        timeout: float = 300.0,
    ) -> None:
        # Ollama OpenAI 兼容端点在 /v1 下
        super().__init__(base_url=base_url, api_key=api_key, timeout=timeout)
        # 原生 Ollama API 基础 URL（去掉 /v1 后缀）
        self._ollama_base = base_url.rstrip("/")
        if self._ollama_base.endswith("/v1"):
            self._ollama_base = self._ollama_base[:-3]

    def capabilities(self, model: str) -> ModelCapabilities:
        return model_capabilities(model)

    async def discover_models(self) -> List[DiscoveredModel]:
        """查询 Ollama 本地已下载模型列表。

        使用 ``/api/tags`` 端点（Ollama 原生 API，非 OpenAI 兼容）。
        """
        try:
            response = await self._client.get(
                f"{self._ollama_base}/api/tags",
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            logger.warning("Ollama /api/tags 请求失败: %s", exc)
            return []

        models: List[DiscoveredModel] = []
        for raw in data.get("models", []):
            name = raw.get("name", "")
            # Ollama model name 格式如 "llama3.1:latest" / "qwen2.5:7b"
            model_id = name.split(":")[0] if name else ""
            models.append(
                DiscoveredModel(
                    id=model_id,
                    name=name,
                    supports_tools=self.capabilities(model_id).tools,
                    size=raw.get("size"),
                )
            )
        return models


# Ollama 通过 OpenAI 兼容端点返回标准 OpenAI usage 格式
# （prompt_tokens / completion_tokens），因此不需要覆盖 _parse_usage。
# 但如果用户使用 Ollama 原生 /api/chat 端点（不在本适配器范围内），
# usage 字段名为 prompt_eval_count / eval_count。
