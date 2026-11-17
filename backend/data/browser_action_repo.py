# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""受控浏览器动作审计仓储（browser_action_log）。

只记录动作元数据（会话 / 工具 / 动作 / 站点 / 元素定位与描述 / 结果 /
审批来源 / 耗时），**不记录页面正文、输入值或凭据**。写入失败只记录
日志，绝不向调用方抛异常 —— 审计不得影响浏览器动作本身。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from backend.data.database import Database, get_database

logger = logging.getLogger(__name__)

#: target_desc 最大落库长度（防单条元素名过长；brief 口径 ≤120 字符）
MAX_TARGET_DESC = 120

VALID_RESULTS = ("ok", "blocked", "confirm_required", "error")
VALID_APPROVALS = ("auto", "approved", "denied", "none")

_COLUMNS = (
    "session_id",
    "conversation_id",
    "ts",
    "domain",
    "tool",
    "action",
    "target_ref",
    "target_desc",
    "result",
    "approval",
    "duration_ms",
)


def _as_text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize(entry: Dict[str, Any]) -> Dict[str, Any]:
    result = _as_text(entry.get("result")) or "error"
    if result not in VALID_RESULTS:
        result = "error"
    approval = _as_text(entry.get("approval")) or "auto"
    if approval not in VALID_APPROVALS:
        approval = "auto"
    conversation_id = entry.get("conversation_id")
    return {
        "session_id": _as_text(entry.get("session_id")) or "unknown",
        "conversation_id": conversation_id if isinstance(conversation_id, str) else None,
        "ts": _as_int(entry.get("ts"), 0),
        "domain": _as_text(entry.get("domain"))[:255],
        "tool": _as_text(entry.get("tool")) or "unknown",
        "action": _as_text(entry.get("action"))[:64],
        "target_ref": _as_text(entry.get("target_ref"))[:120],
        "target_desc": _as_text(entry.get("target_desc"))[:MAX_TARGET_DESC],
        "result": result,
        "approval": approval,
        "duration_ms": max(0, _as_int(entry.get("duration_ms"), 0)),
    }


def record(entry: Dict[str, Any], db: Optional[Database] = None) -> None:
    """写入一条审计记录；任何失败只记录日志，不抛异常。"""
    try:
        row = _normalize(entry if isinstance(entry, dict) else {})
        conn = (db or get_database()).get_connection()
        conn.execute(
            "INSERT INTO browser_action_log ("
            + ", ".join(_COLUMNS)
            + ") VALUES ("
            + ", ".join("?" for _ in _COLUMNS)
            + ")",
            tuple(row[column] for column in _COLUMNS),
        )
        conn.commit()
    except Exception:  # noqa: BLE001 — 审计写入失败不得影响浏览器动作
        logger.debug("browser_action_log 写入失败", exc_info=True)


def list_recent(
    session_id: Optional[str] = None,
    limit: int = 100,
    db: Optional[Database] = None,
) -> List[Dict[str, Any]]:
    """按时间倒序读取最近审计记录；失败返回空列表。"""
    try:
        safe_limit = max(1, min(_as_int(limit, 100), 500))
        conn = (db or get_database()).get_connection()
        if session_id:
            cursor = conn.execute(
                "SELECT * FROM browser_action_log WHERE session_id = ? "
                "ORDER BY ts DESC, id DESC LIMIT ?",
                (session_id, safe_limit),
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM browser_action_log ORDER BY ts DESC, id DESC LIMIT ?",
                (safe_limit,),
            )
        return [dict(row) for row in cursor.fetchall()]
    except Exception:  # noqa: BLE001 — 读取失败按空列表降级
        logger.debug("browser_action_log 查询失败", exc_info=True)
        return []
