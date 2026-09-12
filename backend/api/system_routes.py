"""系统维护路由（R19-C/D）。

- ``GET  /system/backups``: SQLite 备份清单
- ``POST /system/backups``: 手动立即备份
- ``GET  /memory/export``: 记忆全量导出（episodic + semantic JSON 信封）

备份操作是潜在阻塞 IO（整库复制），声明为同步 ``def`` 让 FastAPI 丢进
线程池（同 export_routes 的口径）。
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.services import backup_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"])


@router.get("/system/backups")
def list_backups() -> Dict[str, Any]:
    """列出 SQLite 备份（新→旧）。"""
    return {"backups": backup_service.list_backups()}


@router.post("/system/backups")
def create_backup() -> Dict[str, Any]:
    """手动立即备份（fail-safe：失败返回 500 信封由全局错误处理兜底）。"""
    result = backup_service.create_backup("manual")
    if result is None:
        return {"ok": False, "error": "backup failed (see server log)"}
    return {"ok": True, "backup": result}


@router.post("/system/backups/{name}/restore")
def restore_backup(name: str) -> Dict[str, Any]:
    """安排恢复指定备份（下次启动生效；恢复前自动做安全备份）。"""
    from backend.services import backup_service

    result = backup_service.restore_backup(name)
    if result is None:
        return JSONResponse(status_code=400, content={"error": f"备份不存在或恢复失败: {name}"})
    return result


@router.post("/memory/import")
def import_memory(payload: Dict[str, Any]) -> Dict[str, Any]:
    """导入 R19 导出格式的记忆信封（{version, episodic, semantic}）。

    - episodic 条目: {content, importance?, memory_type?, session_id?}
    - semantic 条目: {content, summary?, tags?, session_id?}
    - 去重：content 精确匹配已有记忆即跳过
    - 单条失败不中断，返回 {imported, skipped, failed, errors[:10]}
    """
    import time as _time

    if not isinstance(payload, dict) or payload.get("version") not in (1, "1"):
        return JSONResponse(status_code=400, content={"error": "unsupported export version"})

    from backend.memory.manager import MemoryManager

    try:
        mgr = MemoryManager()
        episodic_repo = mgr.episodic
        semantic_repo = mgr.semantic
    except Exception as exc:  # noqa: BLE001
        logger.exception("memory import: manager init failed: %s", exc)
        return JSONResponse(status_code=500, content={"error": "memory subsystem unavailable"})

    imported = skipped = failed = 0
    errors: list = []
    for entry in payload.get("episodic") or []:
        if not isinstance(entry, dict):
            failed += 1
            continue
        content = str(entry.get("content") or "").strip()
        if not content:
            skipped += 1
            continue
        try:
            if episodic_repo.exists_by_content(content):
                skipped += 1
                continue
            episodic_repo.save(
                content,
                importance=int(entry.get("importance") or 5),
                memory_type=str(entry.get("memory_type") or "conversation"),
                session_id=entry.get("session_id") or None,
            )
            imported += 1
        except Exception as exc:  # noqa: BLE001 — 单条失败不中断
            failed += 1
            if len(errors) < 10:
                errors.append(f"episodic: {exc}")

    for entry in payload.get("semantic") or []:
        if not isinstance(entry, dict):
            failed += 1
            continue
        content = str(entry.get("content") or "").strip()
        if not content:
            skipped += 1
            continue
        try:
            if semantic_repo.exists_by_content(content):
                skipped += 1
                continue
            tags = entry.get("tags")
            semantic_repo.save(
                content,
                summary=entry.get("summary") or None,
                tags=[str(t) for t in tags] if isinstance(tags, list) else None,
                session_id=entry.get("session_id") or None,
            )
            imported += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            if len(errors) < 10:
                errors.append(f"semantic: {exc}")

    return {
        "imported": imported,
        "skipped": skipped,
        "failed": failed,
        "errors": errors,
        "imported_at": int(_time.time() * 1000),
    }


@router.get("/memory/export")
def export_memory() -> Dict[str, Any]:
    """记忆全量导出 —— episodic + semantic（工作记忆随会话易变，不导出）。

    结构化条目直接来自 MemoryManager 两个仓库，字段与 memory_search
    返回对齐，便于将来做导入/迁移。
    """
    from backend.memory.manager import MemoryManager

    try:
        mgr = MemoryManager()
        episodic = mgr.episodic.get_recent(limit=10000)
        semantic = mgr.semantic.get_all()
    except Exception as exc:  # noqa: BLE001 — 导出失败降级为空集，不 500
        logger.exception("memory export failed: %s", exc)
        episodic, semantic = [], []

    import time

    return {
        "app": "sage",
        "version": 1,
        "exported_at": int(time.time() * 1000),
        "episodic": episodic,
        "semantic": semantic,
    }
