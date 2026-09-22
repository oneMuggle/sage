# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""会话事件日志 → LLM 请求历史投影（DSH 对标 R1，SE1）。

对标 deepseek-harness 的 "Model-visible ⟺ logged"：模型可见历史是
事件日志的**投影**，而非对可变存储的反复重建。本轮（SE1）投影与
既有的 ``history_context.db_rows_to_history`` 并行存在且语义逐条对齐
—— parity 测试守门；SE2 切换 ``history_context`` 读取路径后，
``db_rows_to_history`` 退役。

对数据库保持纯净：只接收 :class:`~backend.data.session_event_repo.SessionEvent`
对象 / dict，不触碰 SQLite；LLM 调用为零。
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

from backend.data.session_event_repo import (
    EVENT_COMPACTION_PERFORMED,
    EVENT_MESSAGE_APPENDED,
    EVENT_MESSAGE_DELETED,
)

#: 进入请求的历史角色白名单 —— 与 history_context._HISTORY_ROLES 保持一致。
_HISTORY_ROLES = ("user", "assistant")


def _event_payload(event: Any) -> Dict[str, Any]:
    """统一读取 SessionEvent 对象 / dict 的 payload（dict 形态）。"""
    payload = (
        event.get("payload") if isinstance(event, dict) else getattr(event, "payload", None)
    )
    return payload if isinstance(payload, dict) else {}


def _event_type(event: Any) -> str:
    if isinstance(event, dict):
        return str(event.get("type") or "")
    return str(getattr(event, "type", None) or "")


def events_to_history(events: Sequence[Any]) -> List[Dict[str, str]]:
    """把 session_events 投影成请求用 ``{"role", "content"}`` 列表。

    语义与 ``history_context.db_rows_to_history`` 逐条对齐（parity 契约，
    含压缩后的会话）：

    - **删除/压缩折叠**：``message.deleted`` 事件宣告的 id 与
      ``compaction.performed`` 携带的 ``deleted_ids`` 都不进投影 ——
      事件日志保持完整（append-only），投影只呈现"当前视图"，
      与 messages 表现状一致；
    - 段感知切片：最后一条 ``subtype='topic_separator'`` 的
      ``message.appended`` 事件之后才入投影（与 get_active_segment /
      db_rows_to_history 同逻辑，双保险）；
    - 只认 ``message.appended`` 事件产生历史消息，其余类型仅参与折叠；
    - 只保留 ``user`` / ``assistant`` 角色；
    - ``tool_calls`` 非空的 assistant 事件跳过（裸 ReAct 中间态，重放
      进请求缺 tool 结果配对会被 API 拒绝）；
    - 空 / 纯空白 content 跳过。
    """
    # 第一遍：收集压缩/删除事件宣告排除的消息 id（session 级永久排除 ——
    # append-only 日志里 id 不会复用，集合语义安全）
    excluded_ids = set()
    for event in events:
        event_type = _event_type(event)
        payload = _event_payload(event)
        if event_type == EVENT_COMPACTION_PERFORMED:
            deleted = payload.get("deleted_ids")
            if isinstance(deleted, (list, tuple)):  # noqa: UP038 — py38 运行时 isinstance 不支持 X | Y
                excluded_ids.update(str(x) for x in deleted)
        elif event_type == EVENT_MESSAGE_DELETED:
            if payload.get("id") is not None:
                excluded_ids.add(str(payload["id"]))

    # 段感知：找到最后一个 topic_separator 消息事件，只保留之后的行。
    # 已被删除/压缩排除的 separator 不参与切段（retreat_segment 撤销分段
    # 后，投影必须回到未切段视图）。
    last_sep_idx = -1
    for i in range(len(events) - 1, -1, -1):
        if _event_type(events[i]) != EVENT_MESSAGE_APPENDED:
            continue
        payload_i = _event_payload(events[i])
        if payload_i.get("subtype") != "topic_separator":
            continue
        if str(payload_i.get("id")) in excluded_ids:
            continue
        last_sep_idx = i
        break
    events = events[last_sep_idx + 1:]

    history: List[Dict[str, str]] = []
    for event in events:
        if _event_type(event) != EVENT_MESSAGE_APPENDED:
            continue
        payload = _event_payload(event)
        # 已被删除/压缩折叠的消息不进当前视图
        if str(payload.get("id")) in excluded_ids:
            continue
        # 防御性：即使未先切片，也不允许 separator 进入请求
        if payload.get("subtype") == "topic_separator":
            continue
        role = str(payload.get("role") or "").strip()
        if role not in _HISTORY_ROLES:
            continue
        if payload.get("tool_calls"):
            continue
        content = payload.get("content")
        if content is None or not str(content).strip():
            continue
        history.append({"role": role, "content": str(content)})
    return history


__all__ = ["events_to_history"]
