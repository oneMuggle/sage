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
    """队列满时新任务被丢弃 (返回 False), 不阻塞调用方。

    用 blocker 卡住 worker 保证确定性: worker 执行 blocker 期间被
    threading.Event 挂起, 主线程持续入队直到队列真正满 (1000),
    此后任何 enqueue 都应被拒绝。
    """
    release = threading.Event()
    started = threading.Event()

    def blocker():
        started.set()
        release.wait(timeout=10)

    # 独占 worker
    enqueue(blocker)
    assert started.wait(timeout=5)

    # worker 被挂起, 持续入队直到队列满
    accepted = 0
    for _ in range(1200):
        if enqueue(lambda: None):
            accepted += 1
        else:
            break

    assert accepted == 1000, f"accepted={accepted}"
    assert enqueue(lambda: None) is False  # 队列满 → 丢弃
    release.set()
    release.set()
