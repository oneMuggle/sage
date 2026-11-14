"""LLMContext: shared LLM/HTTP injection for wiki routes.

Replaces 4 copies of inline ``llm_call``/``http_post`` definitions across
``backend/api/wiki_routes.py``. PR-2/3 will use ``ctx.llm_stream_call`` to
switch ``/chat`` and ``/ingest`` to NDJSON streaming without changing the
dependency wiring.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable, Dict, List, Optional

import httpx

from .reasoning import apply_reasoning_to_request
from .settings import WikiSettings, load_settings, resolve_model_for_task

LlmCall = Callable[[List[Dict], float], Awaitable[str]]
LlmStreamCall = Callable[[List[Dict], float], AsyncIterator[str]]
HttpPost = Callable[[str, Dict[str, str], dict], Awaitable[str]]

# 由 base_url 推断 provider 的关键字（顺序敏感，先匹配到的优先）。
_PROVIDER_HINTS = (
    ("anthropic", "anthropic"),
    ("generativelanguage", "google"),
    ("googleapis", "google"),
    ("deepseek", "deepseek"),
    ("ollama", "ollama"),
    ("11434", "ollama"),
    ("openai", "openai"),
)


def infer_provider(base_url: str) -> str:
    """从 OpenAI 兼容端点 URL 推断 provider，无法识别时返回空串。"""
    lowered = (base_url or "").lower()
    for token, provider in _PROVIDER_HINTS:
        if token in lowered:
            return provider
    return ""


@dataclass
class LLMContext:
    """LLM/HTTP capability bundle injected into wiki route handlers.

    Attributes:
        llm_call: Non-streaming chat completion (returns full content).
        llm_stream_call: Streaming chat completion (yields delta tokens).
        http_post: Generic JSON POST (e.g. for embedding endpoints).
        model: Resolved model name (after task routing); empty when unknown.
    """

    llm_call: LlmCall
    llm_stream_call: LlmStreamCall
    http_post: HttpPost
    model: str = ""


def make_llm_context(
    llm_base_url: str,
    llm_api_key: str,
    llm_model: str,
    timeout_seconds: int = 1800,
    provider: str = "",
    reasoning_mode: str = "",
) -> LLMContext:
    """Build LLMContext for a given provider + model + key.

    ``llm_base_url`` is the OpenAI-compatible ``/chat/completions`` root
    (e.g. ``https://api.openai.com/v1``).

    ``reasoning_mode`` (auto/off/low/medium/high/max) is translated to
    provider-specific request fields; empty/off/auto leaves the body untouched.
    """
    chat_url = f"{llm_base_url.rstrip('/')}/chat/completions"
    auth_headers = {
        "Authorization": f"Bearer {llm_api_key}",
        "Content-Type": "application/json",
    }
    resolved_provider = provider or infer_provider(llm_base_url)

    def _chat_body(messages: List[Dict], temperature: float, stream: bool) -> Dict:
        body: Dict = {
            "model": llm_model,
            "messages": messages,
            "temperature": temperature,
            "stream": stream,
        }
        if reasoning_mode:
            apply_reasoning_to_request(body, resolved_provider, reasoning_mode)
        return body

    async def llm_call(messages: List[Dict], temperature: float) -> str:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            r = await client.post(
                chat_url,
                headers=auth_headers,
                json=_chat_body(messages, temperature, stream=False),
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]

    async def llm_stream_call(
        messages: List[Dict],
        temperature: float,
    ) -> AsyncIterator[str]:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:  # noqa: SIM117 - retain nested form for Python 3.8 syntax compatibility
            async with client.stream(
                "POST",
                chat_url,
                headers=auth_headers,
                json=_chat_body(messages, temperature, stream=True),
            ) as r:
                async for line in r.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:]
                    if payload == "[DONE]":
                        break
                    try:
                        delta = json.loads(payload)["choices"][0].get("delta", {}).get("content", "")
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
                    if delta:
                        yield delta

    async def http_post(url: str, headers: Dict[str, str], body: dict) -> str:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            r = await client.post(url, headers=headers, json=body)
            r.raise_for_status()
            return r.text

    return LLMContext(llm_call, llm_stream_call, http_post, model=llm_model)


def make_task_llm_context(
    llm_base_url: str,
    llm_api_key: str,
    default_model: str,
    project_root: Optional[Path] = None,
    task: str = "chat",
    provider: str = "",
    timeout_seconds: int = 1800,
) -> LLMContext:
    """按项目设置解析任务模型与推理模式，再构建 LLMContext。

    ``project_root`` 为空或未配置设置时退化为 ``default_model`` 与默认推理模式。
    """
    settings = load_settings(project_root) if project_root is not None else WikiSettings()
    model = resolve_model_for_task(settings, task, default_model)
    mode = settings.reasoning.ingest_mode if task == "ingest" else settings.reasoning.chat_mode
    return make_llm_context(
        llm_base_url,
        llm_api_key,
        model,
        timeout_seconds=timeout_seconds,
        provider=provider,
        reasoning_mode=mode,
    )
