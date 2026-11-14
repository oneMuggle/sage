"""Source 目录自动监听。

使用 watchdog 监听 raw/sources/ 目录变化，自动触发 ingest 或级联删除。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from watchdog.events import FileCreatedEvent, FileDeletedEvent, FileSystemEventHandler
    from watchdog.observers import Observer

    _WATCHDOG_AVAILABLE = True
except ImportError:
    _WATCHDOG_AVAILABLE = False
    FileSystemEventHandler = object  # type: ignore[misc, assignment]


def create_observer():
    """创建共享 Observer；watchdog 不可用时返回 ``None``。"""
    if not _WATCHDOG_AVAILABLE:
        return None
    return Observer()


class SourceWatcher:
    """监听 raw/sources/ 目录变化，自动入队 ingest 或触发级联删除。

    传入 ``observer`` 时复用调用方的 Observer（多项目共享一个线程），
    此时生命周期由调用方管理：``start()`` 只注册监听，``stop()`` 只注销监听。
    """

    def __init__(self, project_root: Path, observer: Optional[object] = None) -> None:
        self.project_root = project_root
        self._observer: Optional[object] = observer
        self._owns_observer = observer is None
        self._watch: Optional[object] = None

    def start(self) -> None:
        """启动监听。共享 Observer 时只注册，不启动线程。"""
        if not _WATCHDOG_AVAILABLE:
            logger.debug("watchdog 未安装，跳过 source watcher")
            return

        sources_dir = self.project_root / "raw" / "sources"
        sources_dir.mkdir(parents=True, exist_ok=True)

        if self._observer is None:
            self._observer = Observer()
        handler = _SourceHandler(self.project_root)
        self._watch = self._observer.schedule(handler, str(sources_dir), recursive=False)  # type: ignore[union-attr]
        if self._owns_observer:
            self._observer.start()  # type: ignore[union-attr]
        logger.info("source watcher 已启动: %s", sources_dir)

    def stop(self) -> None:
        """停止监听。共享 Observer 时只注销本项目的监听。"""
        if self._observer is None:
            return
        if self._watch is not None:
            try:
                self._observer.unschedule(self._watch)  # type: ignore[union-attr]
            except Exception:  # noqa: BLE001 - 注销失败不应阻塞关闭
                logger.debug("source watcher: 注销监听失败", exc_info=True)
            self._watch = None
        if self._owns_observer:
            self._observer.stop()  # type: ignore[union-attr]
            self._observer.join(timeout=5)  # type: ignore[union-attr]
            logger.info("source watcher 已停止")
        self._observer = None


class _SourceHandler(FileSystemEventHandler):  # type: ignore[misc]
    """处理 raw/sources/ 目录的文件创建和删除事件。"""

    def __init__(self, project_root: Path) -> None:
        super().__init__()
        self.project_root = project_root

    def on_created(self, event: FileCreatedEvent) -> None:  # type: ignore[override]
        if event.is_directory:
            return
        filename = Path(event.src_path).name
        if filename.startswith("."):
            return
        logger.info("source watcher: 新文件 %s，加入 ingest 队列", filename)
        try:
            from backend.wiki.ingest_queue import IngestQueue

            queue = IngestQueue(self.project_root)
            queue.add(f"raw/sources/{filename}", priority="normal")
        except Exception:
            logger.warning("source watcher: 入队失败", exc_info=True)

    def on_deleted(self, event: FileDeletedEvent) -> None:  # type: ignore[override]
        if event.is_directory:
            return
        filename = Path(event.src_path).name
        logger.info("source watcher: 文件删除 %s，触发级联清理", filename)
        try:
            from backend.wiki.lifecycle import cascade_delete_source

            cascade_delete_source(self.project_root, f"raw/sources/{filename}")
        except Exception:
            logger.warning("source watcher: 级联删除失败", exc_info=True)
