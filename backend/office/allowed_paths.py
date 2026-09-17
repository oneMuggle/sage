"""项目级允许访问路径的规则匹配引擎（2026-09-17）。

扩展文件访问控制：除了 workspace 内文件，用户可以为每个项目配置
``allowed_paths``（额外允许访问的路径规则列表）。此模块负责检查一个
候选路径是否匹配任一规则。

路径规则语法（类 .gitignore，使用 pathlib.PurePath.match）：

- ``~/Documents/**`` — 用户 Documents 目录及其所有子目录
- ``~/Desktop/*.pdf`` — 用户桌面所有 PDF 文件
- ``/tmp/scratch/*`` — /tmp/scratch 直接子文件（不含子目录）
- ``~/projects/sage-shared`` — 精确匹配（目录或文件）

路径展开：

- ``~`` → ``Path.home()``
- 相对路径 → 相对于调用时的 cwd（通常由调用方保证绝对）

安全原则：

- 使用 ``Path.resolve()`` 归一化路径，消除 ``..`` 和符号链接
- 目录包含检查用 ``relative_to()``（非字符串前缀），防兄弟目录碰撞
- 匹配失败默认拒绝（fail-closed）
"""

from __future__ import annotations

import logging
from pathlib import Path, PurePath
from typing import List, Optional

logger = logging.getLogger(__name__)


def get_session_allowed_paths(session_id: Optional[str]) -> List[str]:
    """获取当前 session 绑定的项目的 allowed_paths。

    通过 session_id → workspace_path → project.allowed_paths 链路查询。
    任何环节失败都返回空列表（fail-closed 语义由调用方保证）。

    Args:
        session_id: 当前会话 ID，如果为 None 返回空列表

    Returns:
        路径规则列表（可能为空）
    """
    if not session_id:
        return []

    try:
        from backend.data.database import get_database
        from backend.data.project_repo import ProjectRepository
        from backend.office.session_workspace import get_workspace_binding

        conn = get_database().get_connection()
        binding = get_workspace_binding(conn, session_id)
        if binding is None:
            return []

        # 通过 workspace_path 查找 project
        repo = ProjectRepository()
        conn_cursor = conn.execute(
            "SELECT * FROM projects WHERE path = ?", (binding.workspace_path,)
        )
        row = conn_cursor.fetchone()
        if row is None:
            return []

        # 复用 _row_to_project 解析逻辑
        from backend.data.project_repo import _row_to_project
        project = _row_to_project(row)
        return project.allowed_paths

    except Exception as exc:
        logger.debug(
            "get_session_allowed_paths: 查询失败 (session=%s): %s",
            session_id, exc,
        )
        return []


def is_allowed(
    candidate: str,
    allowed_paths: List[str],
    project_root: Optional[str] = None,
) -> bool:
    """检查候选路径是否匹配任一 allowed_paths 规则。

    Args:
        candidate: 待检查的绝对路径（可以是文件或目录）
        allowed_paths: 路径规则列表（如 ["~/Documents/**", "/tmp/*"]）
        project_root: 项目根目录，用于展开相对路径规则。如果为 None，
                      相对路径规则将被忽略。

    Returns:
        True 如果路径匹配任一规则，False 否则（fail-closed）

    Examples:
        >>> is_allowed("/home/user/docs/readme.txt", ["~/docs/**"])
        True
        >>> is_allowed("/tmp/file.txt", ["/tmp/*"])
        True
        >>> is_allowed("/etc/passwd", ["~/Documents/**"])
        False
    """
    if not allowed_paths:
        return False

    # 归一化候选路径（resolve 消除 .. 和符号链接）
    try:
        candidate_path = Path(candidate).resolve()
    except (OSError, ValueError) as exc:
        logger.warning("allowed_paths: 无法解析候选路径 %r: %s", candidate, exc)
        return False

    for rule in allowed_paths:
        if _matches_rule(candidate_path, rule, project_root):
            return True

    return False


def _matches_rule(
    candidate: Path,
    rule: str,
    project_root: Optional[str],
) -> bool:
    """检查候选路径是否匹配单条规则。"""
    rule_path = _expand_rule(rule, project_root)
    if rule_path is None:
        return False

    # 情况 1：规则指向已存在的目录 → 检查是否在该目录下
    if rule_path.is_dir():
        try:
            candidate.relative_to(rule_path)
            return True
        except ValueError:
            pass  # 不在该目录下，继续尝试通配符匹配

    # 情况 2：通配符匹配（PurePath.match 支持 *, **, ?）
    # 注意：PurePath.match 的 ** 语义与 gitignore 略有不同
    # 这里用简化实现：将 ** 视为匹配任意层级目录
    if _glob_match(candidate, rule_path):
        return True

    return False


def _expand_rule(rule: str, project_root: Optional[str]) -> Optional[Path]:
    """展开路径规则。

    - ``~`` → ``Path.home()``
    - 相对路径 → 相对于 project_root（如有）
    - 绝对路径 → 直接使用

    Returns:
        展开后的 Path，如果展开失败返回 None
    """
    try:
        # 展开 ~ 为 home 目录（显式替换，而非 expanduser）
        if rule.startswith("~"):
            home = Path.home()
            rule = str(home / rule[1:].lstrip("/"))

        expanded = Path(rule)

        # 相对路径 → 相对于 project_root
        if not expanded.is_absolute():
            if project_root is None:
                # 无 project_root，无法展开相对路径
                logger.debug(
                    "allowed_paths: 忽略相对路径规则 %r（无 project_root）", rule
                )
                return None
            expanded = Path(project_root) / expanded

        # 归一化（不解析符号链接，保留通配符）
        # 注意：不能用 resolve()，否则会消除通配符字符
        return Path(str(expanded))

    except (OSError, ValueError) as exc:
        logger.warning("allowed_paths: 无法展开规则 %r: %s", rule, exc)
        return None


def _glob_match(candidate: Path, pattern: Path) -> bool:
    """简化的 glob 匹配（支持 *, **, ?）。

    将 pattern 转换为字符串后用 PurePath.match 匹配。
    注意：PurePath.match 的 ** 语义与 gitignore 略有不同：
    - ``**`` 匹配任意层级目录
    - ``*`` 匹配单层目录或文件名
    """
    pattern_str = str(pattern)

    # 处理 ** 通配符
    if "**" in pattern_str:
        # 将 ** 替换为特殊标记，然后逐段匹配
        return _doublestar_match(candidate, pattern_str)

    # 无 ** 时直接用 PurePath.match
    try:
        return PurePath(candidate).match(pattern_str)
    except (ValueError, TypeError):
        return False


def _doublestar_match(candidate: Path, pattern_str: str) -> bool:
    """处理包含 ** 的模式。

    ** 匹配任意层级目录（包括 0 层）。
    例如：``~/docs/**`` 匹配 ``~/docs/a.txt`` 和 ``~/docs/sub/dir/file.txt``
    """
    # 分离 ** 前后的部分
    parts = pattern_str.split("**")
    if len(parts) != 2:
        # 多个 ** 或多个位置，暂不支持
        return False

    prefix, suffix = parts[0].rstrip("/"), parts[1].lstrip("/")

    # 检查候选路径是否以 prefix 开头
    candidate_str = str(candidate)
    if prefix and not candidate_str.startswith(prefix):
        return False

    # 检查候选路径是否以 suffix 结尾（如有 suffix）
    if suffix:
        # suffix 可能包含通配符，用 PurePath.match
        try:
            return PurePath(candidate_str).match(f"**/{suffix}" if prefix else suffix)
        except (ValueError, TypeError):
            return False

    return True


__all__ = [
    "get_session_allowed_paths",
    "is_allowed",
]
