"""/wiki/chat/stream NDJSON 端点集成测试 (PR-2 Task 2)

将 wiki 同步 /chat 端点替换为 /chat/stream,返回 NDJSON 事件流:

- chunk: 每个 LLM delta 一条
- done:  末尾带 citations 数组
- error: 仅在异常路径出现

所有测试桩化 LLMContext (route module 注入) + _build_chat_context
(wiki.chat module 内部),避开 httpx/vectorstore/embeddings 真实调用。
"""

from __future__ import annotations

import json
from typing import List, Tuple

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app
from backend.wiki.llm_context import LLMContext
from backend.wiki.models import RetrievalStats

pytestmark = pytest.mark.integration

CHAT_STREAM_PATH = "/api/v1/wiki/chat/stream"
CHAT_PATH = "/api/v1/wiki/chat"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _stub_chat_context(
    citations: List[str] = None,
    context: str = "stubbed context",
) -> Tuple[str, List[str], RetrievalStats]:
    """桩 _build_chat_context 返回值,避开 token/embedding/vectorstore 实际调用."""
    if citations is None:
        citations = ["wiki/a.md"]
    stats = RetrievalStats(
        token_hits=1,
        vector_hits=1,
        fused_top_score=1.0,
        total_context_tokens=10,
    )
    return context, citations, stats


def _stub_llm_context(chunks: Tuple[str, ...] = ("Hello", " world", "!")) -> LLMContext:
    """构造带受控 llm_stream_call 的 LLMContext 桩."""

    async def fake_stream(messages, temperature):
        for chunk in chunks:
            yield chunk

    async def fake_http_post(url, headers, body):
        # _build_chat_context 已被桩化,正常情况下不会被调用
        return json.dumps({"data": [{"embedding": [0.0] * 1536}]})

    return LLMContext(
        llm_call=None,
        llm_stream_call=fake_stream,
        http_post=fake_http_post,
    )


def _stub_llm_context_broken() -> LLMContext:
    """构造 llm_stream_call 立即抛异常的 LLMContext 桩."""

    async def broken_stream(messages, temperature):
        if False:  # pragma: no cover — make it an async generator
            yield ""
        raise RuntimeError("LLM exploded")

    async def fake_http_post(url, headers, body):
        return json.dumps({"data": [{"embedding": [0.0] * 1536}]})

    return LLMContext(
        llm_call=None,
        llm_stream_call=broken_stream,
        http_post=fake_http_post,
    )


def _request_body(project_path: str) -> dict:
    return {
        "query": "test",
        "project_path": project_path,
        "llm_base_url": "http://api.test",
        "llm_api_key": "sk-test",
        "llm_model": "gpt-4",
        "embed_base_url": "http://api.test",
        "embed_api_key": "sk-test",
        "embed_model": "text-embedding-3-small",
    }


@pytest.fixture()
def wiki_project(tmp_path):
    """最小 wiki 项目结构 (供 project_path 校验)."""
    project = tmp_path / "wiki-project"
    wiki = project / "wiki"
    wiki.mkdir(parents=True)
    (wiki / "a.md").write_text("# A\nbody A")
    (wiki / "b.md").write_text("# B\nbody B")
    return project


@pytest.fixture()
def patch_wiki_chat(monkeypatch):
    """统一桩化 make_llm_context + _build_chat_context 的 fixture."""
    from backend.api import wiki_routes
    from backend.wiki import chat as wiki_chat

    def _setup(stub_ctx: LLMContext, citations: List[str] = None):
        monkeypatch.setattr(wiki_routes, "make_llm_context", lambda **kwargs: stub_ctx)
        monkeypatch.setattr(
            wiki_chat,
            "_build_chat_context",
            lambda *a, **kw: _stub_chat_context(citations=citations),
        )

    return _setup


def _parse_ndjson(text: str) -> List[dict]:
    return [json.loads(line) for line in text.split("\n") if line.strip()]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_chat_stream_yields_chunk_and_done(wiki_project, patch_wiki_chat):
    """Happy path: stream yields chunk events + terminal done event in NDJSON."""
    patch_wiki_chat(_stub_llm_context())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(CHAT_STREAM_PATH, json=_request_body(str(wiki_project)))

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/x-ndjson")
    events = _parse_ndjson(resp.text)
    chunks = [e["data"] for e in events if e["event"] == "chunk"]
    assert "".join(chunks) == "Hello world!"
    last = events[-1]
    assert last["event"] == "done"
    assert "citations" in last["data"]
    assert "wiki/a.md" in last["data"]["citations"]


@pytest.mark.asyncio()
async def test_chat_stream_empty_citations_yields_only_done(wiki_project, patch_wiki_chat):
    """无命中: 仅一条 done (citations:[]), 无 chunk 事件."""
    patch_wiki_chat(_stub_llm_context(), citations=[])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(CHAT_STREAM_PATH, json=_request_body(str(wiki_project)))

    assert resp.status_code == 200
    events = _parse_ndjson(resp.text)
    assert len(events) == 1
    assert events[0] == {"event": "done", "data": {"citations": []}}


@pytest.mark.asyncio()
async def test_chat_stream_llm_error_reraises_after_error_event(wiki_project, patch_wiki_chat):
    """LLM 异常路径: generator 写 error 行后必须 re-raise (关连接).

    httpx 的 ASGITransport 会把 streaming generator 的 raise 透传给调用方,
    所以这里用 ``pytest.raises`` 锁定"先 yield error + 后 re-raise"契约。
    """

    patch_wiki_chat(_stub_llm_context_broken())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        with pytest.raises(RuntimeError, match="LLM exploded"):
            await ac.post(CHAT_STREAM_PATH, json=_request_body(str(wiki_project)))


@pytest.mark.asyncio()
async def test_old_chat_endpoint_returns_404():
    """旧 /chat 端点已删除 → POST /chat 返回 404 (不命中)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(CHAT_PATH, json={"query": "x"})

    assert resp.status_code == 404


@pytest.mark.asyncio()
async def test_chat_stream_sets_no_cache_headers(wiki_project, patch_wiki_chat):
    """StreamingResponse 设置 Cache-Control: no-cache + X-Accel-Buffering: no."""
    patch_wiki_chat(_stub_llm_context())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(CHAT_STREAM_PATH, json=_request_body(str(wiki_project)))

    assert resp.status_code == 200
    assert resp.headers.get("cache-control") == "no-cache"
    assert resp.headers.get("x-accel-buffering") == "no"
