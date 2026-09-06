"""IngestQueue 单元测试。

测试持久化摄入队列的所有操作。
"""
import json
from pathlib import Path

import pytest

from backend.wiki.ingest_queue import IngestQueue, IngestTask, QueueStatus


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """创建临时项目目录。"""
    project = tmp_path / "wiki-project"
    project.mkdir()
    (project / "wiki").mkdir()
    return project


@pytest.fixture
def queue(project_root: Path) -> IngestQueue:
    """创建测试队列。"""
    return IngestQueue(project_root)


class TestIngestQueueAdd:
    """测试添加任务。"""

    def test_add_task_returns_task_id(self, queue: IngestQueue):
        """添加任务应返回 8 位 task_id。"""
        task_id = queue.add("/path/to/document.pdf")
        assert len(task_id) == 8
        assert isinstance(task_id, str)

    def test_add_task_creates_pending_task(self, queue: IngestQueue):
        """添加的任务状态应为 PENDING。"""
        task_id = queue.add("/path/to/document.pdf")
        task = queue.get(task_id)

        assert task is not None
        assert task.status == QueueStatus.PENDING
        assert task.source_path == "/path/to/document.pdf"
        assert task.retry_count == 0
        assert task.max_retries == 3

    def test_add_task_with_custom_max_retries(self, queue: IngestQueue):
        """可以指定自定义最大重试次数。"""
        task_id = queue.add("/path/to/document.pdf", max_retries=5)
        task = queue.get(task_id)
        assert task.max_retries == 5

    def test_add_multiple_tasks(self, queue: IngestQueue):
        """可以添加多个任务。"""
        queue.add("/path/to/doc1.pdf")
        queue.add("/path/to/doc2.pdf")
        queue.add("/path/to/doc3.pdf")
        assert len(queue.get_all()) == 3


class TestIngestQueuePersistence:
    """测试队列持久化。"""

    def test_queue_persists_to_file(self, queue: IngestQueue, project_root: Path):
        """队列应持久化到 JSON 文件。"""
        queue.add("/path/to/document.pdf")
        queue_file = project_root / ".llm-wiki" / "ingest-queue.json"
        assert queue_file.exists()

        data = json.loads(queue_file.read_text())
        assert "version" in data
        assert "tasks" in data
        assert len(data["tasks"]) == 1

    def test_queue_loads_from_file(self, project_root: Path):
        """新队列实例应从文件加载已有任务。"""
        queue1 = IngestQueue(project_root)
        task_id = queue1.add("/path/to/document.pdf")

        queue2 = IngestQueue(project_root)
        task = queue2.get(task_id)

        assert task is not None
        assert task.source_path == "/path/to/document.pdf"

    def test_queue_handles_corrupted_file(self, project_root: Path):
        """队列应优雅处理损坏的 JSON 文件。"""
        queue_file = project_root / ".llm-wiki" / "ingest-queue.json"
        queue_file.parent.mkdir(parents=True, exist_ok=True)
        queue_file.write_text("{ invalid json }")

        queue = IngestQueue(project_root)
        assert len(queue.get_all()) == 0


class TestIngestQueueStatusTransitions:
    """测试状态转换。"""

    def test_mark_processing(self, queue: IngestQueue):
        """可以将 PENDING 任务标记为 PROCESSING。"""
        task_id = queue.add("/path/to/document.pdf")
        success = queue.mark_processing(task_id)
        assert success is True

        task = queue.get(task_id)
        assert task.status == QueueStatus.PROCESSING
        assert task.started_at is not None

    def test_mark_processing_from_non_pending_fails(self, queue: IngestQueue):
        """不能将非 PENDING 任务标记为 PROCESSING。"""
        task_id = queue.add("/path/to/document.pdf")
        queue.mark_processing(task_id)
        success = queue.mark_processing(task_id)
        assert success is False

    def test_mark_completed(self, queue: IngestQueue):
        """可以将 PROCESSING 任务标记为 COMPLETED。"""
        task_id = queue.add("/path/to/document.pdf")
        queue.mark_processing(task_id)

        result = {"wiki_page_path": "wiki/sources/doc.md"}
        success = queue.mark_completed(task_id, result)
        assert success is True

        task = queue.get(task_id)
        assert task.status == QueueStatus.COMPLETED
        assert task.completed_at is not None
        assert task.result == result

    def test_mark_completed_from_non_processing_fails(self, queue: IngestQueue):
        """不能将非 PROCESSING 任务标记为 COMPLETED。"""
        task_id = queue.add("/path/to/document.pdf")
        success = queue.mark_completed(task_id, {})
        assert success is False

    def test_mark_failed(self, queue: IngestQueue):
        """可以将任务标记为 FAILED。"""
        task_id = queue.add("/path/to/document.pdf")
        queue.mark_processing(task_id)

        success = queue.mark_failed(task_id, "处理失败")
        assert success is True

        task = queue.get(task_id)
        assert task.status == QueueStatus.FAILED
        assert task.error_message == "处理失败"
        assert task.retry_count == 1

    def test_mark_nonexistent_task_fails(self, queue: IngestQueue):
        """标记不存在的任务应返回 False。"""
        assert queue.mark_processing("nonexist") is False
        assert queue.mark_completed("nonexist", {}) is False
        assert queue.mark_failed("nonexist", "error") is False


class TestIngestQueueCancelRetry:
    """测试取消和重试。"""

    def test_cancel_pending_task(self, queue: IngestQueue):
        """可以取消 PENDING 任务。"""
        task_id = queue.add("/path/to/document.pdf")
        success = queue.cancel(task_id)
        assert success is True

        task = queue.get(task_id)
        assert task.status == QueueStatus.CANCELLED

    def test_cancel_failed_task(self, queue: IngestQueue):
        """可以取消 FAILED 任务。"""
        task_id = queue.add("/path/to/document.pdf")
        queue.mark_processing(task_id)
        queue.mark_failed(task_id, "error")

        success = queue.cancel(task_id)
        assert success is True

    def test_cancel_processing_task_fails(self, queue: IngestQueue):
        """不能取消 PROCESSING 任务。"""
        task_id = queue.add("/path/to/document.pdf")
        queue.mark_processing(task_id)

        success = queue.cancel(task_id)
        assert success is False

    def test_cancel_completed_task_fails(self, queue: IngestQueue):
        """不能取消 COMPLETED 任务。"""
        task_id = queue.add("/path/to/document.pdf")
        queue.mark_processing(task_id)
        queue.mark_completed(task_id, {})

        success = queue.cancel(task_id)
        assert success is False

    def test_retry_failed_task(self, queue: IngestQueue):
        """可以重试 FAILED 任务。"""
        task_id = queue.add("/path/to/document.pdf")
        queue.mark_processing(task_id)
        queue.mark_failed(task_id, "error")

        success = queue.retry(task_id)
        assert success is True

        task = queue.get(task_id)
        assert task.status == QueueStatus.PENDING
        assert task.error_message is None
        assert task.started_at is None

    def test_retry_exceeds_max_retries_fails(self, queue: IngestQueue):
        """超过最大重试次数后不能重试。"""
        task_id = queue.add("/path/to/document.pdf", max_retries=2)

        # 第一次失败
        queue.mark_processing(task_id)
        queue.mark_failed(task_id, "error1")
        queue.retry(task_id)

        # 第二次失败
        queue.mark_processing(task_id)
        queue.mark_failed(task_id, "error2")
        queue.retry(task_id)

        # 第三次失败（retry_count 已达 max_retries）
        queue.mark_processing(task_id)
        queue.mark_failed(task_id, "error3")

        success = queue.retry(task_id)
        assert success is False

    def test_retry_non_failed_task_fails(self, queue: IngestQueue):
        """不能重试非 FAILED 任务。"""
        task_id = queue.add("/path/to/document.pdf")
        success = queue.retry(task_id)
        assert success is False


class TestIngestQueueQuery:
    """测试查询操作。"""

    def test_get_next_pending(self, queue: IngestQueue):
        """应返回下一个 PENDING 任务。"""
        task_id1 = queue.add("/path/to/doc1.pdf")
        queue.add("/path/to/doc2.pdf")

        next_task = queue.get_next_pending()
        assert next_task is not None
        assert next_task.task_id == task_id1

    def test_get_next_pending_skips_non_pending(self, queue: IngestQueue):
        """get_next_pending 应跳过非 PENDING 任务。"""
        task_id1 = queue.add("/path/to/doc1.pdf")
        task_id2 = queue.add("/path/to/doc2.pdf")

        queue.mark_processing(task_id1)
        next_task = queue.get_next_pending()
        assert next_task is not None
        assert next_task.task_id == task_id2

    def test_get_next_pending_returns_none_when_empty(self, queue: IngestQueue):
        """队列为空时应返回 None。"""
        assert queue.get_next_pending() is None

    def test_get_by_status(self, queue: IngestQueue):
        """应按状态过滤任务。"""
        queue.add("/path/to/doc1.pdf")
        queue.add("/path/to/doc2.pdf")
        task_id3 = queue.add("/path/to/doc3.pdf")
        queue.mark_processing(task_id3)

        pending_tasks = queue.get_by_status(QueueStatus.PENDING)
        processing_tasks = queue.get_by_status(QueueStatus.PROCESSING)

        assert len(pending_tasks) == 2
        assert len(processing_tasks) == 1

    def test_get_status_summary(self, queue: IngestQueue):
        """应返回各状态的任务数量。"""
        queue.add("/path/to/doc1.pdf")
        queue.add("/path/to/doc2.pdf")
        task_id3 = queue.add("/path/to/doc3.pdf")
        queue.mark_processing(task_id3)
        queue.mark_failed(task_id3, "error")

        summary = queue.get_status_summary()

        assert summary[QueueStatus.PENDING.value] == 2
        assert summary[QueueStatus.FAILED.value] == 1
        assert summary[QueueStatus.COMPLETED.value] == 0


class TestIngestQueueClear:
    """测试清除操作。"""

    def test_clear_completed(self, queue: IngestQueue):
        """应只清除 COMPLETED 任务。"""
        task_id1 = queue.add("/path/to/doc1.pdf")
        task_id2 = queue.add("/path/to/doc2.pdf")
        queue.mark_processing(task_id1)
        queue.mark_completed(task_id1, {})

        count = queue.clear_completed()
        assert count == 1
        assert queue.get(task_id1) is None
        assert queue.get(task_id2) is not None

    def test_clear_all(self, queue: IngestQueue):
        """应清除所有任务。"""
        queue.add("/path/to/doc1.pdf")
        queue.add("/path/to/doc2.pdf")
        queue.add("/path/to/doc3.pdf")

        count = queue.clear_all()
        assert count == 3
        assert len(queue.get_all()) == 0


class TestIngestTaskSerialization:
    """测试任务序列化。"""

    def test_to_dict(self, queue: IngestQueue):
        """任务应能正确序列化为字典。"""
        task_id = queue.add("/path/to/document.pdf")
        task = queue.get(task_id)

        data = task.to_dict()

        assert data["task_id"] == task_id
        assert data["source_path"] == "/path/to/document.pdf"
        assert data["status"] == "pending"
        assert "created_at" in data
        assert data["retry_count"] == 0
        assert data["max_retries"] == 3

    def test_from_dict(self):
        """任务应能从字典反序列化。"""
        data = {
            "task_id": "abc12345",
            "source_path": "/path/to/document.pdf",
            "project_root": "/path/to/project",
            "status": "pending",
            "created_at": "2026-09-06T14:30:00",
            "started_at": None,
            "completed_at": None,
            "error_message": None,
            "retry_count": 0,
            "max_retries": 3,
            "result": None,
        }

        task = IngestTask.from_dict(data)

        assert task.task_id == "abc12345"
        assert task.status == QueueStatus.PENDING
        assert task.created_at.year == 2026
