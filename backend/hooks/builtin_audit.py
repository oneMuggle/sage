"""内置审计日志钩子 (Phase 1)。

post_tool_use 观察型钩子: 把每次工具调用记录到 ~/.sage/audit.jsonl。
永不阻断 (始终返回 allow)。文件按行追加, 超过 max_size_mb 时自动轮转。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

_DEFAULT_LOG_DIR = Path.home() / ".sage"
_DEFAULT_LOG_FILE = "audit.jsonl"
_DEFAULT_MAX_SIZE_MB = 50


def _get_log_path(config: Dict[str, Any]) -> Path:
    """解析审计日志文件路径。"""
    log_dir = config.get("log_dir", _DEFAULT_LOG_DIR)
    log_file = config.get("log_file", _DEFAULT_LOG_FILE)
    return Path(log_dir) / log_file


def _rotate_if_needed(log_path: Path, max_size_mb: float) -> None:
    """日志文件超过大小上限时, 重命名为 .1 备份 (仅保留一份)。"""
    try:
        if not log_path.exists():
            return
        size_mb = log_path.stat().st_size / (1024 * 1024)
        if size_mb > max_size_mb:
            backup = log_path.with_suffix(".jsonl.1")
            if backup.exists():
                backup.unlink()
            log_path.rename(backup)
    except OSError as exc:
        logger.debug("hooks: audit log rotation failed: %s", exc)


async def audit_logger(
    payload: Dict[str, Any],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """记录工具调用到审计日志文件。

    config keys:
        log_dir: str — 日志目录 (默认 ~/.sage)
        log_file: str — 文件名 (默认 audit.jsonl)
        max_size_mb: float — 轮转阈值 (默认 50)
    """
    try:
        log_path = _get_log_path(config)
        max_size_mb = config.get("max_size_mb", _DEFAULT_MAX_SIZE_MB)

        _rotate_if_needed(log_path, max_size_mb)

        log_path.parent.mkdir(parents=True, exist_ok=True)

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),  # noqa: UP017 — py3.10 不支持 datetime.UTC
            "event": payload.get("hook_event_name", "post_tool_use"),
            "tool_name": payload.get("tool_name", ""),
            "tool_input": payload.get("tool_input"),
        }

        line = json.dumps(record, ensure_ascii=False, default=str)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

        return {"decision": "allow"}

    except Exception as exc:
        logger.warning("hooks: audit_logger failed (fail-open): %s", exc)
        return {"decision": "allow", "reason": f"audit_logger error: {exc}"}
