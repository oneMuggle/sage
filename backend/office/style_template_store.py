# ruff: noqa: UP006, UP007, UP035 — py38 compat (typing generics).
"""M2 Word 样式模板库仓储.

CRUD around ``office_style_templates``. Each row stores a **snapshot** of the
converted ``WordFormatSpec`` (JSON text) rather than a rule-pack reference —
editing the source rule pack later must not silently rewrite templates the
user already saved. ``source_kind`` ∈ {preset, rulepack, manual} and
``source_ref`` keep provenance for display and debugging.

设计要点（仿 :mod:`backend.office.spec_library`）:

* ``list_style_templates`` 按 ``is_default DESC, updated_at DESC`` 排序。
* 工作区只允许一个默认模板；``set_default_style_template`` 先把同行复位。
* 所有查询/删除都能用 ``workspace_path`` 限定，路由层必须传入——防止
  凭 id 跨工作区读写模板。
* 旧库宽容：``_has_style_table`` 探测表存在与否；读操作返回空列表/None，
  写操作抛 ``OfficeParseError``（由路由层转 HTTP 503）。
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from backend.office.errors import OfficeParseError
from backend.office.style_template_models import STYLE_TEMPLATE_SOURCE_KINDS

__all__ = [
    "create_style_template",
    "delete_style_template",
    "get_default_style_template",
    "get_style_template",
    "list_style_templates",
    "set_default_style_template",
]

_COLUMNS = (
    "id, workspace_path, name, format_spec, source_kind, source_ref, "
    "is_default, created_at, updated_at"
)
_SELECT = f"SELECT {_COLUMNS} FROM office_style_templates "


def _now_ms() -> int:
    return int(time.time() * 1000)


def _has_style_table(conn: sqlite3.Connection) -> bool:
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='office_style_templates'"
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def _require_table(conn: sqlite3.Connection) -> None:
    if not _has_style_table(conn):
        raise OfficeParseError("样式模板库表尚未初始化，请重启应用以运行迁移")


def _dump_spec(format_spec: Any) -> str:
    """序列化 format_spec 为 JSON 文本（接受 dict 或 JSON 字符串）。"""
    if isinstance(format_spec, str):
        try:
            parsed = json.loads(format_spec)
        except ValueError as exc:
            raise OfficeParseError("format_spec 不是合法 JSON") from exc
        if not isinstance(parsed, dict):
            raise OfficeParseError("format_spec 必须是 JSON 对象")
        return json.dumps(parsed, ensure_ascii=False)
    if not isinstance(format_spec, dict):
        raise OfficeParseError("format_spec 必须是 JSON 对象")
    return json.dumps(format_spec, ensure_ascii=False)


def _load_spec(raw: Any) -> Dict[str, Any]:
    """反序列化 format_spec；单行损坏不拖垮整个列表，退回空画像。"""
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _clean_name(name: Optional[str]) -> str:
    clean = (name or "").strip()
    if not clean:
        raise OfficeParseError("样式模板名称不能为空")
    if len(clean) > 200:
        raise OfficeParseError("样式模板名称过长（最多 200 字符）")
    return clean


def _clean_source(
    source_kind: Optional[str], source_ref: Optional[str]
) -> Tuple[str, Optional[str]]:
    kind = source_kind or "manual"
    if kind not in STYLE_TEMPLATE_SOURCE_KINDS:
        raise OfficeParseError(
            "source_kind 只能是 " + "/".join(STYLE_TEMPLATE_SOURCE_KINDS)
        )
    ref = (source_ref or "").strip() or None
    if ref is not None and len(ref) > 2000:
        raise OfficeParseError("source_ref 过长（最多 2000 字符）")
    return kind, ref


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "workspace_path": row["workspace_path"],
        "name": row["name"],
        "format_spec": _load_spec(row["format_spec"]),
        "source_kind": row["source_kind"],
        "source_ref": row["source_ref"],
        "is_default": bool(row["is_default"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_style_templates(
    conn: sqlite3.Connection,
    workspace_path: str,
) -> List[Dict[str, Any]]:
    """列出工作区所有样式模板。表不存在时返回空列表."""
    if not _has_style_table(conn):
        return []
    rows = conn.execute(
        _SELECT + "WHERE workspace_path = ? "
        "ORDER BY is_default DESC, updated_at DESC",
        (workspace_path,),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_style_template(
    conn: sqlite3.Connection,
    template_id: str,
    *,
    workspace_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """按 id 查样式模板.表不存在/行不存在返回 None.

    ``workspace_path`` 非空时限制在该工作区内——路由层必须传入，防止
    凭 template_id 跨工作区读取模板画像。
    """
    if not _has_style_table(conn):
        return None
    sql = _SELECT + "WHERE id = ?"
    params: List[Any] = [template_id]
    if workspace_path is not None:
        sql += " AND workspace_path = ?"
        params.append(workspace_path)
    row = conn.execute(sql, tuple(params)).fetchone()
    return _row_to_dict(row) if row else None


def get_default_style_template(
    conn: sqlite3.Connection,
    workspace_path: str,
) -> Optional[Dict[str, Any]]:
    """返回工作区默认样式模板（is_default=1）.至多一行."""
    if not _has_style_table(conn):
        return None
    row = conn.execute(
        _SELECT + "WHERE workspace_path = ? AND is_default = 1 LIMIT 1",
        (workspace_path,),
    ).fetchone()
    return _row_to_dict(row) if row else None


def create_style_template(
    conn: sqlite3.Connection,
    *,
    workspace_path: str,
    name: str,
    format_spec: Any,
    source_kind: Optional[str] = "manual",
    source_ref: Optional[str] = None,
    template_id: Optional[str] = None,
    is_default: bool = False,
) -> Dict[str, Any]:
    """新建一行样式模板.若 ``is_default=True``，先复位同工作区其它行."""
    _require_table(conn)
    clean_name = _clean_name(name)
    spec_json = _dump_spec(format_spec)
    kind, ref = _clean_source(source_kind, source_ref)
    new_id = template_id or f"style-{uuid.uuid4().hex[:12]}"
    now = _now_ms()
    if is_default:
        conn.execute(
            "UPDATE office_style_templates SET is_default = 0 "
            "WHERE workspace_path = ?",
            (workspace_path,),
        )
    conn.execute(
        "INSERT INTO office_style_templates "
        "(id, workspace_path, name, format_spec, source_kind, source_ref, "
        "is_default, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            new_id,
            workspace_path,
            clean_name,
            spec_json,
            kind,
            ref,
            1 if is_default else 0,
            now,
            now,
        ),
    )
    conn.commit()
    return get_style_template(conn, new_id, workspace_path=workspace_path) or {}


def delete_style_template(
    conn: sqlite3.Connection,
    template_id: str,
    *,
    workspace_path: Optional[str] = None,
) -> bool:
    """删除一行样式模板.``workspace_path`` 非空时只删该工作区的行."""
    _require_table(conn)
    if get_style_template(conn, template_id, workspace_path=workspace_path) is None:
        return False
    sql = "DELETE FROM office_style_templates WHERE id = ?"
    params: List[Any] = [template_id]
    if workspace_path is not None:
        sql += " AND workspace_path = ?"
        params.append(workspace_path)
    cursor = conn.execute(sql, tuple(params))
    conn.commit()
    return cursor.rowcount > 0


def set_default_style_template(
    conn: sqlite3.Connection,
    workspace_path: str,
    template_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    """设置/清除工作区默认样式模板.

    ``template_id=None`` 时清除（所有行 is_default=0）；否则先复位同行再置
    目标行。先校验目标行属于该工作区再动任何行——避免跨工作区越权，也避免
    失败时对共享连接 ``rollback()`` 波及其它未提交事务。
    """
    _require_table(conn)
    if template_id is not None and get_style_template(
        conn, template_id, workspace_path=workspace_path
    ) is None:
        raise OfficeParseError("样式模板不存在或不属于该工作区")
    conn.execute(
        "UPDATE office_style_templates SET is_default = 0 WHERE workspace_path = ?",
        (workspace_path,),
    )
    if template_id:
        conn.execute(
            "UPDATE office_style_templates SET is_default = 1, updated_at = ? "
            "WHERE id = ? AND workspace_path = ?",
            (_now_ms(), template_id, workspace_path),
        )
    conn.commit()
    if template_id is None:
        return None
    return get_style_template(conn, template_id, workspace_path=workspace_path)
