"""虚拟路径解析 (P5, 2026-11-05 项目管理增强, 设计 §9.2)。

项目内路径可以指向引用别名: ``data/cases`` 的 ``target_path`` 是
``/data/cases``, 于是 ``data/cases/001/a.md`` 解析为
``/data/cases/001/a.md``。解析发生在**权限检查之前** — 调用方先拿到
真实路径, 再走 ``_enforce_workspace`` 的既有层级。

安全约束:
- rel_path 前缀按路径段匹配 (``data/cases`` 不匹配 ``data/cases2``);
- 拼接后的路径必须仍在目标之内 (realpath + normcase 边界检查);
- ``..`` / 绝对 rel_path / NUL 一律拒绝;
- 不递归跟随引用目标中的符号链接 (避免环与二次越界)。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from backend.data.file_reference_repo import (
    FileReference,
    FileReferenceRepository,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ReferenceHit",
    "current_project_id",
    "resolve_virtual",
]


@dataclass(frozen=True)
class ReferenceHit:
    """一次成功解析命中的引用记录。"""

    reference_id: str
    project_id: str
    alias_name: str
    rel_path: str
    target_path: str
    kind: str
    remainder: str = ""
    direct: bool = False


def current_project_id() -> Optional[str]:
    """当前会话绑定的项目 ID (session → workspace → projects); 失败 → None。"""
    try:
        from backend.data.database import get_database
        from backend.office.session_workspace import get_workspace_binding
        from backend.tools.context import current_tool_context

        ctx = current_tool_context()
        session_id = getattr(ctx, "session_id", None) if ctx else None
        if not session_id:
            return None
        conn = get_database().get_connection()
        binding = get_workspace_binding(conn, session_id)
        workspace = getattr(binding, "workspace_path", None) if binding else None
        if not workspace:
            return None
        row = conn.execute(
            "SELECT id FROM projects WHERE path = ?", (workspace,)
        ).fetchone()
        if row is None:
            return None
        return row[0]
    except Exception as exc:  # noqa: BLE001 — 解析失败按"无项目"处理 (fail-closed)
        logger.debug("current_project_id lookup failed: %s", exc)
        return None


def _is_within(base: str, candidate: str) -> bool:
    """candidate 是否等于 base 或位于其下 (按路径段边界, 大小写按平台)。"""
    try:
        base_norm = os.path.normcase(os.path.normpath(base))
        candidate_norm = os.path.normcase(os.path.normpath(candidate))
    except (OSError, ValueError):
        return False
    if candidate_norm == base_norm:
        return True
    separator = os.sep
    prefix = base_norm if base_norm.endswith(separator) else base_norm + separator
    return candidate_norm.startswith(prefix)


def _split_rel_text(raw_path: str) -> Optional[str]:
    """把输入规范成 ``a/b/c`` 形式; 含 ``..`` / NUL / 绝对形态 → None。"""
    if not raw_path or "\x00" in raw_path:
        return None
    text = raw_path.strip().replace("\\", "/")
    if not text or text.startswith("/") or (len(text) > 1 and text[1] == ":"):
        return None
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None
    return "/".join(parts)


def _match_reference(
    references: List[FileReference], rel_text: str
) -> Optional[Tuple[FileReference, str]]:
    """最长前缀匹配 (按路径段); 返回 (引用, 剩余相对部分)。"""
    best: Optional[Tuple[FileReference, str]] = None
    for reference in references:
        rel = reference.rel_path
        if rel_text == rel:
            remainder = ""
        elif rel_text.startswith(rel + "/"):
            remainder = rel_text[len(rel) + 1 :]
        else:
            continue
        if best is None or len(rel) > len(best[0].rel_path):
            best = (reference, remainder)
    return best


def _match_target(
    references: List[FileReference], absolute_text: str
) -> Optional[Tuple[FileReference, str]]:
    """绝对路径是否位于某个引用目标内 (最长目标前缀)。"""
    best: Optional[Tuple[FileReference, str]] = None
    for reference in references:
        if not _is_within(reference.target_path, absolute_text):
            continue
        remainder = os.path.relpath(absolute_text, reference.target_path)
        if remainder == ".":
            remainder = ""
        if best is None or len(reference.target_path) > len(best[0].target_path):
            best = (reference, remainder)
    return best


def _hit(reference: FileReference, remainder: str, direct: bool) -> ReferenceHit:
    return ReferenceHit(
        reference_id=reference.id,
        project_id=reference.project_id,
        alias_name=reference.alias_name,
        rel_path=reference.rel_path,
        target_path=reference.target_path,
        kind=reference.kind,
        remainder=remainder,
        direct=direct,
    )


def resolve_virtual(  # noqa: PLR0911 — 每条拒绝分支独立早返回, 便于逐条对照安全约束
    project_id: Optional[str], raw_path: str
) -> Tuple[Path, Optional[ReferenceHit]]:
    """把项目内虚拟路径翻译成真实路径。

    - ``raw_path`` 是绝对路径且落在某个引用目标内 → 原样返回 + ``direct`` 命中;
    - ``raw_path`` 是项目内相对路径且匹配引用前缀 → 拼接目标 + 剩余部分;
    - 无匹配 / 非法输入 / 拼接越界 → 原样返回 ``Path(raw_path)``, 命中为 None,
      由既有 workspace 逻辑决定放行或拒绝。
    """
    original = Path(raw_path)
    if not project_id:
        return original, None
    try:
        references = FileReferenceRepository().list_by_project(project_id)
    except Exception as exc:  # noqa: BLE001 — 查询失败 → 不翻译
        logger.debug("resolve_virtual: reference lookup failed: %s", exc)
        return original, None
    if not references:
        return original, None

    expanded = raw_path
    if expanded.startswith("~"):
        try:
            expanded = str(Path(expanded).expanduser())
        except (OSError, RuntimeError):
            return original, None

    if Path(expanded).is_absolute():
        matched = _match_target(references, os.path.normpath(expanded))
        if matched is None:
            return original, None
        reference, remainder = matched
        return Path(os.path.normpath(expanded)), _hit(reference, remainder, True)

    rel_text = _split_rel_text(expanded)
    if rel_text is None:
        return original, None
    matched = _match_reference(references, rel_text)
    if matched is None:
        return original, None

    reference, remainder = matched
    candidate = reference.target_path
    if remainder:
        candidate = os.path.join(candidate, remainder.replace("/", os.sep))
    candidate = os.path.normpath(candidate)

    # 拼接后必须仍在目标内 (防 ``..`` / 符号链接越界)
    try:
        resolved = os.path.realpath(candidate)
        target_real = os.path.realpath(reference.target_path)
    except (OSError, ValueError):
        return original, None
    if not _is_within(target_real, resolved):
        logger.warning(
            "resolve_virtual: rejected escape via reference %s: %s",
            reference.rel_path,
            raw_path,
        )
        return original, None
    return Path(candidate), _hit(reference, remainder, False)
