"""记忆作用域 (scope 轴, P1 三层作用域) — user / project / global。

时间轴 (working/episodic/semantic) 之外引入作用域轴, 对标 Mem0 的
user/agent/run 分级与 Cursor/Claude 的 user+project 规则分层:

- ``user``    用户级知识, 跨项目可见 (默认/兜底值, 也是存量行的迁移值)
- ``project`` 绑定某个项目目录的记忆, 仅同项目会话可见
- ``global``  显式共享的全局知识, 跨项目可见

project_key 直接复用 ``session_workspace_bindings`` 的活跃
workspace_path (与 projects 注册表 path 同源, 规范化绝对路径) ——
不引入新的项目 ID 体系。

读侧可见性规则:
- 会话绑定项目 W: user/global/存量行 ∪ project_key == W 的 project 行
- 会话未绑定:     仅 user/global/存量行 (其他项目记忆不可见)
- 管理视图 (记忆浏览器 / 导出) 不过滤, 行上带 scope / project_key 字段
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

SCOPE_USER = "user"
SCOPE_PROJECT = "project"
SCOPE_GLOBAL = "global"
VALID_SCOPES: Tuple[str, ...] = (SCOPE_USER, SCOPE_PROJECT, SCOPE_GLOBAL)

#: 默认会话 ID（与 working.normalize_session_id 的兜底值一致）。
#: 挂在默认会话上的记忆没有项目归属可言。
_DEFAULT_SESSION_ID = "default"


def normalize_scope(scope: Optional[str], default: str = SCOPE_USER) -> str:
    """校验 scope 白名单；非法值降级为 ``default``。"""
    if scope in VALID_SCOPES:
        return str(scope)
    return default


def resolve_session_project_key(db: Any, session_id: Optional[str]) -> Optional[str]:
    """查会话的活跃 workspace 绑定，返回规范化绝对路径；未绑定/异常 → None。

    ``db`` 允许传 Database 实例或 sqlite3.Connection（测试友好）。
    绑定表缺失（未跑 init_db 的内存库）时静默返回 None，不抛错。
    """
    if not session_id or session_id == _DEFAULT_SESSION_ID:
        return None
    try:
        conn = db.get_connection() if hasattr(db, "get_connection") else db
        row = conn.execute(
            """
            SELECT workspace_path FROM session_workspace_bindings
            WHERE session_id = ? AND revoked_at IS NULL
            """,
            (str(session_id),),
        ).fetchone()
        if row is None:
            return None
        values = tuple(row)
        return str(values[0]) if values and values[0] else None
    except Exception as exc:  # noqa: BLE001 - 表不存在等降级为无项目
        logger.debug(f"解析会话项目绑定失败 (session={session_id}): {exc}")
        return None


def derive_write_scope(db: Any, session_id: Optional[str]) -> Tuple[str, Optional[str]]:
    """写入时未显式指定 scope 的自动判定：绑定项目 → project，否则 user。"""
    key = resolve_session_project_key(db, session_id)
    if key:
        return SCOPE_PROJECT, key
    return SCOPE_USER, None


def finalize_scope(
    db: Any,
    scope: Optional[str],
    project_key: Optional[str],
    session_id: Optional[str],
) -> Tuple[str, Optional[str]]:
    """把调用方声明的 (scope, project_key) 规范化为可落库值。

    - scope=None → 自动判定 (derive_write_scope)
    - scope=project 且未给 project_key → 从 session 绑定解析；解析不到
      则降级为 user（project 行没有归属会永远不可见，宁可降级）
    - scope!=project 时 project_key 强制清空，避免脏组合
    """
    if scope is None:
        return derive_write_scope(db, session_id)
    scope = normalize_scope(scope)
    if scope == SCOPE_PROJECT:
        if not project_key:
            project_key = resolve_session_project_key(db, session_id)
        if not project_key:
            logger.debug("scope=project 但会话无 workspace 绑定，降级为 user")
            return SCOPE_USER, None
        return SCOPE_PROJECT, str(project_key)
    return scope, None


def visibility_sql(
    current_project_key: Optional[str], column_prefix: str = ""
) -> Tuple[str, List[Any]]:
    """构造"当前项目会话可见"的 SQL 条件片段（含前导 `` AND ``）。

    存量行 scope 为 NULL 时按 user 处理（始终可见），保证向后兼容。
    """
    p = column_prefix
    if current_project_key:
        return (
            f" AND ({p}scope IS NULL OR {p}scope != '{SCOPE_PROJECT}'"
            f" OR {p}project_key = ?)",
            [current_project_key],
        )
    return (
        f" AND ({p}scope IS NULL OR {p}scope != '{SCOPE_PROJECT}')",
        [],
    )


def is_row_visible(row: Dict[str, Any], current_project_key: Optional[str]) -> bool:
    """对已取出的行做与 :func:`visibility_sql` 等价的内存过滤。

    P3 起同时兜底"时间有效区"：``invalid_at`` 非空的行（已被更新事实
    取代）不可见——存储层读路径大多已过滤, 这里覆盖向量检索等旁路。
    """
    if row.get("invalid_at") is not None:
        return False
    if (row.get("scope") or SCOPE_USER) != SCOPE_PROJECT:
        return True
    return bool(current_project_key) and row.get("project_key") == current_project_key


__all__ = [
    "SCOPE_USER",
    "SCOPE_PROJECT",
    "SCOPE_GLOBAL",
    "VALID_SCOPES",
    "normalize_scope",
    "resolve_session_project_key",
    "derive_write_scope",
    "finalize_scope",
    "visibility_sql",
    "is_row_visible",
]
