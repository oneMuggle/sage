"""远程访问审计：``remote_audit.jsonl``（2 MiB 轮转，内存保留最近 150 条）。

只记录时间 / 工作区 ID / 事件 / 工具名 / 耗时 / 结果码；**不记录**参数、
文件正文、命令文本与 token。任何字段里出现的 ``/mcp/<hex>`` 都会被脱敏。
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

MAX_BYTES = 2 * 1024 * 1024
_TOKEN_IN_URL = re.compile(r"/mcp/[0-9a-fA-F]{16,}")
_ALLOWED_FIELDS = frozenset({"tool", "ms", "code", "reason", "count", "port", "field", "value"})


def redact(text: str) -> str:
    return _TOKEN_IN_URL.sub("/mcp/[redacted]", text)


class AuditLog:
    def __init__(self, path: Optional[str] = None) -> None:
        base = os.environ.get("SAGE_USER_DATA_DIR") or os.path.join("backend", "data")
        self._path = path or os.path.join(base, "remote_audit.jsonl")
        self._recent: Deque[Dict[str, Any]] = deque(maxlen=150)
        self._lock = threading.Lock()

    def record(self, event: str, workspace_id: Optional[str] = None, **detail: Any) -> None:
        row: Dict[str, Any] = {
            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": event,
            "workspace_id": workspace_id,
        }
        for key, value in detail.items():
            if key in _ALLOWED_FIELDS:
                row[key] = redact(value) if isinstance(value, str) else value
        with self._lock:
            self._recent.appendleft(row)
            try:
                Path(self._path).parent.mkdir(parents=True, exist_ok=True)
                log_path = Path(self._path)
                if log_path.exists() and log_path.stat().st_size > MAX_BYTES:
                    log_path.replace(self._path.replace(".jsonl", ".previous.jsonl"))
                with open(self._path, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            except OSError:
                pass  # 审计写盘失败不影响服务

    def recent(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._recent)


__all__ = ["AuditLog", "redact"]
