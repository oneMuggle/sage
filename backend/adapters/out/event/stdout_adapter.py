"""Stdout event adapter — 开发用，把事件打到控制台。"""

from __future__ import annotations

import json
from typing import Any


class StdoutEventAdapter:
    """EventPort 的 stdout 实现（开发用）。"""

    def __init__(self, verbose: bool = True):
        self._verbose = verbose

    def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._verbose:
            print(f"[event] {event_type}: {json.dumps(payload, ensure_ascii=False)}")  # noqa: T201
