# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Agent API 路由组（C2e，DSH 对标 R30，自 legacy_routes.py 迁出）。

7 个 /agents* 端点（list/get/patch/toggle/create/import-files/export）。
路径与前缀保持不变（router 无 prefix，经 legacy_router include 后仍为
/api/v1/agents 等）——纯物理拆分，零行为变更。模型经 legacy_routes 的
再导出面导入归属（legacy_models.py），_VALID_AGENT_ROLES 白名单留
legacy_routes（同被聊天路径引用）。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from backend.api.legacy_models import AgentCreate, AgentRollback, AgentToggle, AgentUpdate
from backend.api.settings_models import model_dump_compat
from backend.data.database import get_database, make_with_db_lock
from backend.domain.agent_limits import (
    MAX_ITERATIONS_CEILING,
    MIN_ITERATIONS,
    is_valid_iteration_count,
)

logger = logging.getLogger(__name__)


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
    # M1-E (2026-11-03): 专家画廊创建向导使用 role=specialist；
    # 导入器（specialist_importer.py）已直接写入该值。
    "specialist",
}

#: M1 (2026-11-03) 专家权限模式白名单。
_VALID_PERMISSION_MODES = {"read_only", "workspace_write", "prompt", "full_access"}

#: 触发专家版本号 +1 的人设/配置字段（spec §2.1：每次修改人设/知识绑定 +1）。
_PERSONA_VERSIONED_FIELDS = ("system_prompt", "persona_ui", "knowledge_bindings", "skills")



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
    if data.max_iterations is not None and not is_valid_iteration_count(data.max_iterations):
        raise HTTPException(
            status_code=422,
            detail={
                "type": "invalid_max_iterations",
                "message": (
                    f"max_iterations must be in {MIN_ITERATIONS}..{MAX_ITERATIONS_CEILING}, "
                    f"got {data.max_iterations}"
                ),
            },
        )

    # M1 — 权限模式白名单
    if data.permission_mode is not None and data.permission_mode not in _VALID_PERMISSION_MODES:
        raise HTTPException(
            status_code=422,
            detail={
                "type": "invalid_permission_mode",
                "message": (
                    f"permission_mode must be one of {sorted(_VALID_PERMISSION_MODES)}, "
                    f"got {data.permission_mode!r}"
                ),
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

    # M1: 人设/配置字段变更且调用方未显式指定 version → 自动 +1（spec §2.1）。
    if "version" not in update_payload and any(
        field in update_payload for field in _PERSONA_VERSIONED_FIELDS
    ):
        current = repo.get(agent_id)
        update_payload["version"] = int(current.get("version", 1)) + 1

    # M4-T3 (2026-11-05)：更新前幂等存「当前版本」快照，保证 v1 等历史版本
    # 在 agent_versions 中有记录可回滚。失败不阻断主流程（快照是辅助审计数据）。
    pre_profile = repo.get(agent_id)
    try:
        from backend.data.agent_version_repo import AgentVersionRepository

        AgentVersionRepository().snapshot(
            agent_id, pre_profile, reason="update", overwrite=False
        )
    except Exception as exc:
        logger.warning("M4-T3 pre-update snapshot 失败 (agent=%s): %s", agent_id, exc)

    repo.update(agent_id, update_payload)
    new_profile = repo.get(agent_id)

    # M4-T3：更新后若版本号变化，再存新版本快照（reason='update'）。
    try:
        if int(new_profile.get("version", 1)) != int(pre_profile.get("version", 1)):
            from backend.data.agent_version_repo import AgentVersionRepository

            AgentVersionRepository().snapshot(agent_id, new_profile, reason="update")
    except Exception as exc:
        logger.warning("M4-T3 post-update snapshot 失败 (agent=%s): %s", agent_id, exc)

    return new_profile


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

    if data.max_iterations is not None and not is_valid_iteration_count(data.max_iterations):
        raise HTTPException(
            status_code=422,
            detail={
                "type": "invalid_max_iterations",
                "message": (
                    f"max_iterations must be in {MIN_ITERATIONS}..{MAX_ITERATIONS_CEILING}, "
                    f"got {data.max_iterations}"
                ),
            },
        )

    # M1: 权限模式白名单（与 PATCH 共用）
    if data.permission_mode is not None and data.permission_mode not in _VALID_PERMISSION_MODES:
        raise HTTPException(
            status_code=422,
            detail={
                "type": "invalid_permission_mode",
                "message": (
                    f"permission_mode must be one of {sorted(_VALID_PERMISSION_MODES)}, "
                    f"got {data.permission_mode!r}"
                ),
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
    created = repo.get(data.id)

    # M4-T3 (2026-11-05)：创建成功后写 v1 快照（reason=create），后续 PATCH
    # 之前无需再补 v1。失败不阻断创建（快照是辅助审计数据）。
    try:
        from backend.data.agent_version_repo import AgentVersionRepository

        AgentVersionRepository().snapshot(data.id, created, reason="create")
    except Exception as exc:
        logger.warning("M4-T3 create snapshot 失败 (agent=%s): %s", data.id, exc)

    return created


@router.delete("/agents/{agent_id}")
@with_db_lock
def delete_agent(agent_id: str):
    """删除一个 agent（M0 2026-11-03）。

    M3-Task 7：删除专家前先级联清理它的私有记忆（``agent_id = <该专家>``
    的情景层/语义层行 + 全部向量表条目）。共享层（``agent_id IS NULL``）
    与其它专家的记忆不动。清理失败 → 500 且**不删专家**（不留下"专家没了
    但记忆还在"的半状态）。

    - 200 + ``{ok: true, id: "<id>"}``
    - 400 + ``type: protected_agent`` —— ``primary`` 等内置专家不可删
    - 404 + ``type: agent_not_found`` —— id 不存在
    - 500 + ``type: memory_purge_failed`` —— 私有记忆清理失败
    """
    _delete_agent_internal(agent_id)
    return {"ok": True, "id": agent_id}


def _delete_agent_internal(agent_id: str) -> None:
    """内部删除逻辑（供单删与批量共用）。失败抛 HTTPException。"""
    from backend.data.agent_repo import AgentRepository

    if agent_id == "primary":
        raise HTTPException(
            status_code=400,
            detail={
                "type": "protected_agent",
                "message": "主助手 (primary) 不可删除",
            },
        )

    repo = AgentRepository()
    if repo.get(agent_id) is None:
        raise HTTPException(
            status_code=404,
            detail={
                "type": "agent_not_found",
                "message": f"agent {agent_id!r} 不存在",
            },
        )

    # M3-Task 7: 级联清理该专家的私有记忆（共享层不受影响）。
    try:
        from backend.memory import get_memory_manager

        purged = get_memory_manager().purge_agent_memories(agent_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("级联清理专家私有记忆失败 (agent=%s): %s", agent_id, exc)
        raise HTTPException(
            status_code=500,
            detail={
                "type": "memory_purge_failed",
                "message": f"清理 agent {agent_id!r} 的私有记忆失败: {exc}",
            },
        )
    logger.info(
        "删除专家并级联清理私有记忆 (agent=%s, episodic=%s, semantic=%s, vector=%s)",
        agent_id,
        purged.get("episodic"),
        purged.get("semantic"),
        purged.get("vector"),
    )

    # M4-T3/T4 (2026-11-05)：级联删除版本快照与评测记录（同事务外，
    # 与记忆级联同一路由内；失败不阻断删除，属辅助审计数据）。
    try:
        from backend.data.agent_version_repo import AgentVersionRepository

        versions_deleted = AgentVersionRepository().delete_all_for_agent(agent_id)
        logger.info("级联删除专家版本快照 (agent=%s, count=%s)", agent_id, versions_deleted)
    except Exception as exc:
        logger.warning("级联删除专家版本快照失败 (agent=%s): %s", agent_id, exc)

    try:
        conn = get_database().get_connection()
        cursor = conn.execute("DELETE FROM agent_eval_runs WHERE agent_id = ?", (agent_id,))
        conn.commit()
        if cursor.rowcount:
            logger.info("级联删除专家评测记录 (agent=%s, count=%s)", agent_id, cursor.rowcount)
    except Exception as exc:
        logger.warning("级联删除专家评测记录失败 (agent=%s): %s", agent_id, exc)

    repo.delete(agent_id)


@router.post("/agents/batch")
@with_db_lock
def batch_agents(data: dict):
    """批量操作专家（P2-a）。

    - 200 + ``{succeeded: [id], failed: [{id, error}]}``
    - ``action``: ``delete`` / ``enable`` / ``disable``
    - ``ids``: 专家 id 列表
    """
    from backend.data.agent_repo import AgentRepository

    action = data.get("action")
    ids = data.get("ids", [])
    if action not in ("delete", "enable", "disable"):
        raise HTTPException(
            status_code=400,
            detail={"type": "invalid_action", "message": f"action 必须为 delete/enable/disable，收到 {action!r}"},
        )
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise HTTPException(
            status_code=400,
            detail={"type": "invalid_ids", "message": "ids 必须为字符串列表"},
        )

    repo = AgentRepository()
    succeeded, failed = [], []
    for agent_id in ids:
        try:
            if action == "delete":
                _delete_agent_internal(agent_id)
            elif action in ("enable", "disable") and not repo.update(
                agent_id, {"enabled": action == "enable"}
            ):
                raise ValueError(f"agent {agent_id!r} 不存在或更新失败")
            succeeded.append(agent_id)
        except HTTPException as exc:
            failed.append({"id": agent_id, "error": exc.detail.get("message", str(exc.detail))})
        except Exception as exc:
            failed.append({"id": agent_id, "error": str(exc)})
    logger.info("批量操作专家 (action=%s, succeeded=%s, failed=%s)", action, len(succeeded), len(failed))
    return {"succeeded": succeeded, "failed": failed}


@router.post("/agents/reorder")
@with_db_lock
def reorder_agents(data: dict):
    """批量更新专家排序（P2-d）。``data: {items: [{id, sort_order}]}``。

    置顶 / 上移 / 下移由前端计算新序列后整体提交，后端只做幂等写入。
    """
    from backend.data.agent_repo import AgentRepository

    items = data.get("items", [])
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        raise HTTPException(
            status_code=400,
            detail={"type": "invalid_items", "message": "items 必须为 {id, sort_order} 对象列表"},
        )
    repo = AgentRepository()
    updated = 0
    for item in items:
        agent_id = item.get("id")
        sort_order = item.get("sort_order")
        if not isinstance(agent_id, str) or not isinstance(sort_order, int):
            continue
        if repo.update(agent_id, {"sort_order": sort_order}):
            updated += 1
    logger.info("批量更新专家排序 (updated=%s/%s)", updated, len(items))
    return {"updated": updated}


# ==================== M4-T3 (2026-11-05) 版本 diff / 回滚 ====================
#
# 依赖 agent_versions 表（migration v12）。快照由 create_agent / update_agent
# / rollback_agent 写入；本组路由只做读与回滚。


@router.get("/agents/{agent_id}/versions")
@with_db_lock
def list_agent_versions(agent_id: str):
    """列出某专家的所有版本快照（version DESC）。

    - 200 + ``[{version, reason, created_at}]``（无快照时为空列表）
    - 404 + ``type: agent_not_found`` —— 专家 id 不存在
    """
    from backend.data.agent_repo import AgentRepository
    from backend.data.agent_version_repo import AgentVersionRepository

    if AgentRepository().get(agent_id) is None:
        raise HTTPException(
            status_code=404,
            detail={"type": "agent_not_found", "message": f"agent {agent_id!r} 不存在"},
        )
    return AgentVersionRepository().list_versions(agent_id)


@router.get("/agents/{agent_id}/versions/diff")
@with_db_lock
def diff_agent_versions(
    agent_id: str,
    from_version: int = Query(..., alias="from", ge=1),
    to_version: int = Query(..., alias="to", ge=1),
):
    """字段级 diff（仅白名单字段）。

    - 200 + ``[{field, before, after}]``；无差异为空列表
    - 404 + ``type: agent_not_found`` —— 专家 id 不存在
    - 404 + ``type: version_not_found`` —— 任一版本不存在
    """
    from backend.data.agent_repo import AgentRepository
    from backend.data.agent_version_repo import AgentVersionRepository

    if AgentRepository().get(agent_id) is None:
        raise HTTPException(
            status_code=404,
            detail={"type": "agent_not_found", "message": f"agent {agent_id!r} 不存在"},
        )
    try:
        return AgentVersionRepository().diff(agent_id, from_version, to_version)
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail={"type": "version_not_found", "message": str(exc)},
        )


@router.get("/agents/{agent_id}/versions/{version}")
@with_db_lock
def get_agent_version(agent_id: str, version: int):
    """读取某版本的完整 profile 快照。

    - 200 + 完整 profile dict
    - 404 + ``type: agent_not_found`` / ``type: version_not_found``
    """
    from backend.data.agent_repo import AgentRepository
    from backend.data.agent_version_repo import AgentVersionRepository

    if AgentRepository().get(agent_id) is None:
        raise HTTPException(
            status_code=404,
            detail={"type": "agent_not_found", "message": f"agent {agent_id!r} 不存在"},
        )
    snapshot = AgentVersionRepository().read_version(agent_id, version)
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail={
                "type": "version_not_found",
                "message": f"agent {agent_id!r} 没有版本 {version}",
            },
        )
    return snapshot


@router.post("/agents/{agent_id}/rollback")
@with_db_lock
def rollback_agent(agent_id: str, data: AgentRollback):
    """回滚到指定版本。

    流程：
    1. 读目标版本完整 profile 快照
    2. 以「当前版本号 + 1」重写 agents 表
    3. 新版本写快照（``reason='rollback'``）

    ``version`` 会被重置为当前+1（而非目标 version），保证历史单调递增，
    并避免与既有快照主键冲突。

    - 200 + 回滚后的新 profile
    - 404 + ``type: agent_not_found`` / ``type: version_not_found``
    """
    from backend.data.agent_repo import AgentRepository
    from backend.data.agent_version_repo import AgentVersionRepository

    repo = AgentRepository()
    current = repo.get(agent_id)
    if current is None:
        raise HTTPException(
            status_code=404,
            detail={"type": "agent_not_found", "message": f"agent {agent_id!r} 不存在"},
        )

    version_repo = AgentVersionRepository()
    target = version_repo.read_version(agent_id, data.version)
    if target is None:
        raise HTTPException(
            status_code=404,
            detail={
                "type": "version_not_found",
                "message": f"agent {agent_id!r} 没有版本 {data.version}",
            },
        )

    # 目标版本可能来自较早 commit，id 字段以当前为准（防跨专家误覆盖）。
    rollback_profile = dict(target)
    rollback_profile["id"] = agent_id
    rollback_profile["version"] = int(current.get("version", 1)) + 1
    rollback_profile.pop("updated_at", None)
    repo.update(agent_id, rollback_profile)

    new_profile = repo.get(agent_id)
    try:
        version_repo.snapshot(agent_id, new_profile, reason="rollback")
    except Exception as exc:
        logger.warning("M4-T3 rollback snapshot 失败 (agent=%s): %s", agent_id, exc)

    return new_profile


@router.post("/agents/{agent_id}/duplicate")
@with_db_lock
def duplicate_agent(agent_id: str):
    """复制一个 agent（M0 2026-11-03）。

    新 id = ``{原id}-copy-{毫秒时间戳}``；新 name = ``{原name} (副本)``；
    默认 ``enabled=False``（避免新专家立刻进入聊天选择器）；其余字段
    （system_prompt / tools / memory_access / model_config / max_iterations /
    role / description）原样复制。

    - 200 + 完整新 profile
    - 404 + ``type: agent_not_found`` —— 源 id 不存在
    """
    import time as _time

    from backend.data.agent_repo import AgentRepository

    repo = AgentRepository()
    source = repo.get(agent_id)
    if source is None:
        raise HTTPException(
            status_code=404,
            detail={
                "type": "agent_not_found",
                "message": f"agent {agent_id!r} 不存在",
            },
        )

    suffix = int(_time.time() * 1000)
    new_id = f"{agent_id}-copy-{suffix}"
    new_profile = {
        **source,
        "id": new_id,
        "name": f"{source.get('name', agent_id)} (副本)",
        "enabled": False,
    }
    # 清掉源 updated_at —— upsert 会自动填新的
    new_profile.pop("updated_at", None)
    repo.upsert(new_profile)
    return repo.get(new_id)


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
