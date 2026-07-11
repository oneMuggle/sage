"""File event adapter — 5 类审计事件。

spec § 6.1 定义的 5 类审计事件：chat_message_sent / chat_response_completed /
tool_invoked / session_created / settings_changed，全部落盘到
``${SAGE_USER_DATA_DIR}/audit/audit.jsonl``（packaged 模式）或
``backend/data/audit/audit.jsonl``（dev fallback）。packaged Electron 注入
``SAGE_USER_DATA_DIR`` 指向 ``<userData>``，避免向 ``C:\\Program Files\\Sage``
这类系统保护目录写入触发 ``PermissionError``。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

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


def _default_audit_log_path() -> Path:
    """Resolve the writable audit JSONL path.

    Order:
      1. Caller-supplied log_path (explicit in __init__).
      2. ``${SAGE_USER_DATA_DIR}/audit/audit.jsonl`` — per-user writable;
         packaged Electron sets the env to ``<userData>``, so audit JSONL
         lands at ``<userData>/audit/audit.jsonl``. Critical for
         installs to ``C:\\Program Files\\Sage`` where the bundled
         ``resources/backend/data/audit/`` is system-protected.
      3. Bundled fallback ``backend/data/audit/audit.jsonl`` — used only
         in dev / tests where ``SAGE_USER_DATA_DIR`` isn't set (assumes
         a writable repo checkout, the documented dev workflow).
    """
    user_data_dir = os.environ.get("SAGE_USER_DATA_DIR")
    if user_data_dir:
        return Path(user_data_dir) / "audit" / "audit.jsonl"
    return Path("backend/data/audit/audit.jsonl")


class FileEventAdapter:
    """EventPort 的文件实现：每个事件一行 JSON。"""

    def __init__(self, log_path: Optional[Union[Path, str]] = None) -> None:
        if log_path is None:
            log_path = _default_audit_log_path()
        self._log_path = Path(log_path)
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        event = envelope(event_type, payload, ts=datetime.now().isoformat())
        with self._log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
