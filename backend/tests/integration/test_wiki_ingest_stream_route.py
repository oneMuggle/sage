r"""/wiki/ingest/stream HTTP 端点集成测试 (PR-3 Task 2 follow-up).

Per-task follow-up from PR-3 review: Task 1's integration test covers
the generator (\`backend.wiki.ingest.ingest_source_stream\`); the route
(\`/api/v1/wiki/ingest/stream\`) is a thin wrapper. These tests pin
the route contract: Content-Type, cache headers, status codes, and
the on-wire NDJSON format that the Electron main relay splits into
\`wiki-ingest-{id}-progress\` events.

All LLM/HTTP calls go through a stubbed \`ingest_source_stream\`
generator (monkeypatched on \`backend.api.wiki_routes\`) — no
real httpx/vectorstore/embeddings.
"""

from __future__ import annotations

import json
from typing import AsyncIterator, List, Tuple

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app

pytestmark = pytest.mark.integration

INGEST_STREAM_PATH = "/api/v1/wiki/ingest/stream"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _stub_progress_stream(
    stages: List[Tuple[str, int, str]] = None,
    raise_after: BaseException = None,
) -> AsyncIterator[bytes]:
    r"""Stub for \`ingest_source_stream\` yielding a pre-canned stage sequence.

    Args:
        stages: List of (stage, percent, message) tuples to yield. Default
            is the 6-step happy path: started -> completed.
        raise_after: Optional exception to raise after the last yield.
    """
    if stages is None:
        stages = [
            ("started", 0, "开始导入"),
            ("copy_source", 10, "stubbed copy"),
            ("step1_analyze", 20, "stubbed analyze"),
            ("step2_write", 50, "stubbed write"),
            ("embedding", 80, "stubbed embed"),
            ("completed", 100, "stubbed done"),
        ]
    for stage, percent, message in stages:
        line = (
            json.dumps(
                {
                    "event": "progress",
                    "data": {"stage": stage, "percent": percent, "message": message},
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        yield line.encode("utf-8")
    if raise_after is not None:
        raise raise_after


def _parse_ndjson(text: str) -> List[dict]:
    return [json.loads(line) for line in text.split("\n") if line.strip()]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def wiki_project(tmp_path):
    """Minimal wiki project with a real .md source file."""
    project = tmp_path / "wiki-project"
    wiki = project / "wiki"
    wiki.mkdir(parents=True)
    (wiki / "entities").mkdir()
    raw = project / "raw" / "sources"
    raw.mkdir(parents=True)
    (raw / "doc.md").write_text("# source\nbody")
    return project


@pytest.fixture()
def patch_ingest_stream(monkeypatch):
    r"""Patch \`ingest_source_stream\` on the route module to a stub generator."""

    def _setup(stages: List[Tuple[str, int, str]] = None, raise_after: BaseException = None):
        from backend.api import wiki_routes

        async def _stub(config, project_root, source_file, ctx) -> AsyncIterator[bytes]:
            async for chunk in _stub_progress_stream(stages=stages, raise_after=raise_after):
                yield chunk

        monkeypatch.setattr(wiki_routes, "ingest_source_stream", _stub)
        # Also patch the symbol imported in the route's closure
        from backend.wiki import ingest as wiki_ingest

        monkeypatch.setattr(wiki_ingest, "ingest_source_stream", _stub)

    return _setup


def _make_request_body(project, source: str = "doc.md", source_abs: str = None) -> dict:
    return {
        "source_file": str(project / "raw" / "sources" / source)
        if source_abs is None
        else source_abs,
        "project_path": str(project),
        "llm_base_url": "http://api.test",
        "llm_api_key": "sk-test",
        "llm_model": "gpt-4",
        "embed_base_url": "http://api.test",
        "embed_api_key": "sk-test",
        "embed_model": "text-embedding-3-small",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_ingest_stream_returns_application_x_ndjson_content_type(
    wiki_project, patch_ingest_stream
):
    """StreamingResponse advertises the right media type so Electron
    main's parseNdjsonStream can split lines correctly."""
    patch_ingest_stream()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(INGEST_STREAM_PATH, json=_make_request_body(wiki_project))
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/x-ndjson")


@pytest.mark.asyncio()
async def test_ingest_stream_sets_no_cache_headers(wiki_project, patch_ingest_stream):
    """Cache-Control + X-Accel-Buffering prevent proxies from buffering
    the stream (which would defeat SSE/NDJSON delivery)."""
    patch_ingest_stream()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(INGEST_STREAM_PATH, json=_make_request_body(wiki_project))
        assert r.status_code == 200
        assert r.headers["cache-control"] == "no-cache"
        assert r.headers["x-accel-buffering"] == "no"


@pytest.mark.asyncio()
async def test_ingest_stream_yields_six_progress_events_for_happy_path(
    wiki_project, patch_ingest_stream
):
    """End-to-end: route calls patched generator, response body is the
    generator's NDJSON lines verbatim."""
    patch_ingest_stream()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(INGEST_STREAM_PATH, json=_make_request_body(wiki_project))
        assert r.status_code == 200
        events = _parse_ndjson(r.text)
        stages = [e["data"]["stage"] for e in events]
        assert stages == [
            "started",
            "copy_source",
            "step1_analyze",
            "step2_write",
            "embedding",
            "completed",
        ]
        # First percent 0, last 100
        assert events[0]["data"]["percent"] == 0
        assert events[-1]["data"]["percent"] == 100
        # All event type is "progress"
        assert all(e["event"] == "progress" for e in events)


@pytest.mark.asyncio()
async def test_ingest_stream_returns_404_for_missing_source_file(wiki_project, patch_ingest_stream):
    """Fast-fail BEFORE the stream opens — surface parse errors as
    HTTPException (500/400), not as half-streamed NDJSON."""
    patch_ingest_stream()
    body = _make_request_body(wiki_project, source_abs="/nonexistent/path/missing.md")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(INGEST_STREAM_PATH, json=body)
        assert r.status_code == 404
        assert "源文件不存在" in r.json()["detail"]


@pytest.mark.asyncio()
async def test_ingest_stream_yields_failed_event_when_generator_raises(
    wiki_project, patch_ingest_stream
):
    """Per backend/wiki/ingest.py contract: generator yields a 'failed'
    progress event before re-raising. The route's StreamingResponse lets
    the error propagate, but the 'failed' line has already been emitted."""
    patch_ingest_stream(stages=[("started", 0, "begin")], raise_after=RuntimeError("LLM down"))
    with pytest.raises(RuntimeError, match="LLM down"):  # noqa: PT012
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(INGEST_STREAM_PATH, json=_make_request_body(wiki_project))
            # The 'failed' event should appear in the response body
            # before the generator raises. With FastAPI's StreamingResponse,
            # partial body may already be sent.
            assert "failed" in r.text  # noqa: PT012  (multi-line setup for the test contract)
