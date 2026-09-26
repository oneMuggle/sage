"""Provider 注册表（A2）。

管理 ``ProviderClient`` 子类的注册与实例化，支持按 provider 名称
（``openai`` / ``anthropic`` / ``gemini`` / ``ollama``）查找并构造
对应的客户端实例。

设计要点

- **惰性注册**：provider 子类不在本模块 import，避免启动时加载不需要的
  HTTP 客户端依赖。
- **工厂模式**：每个 provider 注册一个 ``factory``（callable），接收
  ``base_url`` 和 ``api_key`` 两个必选参数，返回 ``ProviderClient`` 实例。
- **线程安全**：注册在启动期完成，运行时只读。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from backend.ports.llm import ProviderClient

logger = logging.getLogger(__name__)

ProviderFactory = Callable[..., ProviderClient]


@dataclass(frozen=True)
class ProviderInfo:
    """Provider 元信息（前端下拉 / discover_models 用）。"""

    id: str
    label: str
    needs_api_key: bool = True
    default_base_url: str = ""
    default_port: Optional[int] = None


class ProviderRegistry:
    """Provider 注册与实例化工厂。

    用法::

        registry = ProviderRegistry()
        registry.register("openai", OpenAIProvider, info=ProviderInfo(...))
        client = registry.create("openai", base_url="https://api.openai.com/v1", api_key="sk-...")
    """

    def __init__(self) -> None:
        self._factories: Dict[str, ProviderFactory] = {}
        self._info: Dict[str, ProviderInfo] = {}

    def register(
        self,
        name: str,
        factory: ProviderFactory,
        *,
        info: Optional[ProviderInfo] = None,
    ) -> None:
        """注册一个 provider。

        Args:
            name:    provider 标识（与 Endpoint.protocol 对齐：openai/anthropic/gemini/ollama）。
            factory: 可调用对象，``(base_url=..., api_key=...)`` → ``ProviderClient``。
            info:    可选元信息（前端展示用）。
        """
        if name in self._factories:
            logger.warning("覆盖已有 provider 注册: %s", name)
        self._factories[name] = factory
        if info is not None:
            self._info[name] = info

    def create(self, name: str, **kwargs: Any) -> ProviderClient:
        """构造指定 provider 的客户端实例。

        Args:
            name:    provider 标识。
            **kwargs: 透传给 factory（通常为 ``base_url`` + ``api_key``）。

        Raises:
            KeyError: provider 未注册。
        """
        factory = self._factories.get(name)
        if factory is None:
            available = ", ".join(sorted(self._factories)) or "(none)"
            raise KeyError(f"未知的 provider {name!r}；可用: {available}")
        return factory(**kwargs)

    def list_available(self) -> List[str]:
        """返回所有已注册 provider 名称（按字母排序）。"""
        return sorted(self._factories.keys())

    def get_info(self, name: str) -> Optional[ProviderInfo]:
        """返回 provider 元信息（未注册返回 None）。"""
        return self._info.get(name)

    def list_info(self) -> List[ProviderInfo]:
        """返回所有已注册 provider 的元信息（按字母排序）。"""
        return [self._info[n] for n in self.list_available() if n in self._info]


# ============================================================================
# 全局单例
# ============================================================================

_default_registry = ProviderRegistry()


def get_registry() -> ProviderRegistry:
    """返回全局 provider 注册表（惰性填充）。"""
    if not _default_registry.list_available():
        _register_builtins(_default_registry)
    return _default_registry


def _register_builtins(registry: ProviderRegistry) -> None:
    """注册内置 provider（惰性导入避免启动副作用）。"""
    # OpenAI 系 —— 包括 OpenAI 官方、Azure OpenAI、各种兼容代理
    from backend.adapters.out.llm.openai_provider import OpenAIProvider

    registry.register(
        "openai",
        OpenAIProvider,
        info=ProviderInfo(
            id="openai",
            label="OpenAI",
            needs_api_key=True,
            default_base_url="https://api.openai.com/v1",
        ),
    )

    # Anthropic —— 直连 Anthropic Messages API
    from backend.adapters.out.llm.anthropic_provider import AnthropicProvider

    registry.register(
        "anthropic",
        AnthropicProvider,
        info=ProviderInfo(
            id="anthropic",
            label="Anthropic",
            needs_api_key=True,
            default_base_url="https://api.anthropic.com",
        ),
    )

    # Google Gemini —— 直连 generateContent API
    from backend.adapters.out.llm.gemini_provider import GeminiProvider

    registry.register(
        "gemini",
        GeminiProvider,
        info=ProviderInfo(
            id="gemini",
            label="Google Gemini",
            needs_api_key=True,
            default_base_url="https://generativelanguage.googleapis.com/v1beta",
        ),
    )

    # Ollama —— 本地推理（OpenAI 兼容端点）
    from backend.adapters.out.llm.ollama_provider import OllamaProvider

    registry.register(
        "ollama",
        OllamaProvider,
        info=ProviderInfo(
            id="ollama",
            label="Ollama",
            needs_api_key=False,
            default_base_url="http://localhost:11434/v1",
            default_port=11434,
        ),
    )
