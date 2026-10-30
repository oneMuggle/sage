"""摄入队列的顺序处理入口（手动触发；不是后台守护进程）。

`POST /api/v1/wiki/ingest/queue/process` 调这里：按 FIFO 取 pending 任务，
用 app_settings 里的聊天/embedding 配置真实跑 ingest 管线，并把状态写回
`.llm-wiki/ingest-queue.json`。单任务失败不会中断后续任务。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.wiki.ingest import IngestConfig, ingest_source
from backend.wiki.ingest_queue import IngestQueue
from backend.wiki.llm_context import make_llm_context

logger = logging.getLogger(__name__)


def _load_llm_config() -> Optional[Dict[str, Any]]:
    from backend.orchestration.llm_factory import load_llm_config_from_settings

    return load_llm_config_from_settings()


def _load_embedding_config() -> Optional[Dict[str, str]]:
    from backend.tools.workspace_index import load_embedding_config

    return load_embedding_config()


def _resolve_task_source(project_root: Path, source_path: str) -> Path:
    """Resolve a queued source path and enforce project containment."""
    root = project_root.resolve()
    candidate = Path(source_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve(strict=True)
    resolved.relative_to(root)
    return resolved


async def process_pending(project_root: Path, limit: int = 1) -> Dict[str, Any]:
    """Process up to ``limit`` pending tasks in FIFO order."""
    queue = IngestQueue(project_root)
    llm = _load_llm_config()
    embedding = _load_embedding_config()
    if llm is None or embedding is None:
        return {
            "processed": [],
            "remaining": queue.get_status_summary(),
            "error": "LLM 或 embedding 模型未配置",
        }

    config = IngestConfig(
        llm_base_url=llm["base_url"],
        llm_api_key=llm["api_key"],
        llm_model=llm["model"],
        embed_base_url=embedding["base_url"],
        embed_api_key=embedding["api_key"],
        embed_model=embedding["model"],
    )
    ctx = make_llm_context(llm["base_url"], llm["api_key"], llm["model"])
    processed: List[Dict[str, Any]] = []

    for _ in range(max(1, min(int(limit), 20))):
        task = queue.get_next_pending()
        if task is None:
            break
        if not queue.mark_processing(task.task_id):
            break
        try:
            source = _resolve_task_source(project_root, task.source_path)
            result = await ingest_source(
                config,
                project_root,
                source,
                ctx.llm_call,
                ctx.http_post,
            )
            queue.mark_completed(
                task.task_id,
                {
                    "wiki_page_path": result.wiki_page_path,
                    "page_type": result.page_type,
                },
            )
            processed.append(
                {
                    "task_id": task.task_id,
                    "status": "completed",
                    "wiki_page_path": result.wiki_page_path,
                }
            )
        except Exception as exc:  # noqa: BLE001 - 单任务失败不中断队列
            message = str(exc)[:500] or type(exc).__name__
            queue.mark_failed(task.task_id, message)
            logger.warning("wiki queue task %s failed: %s", task.task_id, message)
            processed.append(
                {"task_id": task.task_id, "status": "failed", "error": message}
            )

    return {"processed": processed, "remaining": queue.get_status_summary()}
