"""Zotero 同步 REST 端点（M3 feat/zotero-llm-visible）。

挂载到 ``/api/v1/zotero``，与 ``zotero_routes.py`` 同 prefix：

- ``POST /sync``         触发索引层同步；``body {"force": true}`` 全量重建，
                          缺省增量。``asyncio.Lock`` 单进程内互斥，已运行时
                          409 Conflict。
- ``GET  /sync-status``  返回上次同步状态（时间戳、条目数、错误列表、
                          embedding 是否已配置）。

接线（数据路径 / 客户端 / 嵌入配置 / ingestor 组装）全部来自
``backend/zotero/service.py``，与 MCP 子进程共用同一份实现——两处各写一份
曾经造成「设置页能同步、LLM 却检索不到」的接线漂移。

并发保护说明
------------
``_sync_lock`` 是进程级 ``asyncio.Lock``（经 ``LazyLock`` 延迟构造，满足 py3.8
事件循环约束），同一 Sage 进程内保证同时只有一次同步。MCP 子进程是另一个进程，
**不共享这把锁**。虽然 ``VectorStore.upsert_pages`` 的 JSON 原子写避免文件损坏，
但两个并发调用仍然会出现"后写入者覆盖"的丢失条目问题——前端 / MCP 客户端应当
避免并发触发同步（409 只在进程内生效）。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.orchestration._lazy_lock import LazyLock
from backend.zotero import service as zotero_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["zotero"])

WIKI_PROJECT_KEY = "zotero_wiki_project_path"


def _configured_wiki_project() -> Optional[str]:
    """Read the persisted wiki project binding (empty/absent → None)."""
    try:
        from backend.data.settings_repo import SettingsRepository

        value = SettingsRepository().get(WIKI_PROJECT_KEY) or ""
    except Exception:
        return None
    value = value.strip()
    return value or None


class SyncRequest(BaseModel):
    force: bool = False
    project_path: Optional[str] = None


# ---------------------------------------------------------------------------
# 并发保护（进程级）
# ---------------------------------------------------------------------------

_sync_lock = LazyLock()
_sync_in_progress: bool = False


# ---------------------------------------------------------------------------
# POST /sync
# ---------------------------------------------------------------------------


@router.post("/sync")
async def sync_zotero(body: SyncRequest) -> Dict[str, Any]:
    """触发 Zotero 索引层同步。

    - ``force=true`` → 全量重建
    - ``force=false``（缺省）→ 增量（按 settings 中的水位）
    - ``project_path`` → 同步完成后把带 wiki tag 的文献沉淀为 wiki 页面
    - 已有同步进行中 → 409 Conflict

    嵌入未配置时不抛错，返回 ``skipped=true`` 并在 ``errors`` 里记原因，
    便于前端引导用户配置 embedding 模型。
    """
    global _sync_in_progress
    if _sync_lock.locked():
        raise HTTPException(
            status_code=409,
            detail="zotero sync already running",
        )

    client = zotero_service.build_client()
    if client is None:
        raise HTTPException(
            status_code=503,
            detail="zotero database not configured or not accessible",
        )

    async with _sync_lock:
        _sync_in_progress = True
        try:
            ingestor = zotero_service.build_ingestor(client)
            if body.force:
                result = await ingestor.sync_full()
            else:
                result = await ingestor.sync_incremental()
        finally:
            _sync_in_progress = False

    payload = result.to_dict()

    project_path = body.project_path or _configured_wiki_project()
    if project_path:
        wiki_payload = _run_wiki_export(client, project_path)
        payload["wiki"] = wiki_payload
        # 把 wiki 页数合并到同步状态，供 sync-status 显示
        if not wiki_payload.get("errors"):
            _record_wiki_pages(wiki_payload.get("items_exported", 0) + wiki_payload.get("authors_exported", 0))

    return payload


def _run_wiki_export(client: Any, project_path: str) -> Dict[str, Any]:
    """尽力而为的 wiki 沉淀；任何异常都吞掉并记入返回体。"""
    from backend.zotero.wiki_export import export_wiki

    try:
        root = Path(project_path)
        if not root.is_dir():
            return {"error": f"project_path is not a directory: {project_path}"}
        result = export_wiki(client, root)
        return result.to_dict()
    except Exception as exc:  # noqa: BLE001 - wiki 沉淀不影响主同步
        logger.warning("zotero wiki export failed: %s", exc)
        return {"error": str(exc)}


def _record_wiki_pages(count: int) -> None:
    """把 wiki 页数写回 settings，便于 sync-status 显示。"""
    try:
        from backend.data.settings_repo import SettingsRepository
        from backend.zotero.ingest import SYNC_STATE_KEY

        repo = SettingsRepository()
        state = repo.get_json(SYNC_STATE_KEY) or {}
        if not isinstance(state, dict):
            state = {}
        state["wiki_pages"] = int(count)
        repo.set_json(SYNC_STATE_KEY, state)
    except Exception:  # pragma: no cover - 记录失败不影响主流程
        logger.debug("record wiki_pages failed", exc_info=True)


# ---------------------------------------------------------------------------
# GET /sync-status
# ---------------------------------------------------------------------------


def _load_sync_state() -> Dict[str, Any]:
    """读同步状态；读失败当作空状态（不抛）。"""
    from backend.data.settings_repo import SettingsRepository
    from backend.zotero.ingest import SYNC_STATE_KEY

    try:
        state = SettingsRepository().get_json(SYNC_STATE_KEY) or {}
    except Exception:
        state = {}
    return dict(state) if isinstance(state, dict) else {}


@router.get("/sync-status")
def sync_status() -> Dict[str, Any]:
    """返回当前同步状态（不触发同步）。"""
    state = _load_sync_state()
    vector_dim, record_count = zotero_service.stored_summary()

    # item_count 取 settings 与向量库实际记录数的较大值，避免两者漂移
    item_count = max(int(state.get("items") or 0), record_count)

    return {
        "last_sync_ts": state.get("last_sync_ts") or None,
        "last_sync_at": state.get("last_sync_at") or None,
        "item_count": item_count,
        "wiki_page_count": int(state.get("wiki_pages") or 0),
        "embedding_configured": zotero_service.embed_config() is not None,
        "vector_dim": vector_dim,
        "sync_in_progress": _sync_in_progress,
        "errors": list(state.get("errors") or [])[:10],
        "wiki_project_path": _configured_wiki_project(),
    }


# ---------------------------------------------------------------------------
# 启动期后台增量同步
# ---------------------------------------------------------------------------


async def run_background_sync() -> None:
    """启动期跑一次**增量**同步。

    规则（见方案 §3.8）：

    - 只有 ``zotero_sync_state.last_sync_ts`` 存在时才跑——**首次不同步**，
      避免大库首次全量索引卡住启动 / 意外产生嵌入 API 费用；首次需用户
      在设置页手动点「立即同步」。
    - 任何异常吞掉并记日志，绝不影响后端启动。
    - 与手动同步共用 ``_sync_lock``；锁被占用（用户正点同步）时直接跳过。
    """
    state = _load_sync_state()
    if not state.get("last_sync_ts"):
        logger.info("zotero background sync skipped (no watermark yet)")
        return

    client = zotero_service.build_client()
    if client is None:
        logger.info("zotero background sync skipped (no database configured)")
        return

    global _sync_in_progress
    if _sync_lock.locked():
        logger.info("zotero background sync skipped (sync already running)")
        return

    async with _sync_lock:
        _sync_in_progress = True
        try:
            ingestor = zotero_service.build_ingestor(client)
            result = await ingestor.sync_incremental()
            logger.info(
                "zotero background sync done: %d items, %d errors",
                result.items,
                len(result.errors),
            )
            binding = _configured_wiki_project()
            if binding:
                wiki_payload = _run_wiki_export(client, binding)
                if not wiki_payload.get("errors"):
                    _record_wiki_pages(
                        wiki_payload.get("items_exported", 0)
                        + wiki_payload.get("authors_exported", 0)
                    )
                else:
                    logger.warning(
                        "zotero background wiki export errors: %s",
                        wiki_payload.get("errors"),
                    )
        except Exception as exc:  # pragma: no cover - 启动期兜底
            logger.warning("zotero background sync failed (ignored): %s", exc)
        finally:
            _sync_in_progress = False
