"""SQLite persistence for orchestration task transcripts (M1).

背景：子代理的思考/正文/工具全文此前只存在于内存的聊天事件镜像里
（且 THINKING/REASONING/CONTENT_DELTA 被投影层显式过滤），任务详情
无法回看"子代理到底想了什么、做了什么"。本 repo 以消息级粒度落盘
transcript（append-only，按 run_id + task_id + seq 定位），与
``orch_events``（canonical 状态事件）互补：

- ``orch_events``：状态机事件，供 EventTimeline / 快照 / 断线重放
- ``orch_task_messages``：过程消息（goal / reasoning / assistant /
  tool_call / tool_result / error），供任务详情 Transcript 视图

写入方为 ``TaskTranscriptRecorder``（SubagentRunner 事件流消费者），
读取方为 ``GET /orch/runs/{run_id}/tasks/{task_id}/transcript``。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from backend.data.database import _SQLITE_LOCK, get_database


@dataclass
class TaskTranscriptMessage:
    """一条任务过程消息（行级）。

    ``tool_args`` 以 JSON 字符串存储（SQLite 无 JSON 类型）；读取方经
    ``to_dict()`` 得到解析后的对象。
    """

    run_id: str
    task_id: str
    seq: int
    role: str  # user | assistant | tool
    message_type: str  # goal | reasoning | assistant | tool_call | tool_result | error
    content: Optional[str] = None
    reasoning: Optional[str] = None
    tool_name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_args: Optional[str] = None
    tool_result: Optional[str] = None
    is_error: bool = False
    duration_ms: Optional[int] = None
    created_at: int = 0  # epoch ms

    def to_dict(self) -> Dict[str, Any]:
        parsed_args: Any = None
        if self.tool_args:
            try:
                parsed_args = json.loads(self.tool_args)
            except (TypeError, ValueError):
                parsed_args = self.tool_args
        return {
            "seq": self.seq,
            "role": self.role,
            "message_type": self.message_type,
            "content": self.content,
            "reasoning": self.reasoning,
            "tool_name": self.tool_name,
            "tool_call_id": self.tool_call_id,
            "tool_args": parsed_args,
            "tool_result": self.tool_result,
            "is_error": self.is_error,
            "duration_ms": self.duration_ms,
            "created_at": self.created_at,
        }


class OrchTranscriptRepository:
    """``orch_task_messages`` 的追加/查询实现（模式同 OrchEventRepository）。"""

    def __init__(self) -> None:
        self.db = get_database()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with _SQLITE_LOCK:
            conn = self.db.get_connection()
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS orch_task_messages (
                    run_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    message_type TEXT NOT NULL,
                    content TEXT,
                    reasoning TEXT,
                    tool_name TEXT,
                    tool_call_id TEXT,
                    tool_args TEXT,
                    tool_result TEXT,
                    is_error INTEGER NOT NULL DEFAULT 0,
                    duration_ms INTEGER,
                    created_at INTEGER NOT NULL,
                    PRIMARY KEY (run_id, task_id, seq)
                )
                """
            )
            conn.commit()

    def append(self, message: TaskTranscriptMessage) -> None:
        with _SQLITE_LOCK:
            conn = self.db.get_connection()
            conn.execute(
                """
                INSERT OR IGNORE INTO orch_task_messages (
                    run_id, task_id, seq, role, message_type, content, reasoning,
                    tool_name, tool_call_id, tool_args, tool_result, is_error,
                    duration_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message.run_id,
                    message.task_id,
                    message.seq,
                    message.role,
                    message.message_type,
                    message.content,
                    message.reasoning,
                    message.tool_name,
                    message.tool_call_id,
                    message.tool_args,
                    message.tool_result,
                    1 if message.is_error else 0,
                    message.duration_ms,
                    message.created_at,
                ),
            )
            conn.commit()

    def max_seq(self, run_id: str, task_id: str) -> int:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COALESCE(MAX(seq), 0) AS max_seq FROM orch_task_messages "
            "WHERE run_id = ? AND task_id = ?",
            (run_id, task_id),
        )
        row = cursor.fetchone()
        return int(row["max_seq"]) if row else 0

    def list_messages(
        self,
        run_id: str,
        task_id: str,
        *,
        after_seq: int = 0,
        limit: int = 200,
    ) -> List[TaskTranscriptMessage]:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM orch_task_messages
            WHERE run_id = ? AND task_id = ? AND seq > ?
            ORDER BY seq ASC
            LIMIT ?
            """,
            (run_id, task_id, after_seq, limit),
        )
        return [
            TaskTranscriptMessage(
                run_id=row["run_id"],
                task_id=row["task_id"],
                seq=row["seq"],
                role=row["role"],
                message_type=row["message_type"],
                content=row["content"],
                reasoning=row["reasoning"],
                tool_name=row["tool_name"],
                tool_call_id=row["tool_call_id"],
                tool_args=row["tool_args"],
                tool_result=row["tool_result"],
                is_error=bool(row["is_error"]),
                duration_ms=row["duration_ms"],
                created_at=row["created_at"],
            )
            for row in cursor.fetchall()
        ]
