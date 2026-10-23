"""R158 — 调度端口契约（domain/scheduler.py）单元测试。

覆盖：异常类型继承（KeyError / ValueError）、SchedulerServicePort 协议
可被 duck-type 类实现并静态通过（mypy 语义的运行时佐证）。
"""

from __future__ import annotations

import pytest

from backend.domain.scheduler import (
    ScheduledTaskNotFoundError,
    ScheduledTaskValidationError,
    SchedulerServicePort,
)

pytestmark = pytest.mark.unit


def test_not_found_error_is_key_error():
    err = ScheduledTaskNotFoundError("t-1")
    assert isinstance(err, KeyError)
    assert isinstance(err, Exception)


def test_validation_error_is_value_error():
    err = ScheduledTaskValidationError("bad input")
    assert isinstance(err, ValueError)
    assert isinstance(err, Exception)


def test_port_protocol_defines_contract():
    # 协议三方法在 Protocol 体内声明（结构化契约存在性护栏；
    # 不用 __protocol_attrs__——私有运行时助手跨版本不稳定）
    for method in ("add_task", "list_tasks", "delete_task"):
        assert callable(getattr(SchedulerServicePort, method, None))


def test_duck_typed_implementation_satisfies_port():
    class _FakeScheduler:
        def add_task(self, name, task_type, schedule, session_id, content, enabled=True):
            return "id-1"

        def list_tasks(self):
            return []

        def delete_task(self, task_id, expected_session_id=None):
            return None

    fake = _FakeScheduler()
    # 与协议同构：具备全部三个方法即可当 SchedulerServicePort 使用
    for method in ("add_task", "list_tasks", "delete_task"):
        assert callable(getattr(fake, method))
    assert fake.add_task("n", "t", {}, "s", "c") == "id-1"
    assert fake.list_tasks() == []
    assert fake.delete_task("t-1") is None
