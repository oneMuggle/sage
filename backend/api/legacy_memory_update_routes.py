# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""2026-11-17 记忆详情化 —— 单条记忆编辑端点。

``PUT /memory/{memory_id}``：更新 content / title / tags / importance。
- episodic 优先，未命中落 semantic；working / 会话摘要行不可编辑 → 404。
- 语义层没有 importance 列：显式传 importance → 422（不做静默忽略）。
- 主表更新后由存储层同步 FTS 行并移除旧向量（检索层按需重嵌入），
  避免全文/语义检索继续命中过期内容。
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.data.database import (  # noqa: F401 — _SQLITE_LOCK 由 with_db_lock 闭包解析
    _SQLITE_LOCK,
    make_with_db_lock,
)
from backend.memory import get_memory_manager


def with_db_lock(func):
    """串行化 SQLite 访问（镜像 legacy_memory_list_routes）。"""
    return make_with_db_lock(globals())(func)


router = APIRouter()


class MemoryUpdateRequest(BaseModel):
    """单条记忆编辑请求（只更新显式传入的字段）。"""

    content: Optional[str] = Field(default=None, min_length=1)
    title: Optional[str] = None
    tags: Optional[List[str]] = None
    importance: Optional[int] = Field(default=None, ge=1, le=10)


@router.put("/memory/{memory_id}")
@with_db_lock
def update_memory(memory_id: str, data: MemoryUpdateRequest):
    """更新单条记忆（2026-11-17 记忆详情化）。

    - 只更新显式传入的字段；``content`` 变更时 summary 重算、``title``
      留空时按（新）内容确定性生成。
    - 依次在 episodic / semantic 层定位；working / 会话摘要行不可编辑 → 404。
    """
    if (
        data.content is None
        and data.title is None
        and data.tags is None
        and data.importance is None
    ):
        raise HTTPException(status_code=422, detail="至少提供一个待更新字段")
    try:
        mm = get_memory_manager()
        updated = mm.episodic.update(
            memory_id,
            content=data.content,
            title=data.title,
            tags=data.tags,
            importance=data.importance,
        )
        memory_type = "episodic"
        if not updated:
            # 语义记忆没有 importance 列：显式校验，不做"看起来改了"的静默忽略。
            if mm.semantic.get_by_id(memory_id) is None:
                raise HTTPException(status_code=404, detail="记忆不存在或不可编辑")
            if data.importance is not None:
                raise HTTPException(
                    status_code=422,
                    detail="语义记忆不支持重要性字段（该字段仅情景记忆可用）",
                )
            updated = mm.semantic.update(
                memory_id,
                content=data.content,
                title=data.title,
                tags=data.tags,
            )
            memory_type = "semantic"
            if not updated:
                raise HTTPException(status_code=404, detail="记忆不存在或不可编辑")

        store = mm.episodic if memory_type == "episodic" else mm.semantic
        record = store.get_by_id(memory_id)
        if record is None:
            raise HTTPException(status_code=404, detail="记忆不存在或不可编辑")
        # 复用列表序列化（补 title 兜底/source/layer/created_at_ms），
        # 前端拿到的形状与 GET /memory/list 的 items 完全一致。
        from backend.api.legacy_memory_list_routes import _enrich_memory_records

        enriched = _enrich_memory_records([record], layer=memory_type, source=memory_type)
        return enriched[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
