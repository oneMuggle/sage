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
