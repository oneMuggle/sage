"""P7 (2026-09-14): office 长任务进度注册表单元测试。

覆盖 begin/report/finish 生命周期、百分比单调性、track 上下文的
None 探针与异常清理语义。
"""

from __future__ import annotations

import pytest

from backend.office.progress import snapshot, track


def test_report_snapshot_lifecycle():
    with track("t1", "生成 PPT") as prog:
        prog.report("生成文档", 30)
        snap = snapshot("t1")
        assert snap is not None
        assert snap["percent"] == 30
        assert snap["stage"] == "生成文档"
        prog.report("登记文档", 90)
        assert snapshot("t1")["percent"] == 90

    # track 退出即移除（前端轮询到 None 视为完成）
    assert snapshot("t1") is None


def test_report_percent_is_monotonic_and_clamped():
    with track("t2", "导出 PDF") as prog:
        prog.report("转换", 80)
        prog.report("回退也不该降", 20)
        assert snapshot("t2")["percent"] == 80
        prog.report("越界钳到 100", 150)
        assert snapshot("t2")["percent"] == 100
    assert snapshot("t2") is None


def test_track_without_task_id_is_noop():
    with track(None, "不该有任何状态"):
        pass
    # 无注册表条目、无异常即可


def test_track_exception_still_cleans_up():
    with pytest.raises(RuntimeError), track("t3", "会失败的任务"):
        raise RuntimeError("boom")
    assert snapshot("t3") is None


def test_report_unknown_task_is_noop():
    # 未 begin 的 task_id 直接 report 不报错（宽容语义）
    with track("t4", "x") as prog:
        prog.report("无中生有", 50)
    assert snapshot("t4") is None
