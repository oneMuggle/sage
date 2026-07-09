"""/wiki/ingest/stream NDJSON 端点内部实现 (PR-3 Task 1) 集成测试.

直接驱动 ``backend.wiki.ingest.ingest_source_stream`` 异步生成器,
验证:

- NDJSON 字节流格式 (UTF-8, ``\\n``-terminated)
- Stages 顺序与 ``WikiIngestProgress::STAGE_LABELS`` 一致
- 百分比单调递增,首尾为 0 / 100
- 缓存命中分支:直接 ``completed`` 返回
- 异常分支:yield ``failed`` 后 re-raise

所有 LLM/HTTP 调用都通过 stub ``LLMContext`` 桩化,避开真实 httpx /
vectorstore / embeddings。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Tuple

import pytest

from backend.wiki.ingest import IngestConfig, ingest_source_stream
from backend.wiki.llm_context import LLMContext

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


EMBED_DIM = 1536


def _stub_llm_context(
    analysis_json: str = '{"entities":[],"concepts":[],"tags":[],"related_topics":[],"summary":""}',
    wiki_body: str = "---\npage_type: source\n---\n# stubbed body",
) -> LLMContext:
    """构造受控 LLMContext 桩:每个 LLM/HTTP 调用返回固定内容。"""

    async def fake_llm_call(messages, temperature):
        # 第一次调用 (Step 1) 返回 analysis JSON, 第二次 (Step 2) 返回 wiki body
        if messages and "JSON-only" in messages[0]["content"]:
            return analysis_json
        return wiki_body

    async def fake_llm_stream_call(messages, temperature):
        # ingest_source_stream 不会触发流式 LLM, 仅作 placeholder
        if False:  # pragma: no cover — make it an async generator
            yield ""
            return
        return

    async def fake_http_post(url, headers, body):
        # embed response: 一个 1536 维向量对应一个 chunk
        n_chunks = len(body.get("input", []))
        data = [{"embedding": [0.0] * EMBED_DIM} for _ in range(n_chunks)]
        return json.dumps({"data": data})

    return LLMContext(
        llm_call=fake_llm_call,
        llm_stream_call=fake_llm_stream_call,
        http_post=fake_http_post,
    )


def _make_ingest_config() -> IngestConfig:
    return IngestConfig(
        llm_base_url="http://api.test",
        llm_api_key="sk-test",
        llm_model="gpt-4",
        embed_base_url="http://api.test",
        embed_api_key="sk-test",
        embed_model="text-embedding-3-small",
        embed_dim=EMBED_DIM,
    )


def _make_wiki_project(tmp_path: Path) -> Tuple[Path, Path]:
    """最小 wiki project 结构: 返回 (project_root, source_file)。"""
    project = tmp_path / "wiki-project"
    (project / "wiki" / "entities").mkdir(parents=True)
    raw = project / "raw" / "sources"
    raw.mkdir(parents=True)
    source = raw / "doc.md"
    source.write_text("# source\nbody content for test", encoding="utf-8")
    return project, source


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_ingest_stream_emits_progress_in_order(tmp_path):
    """Happy path: stream yields 6+ progress events in expected stage order."""
    project, source = _make_wiki_project(tmp_path)
    ctx = _stub_llm_context()
    config = _make_ingest_config()

    events = []
    async for line_bytes in ingest_source_stream(config, project, source, ctx):
        events.append(json.loads(line_bytes.decode("utf-8")))

    # All events are progress
    assert all(e["event"] == "progress" for e in events)

    stages = [e["data"]["stage"] for e in events]

    # First / last stage
    assert stages[0] == "started", f"first stage should be 'started', got {stages[0]!r}"
    assert stages[-1] == "completed", f"last stage should be 'completed', got {stages[-1]!r}"

    # Required intermediate stages (subset check, 顺序由实现保证)
    for required in ("copy_source", "step1_analyze", "step2_write", "embedding"):
        assert required in stages, f"missing stage {required!r} in {stages!r}"

    # Percent monotonic non-decreasing
    percents = [e["data"]["percent"] for e in events]
    assert percents == sorted(percents), f"percents not monotonic: {percents}"
    assert percents[0] == 0
    assert percents[-1] == 100

    # Wiki file actually written
    wiki_files = list((project / "wiki" / "sources").glob("*.md"))
    assert len(wiki_files) == 1

    # Cache populated
    cache_file = project / ".llm-wiki" / "ingest-cache.json"
    assert cache_file.exists()
    cache_data = json.loads(cache_file.read_text(encoding="utf-8"))
    assert "raw/sources/doc.md" in cache_data


@pytest.mark.asyncio()
async def test_ingest_stream_ndjson_bytes_format(tmp_path):
    """NDJSON 字节流: 每行 UTF-8 + ``\\n`` 终止 + 可独立 JSON 解析。"""
    project, source = _make_wiki_project(tmp_path)
    ctx = _stub_llm_context()
    config = _make_ingest_config()

    raw_lines: List[bytes] = []
    async for line_bytes in ingest_source_stream(config, project, source, ctx):
        raw_lines.append(line_bytes)

    assert len(raw_lines) >= 6
    for line in raw_lines:
        assert isinstance(line, bytes)
        assert line.endswith(b"\n"), f"line not \\n-terminated: {line!r}"
        # 单独解析该行 (不带 \\n)
        parsed = json.loads(line.decode("utf-8").rstrip("\n"))
        assert parsed["event"] == "progress"
        assert "stage" in parsed["data"]
        assert "percent" in parsed["data"]


@pytest.mark.asyncio()
async def test_ingest_stream_stage_labels_match_widget(tmp_path):
    """Stages 集合必须匹配 ``WikiIngestProgress.tsx::STAGE_LABELS`` 键集合(除 'unknown')。

    6 个 stage keys: ``started`` / ``copy_source`` / ``step1_analyze`` /
    ``step2_write`` / ``embedding`` / ``completed``。
    """
    project, source = _make_wiki_project(tmp_path)
    ctx = _stub_llm_context()
    config = _make_ingest_config()

    events = []
    async for line_bytes in ingest_source_stream(config, project, source, ctx):
        events.append(json.loads(line_bytes.decode("utf-8")))

    stages = {e["data"]["stage"] for e in events}
    expected = {
        "started",
        "copy_source",
        "step1_analyze",
        "step2_write",
        "embedding",
        "completed",
    }
    assert stages == expected, f"stage set mismatch: got {stages}, expected {expected}"


@pytest.mark.asyncio()
async def test_ingest_stream_cache_hit_short_circuits(tmp_path):
    """缓存命中: 在 cache 命中后直接 emit ``completed`` 并 return, 不调用 LLM。"""
    project, source = _make_wiki_project(tmp_path)
    config = _make_ingest_config()

    # 预填缓存 (sha256 of "body content for test" computed by ingest module)
    from backend.wiki.ingest import _compute_sha256

    content = source.read_text(encoding="utf-8")[:50_000]
    sha = _compute_sha256(content)
    cache_file = project / ".llm-wiki" / "ingest-cache.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps(
            {
                "raw/sources/doc.md": {
                    "sha256": sha,
                    "wiki_page_path": "wiki/sources/doc.md",
                    "page_type": "source",
                }
            }
        ),
        encoding="utf-8",
    )

    # LLM call 计数器
    call_count = {"n": 0}

    async def counting_llm(messages, temperature):
        call_count["n"] += 1
        return "should not be called"

    async def noop_stream(messages, temperature):
        if False:  # pragma: no cover
            yield ""
            return
        return

    async def noop_post(url, headers, body):
        return "{}"

    ctx = LLMContext(
        llm_call=counting_llm,
        llm_stream_call=noop_stream,
        http_post=noop_post,
    )

    events = []
    async for line_bytes in ingest_source_stream(config, project, source, ctx):
        events.append(json.loads(line_bytes.decode("utf-8")))

    stages = [e["data"]["stage"] for e in events]
    # 缓存命中: started → copy_source → completed (3 个事件)
    assert stages == ["started", "copy_source", "completed"], f"unexpected stages: {stages!r}"
    assert call_count["n"] == 0, "LLM should NOT be called on cache hit"


@pytest.mark.asyncio()
async def test_ingest_stream_exception_yields_failed_then_reraises(tmp_path):
    """异常路径: yield ``failed`` event (percent=0), 然后 re-raise 给 FastAPI 关流。"""
    project, source = _make_wiki_project(tmp_path)
    config = _make_ingest_config()

    async def exploding_llm(messages, temperature):
        raise RuntimeError("LLM exploded mid-ingest")

    async def noop_stream(messages, temperature):
        if False:  # pragma: no cover
            yield ""
            return
        return

    async def noop_post(url, headers, body):
        return "{}"

    ctx = LLMContext(
        llm_call=exploding_llm,
        llm_stream_call=noop_stream,
        http_post=noop_post,
    )

    async def _collect_events(sink: List[dict]) -> None:
        async for line_bytes in ingest_source_stream(config, project, source, ctx):
            sink.append(json.loads(line_bytes.decode("utf-8")))

    collected: List[dict] = []
    with pytest.raises(RuntimeError, match="LLM exploded mid-ingest"):
        await _collect_events(collected)

    # 最后一条 event 必须是 failed
    assert collected, "expected at least one event before exception"
    last = collected[-1]
    assert last["event"] == "progress"
    assert last["data"]["stage"] == "failed"
    assert last["data"]["percent"] == 0
    assert "LLM exploded" in last["data"]["message"]

    # 之前必须至少 emit 过 started
    assert collected[0]["data"]["stage"] == "started"
