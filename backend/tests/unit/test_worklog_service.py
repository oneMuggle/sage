"""工作日志子系统的服务层与模型映射测试（P2）。

覆盖三层：

- :class:`WorklogService` —— 持久化 + 状态机（pending/confirmed/dismissed）
- :func:`row_to_worklog` —— 行到模型的映射与脏数据降级
- 状态机的关键不变量：**待确认候选绝不进报告统计**

路由层的测试在 ``backend/tests/unit/api/test_worklog_router.py``。
"""
from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from backend.data.database import Database
from backend.services.worklog_models import WorkLog, row_to_worklog
from backend.services.worklog_service import WorklogService


@pytest.fixture()
def worklog_service():
    """WorklogService backed by a throwaway SQLite file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = Database(db_path=str(db_path))
        db.init_db()

        service = WorklogService(db)

        yield service

        db.close()


def _today() -> str:
    return datetime.now().date().isoformat()


def _yesterday() -> str:
    return (datetime.now().date() - timedelta(days=1)).isoformat()


# ======================================================================
# 模型映射
# ======================================================================


def _row(**overrides):
    base = {
        "id": 1,
        "session_id": "sess-1",
        "content": "写完了鉴权模块",
        "kind": "progress",
        "progress_text": None,
        "blocker": None,
        "todo_id": None,
        "project_id": None,
        "project_tag": None,
        "source_type": "chat",
        "source_ref": None,
        "status": "pending",
        "created_at": "2026-11-27T14:32:05.123456",
        "updated_at": "2026-11-27T14:32:05.123456",
    }
    base.update(overrides)
    return base


def test_row_to_worklog_maps_all_fields():
    """按列名映射 —— 列顺序变化不会让字段错位。"""
    worklog = row_to_worklog(_row())

    assert worklog.id == 1
    assert worklog.content == "写完了鉴权模块"
    assert worklog.kind == "progress"
    assert worklog.status == "pending"
    assert worklog.source_type == "chat"
    assert worklog.created_at == "2026-11-27T14:32:05.123456"


def test_row_to_worklog_degrades_unknown_enums():
    """白名单外的枚举值降级为默认值，不让整列表崩掉。"""
    worklog = row_to_worklog(_row(kind="weird", status="archived", source_type="ftp"))

    assert worklog.kind == "progress"
    assert worklog.status == "pending"
    assert worklog.source_type == "chat"


def test_row_to_worklog_tolerates_missing_optional_columns():
    """历史行缺可选列时按缺省值补齐，而不是 ValidationError。"""
    worklog = row_to_worklog(
        {
            "id": 7,
            "content": "x",
            "created_at": "2026-11-27T00:00:00",
            "updated_at": "2026-11-27T00:00:00",
        }
    )

    assert worklog.id == 7
    assert worklog.kind == "progress"
    assert worklog.status == "pending"
    assert worklog.session_id is None


# ======================================================================
# 服务：写入
# ======================================================================


def test_create_worklog_defaults_to_pending(worklog_service):
    """默认落 pending —— 人工确认前不算数。"""
    worklog = worklog_service.create_worklog("完成了登录页")

    assert worklog.status == "pending"
    assert worklog.kind == "progress"
    assert worklog.source_type == "manual"
    assert worklog.content == "完成了登录页"


def test_create_worklog_trims_content(worklog_service):
    """首尾空白被裁掉。"""
    worklog = worklog_service.create_worklog("  修好了导出  ")

    assert worklog.content == "修好了导出"


def test_create_worklog_rejects_empty_content(worklog_service):
    """空白正文不是有效记录。"""
    with pytest.raises(ValueError, match="content must not be empty"):
        worklog_service.create_worklog("   ")


def test_create_worklog_rejects_unknown_kind(worklog_service):
    """kind 走白名单校验。"""
    with pytest.raises(ValueError, match="invalid kind"):
        worklog_service.create_worklog("x", kind="whatever")


def test_create_worklog_rejects_unknown_source_type(worklog_service):
    """source_type 走白名单校验。"""
    with pytest.raises(ValueError, match="invalid source_type"):
        worklog_service.create_worklog("x", source_type="ftp")


def test_create_worklog_rejects_unknown_todo(worklog_service):
    """外键前置校验 —— todo_id 必须真实存在。"""
    with pytest.raises(ValueError, match="todo 4242 not found"):
        worklog_service.create_worklog("x", todo_id=4242)


# ======================================================================
# 服务：状态机
# ======================================================================


def test_confirm_worklog_moves_to_confirmed(worklog_service):
    """pending → confirmed。"""
    created = worklog_service.create_worklog("x")
    confirmed = worklog_service.confirm_worklog(created.id)

    assert confirmed is not None
    assert confirmed.status == "confirmed"


def test_dismiss_worklog_moves_to_dismissed(worklog_service):
    """pending → dismissed。"""
    created = worklog_service.create_worklog("x")
    dismissed = worklog_service.dismiss_worklog(created.id)

    assert dismissed is not None
    assert dismissed.status == "dismissed"


def test_confirm_unknown_worklog_returns_none(worklog_service):
    """不存在的 id 返回 None（而不是抛异常）。"""
    assert worklog_service.confirm_worklog(9999) is None
    assert worklog_service.dismiss_worklog(9999) is None


def test_dismiss_can_revoke_confirmed(worklog_service):
    """已确认的记录也能被撤回 —— 用户可以反悔。"""
    created = worklog_service.create_worklog("x")
    worklog_service.confirm_worklog(created.id)
    revoked = worklog_service.dismiss_worklog(created.id)

    assert revoked.status == "dismissed"


# ======================================================================
# 服务：更新与删除
# ======================================================================


def test_update_worklog_absent_key_leaves_column(worklog_service):
    """键缺席 = 不动该列。"""
    created = worklog_service.create_worklog("原文", kind="progress")
    updated = worklog_service.update_worklog(created.id, content="新文")

    assert updated.content == "新文"
    assert updated.kind == "progress"


def test_update_worklog_explicit_none_clears_column(worklog_service):
    """显式 null = 清空。"""
    created = worklog_service.create_worklog("原文", blocker="卡住了")
    updated = worklog_service.update_worklog(created.id, blocker=None)

    assert updated.blocker is None


def test_update_worklog_cannot_change_status(worklog_service):
    """status 不在可改白名单里 —— 状态迁移只能走 confirm/dismiss。"""
    created = worklog_service.create_worklog("原文")
    updated = worklog_service.update_worklog(created.id, status="confirmed")

    assert updated.status == "pending"


def test_update_worklog_rejects_empty_content(worklog_service):
    """正文不能被改成空串。"""
    created = worklog_service.create_worklog("原文")

    with pytest.raises(ValueError, match="content must not be empty"):
        worklog_service.update_worklog(created.id, content="   ")


def test_update_worklog_unknown_id_returns_none(worklog_service):
    """不存在的 id 返回 None。"""
    assert worklog_service.update_worklog(9999, content="x") is None


def test_delete_worklog(worklog_service):
    """删除返回是否真的删掉了东西。"""
    created = worklog_service.create_worklog("x")

    assert worklog_service.delete_worklog(created.id) is True
    assert worklog_service.delete_worklog(created.id) is False
    assert worklog_service.get_worklog(created.id) is None


# ======================================================================
# 服务：读取与筛选
# ======================================================================


def test_list_worklogs_orders_newest_first(worklog_service):
    """时间倒序 —— 最新的在最前。"""
    worklog_service.create_worklog("第一条")
    worklog_service.create_worklog("第二条")

    items = worklog_service.list_worklogs()

    assert [item.content for item in items] == ["第二条", "第一条"]


def test_list_worklogs_filters_by_status(worklog_service):
    """status 筛选。"""
    pending = worklog_service.create_worklog("待确认")
    confirmed = worklog_service.create_worklog("已确认")
    worklog_service.confirm_worklog(confirmed.id)

    items = worklog_service.list_worklogs(status="pending")

    assert [item.id for item in items] == [pending.id]


def test_list_worklogs_filters_by_kind(worklog_service):
    """kind 筛选。"""
    worklog_service.create_worklog("进展", kind="progress")
    worklog_service.create_worklog("阻塞", kind="blocker")

    items = worklog_service.list_worklogs(kind="blocker")

    assert [item.content for item in items] == ["阻塞"]


def test_list_worklogs_rejects_unknown_status(worklog_service):
    """非法 status 直接抛 ValueError —— 不静默放行。"""
    with pytest.raises(ValueError, match="invalid status"):
        worklog_service.list_worklogs(status="archived")


def test_list_worklogs_date_window_includes_whole_day(worklog_service):
    """日期窗含边界当天整日（from 含当天 00:00，to 含当天 24 点）。"""
    worklog_service.create_worklog("今天")

    same_day = worklog_service.list_worklogs(date_from=_today(), date_to=_today())
    other_day = worklog_service.list_worklogs(date_from=_yesterday(), date_to=_yesterday())

    assert len(same_day) == 1
    assert other_day == []


def test_list_worklogs_rejects_malformed_date(worklog_service):
    """非法日期格式抛 ValueError。"""
    with pytest.raises(ValueError, match="invalid date"):
        worklog_service.list_worklogs(date_from="not-a-date")


def test_count_worklogs_counts_all_matches(worklog_service):
    """total 数的是整个筛选集，不是当前页。"""
    for _ in range(3):
        worklog_service.create_worklog("x")

    assert worklog_service.count_worklogs() == 3
    assert worklog_service.count_worklogs(kind="progress") == 3
    assert worklog_service.count_worklogs(kind="done") == 0


def test_list_pending_returns_candidates(worklog_service):
    """收件箱只给待确认的候选。"""
    pending = worklog_service.create_worklog("待确认")
    confirmed = worklog_service.create_worklog("已确认")
    worklog_service.confirm_worklog(confirmed.id)

    items = worklog_service.list_pending()

    assert [item.id for item in items] == [pending.id]


def test_summarize_counts_only_confirmed(worklog_service):
    """统计快照只认已确认 —— 待确认候选绝不进报告。"""
    worklog_service.create_worklog("候选", kind="progress")
    confirmed = worklog_service.create_worklog("正式", kind="done")
    worklog_service.confirm_worklog(confirmed.id)

    summary = worklog_service.summarize()

    assert summary["total"] == 1
    assert summary["by_kind"]["done"] == 1
    assert summary["by_kind"]["progress"] == 0


def test_summarize_respects_date_window(worklog_service):
    """统计同样受日期窗约束。"""
    confirmed = worklog_service.create_worklog("正式", kind="done")
    worklog_service.confirm_worklog(confirmed.id)

    inside = worklog_service.summarize(date_from=_today(), date_to=_today())
    outside = worklog_service.summarize(date_from=_yesterday(), date_to=_yesterday())

    assert inside["total"] == 1
    assert outside["total"] == 0


def test_worklog_model_roundtrip(worklog_service):
    """落库再读回，模型字段保持一致。"""
    created = worklog_service.create_worklog(
        "推进了导出",
        kind="progress",
        progress_text="补了三个用例",
        project_tag="sage",
        session_id="sess-9",
    )

    fetched = worklog_service.get_worklog(created.id)

    assert fetched is not None
    assert fetched.progress_text == "补了三个用例"
    assert fetched.project_tag == "sage"
    assert fetched.session_id == "sess-9"
    assert isinstance(fetched, WorkLog)
