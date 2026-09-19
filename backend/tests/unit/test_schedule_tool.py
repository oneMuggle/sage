"""LLM 定时任务工具三件套单测（feat/llm-schedule-tool）。

覆盖：
- ``schedule_task``：recurring(cron) / once(ISO-8601 与 epoch ms) 创建成功；
  无效 cron / 过去时间 / 缺参 → 可读错误；无工具上下文 → 显式报错；
- ``list_scheduled_tasks``：只列当前会话任务；
- ``cancel_scheduled_task``：取消本会话任务；拒绝跨会话删除；未知 id 报错。

工具直接复用真实的 ``SchedulerService``（tmp_path JSON 持久化 + mock repo），
借此锁定"工具与 UI 共用同一调度事实源"这一核心设计约束。
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.services.scheduler import SchedulerService
from backend.tools.context import (
    ToolExecutionContext,
    reset_tool_context,
    set_tool_context,
)
from backend.tools.schedule_tool import (
    CancelScheduledTaskTool,
    ListScheduledTasksTool,
    ScheduleTaskTool,
)

pytestmark = pytest.mark.unit

SESSION_A = "sess-alpha"
SESSION_B = "sess-beta"


@pytest.fixture()
def message_repo() -> MagicMock:
    repo = MagicMock()
    repo.insert = MagicMock(return_value={"id": "msg-1"})
    return repo


@pytest.fixture()
def session_repo() -> MagicMock:
    repo = MagicMock()
    repo.exists = MagicMock(return_value=True)
    return repo


@pytest.fixture()
def service(tmp_path: Path, message_repo: MagicMock, session_repo: MagicMock) -> SchedulerService:
    return SchedulerService(
        store_path=tmp_path / "scheduled_tasks.json",
        message_repo=message_repo,
        session_repo=session_repo,
    )


def _bind_session(session_id: str):
    """Bind a ToolExecutionContext for the current task; returns reset token."""
    return set_tool_context(
        ToolExecutionContext(
            session_id=session_id,
            stream_id="stream-1",
            binding_generation=0,
            office_doc_scope=frozenset(),
        )
    )


def _future_iso(minutes: int = 30) -> str:
    return (datetime.now() + timedelta(minutes=minutes)).isoformat()


class TestScheduleTaskTool:
    def test_recurring_cron_creates_task_bound_to_current_session(
        self, service: SchedulerService
    ) -> None:
        token = _bind_session(SESSION_A)
        try:
            tool = ScheduleTaskTool(service_getter=lambda: service)
            result = tool.execute(
                name="检查部署",
                prompt="检查部署状态并报告变化",
                schedule_kind="recurring",
                cron="*/5 * * * *",
            )
        finally:
            reset_tool_context(token)

        assert result.success is True
        tasks = service.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].session_id == SESSION_A
        assert tasks[0].type == "recurring"
        assert tasks[0].schedule == {"kind": "recurring", "cron": "*/5 * * * *"}
        assert tasks[0].id in str(result.output)

    def test_once_accepts_iso8601_string(self, service: SchedulerService) -> None:
        token = _bind_session(SESSION_A)
        try:
            tool = ScheduleTaskTool(service_getter=lambda: service)
            result = tool.execute(
                name="提交报告",
                prompt="提醒提交报告",
                schedule_kind="once",
                at=_future_iso(),
            )
        finally:
            reset_tool_context(token)

        assert result.success is True
        task = service.list_tasks()[0]
        assert task.type == "once"
        assert task.schedule["kind"] == "once"
        assert isinstance(task.schedule["at"], int)

    def test_once_accepts_epoch_millis(self, service: SchedulerService) -> None:
        token = _bind_session(SESSION_A)
        try:
            tool = ScheduleTaskTool(service_getter=lambda: service)
            at_ms = int(time.time() * 1000) + 600_000
            result = tool.execute(
                name="提醒", prompt="提醒内容", schedule_kind="once", at=at_ms
            )
        finally:
            reset_tool_context(token)

        assert result.success is True
        assert service.list_tasks()[0].schedule["at"] == at_ms

    def test_invalid_cron_returns_readable_error(self, service: SchedulerService) -> None:
        token = _bind_session(SESSION_A)
        try:
            tool = ScheduleTaskTool(service_getter=lambda: service)
            result = tool.execute(
                name="坏任务", prompt="x", schedule_kind="recurring", cron="not-a-cron"
            )
        finally:
            reset_tool_context(token)

        assert result.success is False
        assert "cron" in (result.error or "").lower()
        assert service.list_tasks() == []

    def test_past_once_timestamp_returns_error(self, service: SchedulerService) -> None:
        token = _bind_session(SESSION_A)
        try:
            tool = ScheduleTaskTool(service_getter=lambda: service)
            past = (datetime.now() - timedelta(minutes=5)).isoformat()
            result = tool.execute(
                name="过期", prompt="x", schedule_kind="once", at=past
            )
        finally:
            reset_tool_context(token)

        assert result.success is False
        assert service.list_tasks() == []

    def test_missing_cron_for_recurring_returns_error(self, service: SchedulerService) -> None:
        token = _bind_session(SESSION_A)
        try:
            tool = ScheduleTaskTool(service_getter=lambda: service)
            result = tool.execute(name="缺参", prompt="x", schedule_kind="recurring")
        finally:
            reset_tool_context(token)

        assert result.success is False

    def test_without_tool_context_returns_error(self, service: SchedulerService) -> None:
        tool = ScheduleTaskTool(service_getter=lambda: service)
        result = tool.execute(
            name="无会话", prompt="x", schedule_kind="recurring", cron="*/5 * * * *"
        )
        assert result.success is False
        assert "会话" in (result.error or "")

    def test_missing_service_returns_readable_error(self) -> None:
        token = _bind_session(SESSION_A)
        try:
            tool = ScheduleTaskTool(service_getter=lambda: None)
            result = tool.execute(
                name="无服务", prompt="x", schedule_kind="recurring", cron="*/5 * * * *"
            )
        finally:
            reset_tool_context(token)

        assert result.success is False

    def test_once_accepts_z_suffix_iso(self, service: SchedulerService) -> None:
        token = _bind_session(SESSION_A)
        try:
            tool = ScheduleTaskTool(service_getter=lambda: service)
            at = (datetime.now() + timedelta(minutes=15)).isoformat() + "Z"
            result = tool.execute(
                name="UTC 后缀", prompt="x", schedule_kind="once", at=at
            )
        finally:
            reset_tool_context(token)

        assert result.success is True
        assert isinstance(service.list_tasks()[0].schedule["at"], int)

    def test_bool_at_is_rejected(self, service: SchedulerService) -> None:
        token = _bind_session(SESSION_A)
        try:
            tool = ScheduleTaskTool(service_getter=lambda: service)
            result = tool.execute(
                name="布尔", prompt="x", schedule_kind="once", at=True
            )
        finally:
            reset_tool_context(token)

        assert result.success is False
        assert service.list_tasks() == []

    def test_out_of_range_epoch_is_rejected_without_persisting(
        self, service: SchedulerService
    ) -> None:
        """越界 epoch 必须在落盘前被拦下 —— 否则任务留在 JSON 里调度失败，
        且重启时 SchedulerService 构造抛 ValueError，后端起不来。"""
        token = _bind_session(SESSION_A)
        try:
            tool = ScheduleTaskTool(service_getter=lambda: service)
            result = tool.execute(
                name="越界", prompt="x", schedule_kind="once", at=99999999999999999
            )
        finally:
            reset_tool_context(token)

        assert result.success is False
        assert service.list_tasks() == []

    def test_explicit_other_session_is_refused(self, service: SchedulerService) -> None:
        token = _bind_session(SESSION_A)
        try:
            tool = ScheduleTaskTool(service_getter=lambda: service)
            result = tool.execute(
                name="越权",
                prompt="x",
                schedule_kind="recurring",
                cron="0 * * * *",
                session_id=SESSION_B,
            )
        finally:
            reset_tool_context(token)

        assert result.success is False
        assert service.list_tasks() == []

    def test_explicit_same_session_is_allowed(self, service: SchedulerService) -> None:
        token = _bind_session(SESSION_A)
        try:
            tool = ScheduleTaskTool(service_getter=lambda: service)
            result = tool.execute(
                name="同名会话",
                prompt="x",
                schedule_kind="recurring",
                cron="0 * * * *",
                session_id=SESSION_A,
            )
        finally:
            reset_tool_context(token)

        assert result.success is True
        assert service.list_tasks()[0].session_id == SESSION_A


class TestListScheduledTasksTool:
    def test_lists_only_current_session(self, service: SchedulerService) -> None:
        # 会话 A 建一个
        token = _bind_session(SESSION_A)
        try:
            ScheduleTaskTool(service_getter=lambda: service).execute(
                name="A 任务", prompt="pa", schedule_kind="recurring", cron="0 * * * *"
            )
        finally:
            reset_tool_context(token)
        # 会话 B 建一个
        token = _bind_session(SESSION_B)
        try:
            ScheduleTaskTool(service_getter=lambda: service).execute(
                name="B 任务", prompt="pb", schedule_kind="recurring", cron="0 * * * *"
            )
        finally:
            reset_tool_context(token)

        token = _bind_session(SESSION_A)
        try:
            result = ListScheduledTasksTool(service_getter=lambda: service).execute()
        finally:
            reset_tool_context(token)

        assert result.success is True
        assert "A 任务" in str(result.output)
        assert "B 任务" not in str(result.output)

    def test_empty_list_is_success(self, service: SchedulerService) -> None:
        token = _bind_session(SESSION_A)
        try:
            result = ListScheduledTasksTool(service_getter=lambda: service).execute()
        finally:
            reset_tool_context(token)

        assert result.success is True

    def test_explicit_other_session_is_refused(self, service: SchedulerService) -> None:
        token = _bind_session(SESSION_A)
        try:
            result = ListScheduledTasksTool(service_getter=lambda: service).execute(
                session_id=SESSION_B
            )
        finally:
            reset_tool_context(token)

        assert result.success is False


class TestCancelScheduledTaskTool:
    def test_cancel_own_task(self, service: SchedulerService) -> None:
        token = _bind_session(SESSION_A)
        try:
            created = ScheduleTaskTool(service_getter=lambda: service).execute(
                name="待取消", prompt="x", schedule_kind="recurring", cron="0 * * * *"
            )
            task_id = service.list_tasks()[0].id
            result = CancelScheduledTaskTool(service_getter=lambda: service).execute(
                task_id=task_id
            )
        finally:
            reset_tool_context(token)

        assert created.success is True
        assert result.success is True
        assert service.list_tasks() == []

    def test_cancel_other_session_task_is_refused(self, service: SchedulerService) -> None:
        token = _bind_session(SESSION_A)
        try:
            ScheduleTaskTool(service_getter=lambda: service).execute(
                name="A 私有", prompt="x", schedule_kind="recurring", cron="0 * * * *"
            )
            task_id = service.list_tasks()[0].id
        finally:
            reset_tool_context(token)

        token = _bind_session(SESSION_B)
        try:
            result = CancelScheduledTaskTool(service_getter=lambda: service).execute(
                task_id=task_id
            )
        finally:
            reset_tool_context(token)

        assert result.success is False
        assert len(service.list_tasks()) == 1

    def test_cancel_unknown_id_returns_error(self, service: SchedulerService) -> None:
        token = _bind_session(SESSION_A)
        try:
            result = CancelScheduledTaskTool(service_getter=lambda: service).execute(
                task_id="task-does-not-exist"
            )
        finally:
            reset_tool_context(token)

        assert result.success is False
