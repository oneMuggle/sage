"""LLMContext: shared LLM/HTTP injection for wiki routes.

Replaces 4 copies of inline ``llm_call``/``http_post`` definitions across
``backend/api/wiki_routes.py``. PR-2/3 will use ``ctx.llm_stream_call`` to
switch ``/chat`` and ``/ingest`` to NDJSON streaming without changing the
dependency wiring.
"""

import json
from dataclasses import dataclass
from typing import AsyncIterator, Awaitable, Callable, Dict, List

import httpx

LlmCall = Callable[[List[Dict], float], Awaitable[str]]
LlmStreamCall = Callable[[List[Dict], float], AsyncIterator[str]]
HttpPost = Callable[[str, Dict[str, str], dict], Awaitable[str]]


@dataclass
class LLMContext:
    """LLM/HTTP capability bundle injected into wiki route handlers.

    Attributes:
        llm_call: Non-streaming chat completion (returns full content).
        llm_stream_call: Streaming chat completion (yields delta tokens).
        http_post: Generic JSON POST (e.g. for embedding endpoints).
    """

    llm_call: LlmCall
    llm_stream_call: LlmStreamCall
    http_post: HttpPost


def make_llm_context(
    llm_base_url: str,
    llm_api_key: str,
    llm_model: str,
    timeout_seconds: int = 1800,
) -> LLMContext:
    """Build LLMContext for a given provider + model + key.

    ``llm_base_url`` is the OpenAI-compatible ``/chat/completions`` root
    (e.g. ``https://api.openai.com/v1``).
    """
    chat_url = f"{llm_base_url.rstrip('/')}/chat/completions"
    auth_headers = {
        "Authorization": f"Bearer {llm_api_key}",
        "Content-Type": "application/json",
    }

    async def llm_call(messages: List[Dict], temperature: float) -> str:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            r = await client.post(
                chat_url,
                headers=auth_headers,
                json={
                    "model": llm_model,
                    "messages": messages,
                    "temperature": temperature,
                    "stream": False,
                },
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]

    async def llm_stream_call(
        messages: List[Dict],
        temperature: float,
    ) -> AsyncIterator[str]:
        async with (
            httpx.AsyncClient(timeout=timeout_seconds) as client,
            client.stream(
                "POST",
                chat_url,
                headers=auth_headers,
                json={
                    "model": llm_model,
                    "messages": messages,
                    "temperature": temperature,
                    "stream": True,
                },
            ) as r,
        ):
            async for line in r.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload == "[DONE]":
                    break
                try:
                    delta = (
                        json.loads(payload)["choices"][0]
                        .get("delta", {})
                        .get("content", "")
                    )
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
                if delta:
                    yield delta

    async def http_post(url: str, headers: Dict[str, str], body: dict) -> str:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            r = await client.post(url, headers=headers, json=body)
            r.raise_for_status()
            return r.text

    return LLMContext(llm_call, llm_stream_call, http_post)


def get_wiki_llm_context(
    llm_base_url: str,
    llm_api_key: str,
    llm_model: str,
    timeout_seconds: int = 1800,
) -> LLMContext:
    """FastAPI Depends factory: build LLMContext from the 3 LLM fields.

    Each of the wiki route models (ChatRequest / IngestRequest /
    ResearchRequest) carries ``llm_base_url``/``llm_api_key``/``llm_model``;
    routes inject those into this factory. ClipRequest does not — its
    values come from env vars and are passed in directly.
    """
    return make_llm_context(
        llm_base_url=llm_base_url,
        llm_api_key=llm_api_key,
        llm_model=llm_model,
        timeout_seconds=timeout_seconds,
    )


def get_wiki_llm_context_from_body(request_body: dict) -> LLMContext:
    """Alternative factory: build LLMContext from a parsed request body dict.

    Convenience for callers that already have a body dict (e.g. middleware
    that stashed it in ``request.state``). Same semantics as
    :func:`get_wiki_llm_context`.
    """
    return get_wiki_llm_context(
        llm_base_url=request_body.get("llm_base_url") or "",
        llm_api_key=request_body.get("llm_api_key") or "",
        llm_model=request_body.get("llm_model") or "",
    )
