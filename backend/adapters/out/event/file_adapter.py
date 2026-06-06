"""File event adapter — 写 audit 日志（骨架，P3.2 完善事件类型）。"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class FileEventAdapter:
    """EventPort 的文件实现：每个事件一行 JSON。"""

    def __init__(self, log_path: str = "backend/data/audit/audit.jsonl"):
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
