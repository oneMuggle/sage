# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""活跃聊天流事件汇（C2a，DSH 对标 R24）。

``legacy_routes.chat_stream_create`` 此前内联定义四个事件推送闭包
（agent 桥 / todo 快照 / 产物 / 工作区），共享同一形态：**会话过滤 +
``queue.put_nowait`` + 满/关闭静默降级**。本模块把它们收敛为一个
:class:`StreamEventSink`：

- **生命周期对称**：``register()`` / ``unregister()`` 一对一注册注销
  四路监听（闭包持有 queue 引用，不注销会向已关闭的流推送 / 随全局
  listener 表泄漏）；
- **会话过滤**：todo / artifact / workspace 按 session_id 过滤防跨流
  串扰；agent 桥由注册表按 session_id 寻址，无需再过滤；
- **降级铁律**：任何推送失败只 debug 日志，绝不阻塞工具 / 任务线程。

对 FastAPI 零依赖（构造参数只有 queue + session_id），可完整单测。
"""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class StreamEventSink:
    """四路事件 → 活跃流队列投影（行为与原内联闭包逐字节等价）。"""

    def __init__(self, queue: Any, session_id: str) -> None:
        self._queue = queue
        self._session_id = session_id

    # ---- 推送原语（会话过滤 + put_nowait + 静默降级） ---------------------

    def _put(self, event: Any, what: str) -> None:
        try:
            self._queue.put_nowait(event)
        except Exception:  # noqa: BLE001 — 队列满/关闭不阻塞执行
            logger.debug("%s 推送失败（队列满/关闭），忽略", what)

    def emit_agent_bridge(self, event: Dict[str, Any]) -> None:
        """live-events P2：agent 工具事件桥投影（注册表按会话寻址）。"""
        self._put(event, "agent 事件桥")

    def push_todo_snapshot(self, session_id: str, todos: Any) -> None:
        """P1 todo 接线：todo_write 变更 → 全量快照（按会话过滤）。"""
        if session_id != self._session_id:
            return
        self._put(
            {
                "state": "todo_snapshot",
                "session_id": session_id,
                "todos": todos,
            },
            "todo_snapshot",
        )

    def push_artifact(self, event: Dict[str, Any]) -> None:
        """S7：工具产物落库广播 → 活跃流（按会话过滤）。"""
        if event.get("session_id") != self._session_id:
            return
        self._put(event, "artifact_created")

    def push_workspace(self, event: Dict[str, Any]) -> None:
        """right-panel R5：写文件工具落盘 → 活跃流（按会话过滤）。"""
        if event.get("session_id") != self._session_id:
            return
        self._put(event, "workspace_changed")

    async def push_persisted_todo(self) -> None:
        """B4：流启动时推送持久化 todo 快照（重启/重开会话任务板不空）。

        与实时推送不同：这里 ``await put``（启动路径背压可接受，保序）。"""
        try:
            from backend.tools.todo_state import get_todo_store

            persisted = get_todo_store().get(self._session_id)
            if persisted:
                await self._queue.put(
                    {
                        "state": "todo_snapshot",
                        "session_id": self._session_id,
                        "todos": persisted,
                    }
                )
        except Exception:  # noqa: BLE001 — 降级铁律
            logger.debug("todo_snapshot 初始推送失败（忽略）")

    # ---- 生命周期（与原注册/注销块等价；注销无条件，语义不变） -----------

    def register(self) -> None:
        """注册四路监听（模块延迟导入，与原实现同口径）。"""
        from backend.data.artifact_repo import add_artifact_listener
        from backend.data.workspace_events import add_workspace_listener
        from backend.tools.agent_event_bridge import register_stream_emitter
        from backend.tools.todo_state import add_todo_listener

        register_stream_emitter(self._session_id, self.emit_agent_bridge)
        add_todo_listener(self.push_todo_snapshot)
        add_artifact_listener(self.push_artifact)
        add_workspace_listener(self.push_workspace)

    def unregister(self) -> None:
        """注销四路监听（无条件调用，与原 finally 块语义一致）。"""
        from backend.data.artifact_repo import remove_artifact_listener
        from backend.data.workspace_events import remove_workspace_listener
        from backend.tools.agent_event_bridge import unregister_stream_emitter
        from backend.tools.todo_state import remove_todo_listener

        remove_artifact_listener(self.push_artifact)
        remove_workspace_listener(self.push_workspace)
        remove_todo_listener(self.push_todo_snapshot)
        unregister_stream_emitter(self._session_id)
