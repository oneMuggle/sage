"""M1 结构化可观测性 — Agent 事件信封（schema + format_version）。

claw-code ``concept.md`` §4 原则 3「Agent 可观测」：事件带 ``schema`` 与
``format_version``，run 级事件带 ``run_id`` + 单调 ``seq``。

本模块提供：
- 常量 ``AGENT_EVENT_SCHEMA`` / ``AGENT_EVENT_FORMAT_VERSION``。
- ``envelope()``：给任意 (event_type, payload) 包一层版本化信封，供 EventPort
  适配器落盘/输出时统一调用（向后兼容——只增字段，保留 ts/type/payload）。
- ``RunEventScope``：一次 run 的事件作用域，分配稳定 run_id 并自增 seq。

**领域纯净性**：本模块不读时钟（``datetime.now`` 属 I/O，归适配器边界）。
``ts`` 由调用方（file/stdout 适配器）生成后传入。
"""

from __future__ import annotations

from typing import Any, Dict, Protocol

AGENT_EVENT_SCHEMA = "sage.agent.event"
AGENT_EVENT_FORMAT_VERSION = 1


def envelope(event_type: str, payload: Dict[str, Any], *, ts: str) -> Dict[str, Any]:
    """把事件包成版本化信封。

    输出形状（每行审计/流事件的统一形状）::

        {"schema": ..., "format_version": ..., "ts": ..., "type": ..., "payload": {...}}

    ``ts`` 为 iso8601 字符串，由适配器边界生成后传入（领域层不读时钟）。
    """
    return {
        "schema": AGENT_EVENT_SCHEMA,
        "format_version": AGENT_EVENT_FORMAT_VERSION,
        "ts": ts,
        "type": event_type,
        "payload": payload,
    }


class _EventSink(Protocol):
    def emit(self, event_type: str, payload: Dict[str, Any]) -> None: ...


class RunEventScope:
    """一次 run 的事件作用域：稳定 run_id + 单调 seq。

    用法::

        scope = RunEventScope(events, run_id)
        scope.emit("run_start", model="gpt-x")
        scope.emit("run_end", status="ok")
    """

    def __init__(self, events: _EventSink, run_id: str) -> None:
        self._events = events
        self._run_id = run_id
        self._seq = 0

    @property
    def run_id(self) -> str:
        return self._run_id

    def emit(self, event_type: str, **data: Any) -> int:
        """发一个 run 级事件，返回本次 seq。payload 恒含 run_id + seq。"""
        seq = self._seq
        self._seq += 1
        self._events.emit(event_type, {"run_id": self._run_id, "seq": seq, **data})
        return seq
