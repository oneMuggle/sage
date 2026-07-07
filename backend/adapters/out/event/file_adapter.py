"""File event adapter — 5 类审计事件。

spec § 6.1 定义的 5 类审计事件：chat_message_sent / chat_response_completed /
tool_invoked / session_created / settings_changed，全部落盘到
``backend/data/audit/audit.jsonl``（每行一个 JSON）。
"""

from __future__ import annotations
from typing import Dict, List

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.domain.agent_event import envelope


class AuditEventType:
    """5 类审计事件常量（spec § 6.1）。

    用法：
        events.emit(AuditEventType.CHAT_MESSAGE_SENT, {"session_id": "..."})
    """

    CHAT_MESSAGE_SENT = "chat_message_sent"
    CHAT_RESPONSE_COMPLETED = "chat_response_completed"
    TOOL_INVOKED = "tool_invoked"
    SESSION_CREATED = "session_created"
    SETTINGS_CHANGED = "settings_changed"

    # M1 run-lifecycle 事件（claw-code 式 run_start→run_end 序列）。
    # 不并入 all()：all() 仍是审计 spec §6.1 的 5 类。
    RUN_START = "run_start"
    TURN_START = "turn_start"
    LLM_CALL = "llm_call"
    TOOL_RESULT = "tool_result"
    RUN_END = "run_end"

    @classmethod
    def all(cls) -> List[str]:
        """返回全部 5 类审计事件名（便于测试断言、CI 门禁 grep）。"""
        return [
            cls.CHAT_MESSAGE_SENT,
            cls.CHAT_RESPONSE_COMPLETED,
            cls.TOOL_INVOKED,
            cls.SESSION_CREATED,
            cls.SETTINGS_CHANGED,
        ]

    @classmethod
    def run_lifecycle(cls) -> List[str]:
        """返回 run-lifecycle 事件名（run_start → run_end 顺序）。"""
        return [
            cls.RUN_START,
            cls.TURN_START,
            cls.LLM_CALL,
            cls.TOOL_RESULT,
            cls.RUN_END,
        ]


class FileEventAdapter:
    """EventPort 的文件实现：每个事件一行 JSON。"""

    def __init__(self, log_path: str = "backend/data/audit/audit.jsonl") -> None:
        self._log_path = Path(log_path)
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        event = envelope(event_type, payload, ts=datetime.now().isoformat())
        with self._log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
