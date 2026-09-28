# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Agent API 路由组（C2e，DSH 对标 R30，自 legacy_routes.py 迁出）。

7 个 /agents* 端点（list/get/patch/toggle/create/import-files/export）。
路径与前缀保持不变（router 无 prefix，经 legacy_router include 后仍为
/api/v1/agents 等）——纯物理拆分，零行为变更。模型经 legacy_routes 的
再导出面导入归属（legacy_models.py），_VALID_AGENT_ROLES 白名单留
legacy_routes（同被聊天路径引用）。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.api.legacy_models import AgentCreate, AgentToggle, AgentUpdate
from backend.api.settings_models import model_dump_compat
from backend.data.database import make_with_db_lock


def with_db_lock(func):
    """装饰器：包在全局 `_SQLITE_LOCK` 内（D3 make_with_db_lock 模式）。"""
    return make_with_db_lock(globals())(func)

router = APIRouter()


#: agent role 白名单（PATCH/POST 共用）。
_VALID_AGENT_ROLES = {
    "coordinator",
    "researcher",
    "coder",
    "memory_manager",
    "writer",
    "slide-deck-creator",
    "reviewer",
}



# ==================== Agent API (PR-3) ====================
#
# 4 个默认 agent (primary/researcher/coder/memory_manager) 由
# backend/main.py:lifespan 启动时通过 AgentRepository.seed_defaults_if_empty
# 种子化到 SQLite agents 表. 本节路由不写 (PR-4/5 负责 PATCH /toggle).


@router.get("/agents")
@with_db_lock
def list_agents():
    """列出所有 agent (含 disabled), 按 id 排序。

    对应 Tauri command ``list_agents`` (PR-3)。
    """
    from backend.data.agent_repo import AgentRepository

    return AgentRepository().list_all()


@router.get("/agents/{agent_id}")
@with_db_lock
def get_agent_by_id(agent_id: str):
    """按 id 取单个 agent。

    命名注意: 不能叫 ``get_agent`` — 与本文件 line 136 的 dependency
    provider ``def get_agent()`` 同名会覆盖, 导致 ``/interrupt`` 路由
    拿错函数. 后续 PR 可把 dependency 改名 ``make_sage_agent()``,
    本 PR 仅做局部重命名.
    """
    from backend.data.agent_repo import AgentRepository

    agent = AgentRepository().get(agent_id)
    if not agent:
        raise HTTPException(
            status_code=404,
            detail={"type": "agent_not_found", "message": f"agent {agent_id} not found"},
        )
    return agent


@router.patch("/agents/{agent_id}")
@with_db_lock
def update_agent(agent_id: str, data: AgentUpdate):
    """部分更新 agent (PR-4)。

    - 200 + 更新后完整 profile
    - 404 + 结构化 detail (id 不存在)
    - 422 (FastAPI 自动) — 字段类型 / role 白名单 / max_iterations 范围
    - PATCH 是 partial update: 缺省字段保留原值
    - 空 body: 视为 no-op, 返回当前 profile, updated_at 不动
    """
    from backend.data.agent_repo import AgentRepository

    # 字段级校验: role 白名单
    valid_roles = _VALID_AGENT_ROLES
    if data.role is not None and data.role not in valid_roles:
        raise HTTPException(
            status_code=422,
            detail={
                "type": "invalid_role",
                "message": f"role must be one of {sorted(valid_roles)}, got {data.role!r}",
            },
        )

    # 字段级校验: max_iterations 范围
    if data.max_iterations is not None and not (1 <= data.max_iterations <= 50):
        raise HTTPException(
            status_code=422,
            detail={
                "type": "invalid_max_iterations",
                "message": f"max_iterations must be in 1..50, got {data.max_iterations}",
            },
        )

    repo = AgentRepository()

    # 不存在 → 404 (update 返回 0 时区分"没字段改"和"id 不存在")
    if repo.get(agent_id) is None:
        raise HTTPException(
            status_code=404,
            detail={"type": "agent_not_found", "message": f"agent {agent_id} not found"},
        )

    # 转 dict 给 repo.update; 字段名 model_config_data → model_config (避开 Pydantic 保留名)
    update_payload = model_dump_compat(data, exclude_none=True)
    if "model_config_data" in update_payload:
        update_payload["model_config"] = update_payload.pop("model_config_data")

    repo.update(agent_id, update_payload)
    return repo.get(agent_id)


@router.patch("/agents/{agent_id}/toggle")
@with_db_lock
def toggle_agent(agent_id: str, data: AgentToggle):
    """启用/禁用 agent (PR-5)。

    - 200 + 更新后完整 profile (含 enabled / updated_at 新值)
    - 404 + 结构化 detail (id 不存在, 与 PR-3/PR-4 复用同一 type)
    - 422 (FastAPI 自动) — enabled 缺失 / 类型错

    选 ``/toggle`` 子路径而非复用 ``PATCH /agents/{id}`` 的理由:
    - 审计语义清晰: events.jsonl 里可单独 grep 出 toggle 操作
    - 未来权限模型: toggle 与 system_prompt 编辑可独立授权

    同值 toggle 也走 SQL UPDATE — 幂等但 updated_at 仍刷新, 符合
    set_enabled() 语义。
    """
    from backend.data.agent_repo import AgentRepository

    repo = AgentRepository()

    # 与 update_agent 一致: 显式查存在性, 给出比 set_enabled() 更友好的 404 detail
    if repo.get(agent_id) is None:
        raise HTTPException(
            status_code=404,
            detail={"type": "agent_not_found", "message": f"agent {agent_id} not found"},
        )

    repo.set_enabled(agent_id, data.enabled)
    return repo.get(agent_id)


@router.post("/agents")
@with_db_lock
def create_agent(data: AgentCreate):
    """创建自定义 agent（US-4）。

    - 200 + 完整 profile
    - 409 + 结构化 detail（id 已存在）
    - 422 — role 白名单 / max_iterations 范围
    """
    from backend.data.agent_repo import AgentRepository

    if data.role not in _VALID_AGENT_ROLES and data.role != "general":
        raise HTTPException(
            status_code=422,
            detail={
                "type": "invalid_role",
                "message": (
                    f"role must be one of {sorted(_VALID_AGENT_ROLES)} "
                    f"or 'general', got {data.role!r}"
                ),
            },
        )

    if data.max_iterations is not None and not (1 <= data.max_iterations <= 50):
        raise HTTPException(
            status_code=422,
            detail={
                "type": "invalid_max_iterations",
                "message": f"max_iterations must be in 1..50, got {data.max_iterations}",
            },
        )

    repo = AgentRepository()
    if repo.get(data.id) is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "type": "agent_already_exists",
                "message": f"agent {data.id!r} already exists",
            },
        )

    payload = model_dump_compat(data, exclude_none=True)
    if "model_config_data" in payload:
        payload["model_config"] = payload.pop("model_config_data")
    payload.setdefault("tools", [])
    payload.setdefault("memory_access", [])
    payload.setdefault("model_config", {})
    payload.setdefault("max_iterations", 10)
    payload.setdefault("enabled", True)
    payload.setdefault("description", "")

    repo.upsert(payload)
    return repo.get(data.id)


@router.post("/agents/import-files")
@with_db_lock
def import_agents_files():
    """CA1 (round9): 重扫 .sage/agents/*.md 导入档案。

    - 200 + ``{ok, imported, unchanged, errors}``（语义见
      ``backend.agents.agents_files.import_agents_from_files``）
    - 解析失败的单文件计入 errors，绝不 5xx
    """
    from backend.agents.agents_files import import_agents_from_files

    result = import_agents_from_files()
    return {"ok": True, **result}


@router.post("/agents/{agent_id}/export")
@with_db_lock
def export_agent_file(agent_id: str):
    """CA2 (round9): 把 DB 档案导出为 .sage/agents/<agent_id>.md（覆盖写）。

    - 200 + ``{ok, path}``
    - 404 — agent 不存在
    """
    from backend.agents.agents_files import export_agent_to_file

    try:
        path = export_agent_to_file(agent_id)
    except LookupError:
        raise HTTPException(status_code=404, detail=f"agent {agent_id!r} not found")
    return {"ok": True, "path": str(path)}
