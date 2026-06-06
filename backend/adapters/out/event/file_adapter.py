"""File event adapter — 5 类审计事件。

spec § 6.1 定义的 5 类审计事件：chat_message_sent / chat_response_completed /
tool_invoked / session_created / settings_changed，全部落盘到
``backend/data/audit/audit.jsonl``（每行一个 JSON）。
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any


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

    @classmethod
    def all(cls) -> list[str]:
        """返回全部 5 类事件名（便于测试断言、CI 门禁 grep）。"""
        return [
            cls.CHAT_MESSAGE_SENT,
            cls.CHAT_RESPONSE_COMPLETED,
            cls.TOOL_INVOKED,
            cls.SESSION_CREATED,
            cls.SETTINGS_CHANGED,
        ]


class FileEventAdapter:
    """EventPort 的文件实现：每个事件一行 JSON。"""

    def __init__(self, log_path: str = "backend/data/audit/audit.jsonl") -> None:
        self._log_path = Path(log_path)
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        event = {
            "ts": datetime.now().isoformat(),
            "type": event_type,
            "payload": payload,
        }
        with self._log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
