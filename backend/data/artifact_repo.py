"""
产物仓储层
负责追踪 AI 工具调用生成的文件产物 (artifacts 表 CRUD)
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from backend.data.database import get_database


# S7 (2026-09-06): 产物事件监听器 —— record_artifact 成功后广播事件，
# 让活跃 chat 流把 `artifact_created` 推给前端（右侧面板事件驱动刷新 +
# 侧栏产物徽章）。与 tools/todo_state 的 add_todo_listener 同模式：
# 数据层不反向依赖 API 层，由 producer 注册/注销闭包。
# 单进程单事件循环，list 操作无并发问题；监听器异常一律吞掉（降级铁律：
# 事件推送失败不能影响产物落库）。
_ARTIFACT_LISTENERS: List[Callable[[Dict[str, Any]], None]] = []


def add_artifact_listener(fn: Callable[[Dict[str, Any]], None]) -> Callable[[Dict[str, Any]], None]:
    """注册产物事件监听器；返回 fn 便于 ``remove_artifact_listener`` 配对。"""
    _ARTIFACT_LISTENERS.append(fn)
    return fn


def remove_artifact_listener(fn: Callable[[Dict[str, Any]], None]) -> None:
    """注销产物事件监听器（producer finally 必须配对调用，防闭包泄漏）。"""
    try:
        _ARTIFACT_LISTENERS.remove(fn)
    except ValueError:
        pass


def _emit_artifact_event(event: Dict[str, Any]) -> None:
    for fn in list(_ARTIFACT_LISTENERS):
        try:
            fn(event)
        except Exception:  # noqa: BLE001 — 降级铁律，见模块注释
            pass


@dataclass
class Artifact:
    """产物数据模型"""

    id: str
    session_id: str
    path: str
    name: str
    kind: str
    size: int
    created_at: int
    tool_call_id: Optional[str] = None

    @classmethod
    def from_row(cls, row) -> "Artifact":
        return cls(
            id=row["id"],
            session_id=row["session_id"],
            path=row["path"],
            name=row["name"],
            kind=row["kind"],
            size=row["size"] or 0,
            created_at=row["created_at"],
            tool_call_id=row["tool_call_id"],
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "tool_call_id": self.tool_call_id,
            "path": self.path,
            "name": self.name,
            "kind": self.kind,
            "size": self.size,
            "created_at": self.created_at,
        }


def record_artifact(
    session_id: str,
    path: str,
    name: str,
    kind: str,
    size: int,
    tool_call_id: Optional[str] = None,
) -> str:
    """记录一个新产物,返回 artifact id。落库成功后广播 ``artifact_created`` 事件（S7）。"""
    artifact_id = f"art_{uuid.uuid4().hex[:12]}"
    created_at = int(time.time() * 1000)
    db = get_database()
    conn = db.get_connection()
    conn.execute(
        """
        INSERT INTO artifacts
            (id, session_id, tool_call_id, path, name, kind, size, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (artifact_id, session_id, tool_call_id, path, name, kind, size, created_at),
    )
    conn.commit()
    _emit_artifact_event(
        {
            "state": "artifact_created",
            "session_id": session_id,
            "artifact": {
                "id": artifact_id,
                "path": path,
                "name": name,
                "kind": kind,
                "size": size,
                "created_at": created_at,
            },
        }
    )
    return artifact_id


def list_artifacts(session_id: str) -> List[Artifact]:
    """列出指定 session 的所有产物,按 created_at 降序;同毫秒记录用 rowid 兜底防排序 flaky。"""
    db = get_database()
    conn = db.get_connection()
    cursor = conn.execute(
        "SELECT * FROM artifacts WHERE session_id = ? ORDER BY created_at DESC, rowid DESC",
        (session_id,),
    )
    return [Artifact.from_row(row) for row in cursor.fetchall()]


def get_artifact(artifact_id: str) -> Optional[Artifact]:
    """根据 id 查找产物,不存在返回 None。"""
    db = get_database()
    conn = db.get_connection()
    cursor = conn.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,))
    row = cursor.fetchone()
    return Artifact.from_row(row) if row else None
