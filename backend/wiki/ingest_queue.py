"""持久化摄入队列。

支持崩溃恢复、取消/重试机制。队列数据存储在 `.llm-wiki/ingest-queue.json`。
"""
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict, Any
import json
import uuid
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class QueueStatus(str, Enum):
    """摄入任务状态。"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class IngestTask:
    """摄入任务。"""
    task_id: str
    source_path: str
    project_root: str
    status: QueueStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    result: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于 JSON 序列化）。"""
        return {
            "task_id": self.task_id,
            "source_path": self.source_path,
            "project_root": self.project_root,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "result": self.result,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IngestTask":
        """从字典创建任务。"""
        return cls(
            task_id=data["task_id"],
            source_path=data["source_path"],
            project_root=data["project_root"],
            status=QueueStatus(data["status"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            error_message=data.get("error_message"),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 3),
            result=data.get("result"),
        )


class IngestQueue:
    """持久化摄入队列（JSON 文件存储）。

    队列用于管理大量文件的摄入任务，支持：
    - 持久化存储（崩溃恢复）
    - 取消任务
    - 重试失败任务
    - 状态追踪

    示例:
        >>> queue = IngestQueue(Path("/path/to/wiki-project"))
        >>> task_id = queue.add("/path/to/document.pdf")
        >>> task = queue.get_next_pending()
        >>> queue.mark_processing(task_id)
        >>> # ... 处理任务 ...
        >>> queue.mark_completed(task_id, {"wiki_page_path": "wiki/sources/doc.md"})
    """

    def __init__(self, project_root: Path):
        """初始化队列。

        Args:
            project_root: Wiki 项目根目录
        """
        self.project_root = Path(project_root)
        self.queue_file = self.project_root / ".llm-wiki" / "ingest-queue.json"
        self._tasks: Dict[str, IngestTask] = {}
        self._load()

    def _load(self) -> None:
        """从文件加载队列。"""
        if not self.queue_file.exists():
            self._tasks = {}
            return

        try:
            data = json.loads(self.queue_file.read_text(encoding="utf-8"))
            self._tasks = {
                t["task_id"]: IngestTask.from_dict(t)
                for t in data.get("tasks", [])
            }
            logger.debug(f"Loaded {len(self._tasks)} tasks from queue")
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"Failed to load queue from {self.queue_file}: {e}")
            self._tasks = {}

    def _save(self) -> None:
        """持久化队列到文件。"""
        self.queue_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "tasks": [t.to_dict() for t in self._tasks.values()],
        }
        self.queue_file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    def add(self, source_path: str, max_retries: int = 3) -> str:
        """添加入任务到队列。

        Args:
            source_path: 源文件路径
            max_retries: 最大重试次数

        Returns:
            task_id: 任务 ID
        """
        task_id = str(uuid.uuid4())[:8]
        task = IngestTask(
            task_id=task_id,
            source_path=source_path,
            project_root=str(self.project_root),
            status=QueueStatus.PENDING,
            created_at=datetime.now(),
            max_retries=max_retries,
        )
        self._tasks[task_id] = task
        self._save()
        logger.info(f"Added ingest task {task_id}: {source_path}")
        return task_id

    def get(self, task_id: str) -> Optional[IngestTask]:
        """获取任务。

        Args:
            task_id: 任务 ID

        Returns:
            任务对象，如果不存在则返回 None
        """
        return self._tasks.get(task_id)

    def get_next_pending(self) -> Optional[IngestTask]:
        """获取下一个待处理任务。

        Returns:
            待处理任务，如果队列为空则返回 None
        """
        for task in self._tasks.values():
            if task.status == QueueStatus.PENDING:
                return task
        return None

    def mark_processing(self, task_id: str) -> bool:
        """标记任务为处理中。

        Args:
            task_id: 任务 ID

        Returns:
            是否成功标记
        """
        task = self._tasks.get(task_id)
        if not task:
            logger.warning(f"Task {task_id} not found")
            return False

        if task.status != QueueStatus.PENDING:
            logger.warning(f"Task {task_id} is not pending (status={task.status.value})")
            return False

        task.status = QueueStatus.PROCESSING
        task.started_at = datetime.now()
        self._save()
        logger.info(f"Marked task {task_id} as processing")
        return True

    def mark_completed(self, task_id: str, result: Dict[str, Any]) -> bool:
        """标记任务为完成。

        Args:
            task_id: 任务 ID
            result: 处理结果

        Returns:
            是否成功标记
        """
        task = self._tasks.get(task_id)
        if not task:
            logger.warning(f"Task {task_id} not found")
            return False

        if task.status != QueueStatus.PROCESSING:
            logger.warning(f"Task {task_id} is not processing (status={task.status.value})")
            return False

        task.status = QueueStatus.COMPLETED
        task.completed_at = datetime.now()
        task.result = result
        self._save()
        logger.info(f"Marked task {task_id} as completed")
        return True

    def mark_failed(self, task_id: str, error: str) -> bool:
        """标记任务为失败。

        Args:
            task_id: 任务 ID
            error: 错误信息

        Returns:
            是否成功标记
        """
        task = self._tasks.get(task_id)
        if not task:
            logger.warning(f"Task {task_id} not found")
            return False

        task.status = QueueStatus.FAILED
        task.error_message = error
        task.retry_count += 1
        self._save()
        logger.warning(f"Marked task {task_id} as failed: {error}")
        return True

    def cancel(self, task_id: str) -> bool:
        """取消任务。

        只有 PENDING 或 FAILED 状态的任务可以取消。

        Args:
            task_id: 任务 ID

        Returns:
            是否成功取消
        """
        task = self._tasks.get(task_id)
        if not task:
            logger.warning(f"Task {task_id} not found")
            return False

        if task.status not in (QueueStatus.PENDING, QueueStatus.FAILED):
            logger.warning(
                f"Cannot cancel task {task_id} (status={task.status.value}). "
                "Only PENDING or FAILED tasks can be cancelled."
            )
            return False

        task.status = QueueStatus.CANCELLED
        self._save()
        logger.info(f"Cancelled task {task_id}")
        return True

    def retry(self, task_id: str) -> bool:
        """重试失败任务。

        只有 FAILED 状态且重试次数未超限的任务可以重试。

        Args:
            task_id: 任务 ID

        Returns:
            是否成功重试
        """
        task = self._tasks.get(task_id)
        if not task:
            logger.warning(f"Task {task_id} not found")
            return False

        if task.status != QueueStatus.FAILED:
            logger.warning(f"Task {task_id} is not failed (status={task.status.value})")
            return False

        if task.retry_count >= task.max_retries:
            logger.warning(
                f"Task {task_id} has reached max retries ({task.retry_count}/{task.max_retries})"
            )
            return False

        task.status = QueueStatus.PENDING
        task.error_message = None
        task.started_at = None
        task.completed_at = None
        task.result = None
        self._save()
        logger.info(f"Retry task {task_id} (attempt {task.retry_count + 1})")
        return True

    def get_all(self) -> List[IngestTask]:
        """获取所有任务。

        Returns:
            任务列表
        """
        return list(self._tasks.values())

    def get_by_status(self, status: QueueStatus) -> List[IngestTask]:
        """按状态获取任务。

        Args:
            status: 任务状态

        Returns:
            任务列表
        """
        return [t for t in self._tasks.values() if t.status == status]

    def get_status_summary(self) -> Dict[str, int]:
        """获取状态摘要。

        Returns:
            各状态的任务数量
        """
        summary = {status.value: 0 for status in QueueStatus}
        for task in self._tasks.values():
            summary[task.status.value] += 1
        return summary

    def clear_completed(self) -> int:
        """清除已完成的任务。

        Returns:
            清除的任务数量
        """
        completed_ids = [
            tid for tid, t in self._tasks.items()
            if t.status == QueueStatus.COMPLETED
        ]
        for tid in completed_ids:
            del self._tasks[tid]

        if completed_ids:
            self._save()
            logger.info(f"Cleared {len(completed_ids)} completed tasks")

        return len(completed_ids)

    def clear_all(self) -> int:
        """清除所有任务。

        Returns:
            清除的任务数量
        """
        count = len(self._tasks)
        self._tasks.clear()
        self._save()
        logger.info(f"Cleared all {count} tasks")
        return count
