"""ProviderRouter + Provider 抽象 + Token 归一化测试（A2）。

覆盖：

1. ``TokenUsage`` 归一化语义（4 字段 / context_tokens / total / 相加）。
2. ``ProviderRouter`` 路由：前缀分发、裸名走 default、未知前缀不误剥、
   别名、惰性工厂构建与缓存、invalidate、on_use、aclose、未注册报错。
3. ``FauxProvider``（A25）经适配后接入 router 的复用路径。
4. 四个 adapter 的 usage 归一化纯函数（离线，无网络）。
5. Anthropic / Gemini 消息格式翻译（角色合并、tool_result / functionResponse）。
6. ``httpx.MockTransport`` 拦截的端到端往返（OpenAI / Anthropic / Gemini /
   Ollama + 流式 + 错误分类）。不用 respx —— 仓库已知的 respx 0.21 与
   httpx 0.28 不兼容问题（参见 test_httpx_llm_adapter.py 的 xfail 标记）。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Union

import httpx
import pytest
from sage_core import Message, Role, ToolCall

from backend.adapters.out.llm.anthropic import (
    AnthropicProvider,
    messages_to_anthropic,
    tool_choice_to_anthropic,
    usage_from_anthropic,
)
from backend.adapters.out.llm.faux_provider import CompletionRequest, FauxProvider
from backend.adapters.out.llm.gemini import (
    GeminiProvider,
    messages_to_gemini,
    tool_choice_to_gemini,
    usage_from_gemini,
)
from backend.adapters.out.llm.ollama import OllamaProvider
from backend.adapters.out.llm.openai import OpenAIProvider, usage_from_openai
from backend.application.services.provider_router import (
    ProviderRouter,
    UnknownProviderError,
)
from backend.core.errors import LLMError, LLMErrorType
from backend.ports.llm import (
    AssistantTurn,
    ModelCapabilities,
    ProviderClient,
    StreamChunk,
    TokenUsage,
)

pytestmark = pytest.mark.unit


# ============================================================================
# 测试辅助
# ============================================================================


class _RecordingClient(ProviderClient):
    """记录调用的桩 ProviderClient。"""

    def __init__(self, name: str = "stub") -> None:
        self.name = name
        self.complete_calls: List[Dict[str, Any]] = []
        self.stream_calls: List[str] = []
        self.capabilities_calls: List[str] = []
        self.closed = 0
        self.capabilities_result = ModelCapabilities()

    async def complete(
        self,
        *,
        model: str,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        **settings: Any,
    ) -> AssistantTurn:
        self.complete_calls.append(
            {"model": model, "messages": messages, "tools": tools, "settings": settings}
        )
        return AssistantTurn(text=f"{self.name}:{model}", model=model)

    def capabilities(self, model: str) -> ModelCapabilities:
        self.capabilities_calls.append(model)
        return self.capabilities_result

    async def stream(
        self,
        *,
        model: str,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        **settings: Any,
    ):
        self.stream_calls.append(model)
        yield StreamChunk(text_delta="s-")
        yield StreamChunk(turn=AssistantTurn(text=f"{self.name}:{model}", model=model))

    async def aclose(self) -> None:
        self.closed += 1


class _FauxProviderClient(ProviderClient):
    """把已有 ``FauxProvider``（A25）适配为 ``ProviderClient``，复用其
    响应循环与调用计数，避免重复造测试替身。"""

    def __init__(self, faux: FauxProvider) -> None:
        self._faux = faux

    async def complete(
        self,
        *,
        model: str,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        **settings: Any,
    ) -> AssistantTurn:
        resp = await self._faux.complete(CompletionRequest(messages=messages, tools=tools))
        return AssistantTurn(
            text=resp.content,
            model=model,
            usage=TokenUsage(input=resp.usage["input"], output=resp.usage["output"]),
        )

    def capabilities(self, model: str) -> ModelCapabilities:
        return ModelCapabilities()


def _router_with_stubs(**kwargs: Any):
    """构建注册了 4 个桩 client 的 router。"""
    router = ProviderRouter(**kwargs)
    stubs = {}
    for name in ("openai", "anthropic", "gemini", "ollama"):
        stub = _RecordingClient(name)
        stubs[name] = stub
        router.register(name, stub)
    return router, stubs


_USER_MSG = [Message(role=Role.USER, content="hi")]


# ============================================================================
# 1. TokenUsage 归一化
# ============================================================================


class TestTokenUsage:
    """TokenUsage 归一化语义。"""

    def test_defaults_all_zero(self):
        usage = TokenUsage()
        assert usage.as_dict() == {
            "input": 0,
            "output": 0,
            "cache_read": 0,
            "cache_write": 0,
        }

    def test_context_tokens_is_prompt_side_total(self):
        usage = TokenUsage(input=10, output=5, cache_read=3, cache_write=2)
        assert usage.context_tokens == 15  # 10 + 3 + 2

    def test_total_tokens_includes_output(self):
        usage = TokenUsage(input=10, output=5, cache_read=3, cache_write=2)
        assert usage.total_tokens == 20  # 15 + 5

    def test_as_dict_has_exactly_four_fields(self):
        assert set(TokenUsage(input=1).as_dict()) == {
            "input",
            "output",
            "cache_read",
            "cache_write",
        }

    def test_add_combines_fieldwise(self):
        a = TokenUsage(input=1, output=2, cache_read=3, cache_write=4)
        b = TokenUsage(input=10, output=20, cache_read=30, cache_write=40)
        assert a + b == TokenUsage(input=11, output=22, cache_read=33, cache_write=44)

    def test_add_non_usage_raises_type_error(self):
        with pytest.raises(TypeError):
            TokenUsage() + 5  # type: ignore[operator]


# ============================================================================
# 2. ProviderRouter 路由
# ============================================================================


class TestProviderRouterRouting:
    """model name → provider 的路由规则。"""

    async def test_known_prefix_routes_to_provider_and_strips(self):
        router, stubs = _router_with_stubs()
        turn = await router.complete(model="anthropic:claude-sonnet-4-5", messages=_USER_MSG)

        assert turn.text == "anthropic:claude-sonnet-4-5"
        assert stubs["anthropic"].complete_calls[0]["model"] == "claude-sonnet-4-5"
        assert not stubs["openai"].complete_calls

    async def test_bare_model_routes_to_default_provider(self):
        router, stubs = _router_with_stubs()
        await router.complete(model="gpt-4o", messages=_USER_MSG)

        assert stubs["openai"].complete_calls[0]["model"] == "gpt-4o"

    async def test_unknown_prefix_keeps_model_and_uses_default(self):
        """``qwen2.5-coder:32b`` 的冒号是版本 tag，不是 provider 前缀。"""
        router, stubs = _router_with_stubs()
        await router.complete(model="qwen2.5-coder:32b", messages=_USER_MSG)

        assert stubs["openai"].complete_calls[0]["model"] == "qwen2.5-coder:32b"

    async def test_ollama_prefix_with_version_tag_strips_only_provider(self):
        router, stubs = _router_with_stubs()
        await router.complete(model="ollama:llama3.3", messages=_USER_MSG)

        assert stubs["ollama"].complete_calls[0]["model"] == "llama3.3"

    async def test_alias_claude_routes_to_anthropic(self):
        router, stubs = _router_with_stubs()
        await router.complete(model="claude:claude-opus-4-1", messages=_USER_MSG)

        assert stubs["anthropic"].complete_calls[0]["model"] == "claude-opus-4-1"

    async def test_alias_google_routes_to_gemini(self):
        router, stubs = _router_with_stubs()
        await router.complete(model="google:gemini-2.5-pro", messages=_USER_MSG)

        assert stubs["gemini"].complete_calls[0]["model"] == "gemini-2.5-pro"

    async def test_register_with_alias_name_normalizes(self):
        router = ProviderRouter(default_provider="anthropic")
        stub = _RecordingClient("anthropic")
        router.register("claude", stub)  # 别名注册归一到 anthropic

        assert router.providers == ["anthropic"]
        await router.complete(model="anthropic:claude-x", messages=_USER_MSG)
        assert stub.complete_calls[0]["model"] == "claude-x"

    async def test_custom_default_provider(self):
        router, stubs = _router_with_stubs(default_provider="ollama")
        await router.complete(model="some-model", messages=_USER_MSG)

        assert stubs["ollama"].complete_calls[0]["model"] == "some-model"

    def test_providers_property_sorted(self):
        router, _ = _router_with_stubs()
        assert router.providers == ["anthropic", "gemini", "ollama", "openai"]


class TestProviderRouterLifecycle:
    """惰性构建、缓存、失效、回调、关闭。"""

    async def test_factory_lazy_and_cached(self):
        calls: List[str] = []

        def factory():
            calls.append("built")
            return _RecordingClient("lazy")

        router = ProviderRouter()
        router.register("openai", factory)
        assert calls == []  # 注册不构建

        await router.complete(model="m1", messages=_USER_MSG)
        await router.complete(model="m2", messages=_USER_MSG)
        assert calls == ["built"]  # 首次构建后缓存

    async def test_invalidate_forces_rebuild(self):
        calls: List[str] = []

        def factory():
            calls.append("built")
            return _RecordingClient("lazy")

        router = ProviderRouter()
        router.register("openai", factory)
        await router.complete(model="m1", messages=_USER_MSG)
        router.invalidate("openai")
        await router.complete(model="m2", messages=_USER_MSG)
        assert calls == ["built", "built"]

    async def test_invalidate_all_clears_cache(self):
        router, stubs = _router_with_stubs()
        await router.complete(model="gpt-4o", messages=_USER_MSG)
        router.invalidate()  # 全清不报错
        router.invalidate("nonexistent")  # 未知 name 也不报错
        await router.complete(model="gpt-4o", messages=_USER_MSG)
        assert len(stubs["openai"].complete_calls) == 2

    async def test_register_replaces_cached_client(self):
        router = ProviderRouter()
        first, second = _RecordingClient("first"), _RecordingClient("second")
        router.register("openai", first)
        await router.complete(model="m", messages=_USER_MSG)

        router.register("openai", second)
        turn = await router.complete(model="m", messages=_USER_MSG)
        assert turn.text == "second:m"
        assert len(first.complete_calls) == 1

    def test_register_rejects_invalid_argument(self):
        router = ProviderRouter()
        with pytest.raises(TypeError):
            router.register("openai", "not-a-client")  # type: ignore[arg-type]

    async def test_unknown_provider_raises_with_registered_list(self):
        router = ProviderRouter()
        with pytest.raises(UnknownProviderError, match="register"):
            await router.complete(model="gpt-4o", messages=_USER_MSG)

    async def test_default_not_registered_raises(self):
        router = ProviderRouter(default_provider="openai")
        router.register("anthropic", _RecordingClient("anthropic"))
        with pytest.raises(UnknownProviderError, match="openai"):
            await router.complete(model="gpt-4o", messages=_USER_MSG)

    async def test_on_use_callback_receives_provider_name(self):
        seen: List[str] = []
        router, _ = _router_with_stubs(on_use=seen.append)
        await router.complete(model="gemini:gemini-2.5-pro", messages=_USER_MSG)

        assert seen == ["gemini"]

    async def test_on_use_failure_never_breaks_call(self):
        def bad_callback(_name: str):
            raise RuntimeError("boom")

        router, _ = _router_with_stubs(on_use=bad_callback)
        turn = await router.complete(model="gpt-4o", messages=_USER_MSG)
        assert turn.text == "openai:gpt-4o"

    async def test_capabilities_delegates_with_bare_model(self):
        router, stubs = _router_with_stubs()
        stubs["anthropic"].capabilities_result = ModelCapabilities(reasoning=True)

        caps = router.capabilities("anthropic:claude-x")
        assert caps.reasoning is True
        assert stubs["anthropic"].capabilities_calls == ["claude-x"]

    async def test_stream_delegates_chunks(self):
        router, stubs = _router_with_stubs()
        chunks = [c async for c in router.stream(model="ollama:llama3.3", messages=_USER_MSG)]

        assert stubs["ollama"].stream_calls == ["llama3.3"]
        assert [c.text_delta for c in chunks if c.text_delta] == ["s-"]
        assert chunks[-1].turn is not None
        assert chunks[-1].turn.text == "ollama:llama3.3"

    async def test_aclose_closes_only_cached_clients(self):
        router, stubs = _router_with_stubs()
        await router.complete(model="gpt-4o", messages=_USER_MSG)  # 缓存 openai
        await router.complete(model="claude:x", messages=_USER_MSG)  # 缓存 anthropic

        await router.aclose()
        assert stubs["openai"].closed == 1
        assert stubs["anthropic"].closed == 1
        assert stubs["gemini"].closed == 0  # 从未构建，不关闭

    async def test_aclose_swallows_individual_failures(self):
        class _ExplodingClient(_RecordingClient):
            async def aclose(self) -> None:
                raise RuntimeError("close failed")

        router = ProviderRouter()
        exploding, good = _ExplodingClient("bad"), _RecordingClient("good")
        router.register("openai", exploding)
        router.register("anthropic", good)
        await router.complete(model="gpt-4o", messages=_USER_MSG)
        await router.complete(model="anthropic:x", messages=_USER_MSG)

        await router.aclose()  # 不因单个失败中断
        assert good.closed == 1


class TestFauxProviderIntegration:
    """已有 FauxProvider（A25）经适配接入 router。"""

    async def test_faux_provider_routed_through_router(self):
        faux = FauxProvider(responses=["Hello, world!"])
        router = ProviderRouter(default_provider="faux")
        router.register("faux", _FauxProviderClient(faux))

        turn = await router.complete(model="faux:faux-1", messages=_USER_MSG)

        assert turn.text == "Hello, world!"
        assert turn.model == "faux-1"
        assert turn.usage is not None
        assert turn.usage.input + turn.usage.output > 0
        assert faux.call_count == 1

    async def test_faux_default_stream_falls_back_to_single_chunk(self):
        """ProviderClient.stream 默认实现：单 chunk 携带完整 turn。"""
        faux = FauxProvider(responses=["chunked"])
        client = _FauxProviderClient(faux)

        chunks = [c async for c in client.stream(model="faux-1", messages=_USER_MSG)]

        assert len(chunks) == 1
        assert chunks[0].turn is not None
        assert chunks[0].turn.text == "chunked"


# ============================================================================
# 3. usage 归一化纯函数（离线）
# ============================================================================


class TestUsageNormalization:
    """四个 provider 的 usage → TokenUsage 归一化。"""

    def test_openai_usage_subtracts_cached_from_prompt(self):
        usage = usage_from_openai(
            {
                "prompt_tokens": 100,
                "completion_tokens": 30,
                "prompt_tokens_details": {"cached_tokens": 40},
            }
        )
        assert usage == TokenUsage(input=60, output=30, cache_read=40, cache_write=0)

    def test_openai_usage_without_details_has_zero_cache(self):
        usage = usage_from_openai({"prompt_tokens": 10, "completion_tokens": 5})
        assert usage == TokenUsage(input=10, output=5)

    def test_openai_usage_with_null_details(self):
        usage = usage_from_openai(
            {"prompt_tokens": 10, "completion_tokens": 5, "prompt_tokens_details": None}
        )
        assert usage == TokenUsage(input=10, output=5)

    def test_openai_usage_none_returns_none(self):
        assert usage_from_openai(None) is None

    def test_ollama_style_usage_never_guesses_cache(self):
        """Ollama 走 OpenAI 兼容 usage（无 details）→ cache 字段恒 0。"""
        usage = usage_from_openai({"prompt_tokens": 8, "completion_tokens": 4})
        assert usage is not None
        assert usage.cache_read == 0
        assert usage.cache_write == 0

    def test_anthropic_usage_maps_all_four_fields(self):
        usage = usage_from_anthropic(
            {
                "input_tokens": 10,
                "output_tokens": 25,
                "cache_read_input_tokens": 3,
                "cache_creation_input_tokens": 2,
            }
        )
        # Anthropic input_tokens 本身不含缓存，无需减法。
        assert usage == TokenUsage(input=10, output=25, cache_read=3, cache_write=2)

    def test_anthropic_usage_none_returns_none(self):
        assert usage_from_anthropic(None) is None

    def test_gemini_usage_subtracts_cache_and_folds_thoughts(self):
        usage = usage_from_gemini(
            {
                "promptTokenCount": 12,
                "candidatesTokenCount": 7,
                "cachedContentTokenCount": 4,
                "thoughtsTokenCount": 3,
            }
        )
        assert usage == TokenUsage(input=8, output=10, cache_read=4, cache_write=0)

    def test_gemini_usage_none_returns_none(self):
        assert usage_from_gemini(None) is None


# ============================================================================
# 4. 消息格式翻译（离线）
# ============================================================================


class TestMessageConversion:
    """Anthropic / Gemini wire 格式翻译。"""

    def test_anthropic_system_extracted_and_merged(self):
        system, wire = messages_to_anthropic(
            [
                Message(role=Role.SYSTEM, content="s1"),
                Message(role=Role.SYSTEM, content="s2"),
                Message(role=Role.USER, content="hi"),
            ]
        )
        assert system == "s1\n\ns2"
        assert wire == [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]

    def test_anthropic_consecutive_same_role_merged(self):
        _, wire = messages_to_anthropic(
            [
                Message(role=Role.USER, content="a"),
                Message(role=Role.USER, content="b"),
            ]
        )
        assert len(wire) == 1
        assert wire[0]["content"] == [
            {"type": "text", "text": "a"},
            {"type": "text", "text": "b"},
        ]

    def test_anthropic_tool_message_becomes_tool_result(self):
        _, wire = messages_to_anthropic(
            [
                Message(role=Role.USER, content="weather?"),
                Message(
                    role=Role.ASSISTANT,
                    content="",
                    tool_calls=[ToolCall(name="get_weather", args={"city": "BJ"}, id="tu_1")],
                ),
                Message(role=Role.TOOL, content="sunny", tool_call_id="tu_1"),
            ]
        )
        assert wire[1]["content"] == [
            {"type": "tool_use", "id": "tu_1", "name": "get_weather", "input": {"city": "BJ"}}
        ]
        assert wire[2] == {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "tu_1", "content": "sunny"}],
        }

    def test_anthropic_tool_choice_mapping(self):
        assert tool_choice_to_anthropic(None) is None
        assert tool_choice_to_anthropic("auto") == {"type": "auto"}
        assert tool_choice_to_anthropic("required") == {"type": "any"}
        assert tool_choice_to_anthropic("none") == {"type": "none"}
        assert tool_choice_to_anthropic({"name": "fw"}) == {"type": "tool", "name": "fw"}

    def test_gemini_system_instruction(self):
        system, contents = messages_to_gemini(
            [
                Message(role=Role.SYSTEM, content="be nice"),
                Message(role=Role.USER, content="hi"),
            ]
        )
        assert system == {"parts": [{"text": "be nice"}]}
        assert contents == [{"role": "user", "parts": [{"text": "hi"}]}]

    def test_gemini_tool_response_name_backreference(self):
        """TOOL 消息的 functionResponse name 从上一条 assistant 反查。"""
        _, contents = messages_to_gemini(
            [
                Message(role=Role.USER, content="weather?"),
                Message(
                    role=Role.ASSISTANT,
                    content="",
                    tool_calls=[ToolCall(name="get_weather", args={"city": "BJ"}, id="tc_1")],
                ),
                Message(role=Role.TOOL, content="sunny", tool_call_id="tc_1"),
            ]
        )
        tool_response = contents[2]["parts"][0]["functionResponse"]
        assert tool_response["name"] == "get_weather"
        assert tool_response["response"] == {"content": "sunny"}

    def test_gemini_tool_choice_mapping(self):
        assert tool_choice_to_gemini(None) is None
        assert tool_choice_to_gemini("auto") == {"mode": "AUTO"}
        assert tool_choice_to_gemini("required") == {"mode": "ANY"}
        assert tool_choice_to_gemini("none") == {"mode": "NONE"}
        assert tool_choice_to_gemini({"name": "fw"}) == {
            "mode": "ANY",
            "allowedFunctionNames": ["fw"],
        }


# ============================================================================
# 5. httpx.MockTransport 端到端往返
# ============================================================================


def _mock_client(
    handler: Callable[[httpx.Request], httpx.Response],
    base_url: str,
    requests: Optional[List[httpx.Request]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> httpx.AsyncClient:
    """构造带 MockTransport 的 httpx client（记录请求供断言）。

    通过 adapter 的 ``client=`` 注入口传入 —— 完全绕开真实网络与
    respx（仓库已知 respx/httpx 版本不兼容）。
    """

    def recording_handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        return handler(request)

    client_headers = {"Content-Type": "application/json"}
    client_headers.update(headers or {})
    return httpx.AsyncClient(
        transport=httpx.MockTransport(recording_handler),
        base_url=base_url,
        headers=client_headers,
    )


class TestAdapterRoundTrip:
    """MockTransport 拦截下的完整往返（不发真实网络请求）。

    注：注入 client 时 base_url / 鉴权 header 由测试侧模拟 provider
    的 ``_get_client`` 行为；provider 内部逻辑（请求体组装、响应解析、
    归一化）走真实路径。
    """

    async def test_openai_complete_round_trip_with_cache_split(self):
        payload = {
            "model": "gpt-4o",
            "choices": [
                {
                    "message": {"role": "assistant", "content": "Hello!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 50,
                "completion_tokens": 10,
                "prompt_tokens_details": {"cached_tokens": 20},
            },
        }
        requests: List[httpx.Request] = []
        client = _mock_client(
            lambda req: httpx.Response(200, json=payload),
            base_url="https://api.openai.com/v1",
            requests=requests,
            headers={"Authorization": "Bearer sk-test"},
        )
        provider = OpenAIProvider(api_key="sk-test", client=client)
        turn = await provider.complete(model="gpt-4o", messages=_USER_MSG)
        await client.aclose()

        assert requests[0].url.path == "/v1/chat/completions"
        assert turn.text == "Hello!"
        assert turn.finish_reason == "stop"
        assert turn.usage == TokenUsage(input=30, output=10, cache_read=20)

    async def test_openai_builds_auth_header_itself(self):
        """不注入 client 时，provider 自建 client 携带 Bearer 头。

        只验证 header 组装（用 MockTransport 的自建路径无法注入，
        因此构造后立即取出 header 断言，不发请求）。
        """
        provider = OpenAIProvider(api_key="sk-self", base_url="https://x.test/v1")
        inner = provider._get_client()  # noqa: SLF001 — 白盒验证 header 组装
        assert inner.headers["authorization"] == "Bearer sk-self"
        await provider.aclose()

    async def test_openai_tool_calls_parsed(self):
        payload = {
            "model": "gpt-4o",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "get_weather",
                                    "arguments": '{"city": "Beijing"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        }
        client = _mock_client(
            lambda req: httpx.Response(200, json=payload),
            base_url="https://api.openai.com/v1",
        )
        provider = OpenAIProvider(api_key="sk-test", client=client)
        turn = await provider.complete(model="gpt-4o", messages=_USER_MSG)
        await client.aclose()

        assert turn.has_tool_calls
        assert turn.tool_calls[0] == ToolCall(
            name="get_weather", args={"city": "Beijing"}, id="call_1"
        )

    async def test_openai_tool_call_invalid_json_degrades_to_empty_args(self):
        payload = {
            "model": "gpt-4o",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "broken",
                                    "arguments": "{not-json",
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        }
        client = _mock_client(
            lambda req: httpx.Response(200, json=payload),
            base_url="https://api.openai.com/v1",
        )
        provider = OpenAIProvider(api_key="sk-test", client=client)
        turn = await provider.complete(model="gpt-4o", messages=_USER_MSG)
        await client.aclose()

        assert turn.tool_calls[0].args == {}

    async def test_openai_stream_parses_sse_with_final_usage(self):
        sse_body = (
            'data: {"model":"gpt-4o","choices":[{"delta":{"content":"Hel"},"finish_reason":null}]}\n\n'
            'data: {"model":"gpt-4o","choices":[{"delta":{"content":"lo"},"finish_reason":"stop"}]}\n\n'
            'data: {"model":"gpt-4o","choices":[],"usage":{"prompt_tokens":5,"completion_tokens":2}}\n\n'
            "data: [DONE]\n\n"
        )
        client = _mock_client(
            lambda req: httpx.Response(
                200,
                content=sse_body.encode(),
                headers={"content-type": "text/event-stream"},
            ),
            base_url="https://api.openai.com/v1",
        )
        provider = OpenAIProvider(api_key="sk-test", client=client)
        chunks = [c async for c in provider.stream(model="gpt-4o", messages=_USER_MSG)]
        await client.aclose()

        assert [c.text_delta for c in chunks if c.text_delta] == ["Hel", "lo"]
        final = chunks[-1].turn
        assert final is not None
        assert final.text == "Hello"
        assert final.finish_reason == "stop"
        assert final.usage == TokenUsage(input=5, output=2)

    async def test_openai_auth_error_classified(self):
        client = _mock_client(
            lambda req: httpx.Response(401, json={"error": {"message": "bad key"}}),
            base_url="https://api.openai.com/v1",
        )
        provider = OpenAIProvider(api_key="sk-bad", client=client)
        with pytest.raises(LLMError) as exc_info:
            await provider.complete(model="gpt-4o", messages=_USER_MSG)
        await client.aclose()

        assert exc_info.value.type is LLMErrorType.AUTH_FAILED

    async def test_openai_empty_choices_classified_as_parsing(self):
        client = _mock_client(
            lambda req: httpx.Response(200, json={"choices": []}),
            base_url="https://api.openai.com/v1",
        )
        provider = OpenAIProvider(api_key="sk-test", client=client)
        with pytest.raises(LLMError) as exc_info:
            await provider.complete(model="gpt-4o", messages=_USER_MSG)
        await client.aclose()

        assert exc_info.value.type is LLMErrorType.PARSING

    async def test_anthropic_complete_round_trip_with_tool_use(self):
        payload = {
            "id": "msg_1",
            "model": "claude-sonnet-4-5",
            "content": [
                {"type": "text", "text": "Let me check."},
                {
                    "type": "tool_use",
                    "id": "tu_1",
                    "name": "get_weather",
                    "input": {"city": "Beijing"},
                },
            ],
            "stop_reason": "tool_use",
            "usage": {
                "input_tokens": 10,
                "output_tokens": 25,
                "cache_read_input_tokens": 3,
                "cache_creation_input_tokens": 2,
            },
        }
        requests: List[httpx.Request] = []
        client = _mock_client(
            lambda req: httpx.Response(200, json=payload),
            base_url="https://api.anthropic.com",
            requests=requests,
            headers={
                "x-api-key": "sk-ant-test",
                "anthropic-version": "2023-06-01",
            },
        )
        provider = AnthropicProvider(api_key="sk-ant-test", client=client)
        turn = await provider.complete(
            model="claude-sonnet-4-5",
            messages=[
                Message(role=Role.SYSTEM, content="you help"),
                Message(role=Role.USER, content="weather?"),
            ],
        )
        await client.aclose()

        import json as _json

        request = requests[0]
        assert request.url.path == "/v1/messages"
        body = _json.loads(request.content)
        assert body["system"] == "you help"
        assert body["max_tokens"] == 4096  # 必填项默认值

        assert turn.text == "Let me check."
        assert turn.finish_reason == "tool_calls"  # tool_use → tool_calls
        assert turn.tool_calls[0] == ToolCall(
            name="get_weather", args={"city": "Beijing"}, id="tu_1"
        )
        assert turn.usage == TokenUsage(input=10, output=25, cache_read=3, cache_write=2)

    async def test_anthropic_stream_assembles_tool_use(self):
        events = [
            {
                "type": "message_start",
                "message": {
                    "model": "claude-sonnet-4-5",
                    "usage": {"input_tokens": 10, "cache_read_input_tokens": 3},
                },
            },
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "Chec"},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "king"},
            },
            {
                "type": "content_block_start",
                "index": 1,
                "content_block": {
                    "type": "tool_use",
                    "id": "tu_9",
                    "name": "calc",
                },
            },
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": '{"x":',
                },
            },
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": " 42}",
                },
            },
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use"},
                "usage": {"output_tokens": 17},
            },
        ]
        sse_body = "".join("event: x\n" + "data: " + _json_dumps(e) + "\n\n" for e in events)
        client = _mock_client(
            lambda req: httpx.Response(
                200,
                content=sse_body.encode(),
                headers={"content-type": "text/event-stream"},
            ),
            base_url="https://api.anthropic.com",
        )
        provider = AnthropicProvider(api_key="sk-ant-test", client=client)
        chunks = [c async for c in provider.stream(model="claude-sonnet-4-5", messages=_USER_MSG)]
        await client.aclose()

        assert [c.text_delta for c in chunks if c.text_delta] == ["Chec", "king"]
        final = chunks[-1].turn
        assert final is not None
        assert final.text == "Checking"
        assert final.finish_reason == "tool_calls"
        assert final.tool_calls[0] == ToolCall(name="calc", args={"x": 42}, id="tu_9")
        assert final.usage == TokenUsage(input=10, output=17, cache_read=3)

    async def test_gemini_complete_round_trip_with_function_call(self):
        payload = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "functionCall": {
                                    "name": "get_weather",
                                    "args": {"city": "Beijing"},
                                }
                            }
                        ]
                    },
                    "finishReason": "STOP",
                }
            ],
            "modelVersion": "gemini-2.5-pro",
            "usageMetadata": {
                "promptTokenCount": 12,
                "candidatesTokenCount": 7,
                "cachedContentTokenCount": 4,
            },
        }
        requests: List[httpx.Request] = []
        client = _mock_client(
            lambda req: httpx.Response(200, json=payload),
            base_url="https://generativelanguage.googleapis.com",
            requests=requests,
            headers={"x-goog-api-key": "AIza-test"},
        )
        provider = GeminiProvider(api_key="AIza-test", client=client)
        turn = await provider.complete(model="gemini-2.5-pro", messages=_USER_MSG)
        await client.aclose()

        assert requests[0].url.path == "/v1beta/models/gemini-2.5-pro:generateContent"
        assert turn.has_tool_calls
        assert turn.tool_calls[0].name == "get_weather"
        assert turn.finish_reason == "tool_calls"  # STOP + functionCall → tool_calls
        assert turn.model == "gemini-2.5-pro"
        assert turn.usage == TokenUsage(input=8, output=7, cache_read=4)

    async def test_gemini_safety_block_raises(self):
        payload = {"promptFeedback": {"blockReason": "SAFETY"}}
        client = _mock_client(
            lambda req: httpx.Response(200, json=payload),
            base_url="https://generativelanguage.googleapis.com",
        )
        provider = GeminiProvider(api_key="AIza-test", client=client)
        with pytest.raises(LLMError, match="SAFETY"):
            await provider.complete(model="gemini-2.5-pro", messages=_USER_MSG)
        await client.aclose()

    async def test_ollama_defaults_to_local_and_no_auth(self):
        payload = {
            "model": "llama3.3",
            "choices": [
                {
                    "message": {"role": "assistant", "content": "local reply"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2},
        }
        requests: List[httpx.Request] = []
        # 模拟 OllamaProvider._get_client 的自建行为（无 Authorization）
        client = _mock_client(
            lambda req: httpx.Response(200, json=payload),
            base_url="http://localhost:11434/v1",
            requests=requests,
        )
        provider = OllamaProvider(client=client)
        turn = await provider.complete(model="llama3.3", messages=_USER_MSG)
        await client.aclose()

        assert requests[0].url == "http://localhost:11434/v1/chat/completions"
        assert "authorization" not in requests[0].headers
        assert turn.text == "local reply"
        assert turn.usage == TokenUsage(input=4, output=2)
        assert provider.capabilities("llama3.3").parallel_tool_calls is False


def _json_dumps(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
