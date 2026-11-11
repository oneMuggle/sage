# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""工作区快照与 diff 工具 — execute_code/bash_tool 执行后扫描新增/修改文件。

``execute_code`` / ``bash`` 可以在脚本或命令里任意创建、修改文件 —— 这些
写操作不经过 ``write_file`` 的产物桥接，产物面板会漏掉脚本产物。本模块在
工具执行**前后**各拍一次工作区快照，把新增/修改的文件补记为 artifact。

设计取舍：

- 快照只做 ``stat``（不读文件内容），成本随文件数量线性增长；
- 遍历时剪枝隐藏目录 / 依赖目录（``node_modules``、``__pycache__`` 等），
  并过滤隐藏文件与编译/临时产物，避免把噪音写进产物表；
- 文件数与实际记录数都有上限，防止超大工作区拖慢工具执行或造成产物洪水；
- 所有扫描/记录失败一律静默（best-effort）—— **绝不**影响工具本身结果。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

#: 单次快照最多统计的文件数（超出后跳过的文件不会进入 diff）
MAX_SCAN_FILES = 5000

#: 单次 diff 最多记录的新增/修改文件数（防止一次生成海量文件刷屏产物表）
MAX_RECORDED_FILES = 500

#: 遍历剪枝目录（依赖目录 / 缓存 / 版本控制元数据）
EXCLUDED_DIRS = frozenset(
    {
        "node_modules",
        "__pycache__",
        "venv",
        "site-packages",
        "target",
        ".git",
        ".hg",
        ".svn",
        ".venv",
        ".sage",
        ".llm-wiki",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        ".idea",
        ".vscode",
        ".next",
        ".turbo",
    }
)

#: 忽略的编译/临时产物后缀（不是用户想看的产物）
EXCLUDED_SUFFIXES = frozenset(
    {
        ".pyc",
        ".pyo",
        ".pyd",
        ".class",
        ".o",
        ".obj",
        ".a",
        ".so",
        ".dylib",
        ".dll",
        ".exe",
        ".tmp",
        ".temp",
        ".swp",
        ".swo",
    }
)

#: 忽略的操作系统垃圾文件
EXCLUDED_NAMES = frozenset({".DS_Store", "Thumbs.db", "desktop.ini"})


def _is_excluded_file(name: str) -> bool:
    """文件名层面是否应忽略（隐藏 / 系统垃圾 / 编译临时产物 / Office 锁文件）。"""
    if not name or name.startswith("."):
        return True
    if name in EXCLUDED_NAMES:
        return True
    if name.startswith("~$"):  # Office 临时锁文件
        return True
    return Path(name).suffix.lower() in EXCLUDED_SUFFIXES


def snapshot_workspace(workspace_path: Path) -> Dict[str, float]:
    """返回 ``{relative_path: mtime}``，跳过不可访问的文件与忽略项。

    ``workspace_path`` 不存在或不可遍历时返回空 dict（不抛异常）。
    """
    result: Dict[str, float] = {}
    try:
        ws = Path(workspace_path)
        if not ws.is_dir():
            return result
        for dirpath, dirnames, filenames in os.walk(ws):
            # 原地修改 dirnames 才能让 os.walk 剪枝（隐藏目录 + 依赖/缓存目录）
            dirnames[:] = sorted(
                d for d in dirnames if not d.startswith(".") and d not in EXCLUDED_DIRS
            )
            for name in sorted(filenames):
                if len(result) >= MAX_SCAN_FILES:
                    logger.debug(
                        "snapshot_workspace: 达到 %d 文件上限，截断扫描", MAX_SCAN_FILES
                    )
                    return result
                if _is_excluded_file(name):
                    continue
                abs_path = Path(dirpath) / name
                try:
                    # 符号链接可能指向工作区外 —— 一律不记录（避免越界读/写猜测）
                    if abs_path.is_symlink():
                        continue
                    rel = str(abs_path.relative_to(ws))
                    result[rel] = abs_path.stat().st_mtime
                except (OSError, ValueError):
                    continue
    except OSError as exc:  # noqa: BLE001 — 快照失败按空处理
        logger.warning("snapshot_workspace failed: %s", exc)
    return result


def diff_and_record(
    workspace_path: Path,
    before: Dict[str, float],
    session_id: str,
    tool_call_id: Optional[str] = None,
) -> int:
    """比较 ``before`` 与当前工作区，把新增/修改的文件记录为 artifact。

    Returns:
        实际记录的文件数（受 ``MAX_RECORDED_FILES`` 限制）。
    """
    if not session_id:
        return 0
    ws = Path(workspace_path)
    after = snapshot_workspace(ws)
    count = 0
    for rel_path in sorted(after):
        mtime = after[rel_path]
        if rel_path in before and before[rel_path] >= mtime:
            continue  # 未变化
        abs_path = ws / rel_path
        try:
            size = abs_path.stat().st_size
        except OSError:
            continue
        # 延迟导入：file_tool 依赖面较大，避免模块导入期的潜在循环
        from backend.tools.file_tool import _record_artifact_safely

        _record_artifact_safely(
            resolved_path=str(abs_path),
            size=size,
            workspace_path=str(ws),
            session_id=session_id,
            tool_call_id=tool_call_id,
        )
        count += 1
        if count >= MAX_RECORDED_FILES:
            logger.debug(
                "diff_and_record: 达到 %d 文件上限，剩余变更不再记录",
                MAX_RECORDED_FILES,
            )
            break
    return count


def resolve_workspace_root(policy: Any) -> Optional[Path]:
    """确定扫描根目录：显式 ``policy.workspace_root`` 优先，否则回退会话绑定。

    主聊天路径构造工具时 ``ToolPolicy`` 通常不带 ``workspace_root``（安全边界
    由会话工作区绑定决定），因此必须回退到当前 session 的绑定，否则扫描永远
    是空操作。任一步失败都返回 ``None``（不扫描）。
    """
    root = getattr(policy, "workspace_root", None)
    if root:
        try:
            candidate = Path(root)
            return candidate if candidate.is_dir() else None
        except (OSError, ValueError):
            return None
    try:
        from backend.data.database import get_database
        from backend.office.session_workspace import get_workspace_binding
        from backend.tools.context import current_tool_context

        ctx = current_tool_context()
        session_id = getattr(ctx, "session_id", None) if ctx is not None else None
        if not session_id:
            return None
        binding = get_workspace_binding(get_database().get_connection(), session_id)
        if binding is None:
            return None
        candidate = Path(binding.workspace_path)
        return candidate if candidate.is_dir() else None
    except Exception:  # noqa: BLE001 — 解析失败按"无工作区"处理
        logger.debug("resolve_workspace_root failed", exc_info=True)
        return None


def record_workspace_changes(
    workspace_path: Optional[Path],
    before: Optional[Dict[str, float]],
    tool_call_id: Optional[str] = None,
) -> int:
    """端到端助手：从当前工具上下文取 ``session_id``，diff 并记录。

    best-effort：任何异常都吞掉并返回 0，保证调用方工具结果不受影响。
    """
    if workspace_path is None or before is None:
        return 0
    try:
        from backend.tools.context import current_tool_context

        ctx = current_tool_context()
        session_id = getattr(ctx, "session_id", None) if ctx is not None else None
        if not session_id:
            return 0
        return diff_and_record(workspace_path, before, session_id, tool_call_id)
    except Exception:  # noqa: BLE001 — 扫描失败绝不影响工具执行
        logger.debug("record_workspace_changes failed", exc_info=True)
        return 0


__all__ = [
    "MAX_RECORDED_FILES",
    "MAX_SCAN_FILES",
    "diff_and_record",
    "record_workspace_changes",
    "resolve_workspace_root",
    "snapshot_workspace",
]
