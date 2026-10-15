"""Provider 层模型能力判定测试。

评审 (HIGH-1/MEDIUM-3) 发现：四个 provider 的 ``capabilities()`` 把多个实际
支持 vision 的模型判为 False（gpt-4-turbo / gpt-4.1 / gpt-5 /
claude-sonnet-4-5 / qwen2.5-vl-7b / llava-1.6 / glm-4v / internvl2-8b /
deepseek-vl2），而 ``gemini-embedding-001`` 这类非生成式模型却被判为支持
vision。本文件把这些 id 固化成回归护栏，防止能力判定再次退化。
"""

import pytest

from backend.adapters.out.llm.anthropic_provider import (
    AnthropicProvider,
    model_capabilities as anthropic_caps,
)
from backend.adapters.out.llm.gemini_provider import (
    GeminiProvider,
    model_capabilities as gemini_caps,
)
from backend.adapters.out.llm.ollama_provider import (
    OllamaProvider,
    model_capabilities as ollama_caps,
)
from backend.adapters.out.llm.openai_provider import (
    OpenAIProvider,
    model_capabilities as openai_caps,
)
from backend.adapters.out.llm.provider_registry import get_model_capabilities

# (provider 名, 能力判定函数, 应判为支持 vision 的模型)
_VISION_TRUE_CASES = [
    ("openai", openai_caps, "gpt-4o"),
    ("openai", openai_caps, "gpt-4"),
    ("openai", openai_caps, "gpt-4-turbo"),
    ("openai", openai_caps, "gpt-4.1"),
    ("openai", openai_caps, "gpt-4-vision"),
    ("openai", openai_caps, "gpt-5"),
    ("openai", openai_caps, "deepseek-vl2"),
    ("anthropic", anthropic_caps, "claude-3-opus"),
    ("anthropic", anthropic_caps, "claude-3-5-sonnet"),
    ("anthropic", anthropic_caps, "claude-sonnet-4-5"),
    ("anthropic", anthropic_caps, "claude-opus-4-5"),
    ("anthropic", anthropic_caps, "claude-haiku-4-5"),
    ("gemini", gemini_caps, "gemini-2.5-pro"),
    ("gemini", gemini_caps, "gemini-2.0-flash"),
    ("ollama", ollama_caps, "llava-1.6"),
    ("ollama", ollama_caps, "qwen2.5-vl-7b"),
    ("ollama", ollama_caps, "glm-4v"),
    ("ollama", ollama_caps, "internvl2-8b"),
    ("ollama", ollama_caps, "moondream"),
]

# (provider 名, 能力判定函数, 应判为【不】支持 vision 的模型)
_VISION_FALSE_CASES = [
    ("openai", openai_caps, "gpt-3.5-turbo"),
    ("openai", openai_caps, "text-embedding-3-small"),
    ("openai", openai_caps, "text-embedding-3-large"),
    ("openai", openai_caps, "dall-e-3"),
    ("openai", openai_caps, "whisper-1"),
    ("openai", openai_caps, "deepseek-chat"),
    ("anthropic", anthropic_caps, "claude-2.1"),
    ("anthropic", anthropic_caps, "claude-instant-1"),
    # 评审点名的误判：embedding 模型不接受图像输入
    ("gemini", gemini_caps, "gemini-embedding-001"),
    ("ollama", ollama_caps, "nomic-embed-text"),
    ("ollama", ollama_caps, "bge-m3"),
    ("ollama", ollama_caps, "llama3.1:8b"),
]


@pytest.mark.parametrize(("provider", "caps_fn", "model"), _VISION_TRUE_CASES)
def test_model_judged_as_vision_capable(provider, caps_fn, model):
    assert caps_fn(model).vision is True, f"{provider}/{model} 应判为支持 vision"


@pytest.mark.parametrize(("provider", "caps_fn", "model"), _VISION_FALSE_CASES)
def test_model_judged_as_not_vision_capable(provider, caps_fn, model):
    assert caps_fn(model).vision is False, f"{provider}/{model} 不应判为支持 vision"


@pytest.mark.parametrize("caps_fn", [openai_caps, anthropic_caps, gemini_caps, ollama_caps])
def test_empty_model_is_not_vision_capable(caps_fn):
    """空模型 id 不应崩溃，也不应乐观判为支持。"""
    assert caps_fn("").vision is False


@pytest.mark.parametrize("caps_fn", [openai_caps, anthropic_caps, gemini_caps, ollama_caps])
def test_capabilities_is_case_insensitive(caps_fn):
    assert caps_fn("GPT-4O").vision == caps_fn("gpt-4o").vision


class TestProviderInstanceDelegates:
    """各 provider 的实例方法必须与模块级纯函数同源（避免判定漂移）。"""

    @pytest.mark.parametrize(
        ("provider_cls", "caps_fn", "model"),
        [
            (OpenAIProvider, openai_caps, "gpt-4o"),
            (AnthropicProvider, anthropic_caps, "claude-sonnet-4-5"),
            (GeminiProvider, gemini_caps, "gemini-2.5-pro"),
            (OllamaProvider, ollama_caps, "qwen2.5-vl:7b"),
        ],
    )
    def test_instance_method_matches_pure_function(self, provider_cls, caps_fn, model):
        # 不走 __init__：能力判定是纯函数，不该依赖 base_url / httpx 客户端
        instance = provider_cls.__new__(provider_cls)
        assert instance.capabilities(model) == caps_fn(model)


class TestRegistryCapabilityLookup:
    """``get_model_capabilities`` 的 provider 名归一 + 未知语义。"""

    @pytest.mark.parametrize(
        ("provider", "model", "expected_vision"),
        [
            ("openai", "gpt-4o", True),
            ("claude", "claude-sonnet-4-5", True),
            ("anthropic", "claude-3-5-sonnet", True),
            ("gemini", "gemini-2.5-pro", True),
            ("gemini", "gemini-embedding-001", False),
            ("ollama", "llava-1.6", True),
            # deepseek / custom 走 OpenAI 兼容协议
            ("deepseek", "deepseek-vl2", True),
            ("custom", "glm-4v", True),
            ("OPENAI", "gpt-4o", True),
            ("  openai  ", "gpt-4o", True),
        ],
    )
    def test_known_providers_resolve(self, provider, model, expected_vision):
        resolved = get_model_capabilities(provider, model)

        assert resolved is not None, f"{provider} 应可解析"
        assert resolved.vision is expected_vision

    @pytest.mark.parametrize("provider", ["bogus", "", "   ", "some-future-provider"])
    def test_unknown_provider_returns_none_not_false(self, provider):
        """未知 provider 必须返回 None（能力未知），不能返回 vision=False。

        调用方据此区分「未知」与「确认不支持」：未知时保守按支持处理，
        只有明确确认不支持才降级，否则功能开关一开就会让现有用户回归。
        """
        assert get_model_capabilities(provider, "gpt-4o") is None

    def test_registry_alias_maps_to_same_verdict_as_provider(self):
        assert get_model_capabilities("deepseek", "gpt-4o") == get_model_capabilities(
            "openai", "gpt-4o"
        )
