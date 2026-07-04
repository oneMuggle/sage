"""Stdout event adapter — 开发用，把事件打到控制台。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from backend.domain.agent_event import envelope


class StdoutEventAdapter:
    """EventPort 的 stdout 实现（开发用）：输出纯 NDJSON 行。"""

    def __init__(self, verbose: bool = True):
        self._verbose = verbose

    def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._verbose:
            event = envelope(event_type, payload, ts=datetime.now().isoformat())
            print(json.dumps(event, ensure_ascii=False))  # noqa: T201
