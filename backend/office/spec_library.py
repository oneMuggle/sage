# ruff: noqa: UP006, UP007, UP035 — py38 compat (typing generics).
"""M2.5 格式规范书库仓储.

CRUD 操作围绕 ``office_spec_documents`` 表。规范书的具体规则内容仍存于
``<workspace>/.sage/word-rulepacks/<rulepack_id>.json``（复用
``word_rulepack_store`` 文件系统布局），本模块只持有「规范书元数据 + 绑定关系」。

设计要点:
* ``list_specs`` 返回工作区下所有规范书；``get_default_spec`` 取 is_default=1 行
  （工作区仅允许一个默认；set_default 时先把同行其它行复位）。
* ``bind_document`` / ``unbind_document`` 仅改 ``office_documents.active_spec_id``。
* ``resolve_effective_spec`` 依次查：文档绑定 → 工作区默认 → None.
* 所有写操作幂等且对旧版 DB 宽容：``_has_spec_table`` 探测表存在与否，
  不存在时读操作返回空列表、写操作抛 OfficeParseError（由路由层转 HTTP 503）。
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional

from backend.office.errors import OfficeParseError
from backend.office.word_rulepack_store import _validate_name

__all__ = [
    "create_spec",
    "delete_spec",
    "get_default_spec",
    "get_document_spec_id",
    "get_spec",
    "list_specs",
    "resolve_effective_spec",
    "set_default_spec",
    "update_document_spec",
    "update_spec",
]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _has_spec_table(conn: sqlite3.Connection) -> bool:
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='office_spec_documents'"
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def _require_table(conn: sqlite3.Connection) -> None:
    if not _has_spec_table(conn):
        raise OfficeParseError("规范书库表尚未初始化，请重启应用以运行迁移")


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "workspace_path": row["workspace_path"],
        "name": row["name"],
        "source_file_path": row["source_file_path"],
        "source_content_hash": row["source_content_hash"],
        "rulepack_id": row["rulepack_id"],
        "is_default": bool(row["is_default"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_specs(
    conn: sqlite3.Connection,
    workspace_path: str,
) -> List[Dict[str, Any]]:
    """列出工作区所有规范书（元数据）。表不存在时返回空列表."""
    if not _has_spec_table(conn):
        return []
    rows = conn.execute(
        "SELECT id, workspace_path, name, source_file_path, source_content_hash, "
        "rulepack_id, is_default, created_at, updated_at "
        "FROM office_spec_documents WHERE workspace_path = ? "
        "ORDER BY is_default DESC, updated_at DESC",
        (workspace_path,),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_spec(
    conn: sqlite3.Connection,
    spec_id: str,
    *,
    workspace_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """按 id 查规范书元数据.表不存在/行不存在返回 None.

    ``workspace_path`` 非空时限制在该工作区内——路由层必须传入，防止
    凭 spec_id 跨工作区读取规范书元数据。
    """
    if not _has_spec_table(conn):
        return None
    sql = (
        "SELECT id, workspace_path, name, source_file_path, source_content_hash, "
        "rulepack_id, is_default, created_at, updated_at "
        "FROM office_spec_documents WHERE id = ?"
    )
    params: List[Any] = [spec_id]
    if workspace_path is not None:
        sql += " AND workspace_path = ?"
        params.append(workspace_path)
    row = conn.execute(sql, tuple(params)).fetchone()
    return _row_to_dict(row) if row else None


def get_default_spec(
    conn: sqlite3.Connection,
    workspace_path: str,
) -> Optional[Dict[str, Any]]:
    """返回工作区默认规范书（is_default=1）.至多一行."""
    if not _has_spec_table(conn):
        return None
    row = conn.execute(
        "SELECT id, workspace_path, name, source_file_path, source_content_hash, "
        "rulepack_id, is_default, created_at, updated_at "
        "FROM office_spec_documents WHERE workspace_path = ? AND is_default = 1 "
        "LIMIT 1",
        (workspace_path,),
    ).fetchone()
    return _row_to_dict(row) if row else None


def create_spec(
    conn: sqlite3.Connection,
    *,
    workspace_path: str,
    name: str,
    rulepack_id: str,
    source_file_path: Optional[str] = None,
    source_content_hash: Optional[str] = None,
    spec_id: Optional[str] = None,
    is_default: bool = False,
) -> Dict[str, Any]:
    """新建一行规范书元数据.

    ``rulepack_id`` 必须已通过 ``word_rulepack_store.save_rulepack`` 落盘；
    本函数不强制校验（路由层在调用前已确保）。若 ``is_default=True``，
    先把同行工作区其它行复位（工作区只能有一个默认）。
    """
    _require_table(conn)
    clean_name = (name or "").strip()
    if not clean_name:
        raise OfficeParseError("规范书名称不能为空")
    _validate_name(rulepack_id)
    new_id = spec_id or f"spec-{uuid.uuid4().hex[:12]}"
    now = _now_ms()
    if is_default:
        conn.execute(
            "UPDATE office_spec_documents SET is_default = 0 "
            "WHERE workspace_path = ?",
            (workspace_path,),
        )
    conn.execute(
        "INSERT INTO office_spec_documents "
        "(id, workspace_path, name, source_file_path, source_content_hash, "
        "rulepack_id, is_default, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            new_id,
            workspace_path,
            clean_name,
            source_file_path,
            source_content_hash,
            rulepack_id,
            1 if is_default else 0,
            now,
            now,
        ),
    )
    conn.commit()
    return get_spec(conn, new_id, workspace_path=workspace_path) or {}


def update_spec(
    conn: sqlite3.Connection,
    spec_id: str,
    *,
    workspace_path: Optional[str] = None,
    name: Optional[str] = None,
    rulepack_id: Optional[str] = None,
    source_file_path: Optional[str] = None,
    source_content_hash: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """部分更新规范书元数据.返回更新后行或 None.

    ``workspace_path`` 非空时仅匹配该工作区内的行——路由层必须传入。
    """
    _require_table(conn)
    existing = get_spec(conn, spec_id, workspace_path=workspace_path)
    if existing is None:
        return None
    patches: List[str] = []
    values: List[Any] = []
    if name is not None:
        clean = name.strip()
        if not clean:
            raise OfficeParseError("规范书名称不能为空")
        patches.append("name = ?")
        values.append(clean)
    if rulepack_id is not None:
        _validate_name(rulepack_id)
        patches.append("rulepack_id = ?")
        values.append(rulepack_id)
    if source_file_path is not None:
        patches.append("source_file_path = ?")
        values.append(source_file_path)
    if source_content_hash is not None:
        patches.append("source_content_hash = ?")
        values.append(source_content_hash)
    if not patches:
        return existing
    patches.append("updated_at = ?")
    values.append(_now_ms())
    values.append(spec_id)
    sql = f"UPDATE office_spec_documents SET {', '.join(patches)} WHERE id = ?"
    if workspace_path is not None:
        sql += " AND workspace_path = ?"
        values.append(workspace_path)
    conn.execute(sql, values)
    conn.commit()
    return get_spec(conn, spec_id, workspace_path=workspace_path)


def delete_spec(
    conn: sqlite3.Connection,
    spec_id: str,
    *,
    workspace_path: Optional[str] = None,
) -> bool:
    """删除一行规范书元数据.同步清理引用此 spec 的文档绑定.

    ``workspace_path`` 非空时只删该工作区的行，且只清理该工作区文档的
    绑定——防止跨工作区删除。
    """
    _require_table(conn)
    if get_spec(conn, spec_id, workspace_path=workspace_path) is None:
        return False
    unbind_sql = "UPDATE office_documents SET active_spec_id = NULL WHERE active_spec_id = ?"
    unbind_params: List[Any] = [spec_id]
    delete_sql = "DELETE FROM office_spec_documents WHERE id = ?"
    delete_params: List[Any] = [spec_id]
    if workspace_path is not None:
        unbind_sql += " AND workspace_path = ?"
        unbind_params.append(workspace_path)
        delete_sql += " AND workspace_path = ?"
        delete_params.append(workspace_path)
    conn.execute(unbind_sql, tuple(unbind_params))
    cursor = conn.execute(delete_sql, tuple(delete_params))
    conn.commit()
    return cursor.rowcount > 0


def set_default_spec(
    conn: sqlite3.Connection,
    workspace_path: str,
    spec_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    """设置/清除工作区默认规范书.

    ``spec_id=None`` 时清除（所有行 is_default=0）；否则先把同行复位再置目标行。
    返回新的默认行或 None（清除时）。

    先校验目标行属于该工作区再动任何行——避免跨工作区越权，也避免
    失败时对共享连接 ``rollback()`` 波及其它未提交事务。
    """
    _require_table(conn)
    if spec_id is not None and get_spec(
        conn, spec_id, workspace_path=workspace_path
    ) is None:
        raise OfficeParseError("规范书不存在或不属于该工作区")
    conn.execute(
        "UPDATE office_spec_documents SET is_default = 0 WHERE workspace_path = ?",
        (workspace_path,),
    )
    if spec_id:
        conn.execute(
            "UPDATE office_spec_documents SET is_default = 1, updated_at = ? "
            "WHERE id = ? AND workspace_path = ?",
            (_now_ms(), spec_id, workspace_path),
        )
    conn.commit()
    if spec_id is None:
        return None
    return get_spec(conn, spec_id, workspace_path=workspace_path)


def update_document_spec(
    conn: sqlite3.Connection,
    doc_id: str,
    spec_id: Optional[str],
    *,
    workspace_path: Optional[str] = None,
) -> bool:
    """设置/清除文档级规范书绑定.

    ``spec_id=None`` 解绑（跟随工作区默认）。返回是否成功更新行。
    ``workspace_path`` 非空时目标文档与被绑定的规范书都必须属于该工作区。
    """
    if spec_id is not None:
        _require_table(conn)
        if get_spec(conn, spec_id, workspace_path=workspace_path) is None:
            raise OfficeParseError("规范书不存在或不属于该工作区")
    sql = "UPDATE office_documents SET active_spec_id = ? WHERE id = ?"
    params: List[Any] = [spec_id, doc_id]
    if workspace_path is not None:
        sql += " AND workspace_path = ?"
        params.append(workspace_path)
    cursor = conn.execute(sql, tuple(params))
    conn.commit()
    if cursor.rowcount == 0 and workspace_path is not None:
        raise OfficeParseError("文档不存在或不属于该工作区")
    return cursor.rowcount > 0


def get_document_spec_id(
    conn: sqlite3.Connection,
    doc_id: str,
    *,
    workspace_path: Optional[str] = None,
) -> Optional[str]:
    """返回文档级绑定的规范书 id（``office_documents.active_spec_id``）.

    旧库无该列时 ``row["active_spec_id"]`` 会抛 KeyError，统一按未绑定处理。
    ``workspace_path`` 非空时仅匹配该工作区内的文档。
    """
    sql = "SELECT active_spec_id FROM office_documents WHERE id = ?"
    params: List[Any] = [doc_id]
    if workspace_path is not None:
        sql += " AND workspace_path = ?"
        params.append(workspace_path)
    try:
        row = conn.execute(sql, tuple(params)).fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    try:
        return row["active_spec_id"]
    except (IndexError, KeyError):
        return None


def resolve_effective_spec(
    conn: sqlite3.Connection,
    *,
    workspace_path: str,
    doc_id: Optional[str] = None,
    spec_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """解析「当前生效的规范书」.优先级: 显式 spec_id > 文档绑定 > 工作区默认.

    三层都限定在 ``workspace_path`` 内——跨工作区的 spec_id / doc_id
    一律解析不到，防止元数据（路径、规范书名称）泄漏。
    """
    if spec_id:
        return get_spec(conn, spec_id, workspace_path=workspace_path)
    if doc_id:
        try:
            row = conn.execute(
                "SELECT active_spec_id FROM office_documents "
                "WHERE id = ? AND workspace_path = ?",
                (doc_id, workspace_path),
            ).fetchone()
        except sqlite3.Error:
            row = None
        if row and row["active_spec_id"]:
            found = get_spec(
                conn, row["active_spec_id"], workspace_path=workspace_path
            )
            if found:
                return found
    return get_default_spec(conn, workspace_path)
