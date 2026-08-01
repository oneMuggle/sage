"""LLM 出站适配器。

- ``HttpxLLMAdapter`` ：LLMPort 生产实现，包装 ``core.llm_client.LLMClient``。
- ``MockLLMAdapter`` ：LLMPort 测试实现（PG2.4 落地）。
- ``FauxProvider`` ：模拟 Provider（A25，pi 借鉴），测试专用。

A2 Provider 抽象（实现 ``backend.ports.llm.ProviderClient``）：

- ``OpenAIProvider``    ：OpenAI / OpenAI-compatible（httpx 直连，零 SDK 依赖）。
- ``AnthropicProvider`` ：Anthropic Messages API。
- ``GeminiProvider``    ：Google Gemini generateContent API。
- ``OllamaProvider``    ：Ollama 本地推理（OpenAI 兼容端点）。

本模块刻意不在 import 时加载上述 adapter（避免 httpx 客户端相关副作用）；
按需从子模块导入，例如 ``from backend.adapters.out.llm.openai import OpenAIProvider``。
"""
