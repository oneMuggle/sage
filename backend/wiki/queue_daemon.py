"""Wiki 摄入队列后台守护进程。

用户显式入队的任务由这里周期性消费；API 的「处理队列」按钮仍可手动触发。
守护进程与手动入口共享 ``queue_worker.queue_process_lock``。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

DEFAULT_POLL_SECONDS = 60.0
BATCH_LIMIT = 5


def _candidate_projects() -> List[Path]:
    """Return unique existing project roots from the projects/recent registries."""
    paths: Set[Path] = set()
    try:
        from backend.data.project_repo import ProjectRepository

        paths.update(Path(project.path) for project in ProjectRepository().list(limit=200))
    except Exception:  # noqa: BLE001 - registry unavailable → skip
        logger.debug("wiki queue daemon: project registry unavailable", exc_info=True)
    try:
        from backend.storage.recent_projects import load_recent

        paths.update(Path(project.path) for project in load_recent())
    except Exception:  # noqa: BLE001 - registry unavailable → skip
        logger.debug("wiki queue daemon: recent projects unavailable", exc_info=True)
    return sorted(path for path in paths if path.is_dir())


def _pending_projects() -> List[Path]:
    """Projects whose persisted ingest queue has at least one pending task."""
    from backend.wiki.ingest_queue import IngestQueue

    pending: List[Path] = []
    for root in _candidate_projects():
        if not (root / ".llm-wiki" / "ingest-queue.json").is_file():
            continue
        try:
            if IngestQueue(root).get_status_summary().get("pending", 0) > 0:
                pending.append(root)
        except Exception:  # noqa: BLE001 - corrupt queue must not stop others
            logger.warning("wiki queue daemon: failed to read queue at %s", root, exc_info=True)
    return pending


async def _drain_once() -> None:
    from backend.wiki.queue_worker import process_pending, queue_process_lock

    if queue_process_lock.locked():
        return

    for root in _pending_projects():
        if queue_process_lock.locked():
            return
        async with queue_process_lock:
            try:
                result = await process_pending(root, limit=BATCH_LIMIT)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - one project must not stop others
                logger.warning("wiki queue daemon: project %s failed", root, exc_info=True)
                continue
        processed = result.get("processed") or []
        if processed:
            logger.info(
                "wiki queue daemon: processed %d task(s) in %s", len(processed), root
            )
        elif result.get("error"):
            logger.debug("wiki queue daemon: %s — %s", root, result["error"])


def _watched_projects() -> List[Path]:
    """已初始化 wiki（存在 ``.llm-wiki`` 目录）的项目根目录。"""
    return [root for root in _candidate_projects() if (root / ".llm-wiki").is_dir()]


def _start_source_watchers() -> Tuple[Optional[object], List[object]]:
    """为已初始化的项目启动 raw/sources/ 监听（共享单个 Observer）。"""
    from backend.wiki.source_watcher import SourceWatcher, create_observer

    observer = create_observer()
    if observer is None:
        return None, []
    watchers: List[object] = []
    for root in _watched_projects():
        try:
            watcher = SourceWatcher(root, observer=observer)
            watcher.start()
        except Exception:  # noqa: BLE001 - one project must not stop others
            logger.warning("wiki queue daemon: failed to watch %s", root, exc_info=True)
            continue
        watchers.append(watcher)
    if not watchers:
        return None, []
    try:
        observer.start()  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001 - watcher 不可用不应阻断队列消费
        logger.warning("wiki queue daemon: failed to start observer", exc_info=True)
        return None, watchers
    logger.info("wiki queue daemon: watching raw/sources/ of %d project(s)", len(watchers))
    return observer, watchers


def _stop_source_watchers(observer: Optional[object], watchers: List[object]) -> None:
    """先注销各项目监听，再停止共享 Observer。"""
    for watcher in watchers:
        try:
            watcher.stop()  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001 - shutdown must continue
            logger.warning("wiki queue daemon: failed to stop watcher", exc_info=True)
    if observer is None:
        return
    try:
        observer.stop()  # type: ignore[union-attr]
        observer.join(timeout=5)  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001 - shutdown must continue
        logger.warning("wiki queue daemon: failed to stop observer", exc_info=True)


async def run_queue_daemon(
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    max_cycles: Optional[int] = None,
    watch_sources: bool = True,
) -> None:
    """Poll pending queues forever (or ``max_cycles`` times for tests)."""
    observer, watchers = _start_source_watchers() if watch_sources else (None, [])
    cycles = 0
    try:
        while True:
            cycles += 1
            try:
                await _drain_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - daemon must survive unexpected errors
                logger.warning("wiki queue daemon cycle failed", exc_info=True)
            if max_cycles is not None and cycles >= max_cycles:
                return
            await asyncio.sleep(poll_seconds)
    finally:
        _stop_source_watchers(observer, watchers)
