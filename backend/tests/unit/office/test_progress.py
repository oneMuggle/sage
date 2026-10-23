"""R123 — office 长任务进度注册表单元测试。

覆盖：track 建立与移除（正常/异常路径）、reporter 上报、百分比钳制
与单调不回退、task_id=None 全 no-op 探针、未知 task_id 容错、P12
ContextVar 关联（track 内写当前任务/退出复位后 no-op）、snapshot 副本
语义、多线程并发上报。
"""

from __future__ import annotations

import threading

import pytest

from backend.office import progress as progress_mod
from backend.office.progress import report, report_current, snapshot, track

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean_registry():
    """隔离进程内注册表，防跨用例污染。"""
    progress_mod._progress.clear()
    yield
    progress_mod._progress.clear()


# ---------------------------------------------------------------------------
# track 生命周期
# ---------------------------------------------------------------------------


def test_track_creates_entry_and_report_updates():
    with track("t1", "生成 PPT") as prog:
        assert snapshot("t1") == {"title": "生成 PPT", "stage": "开始", "percent": 0}
        prog.report("生成文档", 30)
        assert snapshot("t1")["stage"] == "生成文档"
        assert snapshot("t1")["percent"] == 30


def test_track_exit_removes_entry():
    with track("t1", "导出"):
        assert snapshot("t1") is not None
    assert snapshot("t1") is None  # 前端轮询 404/None 即完成


def test_track_exit_on_exception_still_removes():
    with pytest.raises(RuntimeError), track("t1", "生成"):
        raise RuntimeError("boom")
    assert snapshot("t1") is None


# ---------------------------------------------------------------------------
# 百分比钳制与单调
# ---------------------------------------------------------------------------


def test_percent_clamped_to_range():
    with track("t1", "T") as prog:
        prog.report("a", 150)
        assert snapshot("t1")["percent"] == 100


def test_percent_lower_bound_from_initial_zero():
    with track("t1", "T") as prog:
        prog.report("a", -5)
        assert snapshot("t1")["percent"] == 0  # 负值钳到下界


def test_percent_monotonic_non_decreasing():
    with track("t1", "T") as prog:
        prog.report("a", 50)
        prog.report("b", 30)
        assert snapshot("t1")["percent"] == 50  # 不回退


def test_percent_accepts_string_digits():
    with track("t1", "T") as prog:
        prog.report("a", "40")
        assert snapshot("t1")["percent"] == 40  # int() 容错


# ---------------------------------------------------------------------------
# None 探针与未知 task_id
# ---------------------------------------------------------------------------


def test_none_task_id_is_full_noop():
    with track(None, "旧客户端") as prog:
        prog.report("a", 50)  # 不得抛错
        assert snapshot("旧客户端") is None
    report("t-none", "a", 10)  # 同样 no-op


def test_report_unknown_task_id_ignored():
    report("ghost", "a", 10)  # 无条目 → 静默忽略而非 KeyError
    assert snapshot("ghost") is None


# ---------------------------------------------------------------------------
# P12 ContextVar 关联
# ---------------------------------------------------------------------------


def test_report_current_writes_bound_task():
    with track("t1", "T"):
        report_current("阶段X", 60)
        entry = snapshot("t1")
        assert entry["stage"] == "阶段X"
        assert entry["percent"] == 60


def test_report_current_outside_track_is_noop():
    report_current("阶段Y", 10)  # 未绑定任务 → no-op
    assert not progress_mod._progress


def test_report_current_after_track_exit_is_noop():
    with track("t1", "T"):
        pass
    report_current("阶段Z", 10)  # token 已复位 → no-op
    assert snapshot("t1") is None


# ---------------------------------------------------------------------------
# snapshot 副本与并发
# ---------------------------------------------------------------------------


def test_snapshot_returns_copy():
    with track("t1", "T"):
        snap = snapshot("t1")
        snap["percent"] = 999
        assert snapshot("t1")["percent"] == 0  # 注册表不受快照修改影响


def test_concurrent_reports_are_safe():
    errors = []

    def worker(n: int) -> None:
        try:
            for i in range(50):
                with track(f"t{n}", "T") as prog:
                    prog.report("s", i)
                    snapshot(f"t{n}")
        except Exception as exc:  # pragma: no cover - 汇入 errors 断言
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    # 全部 track 已退出：注册表清空
    assert not progress_mod._progress
