"""ProviderRouter —— 按 model name 前缀路由的 ``ProviderClient``（A2 / A20）。

借鉴 OpenWorker ``coworker/providers/router.py``：对外是**单个**
``ProviderClient``，内部按 model 字符串的 ``provider:`` 前缀分发到
per-provider client。每次 ``complete`` / ``stream`` 调用自带完整 model
字符串，因此路由是自描述的：

- ``anthropic:claude-sonnet-4-5``  → Anthropic client，委派时剥前缀为 ``claude-sonnet-4-5``
- ``openai:gpt-4o``                → OpenAI client，委派时剥前缀为 ``gpt-4o``
- ``gemini:gemini-2.5-pro``        → Gemini client
- ``ollama:llama3.3``              → Ollama client，委派时剥前缀为 ``llama3.3``
- 裸 ``gpt-4o``                     → default provider（默认 openai）
- ``qwen2.5-coder:32b``            → 前缀不是已注册 provider（是版本 tag），
                                     按裸名走 default，model 原样保留

client 通过工厂**惰性构建**并缓存：注册的是零参工厂时，首次用到该
provider 才真正实例化（避免为永不使用的 provider 建连）。配置变更
（换 key / 换 base_url）调用 ``invalidate()`` 丢弃缓存 client，下一次
调用即按新配置重建 —— 调用方无需重建 router。

分层约束（import-linter hexagonal）：application 层只依赖 ports 与
domain，**不 import adapters** —— 具体 client 由装配层（api / main）
通过 ``register`` 注入。
"""

from __future__ import annotations

import logging
import threading
from collections.abc import AsyncIterator
from typing import Any, Callable, Dict, List, Mapping, Optional, Union

from sage_core import Message

from backend.ports.llm import (
    AssistantTurn,
    ModelCapabilities,
    ProviderClient,
    StreamChunk,
)

logger = logging.getLogger(__name__)

#: 惰性构建工厂：零参 callable，返回一个 ProviderClient。
ProviderFactory = Callable[[], ProviderClient]

#: 常见别名 → 规范 provider 名（注册与路由两侧都生效）。
DEFAULT_PROVIDER_ALIASES: Dict[str, str] = {
    "claude": "anthropic",
    "google": "gemini",
}


class UnknownProviderError(ValueError):
    """请求路由到一个未注册的 provider。"""


def _split_prefix(model: str) -> Optional[str]:
    """提取 ``prefix:rest`` 的 prefix；无冒号返回 None。"""
    prefix, sep, _ = model.partition(":")
    return prefix if sep and prefix else None


class ProviderRouter(ProviderClient):
    """按 model name 路由到 per-provider client 的分发器。

    用法::

        router = ProviderRouter(default_provider="openai")
        router.register("openai", lambda: OpenAIProvider(api_key=...))
        router.register("anthropic", lambda: AnthropicProvider(api_key=...))

        turn = await router.complete(
            model="anthropic:claude-sonnet-4-5",
            messages=[Message(role=Role.USER, content="hi")],
        )
    """

    def __init__(
        self,
        *,
        default_provider: str = "openai",
        aliases: Optional[Mapping[str, str]] = None,
        on_use: Optional[Callable[[str], None]] = None,
    ) -> None:
        """初始化路由器。

        Args:
            default_provider: 裸 model name（无已知前缀）路由到的 provider。
            aliases:          附加别名映射（并入 ``DEFAULT_PROVIDER_ALIASES``）。
            on_use:           每次分发时触发的 ``callback(provider_name)``，
                              例如驱动设置页"最近使用"。Best-effort：其异常
                              永远不中断模型调用。
        """
        self._default = default_provider
        self._aliases: Dict[str, str] = dict(DEFAULT_PROVIDER_ALIASES)
        if aliases:
            self._aliases.update(aliases)
        self._factories: Dict[str, ProviderFactory] = {}
        self._clients: Dict[str, ProviderClient] = {}
        # dict 上的惰性构建/失效可能并发发生（多个请求同时首访同一
        # provider）；锁内不含 await，无死锁风险。
        self._lock = threading.Lock()
        self._on_use = on_use

    # -- 注册 / 失效 -----------------------------------------------------

    def register(
        self,
        name: str,
        factory_or_client: Union[ProviderClient, ProviderFactory],
    ) -> None:
        """注册 provider：接受 client 实例（即时生效）或零参工厂（惰性构建）。

        重复注册同一 name 会丢弃已缓存的旧 client，下一次调用按新工厂重建。
        """
        name = self._canonical(name)
        if isinstance(factory_or_client, ProviderClient):
            client = factory_or_client

            def _factory(_client: ProviderClient = client) -> ProviderClient:
                return _client

            factory: ProviderFactory = _factory
        elif callable(factory_or_client):
            factory = factory_or_client
        else:
            raise TypeError(
                "register() 需要 ProviderClient 实例或零参工厂，"
                f"收到: {type(factory_or_client).__name__}"
            )
        with self._lock:
            self._factories[name] = factory
            self._clients.pop(name, None)

    def invalidate(self, name: Optional[str] = None) -> None:
        """丢弃缓存 client，使下一次调用按当前工厂重建。

        ``name=None`` 清空全部；配置变更（新 key / 新 base_url）后调用。
        """
        with self._lock:
            if name is None:
                self._clients.clear()
            else:
                self._clients.pop(self._canonical(name), None)

    @property
    def providers(self) -> List[str]:
        """已注册的 provider 名（规范名，排序后返回）。"""
        with self._lock:
            return sorted(self._factories)

    # -- 路由 -------------------------------------------------------------

    def provider_name(self, model: str) -> str:
        """model 字符串路由到的 provider 名。

        ``prefix:rest`` 且 prefix 是已注册 provider（或别名）→ 该 provider；
        否则 → default provider（裸名，或冒号前缀不是 provider 的情形，
        如 ``qwen2.5-coder:32b`` 的版本 tag）。
        """
        prefix = _split_prefix(model)
        if prefix is not None:
            candidate = self._canonical(prefix)
            with self._lock:
                if candidate in self._factories:
                    return candidate
        return self._default

    def bare_model(self, model: str) -> str:
        """剥掉已知 provider 前缀，返回厂商 SDK 想要的裸 model 名。

        前缀不是已注册 provider 时（``qwen2.5-coder:32b``）原样返回，
        避免把版本 tag 的冒号误认为 provider 分隔符。
        """
        prefix = _split_prefix(model)
        if prefix is not None:
            candidate = self._canonical(prefix)
            with self._lock:
                if candidate in self._factories:
                    return model.split(":", 1)[1]
        return model

    def _canonical(self, name: str) -> str:
        """别名归一：``claude`` → ``anthropic``。"""
        return self._aliases.get(name, name)

    def _client_for(self, name: str) -> ProviderClient:
        """取（或惰性构建）provider client；未注册抛 UnknownProviderError。"""
        with self._lock:
            client = self._clients.get(name)
            if client is None:
                factory = self._factories.get(name)
                if factory is None:
                    # 注意：Lock 不可重入 —— 错误信息里直接快照已注册名，
                    # 不能调用 self.providers（会二次加锁死锁）。
                    registered = sorted(self._factories) or "无"
                    raise UnknownProviderError(
                        f"provider '{name}' 未注册（已注册: {registered}）。"
                        "请先调用 register() 注入 client 或工厂。"
                    )
                client = factory()
                self._clients[name] = client
            return client

    def _note_use(self, provider_name: str) -> None:
        """触发 on_use 回调（best-effort，失败静默）。"""
        if self._on_use is None:
            return
        try:
            self._on_use(provider_name)
        except Exception:  # noqa: BLE001 — 回调失败不得中断模型调用
            logger.debug("on_use 回调失败（已忽略）", exc_info=True)

    # -- ProviderClient 实现 -----------------------------------------------

    def capabilities(self, model: str) -> ModelCapabilities:
        """委派给路由到的 client（惰性构建）。"""
        name = self.provider_name(model)
        return self._client_for(name).capabilities(self.bare_model(model))

    async def complete(
        self,
        *,
        model: str,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        **settings: Any,
    ) -> AssistantTurn:
        """路由 ``complete``：剥前缀后委派给 per-provider client。"""
        name = self.provider_name(model)
        self._note_use(name)
        client = self._client_for(name)
        return await client.complete(
            model=self.bare_model(model),
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            **settings,
        )

    async def stream(
        self,
        *,
        model: str,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        **settings: Any,
    ) -> AsyncIterator[StreamChunk]:
        """路由 ``stream``：剥前缀后透传 per-provider client 的 chunk 流。"""
        name = self.provider_name(model)
        self._note_use(name)
        client = self._client_for(name)
        async for chunk in client.stream(
            model=self.bare_model(model),
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            **settings,
        ):
            yield chunk

    async def aclose(self) -> None:
        """关闭所有已缓存的 client（逐个 aclose，单个失败不中断其余）。"""
        with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
        for client in clients:
            try:
                await client.aclose()
            except Exception:  # noqa: BLE001 — 关闭失败不应阻断其余 client
                logger.debug("aclose provider client 失败（已忽略）", exc_info=True)
