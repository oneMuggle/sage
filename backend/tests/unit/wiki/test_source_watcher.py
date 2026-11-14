"""Wiki Source 目录监听（watchdog 可选 + handler 行为）。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.wiki import source_watcher as sw

pytestmark = pytest.mark.unit


class _FakeObserver:
    """记录 schedule/unschedule/start/stop 调用，不启动线程。"""

    def __init__(self) -> None:
        self.scheduled: list[tuple[object, str, bool]] = []
        self.unscheduled: list[object] = []
        self.started: int = 0
        self.stopped: int = 0

    def schedule(self, handler: object, path: str, recursive: bool) -> str:
        self.scheduled.append((handler, path, recursive))
        return "watch-1"

    def unschedule(self, watch: object) -> None:
        self.unscheduled.append(watch)

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1

    def join(self, timeout: float = 0) -> None:
        return None


@pytest.mark.skipif(
    sw._WATCHDOG_AVAILABLE, reason="watchdog 已安装，跳过降级路径测试"
)
def test_degraded_mode_noop_without_watchdog(tmp_path: Path) -> None:
    assert sw.create_observer() is None

    watcher = sw.SourceWatcher(tmp_path)
    watcher.start()
    watcher.stop()


def test_handler_enqueues_new_source_file(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    class _Queue:
        def __init__(self, root: Path) -> None:
            self.root = root

        def add(self, path: str, priority: str = "normal") -> None:
            calls.append((path, priority))

    from backend.wiki import ingest_queue

    monkeypatch.setattr(ingest_queue, "IngestQueue", _Queue)

    handler = sw._SourceHandler(tmp_path)
    handler.on_created(
        SimpleNamespace(
            is_directory=False,
            src_path=str(tmp_path / "raw/sources/a.pdf"),
        )
    )

    assert calls == [("raw/sources/a.pdf", "normal")]


def test_handler_ignores_directories_and_hidden_files(
    tmp_path: Path, monkeypatch
) -> None:
    from backend.wiki import ingest_queue

    calls: list[tuple[str, str]] = []

    class _Queue:
        def __init__(self, root: Path) -> None:
            self.root = root

        def add(self, path: str, priority: str = "normal") -> None:
            calls.append((path, priority))

    monkeypatch.setattr(ingest_queue, "IngestQueue", _Queue)

    handler = sw._SourceHandler(tmp_path)
    handler.on_created(
        SimpleNamespace(is_directory=True, src_path=str(tmp_path / "raw/sources/dir"))
    )
    handler.on_created(
        SimpleNamespace(
            is_directory=False,
            src_path=str(tmp_path / "raw/sources/.DS_Store"),
        )
    )

    assert calls == []


def test_handler_deletes_source_and_triggers_cascade(
    tmp_path: Path, monkeypatch
) -> None:
    from backend.wiki import lifecycle

    calls: list[tuple[Path, str]] = []
    monkeypatch.setattr(
        lifecycle,
        "cascade_delete_source",
        lambda root, rel: calls.append((root, rel)),
    )

    handler = sw._SourceHandler(tmp_path)
    handler.on_deleted(
        SimpleNamespace(
            is_directory=False,
            src_path=str(tmp_path / "raw/sources/a.pdf"),
        )
    )

    assert calls == [(tmp_path, "raw/sources/a.pdf")]


def test_shared_observer_start_registers_only(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sw, "_WATCHDOG_AVAILABLE", True)
    observer = _FakeObserver()

    watcher = sw.SourceWatcher(tmp_path, observer=observer)
    watcher.start()

    assert (tmp_path / "raw" / "sources").is_dir()
    assert len(observer.scheduled) == 1
    _handler, path, recursive = observer.scheduled[0]
    assert path == str(tmp_path / "raw" / "sources")
    assert recursive is False
    # 共享 observer 不自动启动（由 queue_daemon 统一启动）
    assert observer.started == 0

    watcher.stop()
    assert observer.unscheduled == ["watch-1"]
    # 共享 observer 不由本 watcher 停止
    assert observer.stopped == 0


def test_owned_observer_starts_and_stops(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sw, "_WATCHDOG_AVAILABLE", True)
    owned = _FakeObserver()
    # watchdog 未安装时模块命名空间不含 Observer，需 raising=False 注入
    monkeypatch.setattr(sw, "Observer", lambda: owned, raising=False)

    watcher = sw.SourceWatcher(tmp_path)
    watcher.start()

    assert owned.started == 1

    watcher.stop()
    assert owned.stopped == 1
