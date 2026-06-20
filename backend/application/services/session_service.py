"""SessionService — 编排会话生命周期用例 (PG-A1, hex 迁移第一刀)。

与 ChatService 的关系
---------------------

- ``ChatService`` 负责"一次对话轮次" (``run_turn`` 编排
  LLM / tools / memory)
- ``SessionService`` 负责"会话本身"的 CRUD + 审计 + 指标
- 后续 PR 将 ``ChatService.create_session`` / ``delete_session``
  委托给 ``SessionService`` 消除重复(本 PR 暂不动 ChatService,
  避免 scope 蔓延)

设计要点
--------

- **不依赖具体 adapter**:仅通过 ``backend.ports.*`` 中的
  ``Protocol`` 类型与外部能力交互;具体实现 (SqliteStorageAdapter / ...)
  由 API 路由层在装配时注入。
- **可观测性内置**:与 ChatService 同一套 OTel / 事件 / 指标
  模板,便于 Grafana 面板统一消费。
- **错误透传**:会话不存在抛 ``SessionNotFoundError`` (domain),
  由 API 路由层翻译为 HTTP 404。
"""

from __future__ import annotations

from typing import Any

from sage_core.exceptions import SessionNotFoundError
from sage_core import Message
from sage_core.repositories import EventPort, MetricPort
from sage_core.repositories import StoragePort
from backend.utils.otel import get_tracer

# 9 指标之一(与 chat_service.py 的 _ACTIVE_SESSIONS_METRIC 保持同源)
_ACTIVE_SESSIONS_METRIC = "sage_active_sessions"

# OTel tracer(P3.3:用于在 span 上记录关键属性)
_tracer = get_tracer("session_service")


def _message_to_dict(m: Message) -> dict[str, Any]:
    """``domain.Message`` → API 响应 dict(供 list_messages 等端点用)。

    比 ``dataclasses.asdict`` 多一层:把 ``Role`` 枚举转字符串、把
    ``ToolCall`` 列表转简化 dict,JSON 友好。
    """
    return {
        "role": m.role.value,
        "content": m.content,
        "tool_calls": [
            {"name": tc.name, "args": tc.args, "id": tc.id} for tc in m.tool_calls
        ],
        "tool_call_id": m.tool_call_id,
    }


class SessionService:
    """会话生命周期用例编排。

    6 个方法对应 hex 路由的 6 个端点:

    +-------------------+-----------------------------+------------------------+
    | 方法              | 路由端点                    | 行为                   |
    +===================+=============================+========================+
    | create_session    | POST   /sessions            | 创建 + 审计 + 指标 +1  |
    | list_sessions     | GET    /sessions            | 列出(分页)             |
    | get_session       | GET    /sessions/{id}       | 单个(None→404)         |
    | update_session    | PATCH  /sessions/{id}       | 局部更新(空 body 也行)|
    | delete_session    | DELETE /sessions/{id}       | 删除(返 bool)          |
    | list_messages     | GET    /sessions/{id}/...   | 列出消息(转 dict)      |
    +-------------------+-----------------------------+------------------------+
    """

    def __init__(
        self,
        storage: StoragePort,
        metrics: MetricPort,
        events: EventPort,
    ) -> None:
        self.storage = storage
        self.metrics = metrics
        self.events = events
        # 当前活跃 session 计数(用于 sage_active_sessions gauge)
        self._active_session_count: int = 0

    # ------------------------------------------------------------------ #
    # 会话 CRUD
    # ------------------------------------------------------------------ #

    async def create_session(self, title: str = "") -> str:
        """创建会话 → 返 ID;emit ``session_created`` 审计 + active_sessions gauge +1。

        P3.2 引入:业务方应通过本方法建会话,而不是直接调
        ``self.storage.create_session``,确保审计与指标埋点不被遗漏。

        P3.3 增强:包一层 OTel span ``session.create``。
        """
        with _tracer.start_as_current_span("session.create") as span:
            session_id = await self.storage.create_session(title=title)
            span.set_attribute("session.id", session_id)
            # 审计事件:与 spec § 6.1 5 类事件对齐
            self.events.emit(
                "session_created",
                {"session_id": session_id, "title": title},
            )
            # 9 指标之一:active_sessions gauge(set 绝对值)
            self._active_session_count += 1
            self.metrics.gauge(
                _ACTIVE_SESSIONS_METRIC,
                float(self._active_session_count),
                {},
            )
            return session_id

    async def list_sessions(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """列出会话;offset/limit 仅做分页(底层 storage 暂不支持,先 in-mem 切片)。"""
        all_sessions = await self.storage.list_sessions()
        return all_sessions[offset : offset + limit]

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        """取单个会话;不存在返 ``None``(路由层映射 404)。"""
        return await self.storage.get_session(session_id)

    async def update_session(
        self,
        session_id: str,
        *,
        title: str | None = None,
        is_pinned: bool | None = None,
    ) -> dict[str, Any]:
        """局部更新会话字段;全 ``None`` 等于 no-op(返当前快照)。

        Args:
            session_id: 目标会话 ID
            title:      新标题;``None`` 表示不更新
            is_pinned:  置顶标志;``None`` 表示不更新

        Returns:
            更新后(或当前)的会话字典

        Raises:
            SessionNotFoundError: 会话不存在
        """
        # 先确认存在(用 get 而不是 update,这样空 body 也走"返当前"路径)
        current = await self.storage.get_session(session_id)
        if current is None:
            raise SessionNotFoundError(session_id)

        # 收集非 None 字段
        fields: dict[str, Any] = {}
        if title is not None:
            fields["title"] = title
        if is_pinned is not None:
            fields["is_pinned"] = is_pinned

        if fields:
            await self.storage.update_session(session_id, **fields)
            refreshed = await self.storage.get_session(session_id)
            if refreshed is not None:
                return refreshed
        return current

    async def delete_session(self, session_id: str) -> bool:
        """删除会话;返是否真删了 (``False`` = 会话不存在)。

        与 ChatService 现有 ``delete_session`` 的差异:本方法依赖
        storage 返回的 rowcount 决定是否扣减 active_sessions
        计数,避免误减到负数(参见 test_active_sessions_counter_
        does_not_go_negative)。
        """
        rowcount = await self.storage.delete_session(session_id)
        if rowcount == 0:
            return False
        self._active_session_count = max(0, self._active_session_count - 1)
        self.metrics.gauge(
            _ACTIVE_SESSIONS_METRIC,
            float(self._active_session_count),
            {},
        )
        return True

    async def list_messages(
        self,
        session_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """列出会话消息(转 dict 格式供 API);offset/limit in-mem 切片。

        底层 storage.get_messages 已带 limit;本方法先取较大窗口
        (10 000)再切片,符合"返回按时间正序"语义。
        """
        all_msgs = await self.storage.get_messages(session_id, limit=10_000)
        sliced = all_msgs[offset : offset + limit]
        return [_message_to_dict(m) for m in sliced]
