# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""回答版本仓储（对话阅读体验第二轮 C2，docs/mcp-chat-reading-nav-optimization.md §10.6）。

会话最后一轮「重新生成」时，旧回答整轮（锚点 user 消息之后的全部消息行）归档到
``message_versions``，新回答照常落库；用户可以在同一位置切换版本。

与会话事件日志（session_events，「模型可见 ⟺ 已记录」）的约定：

- 归档 = 删除消息行并写 ``message.deleted`` 事件，模型历史随之排除；
- 恢复 = 以**新 id** 重新插入快照行并写 ``message.appended`` 事件。投影对
  ``message.deleted`` 宣告过的 id 永久排除（日志里 id 不复用），不能沿用旧 id。

只对最后一轮生效：锚点之后出现别的 user 消息即视为无效（原位切换要连带替换
后面的全部消息，不在本轮范围内）。
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Dict, Iterable, List, Optional, Set, TypeVar

from backend.data.database import get_database

logger = logging.getLogger(__name__)

#: 列表里「当前显示中的版本」的占位 id
CURRENT_VERSION_ID = "current"

_PREVIEW_CHARS = 80

T = TypeVar("T")


class AnswerVersionError(LookupError):
    """``kind``：anchor_not_found / anchor_not_last / version_not_found。"""

    def __init__(self, kind: str, message: str):
        self.kind = kind
        super().__init__(message)


def _append_event(cursor: Any, session_id: str, event_type: str, payload: Dict[str, Any]) -> None:
    """在当前事务里追加会话事件（best-effort，与 session_repo 双写同一降级口径）。"""
    try:
        from backend.data.session_event_repo import SessionEventRepository

        SessionEventRepository.append_with_cursor(cursor, session_id, event_type, payload=payload)
    except Exception as exc:  # noqa: BLE001 — 事件日志故障不影响版本操作
        logger.warning("回答版本事件双写失败 (%s): %s", event_type, exc)


def _message_event_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    """与 MessageRepository.save 的 message.appended 载荷同构（投影依赖这些字段）。"""
    return {
        "id": row.get("id"),
        "role": row.get("role"),
        "content": row.get("content"),
        "subtype": row.get("subtype"),
        "segment_id": row.get("segment_id"),
        "tool_calls": row.get("tool_calls"),
        "created_at": row.get("created_at"),
    }


def _preview(rows: List[Any]) -> str:
    """版本预览：最后一条有内容的 assistant 消息，压成单行后截断。"""
    for row in reversed(rows):
        if not isinstance(row, dict) or row.get("role") != "assistant":
            continue
        text = " ".join(str(row.get("content") or "").split())
        if text:
            return text[:_PREVIEW_CHARS]
    return ""


def _sync_search_index(removed: Iterable[str], added: List[Dict[str, Any]]) -> None:
    """同步消息全文索引（session_search 工具）；best-effort，与 save() 同口径。"""
    try:
        from backend.data.message_search import get_message_search_index

        index = get_message_search_index()
        for message_id in removed:
            index.remove_message(message_id)
        for row in added:
            index.index_message(
                row["id"], row["session_id"], row.get("role"), row.get("content"), row.get("created_at")
            )
    except Exception as exc:  # noqa: BLE001 — 索引故障不影响版本操作
        logger.warning("回答版本索引同步失败: %s", exc)


class AnswerVersionRepository:
    """``message_versions`` 表的读写，以及与 messages / 事件日志的同事务联动。"""

    def __init__(self) -> None:
        self.db = get_database()

    # ---- 查询 -----------------------------------------------------------------

    @staticmethod
    def _turn_rows(cursor: Any, session_id: str, anchor_id: str) -> List[Dict[str, Any]]:
        """锚点之后（本轮回答）的消息行；锚点不存在或不是最后一轮时抛错。"""
        cursor.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at ASC, rowid ASC",
            (session_id,),
        )
        rows = [dict(row) for row in cursor.fetchall()]
        index = next(
            (i for i, row in enumerate(rows) if row["id"] == anchor_id and row["role"] == "user"),
            None,
        )
        if index is None:
            raise AnswerVersionError("anchor_not_found", f"anchor message not found: {anchor_id}")
        after = rows[index + 1 :]
        if any(row["role"] == "user" for row in after):
            raise AnswerVersionError("anchor_not_last", f"anchor is not the last turn: {anchor_id}")
        return after

    def is_last_turn(self, session_id: str, anchor_id: str) -> bool:
        try:
            self._turn_rows(self.db.get_connection().cursor(), session_id, anchor_id)
        except AnswerVersionError:
            return False
        return True

    def turn_message_ids(self, session_id: str, anchor_id: str) -> List[str]:
        """本轮回答的消息 id；锚点无效时返回空列表。"""
        try:
            rows = self._turn_rows(self.db.get_connection().cursor(), session_id, anchor_id)
        except AnswerVersionError:
            return []
        return [str(row["id"]) for row in rows]

    def last_user_message_id(self, session_id: str) -> Optional[str]:
        cursor = self.db.get_connection().cursor()
        cursor.execute(
            "SELECT id FROM messages WHERE session_id = ? AND role = 'user' "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (session_id,),
        )
        row = cursor.fetchone()
        return str(row[0]) if row else None

    def list_versions(self, session_id: str, anchor_id: Optional[str] = None) -> Dict[str, Any]:
        """列出最后一轮的全部版本（含当前显示的），按版本首行时间排序。"""
        anchor = anchor_id or self.last_user_message_id(session_id)
        result: Dict[str, Any] = {
            "anchor_id": anchor,
            "total": 0,
            "current_index": 0,
            "versions": [],
        }
        if not anchor:
            return result
        cursor = self.db.get_connection().cursor()
        try:
            current = self._turn_rows(cursor, session_id, anchor)
        except AnswerVersionError:
            return result
        cursor.execute(
            "SELECT id, rows_json, generated_at FROM message_versions "
            "WHERE session_id = ? AND anchor_id = ?",
            (session_id, anchor),
        )
        versions: List[Dict[str, Any]] = []
        for row in cursor.fetchall():
            try:
                snapshot = json.loads(row["rows_json"])
            except (TypeError, ValueError):
                snapshot = []
            versions.append(
                {
                    "id": row["id"],
                    "generated_at": row["generated_at"],
                    "preview": _preview(snapshot if isinstance(snapshot, list) else []),
                    "current": False,
                }
            )
        if current:
            versions.append(
                {
                    "id": CURRENT_VERSION_ID,
                    "generated_at": min(int(r["created_at"]) for r in current),
                    "preview": _preview(current),
                    "current": True,
                }
            )
        versions.sort(key=lambda v: (v["generated_at"], v["current"]))
        result["total"] = len(versions)
        result["current_index"] = next(
            (i + 1 for i, v in enumerate(versions) if v["current"]), 0
        )
        result["versions"] = versions
        return result

    # ---- 写入 -----------------------------------------------------------------

    @staticmethod
    def _archive_rows(
        cursor: Any, session_id: str, anchor_id: str, rows: List[Dict[str, Any]], now: int
    ) -> None:
        """同一事务：把本轮消息行存成一个版本，再删除这些行（写 message.deleted 事件）。"""
        from backend.data.session_event_repo import EVENT_MESSAGE_DELETED

        cursor.execute(
            "INSERT INTO message_versions "
            "(id, session_id, anchor_id, rows_json, generated_at, archived_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                f"ver-{uuid.uuid4().hex[:12]}",
                session_id,
                anchor_id,
                json.dumps(rows, ensure_ascii=False),
                min(int(row["created_at"]) for row in rows),
                now,
            ),
        )
        for row in rows:
            cursor.execute("DELETE FROM messages WHERE id = ?", (row["id"],))
            _append_event(
                cursor,
                session_id,
                EVENT_MESSAGE_DELETED,
                {"id": row["id"], "reason": "answer_version_archive"},
            )

    @staticmethod
    def _bump_message_count(cursor: Any, session_id: str, delta: int, now: int) -> None:
        if delta:
            cursor.execute(
                "UPDATE sessions SET message_count = MAX(0, message_count + ?), updated_at = ? "
                "WHERE id = ?",
                (delta, now, session_id),
            )

    def archive_turn(self, session_id: str, anchor_id: str) -> int:
        """把本轮回答整轮归档为一个版本；返回归档的行数（0 = 本轮还没有回答）。"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        rows = self._turn_rows(cursor, session_id, anchor_id)
        if not rows:
            return 0
        now = int(time.time() * 1000)
        try:
            self._archive_rows(cursor, session_id, anchor_id, rows, now)
            self._bump_message_count(cursor, session_id, -len(rows), now)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        _sync_search_index((str(row["id"]) for row in rows), [])
        return len(rows)

    def activate(self, session_id: str, version_id: str) -> int:
        """切换到指定版本：当前回答先归档，目标版本以新 id 恢复；返回恢复的行数。"""
        from backend.data.session_event_repo import EVENT_MESSAGE_APPENDED

        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT anchor_id, rows_json FROM message_versions WHERE id = ? AND session_id = ?",
            (version_id, session_id),
        )
        version = cursor.fetchone()
        if version is None:
            raise AnswerVersionError("version_not_found", f"answer version not found: {version_id}")
        anchor_id = str(version["anchor_id"])
        current = self._turn_rows(cursor, session_id, anchor_id)
        try:
            snapshot = json.loads(version["rows_json"])
        except (TypeError, ValueError):
            snapshot = []
        cursor.execute("PRAGMA table_info(messages)")
        columns = {str(row["name"]) for row in cursor.fetchall()}
        now = int(time.time() * 1000)
        restored: List[Dict[str, Any]] = []
        try:
            if current:
                self._archive_rows(cursor, session_id, anchor_id, current, now)
            for old in snapshot if isinstance(snapshot, list) else []:
                if not isinstance(old, dict):
                    continue
                # 只回填当前表里存在的列；id 必须换新（见模块说明）
                row = {key: value for key, value in old.items() if key in columns}
                row["id"] = f"msg-{uuid.uuid4().hex[:12]}"
                row["session_id"] = session_id
                keys = list(row)
                cursor.execute(
                    f"INSERT INTO messages ({', '.join(keys)}) "
                    f"VALUES ({', '.join('?' for _ in keys)})",
                    [row[key] for key in keys],
                )
                _append_event(
                    cursor, session_id, EVENT_MESSAGE_APPENDED, _message_event_payload(row)
                )
                restored.append(row)
            cursor.execute("DELETE FROM message_versions WHERE id = ?", (version_id,))
            self._bump_message_count(cursor, session_id, len(restored) - len(current), now)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        _sync_search_index((str(row["id"]) for row in current), restored)
        return len(restored)


# ---- producer 接线（backend/api/legacy_routes.py） ------------------------------


def regenerate_excluded_ids(session_id: str, anchor_id: Optional[str]) -> Set[str]:
    """原位重新生成时要从本轮 LLM 历史里剔除的消息：锚点 user 消息与旧回答。

    锚点 user 消息已在历史里，而本轮 user_text 会再追加一次；旧回答在新回答
    首次落库前才归档（见 :class:`ArchiveOnFirstSave`），加载历史时仍在库里。
    """
    if not anchor_id:
        return set()
    try:
        answer_ids = AnswerVersionRepository().turn_message_ids(session_id, anchor_id)
    except Exception as exc:  # noqa: BLE001 — 查询失败时至少剔除锚点
        logger.warning("重新生成历史剔除查询失败: %s", exc)
        answer_ids = []
    return {anchor_id, *answer_ids}


def drop_excluded(items: List[T], excluded: Set[str]) -> List[T]:
    """从历史行 / 会话事件里去掉 ``excluded`` 中的消息（事件看 payload.id，行看 .id）。"""
    if not excluded:
        return items

    def message_id(item: Any) -> Any:
        payload = getattr(item, "payload", None)
        if isinstance(payload, dict):
            return payload.get("id")
        return getattr(item, "id", None)

    return [item for item in items if message_id(item) not in excluded]


class ArchiveOnFirstSave:
    """包装 MessageRepository：本轮第一次落库前，先把旧回答归档为一个版本。

    这样只有重新生成真的产出了内容（或被用户中断、留下 partial）时才替换旧回答；
    失败且没有任何落库时旧回答原样保留，前端对账后重新显示。
    """

    def __init__(self, repo: Any, session_id: str, anchor_id: str) -> None:
        self._repo = repo
        self._session_id = session_id
        self._anchor_id = anchor_id
        self._archived = False

    def save(self, message: Any) -> Any:
        if not self._archived:
            self._archived = True
            try:
                AnswerVersionRepository().archive_turn(self._session_id, self._anchor_id)
            except Exception as exc:  # noqa: BLE001 — 归档失败不阻断新回答落库
                logger.warning("重新生成归档旧回答失败: %s", exc)
        return self._repo.save(message)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._repo, name)


__all__ = [
    "CURRENT_VERSION_ID",
    "AnswerVersionError",
    "AnswerVersionRepository",
    "ArchiveOnFirstSave",
    "drop_excluded",
    "regenerate_excluded_ids",
]
