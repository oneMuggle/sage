"""工作日志数据模型 —— ``work_logs`` 行 ↔ ``WorkLog`` 模型的映射（P2）。

与 :mod:`backend.services.todo_models` 同款结构：模型定义与行映射各自独立成
模块，服务层只留业务逻辑。

**双轨存储的关键不变量**（日报/周报依赖它）：

``status='pending'`` 的行是「待确认候选」—— 对话 LLM 抽取的产物，抽取可能
误记，所以人工确认前**不算数**；只有 ``confirmed`` 才进报告统计。``dismissed``
是用户主动忽略的候选。
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

# ``work_logs`` columns that map onto :class:`WorkLog`, in model-field order.
WORKLOG_MODEL_FIELDS = (
    "id",
    "session_id",
    "content",
    "kind",
    "progress_text",
    "blocker",
    "todo_id",
    "project_id",
    "project_tag",
    "source_type",
    "source_ref",
    "status",
    "created_at",
    "updated_at",
)

#: 日志类型白名单 —— 进展 / 完成 / 阻塞 / 下一步。
WORKLOG_KINDS = ("progress", "done", "blocker", "next")

#: 状态白名单 —— 待确认 / 已确认 / 已忽略。
WORKLOG_STATUSES = ("pending", "confirmed", "dismissed")

#: 来源类型白名单 —— 对话抽取 / 手动录入 / agent 工具。
WORKLOG_SOURCE_TYPES = ("chat", "manual", "agent")


class WorkLog(BaseModel):
    """工作日志条目 —— 「已经做了什么」。"""

    id: int
    session_id: Optional[str] = None
    content: str
    kind: str = "progress"  # progress / done / blocker / next
    progress_text: Optional[str] = None
    blocker: Optional[str] = None
    todo_id: Optional[int] = None
    project_id: Optional[str] = None
    project_tag: Optional[str] = None
    source_type: str = "chat"  # chat / manual / agent
    source_ref: Optional[str] = None
    status: str = "pending"  # pending / confirmed / dismissed
    created_at: str
    updated_at: str


def row_to_worklog(row) -> WorkLog:
    """Convert a ``work_logs`` row to a :class:`WorkLog` model.

    Maps by column *name* rather than position, so adding a column to the
    table cannot silently shift the model's fields. 白名单外的枚举值（历史脏
    数据 / 手工改库）降级为默认值，不让列表渲染整体崩掉。
    """
    keys = set(row.keys())
    data = {name: row[name] for name in WORKLOG_MODEL_FIELDS if name in keys}
    if data.get("kind") not in WORKLOG_KINDS:
        data["kind"] = "progress"
    if data.get("status") not in WORKLOG_STATUSES:
        data["status"] = "pending"
    if data.get("source_type") not in WORKLOG_SOURCE_TYPES:
        data["source_type"] = "chat"
    return WorkLog(**data)
