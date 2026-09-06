"""Wiki Ingest Queue API 集成测试。

测试 queue_* 端点处理函数，使用 monkeypatch 绕过项目授权。
"""
from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.api import wiki_routes
from backend.api.wiki_routes import (
    QueueAddRequest,
    queue_add,
    queue_cancel,
    queue_clear,
    queue_next,
    queue_retry,
    queue_status,
    queue_tasks,
)
from backend.wiki import IngestQueue


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """创建临时 Wiki 项目。"""
    project = tmp_path / "wiki-project"
    project.mkdir()
    (project / "wiki").mkdir()
    return project


@pytest.fixture(autouse=True)
def patch_auth(monkeypatch, project_root: Path):
    """绕过项目授权。"""
    monkeypatch.setattr(
        wiki_routes,
        "authorize_registered_project",
        lambda _: project_root,
    )


class TestQueueAddEndpoint:
    """测试 POST /ingest/queue/add。"""

    async def test_add_task_returns_task_id(self, project_root: Path):
        """添加任务应返回 task_id 和 pending 状态。"""
        req = QueueAddRequest(
            project_path=str(project_root),
            source_path="/path/to/doc.pdf",
        )
        result = await queue_add(req)

        assert "task_id" in result
        assert result["status"] == "pending"
        assert len(result["task_id"]) == 8

    async def test_add_with_custom_max_retries(self, project_root: Path):
        """可以指定自定义最大重试次数。"""
        req = QueueAddRequest(
            project_path=str(project_root),
            source_path="/path/to/doc.pdf",
            max_retries=5,
        )
        result = await queue_add(req)

        queue = IngestQueue(project_root)
        task = queue.get(result["task_id"])
        assert task.max_retries == 5


class TestQueueStatusEndpoint:
    """测试 GET /ingest/queue/status。"""

    async def test_status_empty_queue(self, project_root: Path):
        """空队列应返回所有状态 0。"""
        result = await queue_status(str(project_root))

        assert result["pending"] == 0
        assert result["processing"] == 0
        assert result["completed"] == 0
        assert result["failed"] == 0
        assert result["cancelled"] == 0

    async def test_status_counts_tasks(self, project_root: Path):
        """应正确统计各状态的任务数量。"""
        queue = IngestQueue(project_root)
        queue.add("/doc1.pdf")
        queue.add("/doc2.pdf")
        task_id = queue.add("/doc3.pdf")
        queue.mark_processing(task_id)
        queue.mark_failed(task_id, "error")

        result = await queue_status(str(project_root))

        assert result["pending"] == 2
        assert result["failed"] == 1


class TestQueueTasksEndpoint:
    """测试 GET /ingest/queue/tasks。"""

    async def test_list_all_tasks(self, project_root: Path):
        """无过滤时应返回所有任务。"""
        queue = IngestQueue(project_root)
        queue.add("/doc1.pdf")
        queue.add("/doc2.pdf")

        result = await queue_tasks(str(project_root), status=None)

        assert len(result["tasks"]) == 2

    async def test_filter_by_status(self, project_root: Path):
        """可以按状态过滤。"""
        queue = IngestQueue(project_root)
        queue.add("/doc1.pdf")
        task_id = queue.add("/doc2.pdf")
        queue.mark_processing(task_id)

        result = await queue_tasks(str(project_root), status="processing")

        assert len(result["tasks"]) == 1
        assert result["tasks"][0]["status"] == "processing"

    async def test_invalid_status_returns_400(self, project_root: Path):
        """无效状态应返回 400。"""
        with pytest.raises(HTTPException) as exc_info:
            await queue_tasks(str(project_root), status="invalid-status")
        assert exc_info.value.status_code == 400


class TestQueueCancelEndpoint:
    """测试 POST /ingest/queue/cancel/{task_id}。"""

    async def test_cancel_pending_task(self, project_root: Path):
        """可以取消 PENDING 任务。"""
        queue = IngestQueue(project_root)
        task_id = queue.add("/doc.pdf")

        result = await queue_cancel(task_id, str(project_root))

        assert result["success"] is True
        # Re-load from disk (handler created its own instance)
        queue_reloaded = IngestQueue(project_root)
        task = queue_reloaded.get(task_id)
        assert task.status.value == "cancelled"

    async def test_cancel_processing_task_returns_400(self, project_root: Path):
        """不能取消 PROCESSING 任务，应返回 400。"""
        queue = IngestQueue(project_root)
        task_id = queue.add("/doc.pdf")
        queue.mark_processing(task_id)

        with pytest.raises(HTTPException) as exc_info:
            await queue_cancel(task_id, str(project_root))
        assert exc_info.value.status_code == 400

    async def test_cancel_nonexistent_task_returns_400(self, project_root: Path):
        """取消不存在的任务应返回 400。"""
        with pytest.raises(HTTPException) as exc_info:
            await queue_cancel("nonexist", str(project_root))
        assert exc_info.value.status_code == 400


class TestQueueRetryEndpoint:
    """测试 POST /ingest/queue/retry/{task_id}。"""

    async def test_retry_failed_task(self, project_root: Path):
        """可以重试 FAILED 任务。"""
        queue = IngestQueue(project_root)
        task_id = queue.add("/doc.pdf")
        queue.mark_processing(task_id)
        queue.mark_failed(task_id, "error")

        result = await queue_retry(task_id, str(project_root))

        assert result["success"] is True
        queue_reloaded = IngestQueue(project_root)
        task = queue_reloaded.get(task_id)
        assert task.status.value == "pending"

    async def test_retry_pending_task_returns_400(self, project_root: Path):
        """不能重试非 FAILED 任务，应返回 400。"""
        queue = IngestQueue(project_root)
        task_id = queue.add("/doc.pdf")

        with pytest.raises(HTTPException) as exc_info:
            await queue_retry(task_id, str(project_root))
        assert exc_info.value.status_code == 400


class TestQueueNextEndpoint:
    """测试 GET /ingest/queue/next。"""

    async def test_next_empty_queue(self, project_root: Path):
        """空队列应返回 task=null。"""
        result = await queue_next(str(project_root))
        assert result["task"] is None

    async def test_next_returns_pending_task(self, project_root: Path):
        """应返回下一个 PENDING 任务。"""
        queue = IngestQueue(project_root)
        task_id = queue.add("/doc1.pdf")
        queue.add("/doc2.pdf")

        result = await queue_next(str(project_root))

        assert result["task"] is not None
        assert result["task"]["task_id"] == task_id
        assert result["task"]["status"] == "pending"

    async def test_next_skips_processing_task(self, project_root: Path):
        """get_next_pending 应跳过 PROCESSING 任务。"""
        queue = IngestQueue(project_root)
        task_id1 = queue.add("/doc1.pdf")
        queue.add("/doc2.pdf")
        queue.mark_processing(task_id1)

        result = await queue_next(str(project_root))

        assert result["task"] is not None
        assert result["task"]["task_id"] != task_id1


class TestQueueClearEndpoint:
    """测试 POST /ingest/queue/clear。"""

    async def test_clear_completed_only(self, project_root: Path):
        """completed_only=True 应只清除 COMPLETED 任务。"""
        queue = IngestQueue(project_root)
        task_id1 = queue.add("/doc1.pdf")
        queue.add("/doc2.pdf")  # PENDING，保留
        queue.mark_processing(task_id1)
        queue.mark_completed(task_id1, {"wiki_page_path": "wiki/sources/doc1.md"})

        result = await queue_clear(str(project_root), completed_only=True)

        assert result["cleared"] == 1
        queue_reloaded = IngestQueue(project_root)
        remaining = queue_reloaded.get_all()
        assert len(remaining) == 1
        assert remaining[0].source_path == "/doc2.pdf"

    async def test_clear_all(self, project_root: Path):
        """completed_only=False 应清除所有任务。"""
        queue = IngestQueue(project_root)
        queue.add("/doc1.pdf")
        queue.add("/doc2.pdf")
        queue.add("/doc3.pdf")

        result = await queue_clear(str(project_root), completed_only=False)

        assert result["cleared"] == 3
        queue_reloaded = IngestQueue(project_root)
        assert len(queue_reloaded.get_all()) == 0


class TestQueueWorkflow:
    """端到端工作流测试。"""

    async def test_full_lifecycle(self, project_root: Path):
        """完整生命周期: add → next → mark processing → complete。"""
        # 添加任务
        req = QueueAddRequest(
            project_path=str(project_root),
            source_path="/doc.pdf",
        )
        add_result = await queue_add(req)
        task_id = add_result["task_id"]

        # 查看状态
        status = await queue_status(str(project_root))
        assert status["pending"] == 1

        # 获取下一个任务
        next_result = await queue_next(str(project_root))
        assert next_result["task"]["task_id"] == task_id

        # 清除已完成（此时没有完成的）
        clear_result = await queue_clear(str(project_root), completed_only=True)
        assert clear_result["cleared"] == 0

        # 手动推进状态
        queue = IngestQueue(project_root)
        queue.mark_processing(task_id)
        queue.mark_completed(task_id, {"wiki_page_path": "wiki/sources/doc.md"})

        # 验证最终状态
        status = await queue_status(str(project_root))
        assert status["completed"] == 1
        assert status["pending"] == 0

        # 清除已完成
        clear_result = await queue_clear(str(project_root), completed_only=True)
        assert clear_result["cleared"] == 1
