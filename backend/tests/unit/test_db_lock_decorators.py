"""D3 (P6): with_db_lock 统一实现后的行为一致性测试。

orch_routes / legacy_routes 两份装饰器此前是逐字重复实现, 收敛到
``database.make_with_db_lock`` 后, 用测试锁定三个不变量:
1. 两个模块的装饰器共享同一把 ``_SQLITE_LOCK``;
2. wrapper 的 ``__globals__`` 指向各自定义模块 (FastAPI 字符串注解
   在本模块解析的硬约束, 见 orch_routes.with_db_lock docstring);
3. ``__wrapped__``/``__doc__`` 等元数据在 FunctionType 重建后保留
   (FastAPI 签名解析沿 __wrapped__ 链);
4. 并发调用确实被串行化。
"""

import threading
import time

import pytest

from backend.api import legacy_routes, orch_routes
from backend.data.database import _SQLITE_LOCK, make_with_db_lock

pytestmark = pytest.mark.unit


def test_both_modules_share_the_same_sqlite_lock():
    """两个 routes 模块 import 的必须是 database 的同一把锁。"""
    assert legacy_routes._SQLITE_LOCK is _SQLITE_LOCK
    assert orch_routes._SQLITE_LOCK is _SQLITE_LOCK


def test_wrapper_globals_resolve_to_their_own_module():
    """wrapper.__globals__ 必须指向各自模块。

    FastAPI get_typed_signature 用 call.__globals__ 求值字符串注解;
    若指向 database 模块, 各 routes 的 body 模型会报
    PydanticUndefinedAnnotation —— 这是不能简单合并实现的硬约束,
    本测试防止未来重构悄悄退化。
    """
    state = {"calls": 0}

    def _handler(x: int) -> int:
        """handler docstring"""
        state["calls"] += 1
        return x

    wrapped_legacy = legacy_routes.with_db_lock(_handler)
    wrapped_orch = orch_routes.with_db_lock(_handler)

    assert wrapped_legacy.__globals__ is legacy_routes.__dict__
    assert wrapped_orch.__globals__ is orch_routes.__dict__


def test_rebuilt_wrapper_keeps_wrapped_and_doc_metadata():
    """FunctionType 重建会丢 functools.wraps 元数据, 工厂必须补回。"""

    def _handler(x: int = 3) -> int:
        """handler docstring"""
        return x

    wrapped = make_with_db_lock(globals())(_handler)

    assert wrapped.__wrapped__ is _handler
    assert wrapped.__doc__ == _handler.__doc__
    assert wrapped.__name__ == "_handler"


def test_make_with_db_lock_serializes_concurrent_calls():
    """并发调用经同一把锁串行执行, 不产生交错。"""
    counters = {"value": 0, "max_concurrent": 0, "in_critical": 0}
    guard = threading.Lock()

    def bump():
        with guard:
            counters["in_critical"] += 1
            counters["max_concurrent"] = max(
                counters["max_concurrent"], counters["in_critical"]
            )
        time.sleep(0.005)
        with guard:
            counters["in_critical"] -= 1
        counters["value"] += 1

    wrapped = make_with_db_lock(globals())(bump)
    threads = [threading.Thread(target=wrapped) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert counters["value"] == 8
    assert counters["max_concurrent"] == 1
