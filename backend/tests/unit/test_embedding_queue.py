"""T2/T3 (P10): 编码队列与检索埋点单元测试。"""

from __future__ import annotations

import threading
import time

import pytest

from backend.memory import embedding_queue
from backend.memory.embedding_queue import enqueue, reset_for_tests

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean_queue():
    reset_for_tests()
    yield
    reset_for_tests()


def test_enqueue_executes_task():
    """入队任务被 worker 执行。"""
    done = threading.Event()
    enqueue(lambda: done.set())
    assert done.wait(timeout=5)


def test_enqueue_preserves_args_and_kwargs():
    seen = {}

    def task(a, b, key=None):
        seen["args"] = (a, b)
        seen["key"] = key

    enqueue(task, 1, 2, key="k")
    deadline = time.time() + 5
    while "key" not in seen and time.time() < deadline:
        time.sleep(0.01)
    assert seen == {"args": (1, 2), "key": "k"}


def test_task_exception_does_not_kill_worker():
    """任务抛异常后 worker 仍能处理后续任务。"""
    results = []

    def bad():
        raise RuntimeError("boom")

    enqueue(bad)
    time.sleep(0.2)  # 让 bad 先被执行
    enqueue(lambda: results.append(1))
    deadline = time.time() + 5
    while not results and time.time() < deadline:
        time.sleep(0.01)
    assert results == [1]


def test_enqueue_returns_false_when_queue_rejects(monkeypatch):
    """队列拒绝 (Full) 时 enqueue 返回 False 且不抛异常。"""
    import queue as queue_mod

    def _raise_full(_item):
        raise queue_mod.Full

    monkeypatch.setattr(embedding_queue._queue, "put_nowait", _raise_full, raising=False)
    assert enqueue(lambda: None) is False


def test_worker_survives_task_exception_and_keeps_consuming():
    """任务异常后 worker 仍存活并继续消费后续任务 (worker 不会被毒死)。"""
    results = []

    def bad():
        raise RuntimeError("boom")

    enqueue(bad)
    enqueue(lambda: results.append(1))

    deadline = time.time() + 5
    while not results and time.time() < deadline:
        time.sleep(0.01)
    assert results == [1]
