"""唤醒领域模型（纯，零外部依赖）。

A4 Suspend-Resume：把 always-on 的 agent 会话改造成挂起/恢复（事件驱动，
空闲零成本）。会话挂起时注册一条 ``Wake`` 记录，运行时在条件满足时
（定时器到期 / 后台任务完成 / 命名事件触发）重新唤起该会话。

三种触发类型（对齐 OpenWorker ``selfwake.py`` 的语义）：

- ``TIMER``      —— ``sleep_for`` / ``sleep_until`` 注册的定时唤醒
- ``COMPLETION`` —— ``wake_on(job_id)`` 注册，后台任务退出时触发
- ``EVENT``      —— 命名事件（connector / webhook）触发，Phase 3 预留

状态机::

    PENDING ──(timer 到期 / complete_job / fire_event)──▶ DUE ──(scheduler 消费)──▶ FIRED

    TIMER 类型可长期停留在 PENDING（到 ``fire_at`` 为止由 scheduler tick
    直接判定为到期）；COMPLETION / EVENT 类型先被外部信号标记为 DUE，
    再由 scheduler tick 消费。FIRED 为终态。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


def utc_now_iso() -> str:
    """当前 UTC 时间的 ISO-8601 字符串（统一 ``+00:00`` 后缀）。

    WakeStore 依赖统一格式做字符串字典序比较 —— 所有时间戳必须经
    ``to_utc_iso`` / 本函数归一化，禁止混用 ``Z`` 后缀或 naive 时间。
    """
    return to_utc_iso(datetime.now(timezone.utc))  # noqa: UP017


def to_utc_iso(when: datetime) -> str:
    """把任意 datetime 归一化为 UTC ISO-8601 字符串。

    naive datetime 按 UTC 解释（与 OpenWorker 行为一致）。
    """
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)  # noqa: UP017
    return when.astimezone(timezone.utc).isoformat()  # noqa: UP017


class WakeKind(str, Enum):
    """唤醒触发类型。"""

    TIMER = "timer"  # 定时唤醒（fire_at）
    COMPLETION = "completion"  # 后台任务完成（job_id）
    EVENT = "event"  # 命名事件触发（event_key）


class WakeState(str, Enum):
    """唤醒生命周期状态。"""

    PENDING = "pending"  # 已注册，条件未满足
    DUE = "due"  # 条件已满足，等待 scheduler 消费
    FIRED = "fired"  # 已被 scheduler 消费（终态）


@dataclass(frozen=True)
class Wake:
    """一条挂起会话的唤醒记录（不可变，状态迁移返回新实例）。

    Attributes:
        id:         全局唯一 ID（uuid4 hex）
        session_id: 挂起的会话 ID（恢复时在此会话注入新一轮对话）
        kind:       触发类型
        state:      生命周期状态
        fire_at:    UTC ISO-8601 触发时间（仅 TIMER）
        job_id:     监听的后台任务 ID（仅 COMPLETION）
        event_key:  监听的命名事件（仅 EVENT）
        note:       agent 留下的唤醒备注（恢复时注入对话上下文）
        created_at: 注册时间（UTC ISO-8601）
        fired_at:   消费时间（UTC ISO-8601，FIRED 后填充）
    """

    id: str
    session_id: str
    kind: WakeKind
    state: WakeState = WakeState.PENDING
    fire_at: Optional[str] = None
    job_id: Optional[str] = None
    event_key: Optional[str] = None
    note: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    fired_at: Optional[str] = None

    # ------------------------------------------------------------------ #
    # 工厂
    # ------------------------------------------------------------------ #

    @classmethod
    def create(
        cls,
        session_id: str,
        kind: WakeKind,
        *,
        fire_at: Optional[str] = None,
        job_id: Optional[str] = None,
        event_key: Optional[str] = None,
        note: str = "",
    ) -> Wake:
        """生成带新 uuid 的 Wake，并按 kind 校验必要字段。

        Raises:
            ValueError: kind 所需字段缺失（TIMER 无 fire_at 等）。
        """
        if kind is WakeKind.TIMER and not fire_at:
            raise ValueError("TIMER wake requires fire_at")
        if kind is WakeKind.COMPLETION and not job_id:
            raise ValueError("COMPLETION wake requires job_id")
        if kind is WakeKind.EVENT and not event_key:
            raise ValueError("EVENT wake requires event_key")
        return cls(
            id=uuid.uuid4().hex,
            session_id=session_id,
            kind=kind,
            fire_at=fire_at,
            job_id=job_id,
            event_key=event_key,
            note=note,
        )

    # ------------------------------------------------------------------ #
    # 状态迁移（不可变：返回新实例）
    # ------------------------------------------------------------------ #

    def mark_due(self) -> Wake:
        """PENDING → DUE（条件已满足，等待 scheduler 消费）。"""
        if self.state is not WakeState.PENDING:
            raise ValueError(
                f"wake {self.id} cannot transition {self.state.value} → due"
            )
        return replace(self, state=WakeState.DUE)

    def mark_fired(self, fired_at: Optional[str] = None) -> Wake:
        """PENDING / DUE → FIRED（scheduler 已消费，终态）。"""
        if self.state is WakeState.FIRED:
            raise ValueError(f"wake {self.id} already fired")
        return replace(self, state=WakeState.FIRED, fired_at=fired_at or utc_now_iso())

    @property
    def is_fired(self) -> bool:
        return self.state is WakeState.FIRED
