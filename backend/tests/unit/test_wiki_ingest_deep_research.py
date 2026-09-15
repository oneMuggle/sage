"""Regression tests for immutable ingest input and Deep Research embedding wiring."""

import asyncio
import importlib
from unittest.mock import AsyncMock, Mock

import pytest

deep_research_module = importlib.import_module("backend.wiki.deep_research")
from backend.wiki.deep_research import ResearchTask
from backend.wiki.extract import MAX_FILE_BYTES, FileTooLargeError
from backend.wiki.ingest import IngestConfig, ingest_source, ingest_source_stream
from backend.wiki.llm_context import LLMContext
from backend.wiki.models import Analysis, IngestResult
from backend.wiki.web_search import SearchProvider, WebSearchResult


@pytest.fixture()
def ingest_config() -> IngestConfig:
    return IngestConfig(
        llm_base_url="http://llm.test",
        llm_api_key="test-key",
        llm_model="test-model",
        embed_base_url="http://embed.test",
        embed_api_key="test-key",
        embed_model="test-embedding",
    )


@pytest.mark.asyncio()
async def test_ingest_source_uses_supplied_bytes_after_source_path_disappears(
    tmp_path, ingest_config, monkeypatch
):
    """A caller-held snapshot remains the input for every ingest stage."""
    import backend.wiki.ingest as ingest_module

    source_path = tmp_path / "removed-before-ingest.md"
    target = tmp_path / "raw" / "sources" / "Explicit Name.md"
    supplied = b"# Immutable source\n\nThe path may disappear."
    secure_read = Mock()
    monkeypatch.setattr(ingest_module, "secure_read_file_bounded", secure_read)

    monkeypatch.setattr(ingest_module, "copy_to_raw", AsyncMock(return_value=target))
    monkeypatch.setattr(ingest_module, "cache_get", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        ingest_module,
        "analyze_source",
        AsyncMock(return_value=Analysis([], [], [], [], "summary")),
    )
    monkeypatch.setattr(
        ingest_module,
        "generate_pages",
        AsyncMock(
            return_value=(
                tmp_path / "wiki" / "sources" / "explicit-name.md",
                "source",
                "---\npage_type: source\n---\n# Generated",
            )
        ),
    )
    monkeypatch.setattr(ingest_module, "embed_pages", AsyncMock())
    cache_put = Mock()
    monkeypatch.setattr(ingest_module, "cache_put", cache_put)

    result = await ingest_source(
        config=ingest_config,
        project_root=tmp_path,
        source_file_path=source_path,
        llm_call=AsyncMock(),
        http_post=AsyncMock(),
        logical_filename="Explicit Name.md",
        source_content=supplied,
    )

    assert result == IngestResult(
        source_path="raw/sources/Explicit Name.md",
        wiki_page_path="wiki/sources/explicit-name.md",
        page_type="source",
    )
    secure_read.assert_not_called()
    copy_call = ingest_module.copy_to_raw.await_args
    assert copy_call.kwargs["source_content"] == supplied
    assert copy_call.kwargs["logical_filename"] == "Explicit Name.md"
    assert ingest_module.analyze_source.await_args.kwargs["source_content"] == supplied
    assert ingest_module.generate_pages.await_args.kwargs["source_name"] == "Explicit Name.md"
    assert ingest_module.cache_put.call_args.kwargs["source_content"] == supplied


@pytest.mark.asyncio()
async def test_ingest_source_stream_reuses_one_source_snapshot(
    tmp_path, ingest_config, monkeypatch
):
    """The streaming implementation keeps source bytes stable through all stages."""
    import backend.wiki.ingest as ingest_module

    source_path = tmp_path / "source.md"
    supplied = b"# stream source"
    secure_read = Mock()
    monkeypatch.setattr(ingest_module, "secure_read_file_bounded", secure_read)
    monkeypatch.setattr(ingest_module, "copy_to_raw", AsyncMock(return_value=tmp_path / "target.md"))
    monkeypatch.setattr(ingest_module, "cache_get", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        ingest_module,
        "analyze_source",
        AsyncMock(return_value=Analysis([], [], [], [], "summary")),
    )
    monkeypatch.setattr(
        ingest_module,
        "generate_pages",
        AsyncMock(return_value=(tmp_path / "page.md", "source", "# content")),
    )
    monkeypatch.setattr(ingest_module, "embed_pages", AsyncMock())
    monkeypatch.setattr(ingest_module, "cache_put", Mock())

    secure_read.return_value = supplied

    async def llm_call(messages, temperature):
        return ""

    async def stream_call(messages, temperature):
        if False:
            yield ""

    async def http_post(url, headers, body):
        return "{}"

    events = [
        event
        async for event in ingest_source_stream(
            ingest_config,
            tmp_path,
            source_path,
            LLMContext(llm_call, stream_call, http_post),
            logical_filename="named.md",
        )
    ]

    assert '"stage": "completed"' in events[-1].decode()
    secure_read.assert_called_once_with(tmp_path, source_path, MAX_FILE_BYTES)
    assert ingest_module.analyze_source.await_args.kwargs["source_content"] == supplied
    assert ingest_module.generate_pages.await_args.kwargs["source_name"] == "named.md"
    assert ingest_module.cache_put.call_args.kwargs["source_content"] == supplied


@pytest.mark.asyncio()
async def test_ingest_source_rejects_oversized_supplied_bytes(tmp_path, ingest_config):
    """Caller-provided snapshots obey the same byte cap as file inputs."""
    with pytest.raises(FileTooLargeError):
        await ingest_source(
            config=ingest_config,
            project_root=tmp_path,
            source_file_path=tmp_path / "source.md",
            llm_call=AsyncMock(),
            http_post=AsyncMock(),
            source_content=b"x" * (MAX_FILE_BYTES + 1),
        )
async def _run_research(
    monkeypatch, tmp_path, http_post=None, patch_temp=True, patch_cleanup=True
):
    monkeypatch.setattr(deep_research_module, "generate_search_queries", AsyncMock(return_value=["q"]))
    monkeypatch.setattr(
        deep_research_module,
        "multi_query_search",
        AsyncMock(
            return_value=[WebSearchResult(title="title", url="https://example.test", snippet="snippet")]
        ),
    )
    monkeypatch.setattr(deep_research_module, "synthesize_research", AsyncMock(return_value="# report"))
    if patch_temp:
        monkeypatch.setattr(deep_research_module, "secure_write_temp_file", lambda *args: tmp_path / "report.md")
    if patch_cleanup:
        monkeypatch.setattr(deep_research_module, "secure_delete_path", lambda *args: None)
    return await deep_research_module.deep_research(
        ResearchTask(id="task", topic="topic"),
        tmp_path,
        SearchProvider.SEARXNG,
        llm_call=AsyncMock(),
        ingest_config=IngestConfig("", "", "", "", "", ""),
        http_post=http_post,
    )


@pytest.mark.asyncio()
async def test_deep_research_passes_http_post_to_automatic_ingest(tmp_path, monkeypatch):
    """Automatic ingest receives the caller's real embedding callback."""
    callback = AsyncMock()
    captured = {}

    async def fake_ingest_source(**kwargs):
        captured.update(kwargs)
        return IngestResult("raw/sources/report.md", "wiki/sources/report.md", "source")

    monkeypatch.setattr(deep_research_module, "ingest_source", fake_ingest_source)
    task = await _run_research(monkeypatch, tmp_path, http_post=callback)

    assert task.status == "done"
    assert captured["http_post"] is callback
    assert callable(captured["http_post"])


@pytest.mark.asyncio()
async def test_deep_research_ingest_failure_reports_error(tmp_path, monkeypatch):
    """An ingest exception must not be reported as a completed research task."""
    monkeypatch.setattr(deep_research_module, "ingest_source", AsyncMock(side_effect=RuntimeError("provider failure")))

    task = await _run_research(monkeypatch, tmp_path, http_post=AsyncMock())

    assert task.status == "error"
    assert task.error == {
        "code": "deep_research_ingest_failed",
        "message": "自动 Ingest 失败",
    }


@pytest.mark.asyncio()
async def test_deep_research_missing_http_post_reports_error(tmp_path, monkeypatch):
    """Missing embedding capability cannot be reported as successful ingest."""
    ingest = AsyncMock()
    monkeypatch.setattr(deep_research_module, "ingest_source", ingest)

    task = await _run_research(monkeypatch, tmp_path)

    assert task.status == "error"
    assert task.error == {
        "code": "deep_research_ingest_failed",
        "message": "自动 Ingest 失败",
    }
    ingest.assert_not_awaited()


@pytest.mark.asyncio()
async def test_deep_research_cancelled_ingest_cleans_up_report(tmp_path, monkeypatch):
    """Cancellation must remove the private report before propagating."""
    temp_file = tmp_path / "report.md"
    deleted = []
    monkeypatch.setattr(deep_research_module, "secure_write_temp_file", lambda *args: temp_file)
    monkeypatch.setattr(
        deep_research_module,
        "secure_delete_path",
        lambda root, path: deleted.append((root, path)),
    )
    monkeypatch.setattr(
        deep_research_module,
        "ingest_source",
        AsyncMock(side_effect=asyncio.CancelledError),
    )

    with pytest.raises(asyncio.CancelledError):
        await _run_research(
            monkeypatch,
            tmp_path,
            http_post=AsyncMock(),
            patch_temp=False,
            patch_cleanup=False,
        )

    assert deleted == [(tmp_path, temp_file)]
