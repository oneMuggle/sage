"""
Legacy 会话 CRUD 路由 (S7-3, P7 — 从 legacy_routes.py 拆出)。

拆分原则 (零行为变更):
- 复用 legacy_routes 的同一个 ``router`` 对象 —— 本模块被 import 时端点
  即注册到该 router; main.py 必须在 ``include_router(legacy_router)``
  之前 import 本模块 (import 顺序即装配顺序)。
- 会话 CRUD + 会话级模型覆盖 (G5) 属纯 DB/KV 操作, 不依赖 chat
  producer/stream 机制, 可独立成模块; compact/fork 仍留在
  legacy_routes (与 LLM 装配、流注册表耦合)。
- 委托范围: 7 个端点 (POST/GET /sessions, GET/PUT /sessions/{id}/model,
  GET/PATCH/DELETE /sessions/{id})。
"""

from __future__ import annotations

import json
from typing import List

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from backend.api.legacy_routes import (
    SessionCreate,
    SessionUpdate,
    get_session_repo,
    router,
    with_db_lock,
)
from backend.data.session_repo import SessionRepository
from backend.orchestration.llm_factory import (
    SESSION_MODEL_OVERRIDES_KEY,
    load_session_model_overrides,
)

__all__ = ["SessionModelOverride"]


class SessionModelOverride(BaseModel):
    model_config = {"protected_namespaces": ()}

    model: str


@router.post("/sessions", response_model=dict)
@with_db_lock
def create_session(data: SessionCreate, repo: SessionRepository = Depends(get_session_repo)):
    """创建新会话"""
    session = repo.create(title=data.title, parent_id=data.parent_id)
    return session.to_dict()


@router.get("/sessions", response_model=List[dict])
@with_db_lock
def list_sessions(
    limit: int = 100, offset: int = 0, repo: SessionRepository = Depends(get_session_repo)
):
    """获取会话列表"""
    sessions = repo.list(limit=limit, offset=offset)
    return [s.to_dict() for s in sessions]


@router.get("/sessions/{session_id}/model")
def get_session_model(session_id: str):
    """读取某会话的模型覆盖；未设置返回 {"model": null}。"""
    override = load_session_model_overrides().get(session_id)
    return {"session_id": session_id, "model": override}


@router.put("/sessions/{session_id}/model")
def set_session_model(session_id: str, payload: SessionModelOverride):
    """设置/清除（model 传空串）某会话的模型覆盖。

    设置后该会话的 chat 固定用此模型（端点仍取全局选择）；传空串清除
    覆盖，回到全局选择。非法值整体拒绝，绝不部分写入。
    """
    model = payload.model.strip() if isinstance(payload.model, str) else ""
    overrides = load_session_model_overrides()
    if model:
        overrides[session_id] = model
    else:
        overrides.pop(session_id, None)
    try:
        from backend.data.settings_repo import SettingsRepository

        SettingsRepository().set(
            SESSION_MODEL_OVERRIDES_KEY,
            json.dumps(overrides, ensure_ascii=False),
            value_type="json",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"写入会话模型覆盖失败: {exc}")
    return {"session_id": session_id, "model": model or None}


@router.get("/sessions/{session_id}", response_model=dict)
@with_db_lock
def get_session(session_id: str, repo: SessionRepository = Depends(get_session_repo)):
    """获取单个会话"""
    session = repo.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session.to_dict()


@router.patch("/sessions/{session_id}", response_model=dict)
@with_db_lock
def update_session(
    session_id: str, data: SessionUpdate, repo: SessionRepository = Depends(get_session_repo)
):
    """更新会话"""
    update_data = {}
    if data.title is not None:
        update_data["title"] = data.title
    if data.is_pinned is not None:
        update_data["is_pinned"] = 1 if data.is_pinned else 0

    if update_data:
        repo.update(session_id, **update_data)

    session = repo.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session.to_dict()


@router.delete("/sessions/{session_id}")
@with_db_lock
def delete_session(session_id: str, repo: SessionRepository = Depends(get_session_repo)):
    """删除会话"""
    if not repo.delete(session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"status": "ok"}
