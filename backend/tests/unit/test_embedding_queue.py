"""T2/T3 (P10): 编码队列与检索埋点单元测试。"""

from __future__ import annotations

import threading
import time

import pytest

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


def test_queue_full_drops_oldest_gracefully():
    """队列满时新任务被丢弃 (返回 False), 不阻塞调用方。"""
    release = threading.Event()
    blocked = threading.Event()

    def blocker():
        blocked.set()
        release.wait(timeout=5)

    # 独占 worker
    enqueue(blocker)
    assert blocked.wait(timeout=5)

    # 灌满队列
    accepted = 0
    for _ in range(1000):
        if enqueue(lambda: None):
            accepted += 1

    assert accepted == 1000
    assert enqueue(lambda: None) is False  # 队列满 → 丢弃
    release.set()
