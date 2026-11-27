"""Todo 数据模型 —— ``todos`` 行 ↔ ``Todo`` 模型的映射（P1 抽出）。

从 ``todo_service`` 抽出，让服务层只留业务逻辑：模型定义与行映射各自独立成
模块后，``todo_service`` 才有行数余量加拖拽排序相关代码（该文件已逼近
``architecture-baseline`` 的 800 行硬顶）。

``todo_service`` 继续 ``from backend.services.todo_models import Todo`` 并对外
暴露，外部 ``from backend.services.todo_service import Todo`` 的调用方不受影响。
"""
from __future__ import annotations

import json
from typing import List, Optional

from pydantic import BaseModel, Field

from backend.services import todo_tags

# ``todos`` columns that map onto :class:`Todo`, in model-field order.
# Deliberately excludes ``reminder_24h_fired`` / ``reminder_1h_fired`` — those
# are bookkeeping columns owned by the reminder scheduler, not model fields.
TODO_MODEL_FIELDS = (
    "id",
    "title",
    "description",
    "status",
    "priority",
    "effective_urgency",
    "due_at",
    "completed_at",
    "project_tag",
    "project_id",
    "tags",
    "reminder_offsets",
    "source_type",
    "source_ref",
    "specialist_id",
    "snooze_count",
    "is_recurring",
    "recurrence_rule",
    "parent_id",
    "sort_order",
    "created_at",
    "updated_at",
)

# 自定义提醒档位：分钟偏移，上限 5 档、单档 ≤7 天。
MAX_REMINDER_OFFSETS = 5
MAX_REMINDER_OFFSET_MINUTES = 7 * 24 * 60


class Todo(BaseModel):
    """Todo item model"""

    id: int
    title: str
    description: Optional[str] = None
    status: str  # pending / in_progress / completed / cancelled
    priority: str  # high / medium / low
    effective_urgency: Optional[str] = None  # critical / urgent / normal
    due_at: Optional[str] = None  # ISO8601
    completed_at: Optional[str] = None
    project_tag: Optional[str] = None
    project_id: Optional[str] = None  # TEXT — projects.id is a hex/uuid string
    tags: List[str] = Field(default_factory=list)
    reminder_offsets: List[int] = Field(default_factory=list)
    source_type: Optional[str] = None
    source_ref: Optional[str] = None
    specialist_id: Optional[str] = None
    snooze_count: int = 0
    is_recurring: bool = False
    recurrence_rule: Optional[str] = None
    parent_id: Optional[int] = None
    # 同层内的手工次序（P1 拖拽排序）。旧行默认 0，由 id 次序兜底。
    sort_order: float = 0.0
    created_at: str
    updated_at: str


def normalize_reminder_offsets(offsets: Optional[List[int]]) -> List[int]:
    """清洗提醒档位：取正整数、去重、升序、上限 5 档且单档 ≤7 天。"""
    if not offsets:
        return []
    cleaned: List[int] = []
    seen = set()
    for raw in offsets:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value < 1 or value > MAX_REMINDER_OFFSET_MINUTES or value in seen:
            continue
        seen.add(value)
        cleaned.append(value)
        if len(cleaned) >= MAX_REMINDER_OFFSETS:
            break
    return sorted(cleaned)


def dump_reminder_offsets(offsets: Optional[List[int]]) -> Optional[str]:
    normalized = normalize_reminder_offsets(offsets)
    return json.dumps(normalized) if normalized else None


def row_to_todo(row) -> Todo:
    """Convert a ``todos`` row to a Todo model.

    Maps by column *name* rather than position, so adding a column to the
    table cannot silently shift the model's fields. ``tags`` 存 JSON 数组
    字符串，坏数据降级为空列表（不阻塞列表渲染）。
    """
    keys = set(row.keys())
    data = {name: row[name] for name in TODO_MODEL_FIELDS if name in keys}
    data["is_recurring"] = bool(data.get("is_recurring"))
    data["snooze_count"] = int(data.get("snooze_count") or 0)
    data["tags"] = todo_tags.parse_tags(data.get("tags"))
    try:
        parsed_offsets = (
            json.loads(data["reminder_offsets"])
            if data.get("reminder_offsets")
            else []
        )
    except (json.JSONDecodeError, TypeError):
        parsed_offsets = []
    data["reminder_offsets"] = normalize_reminder_offsets(
        parsed_offsets if isinstance(parsed_offsets, list) else []
    )

    return Todo(**data)
