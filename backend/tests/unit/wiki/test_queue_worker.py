"""摄入队列处理入口测试。"""

from __future__ import annotations

import asyncio

import pytest

from backend.wiki import queue_worker as qw
from backend.wiki.ingest_queue import IngestQueue, QueueStatus

pytestmark = pytest.mark.unit


class _Result:
    wiki_page_path = "wiki/sources/a.md"
    page_type = "source"


def _seed_task(tmp_path):
    (tmp_path / "raw" / "sources").mkdir(parents=True)
    source = tmp_path / "raw" / "sources" / "a.md"
    source.write_text("# a", encoding="utf-8")
    queue = IngestQueue(tmp_path)
    return queue.add("raw/sources/a.md")


def _configure(monkeypatch):
    monkeypatch.setattr(
        qw,
        "_load_llm_config",
        lambda: {"base_url": "https://example.test", "api_key": "k", "model": "m"},
    )
    monkeypatch.setattr(
        qw,
        "_load_embedding_config",
        lambda: {"base_url": "https://example.test", "api_key": "k", "model": "e"},
    )


@pytest.mark.asyncio()
async def test_process_pending_marks_completed(tmp_path, monkeypatch):
    task_id = _seed_task(tmp_path)
    _configure(monkeypatch)

    async def fake_ingest(*args, **kwargs):
        return _Result()

    monkeypatch.setattr(qw, "ingest_source", fake_ingest)

    out = await qw.process_pending(tmp_path, limit=1)

    assert out["processed"] == [
        {"task_id": task_id, "status": "completed", "wiki_page_path": "wiki/sources/a.md"}
    ]
    assert IngestQueue(tmp_path).get(task_id).status is QueueStatus.COMPLETED


@pytest.mark.asyncio()
async def test_process_pending_marks_failed_on_error(tmp_path, monkeypatch):
    task_id = _seed_task(tmp_path)
    _configure(monkeypatch)

    async def fake_ingest(*args, **kwargs):
        raise RuntimeError("LLM down")

    monkeypatch.setattr(qw, "ingest_source", fake_ingest)

    out = await qw.process_pending(tmp_path, limit=1)

    assert out["processed"][0]["status"] == "failed"
    assert "LLM down" in out["processed"][0]["error"]
    assert IngestQueue(tmp_path).get(task_id).status is QueueStatus.FAILED


@pytest.mark.asyncio()
async def test_process_pending_requires_llm_and_embedding_config(tmp_path, monkeypatch):
    task_id = _seed_task(tmp_path)
    monkeypatch.setattr(qw, "_load_llm_config", lambda: None)
    monkeypatch.setattr(qw, "_load_embedding_config", lambda: None)

    out = await qw.process_pending(tmp_path, limit=1)

    assert out["processed"] == []
    assert "未配置" in out["error"]
    assert IngestQueue(tmp_path).get(task_id).status is QueueStatus.PENDING


@pytest.mark.asyncio()
async def test_process_pending_rejects_source_outside_project(tmp_path, monkeypatch):
    queue = IngestQueue(tmp_path)
    task_id = queue.add("../../outside.md")
    _configure(monkeypatch)

    async def fake_ingest(*args, **kwargs):  # pragma: no cover - 不应被调用
        raise AssertionError("ingest must not run for escaped paths")

    monkeypatch.setattr(qw, "ingest_source", fake_ingest)

    out = await qw.process_pending(tmp_path, limit=1)

    assert out["processed"][0]["status"] == "failed"
    assert IngestQueue(tmp_path).get(task_id).status is QueueStatus.FAILED


@pytest.mark.asyncio()
async def test_cancellation_returns_task_to_pending(tmp_path, monkeypatch):
    task_id = _seed_task(tmp_path)
    _configure(monkeypatch)

    async def cancelled_ingest(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(qw, "ingest_source", cancelled_ingest)

    with pytest.raises(asyncio.CancelledError):
        await qw.process_pending(tmp_path, limit=1)

    task = IngestQueue(tmp_path).get(task_id)
    assert task.status is QueueStatus.PENDING
    assert task.retry_count == 0


@pytest.mark.asyncio()
async def test_stale_processing_is_recovered(tmp_path, monkeypatch):
    task_id = _seed_task(tmp_path)
    queue = IngestQueue(tmp_path)
    queue.mark_processing(task_id)
    _configure(monkeypatch)

    async def fake_ingest(*args, **kwargs):
        return _Result()

    monkeypatch.setattr(qw, "ingest_source", fake_ingest)

    out = await qw.process_pending(tmp_path, limit=1)

    assert out["processed"][0]["status"] == "completed"
    assert IngestQueue(tmp_path).get(task_id).status is QueueStatus.COMPLETED


@pytest.mark.asyncio()
async def test_concurrent_enqueue_is_not_lost(tmp_path, monkeypatch):
    _seed_task(tmp_path)
    _configure(monkeypatch)

    async def fake_ingest(*args, **kwargs):
        # 模拟处理期间 UI 另一个实例入队
        IngestQueue(tmp_path).add("raw/sources/a.md")
        return _Result()

    monkeypatch.setattr(qw, "ingest_source", fake_ingest)

    await qw.process_pending(tmp_path, limit=1)

    tasks = IngestQueue(tmp_path).get_all()
    assert len(tasks) == 2
    assert sum(1 for task in tasks if task.status is QueueStatus.COMPLETED) == 1
    assert sum(1 for task in tasks if task.status is QueueStatus.PENDING) == 1
