# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""U19: 会话工作区变更的部分撤销（逐文件 / 逐 hunk）。

对标增强第四轮批次 B（docs/plans/2026-09-07_coding-agent-parity-round4.md）。
此前变更面板只读，用户对 agent 的改动只有"整体接受"或"checkpoint 整体回滚"
两个粒度；本模块提供更细的控制面（用户在 UI 显式触发，非 LLM 工具）：

- ``revert_files``：把工作区改动恢复到 index/HEAD（``git checkout --``）；
  未跟踪文件需显式 ``delete_untracked`` 才删除。
- ``revert_hunks``：对该路径的未暂存 unified diff 按 ``@@`` 切 hunk，
  取所选子集重建补丁后 ``git apply --reverse``。git apply 天然原子：
  任一 hunk 应用失败则整体不动盘。

纯函数（``split_hunks`` / ``build_hunk_patch``）与 git 执行分离，可单测。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from backend.tools.git_tool import _run_git

logger = logging.getLogger(__name__)


def guard_rel_path(root: str, path: str) -> Optional[str]:
    """校验 path 是仓库根下的相对路径且不越界;返回错误文案或 None。"""
    if not path or not path.strip():
        return "path 不能为空"
    if Path(path).is_absolute() or path.startswith("\\\\"):
        return f"path 必须是相对仓库根的相对路径: {path}"
    absolute = os.path.abspath(os.path.join(root, path))
    root_abs = os.path.abspath(root)
    try:
        if os.path.commonpath([absolute, root_abs]) != root_abs:
            return f"path 越出工作区边界: {path}"
    except ValueError:  # Windows 跨盘符
        return f"path 越出工作区边界: {path}"
    return None


def split_hunks(diff_text: str) -> List[str]:
    """把 unified diff 切成带文件头的 hunk 补丁段列表。

    每个元素 = 文件头（diff --git / index / --- / +++）+ 一个 @@ hunk，
    独立可 ``git apply``。空 diff 或无 hunk → 空列表。
    """
    hunks: List[str] = []
    header_lines: List[str] = []
    current: Optional[List[str]] = None

    def _flush() -> None:
        nonlocal current
        if current:
            hunks.append("".join(header_lines + current))
        current = None

    for line in diff_text.splitlines(keepends=True):
        if line.startswith("diff --git"):
            _flush()
            header_lines = [line]
        elif line.startswith("@@"):
            _flush()
            current = [line]
        elif current is not None:
            current.append(line)
        else:
            header_lines.append(line)
    _flush()
    return hunks


def build_hunk_patch(diff_text: str, hunk_indices: List[int]) -> Tuple[str, Optional[str]]:
    """按 0-based 序号取 hunk 子集重建补丁;越界返回 ("" , 错误文案)。"""
    hunks = split_hunks(diff_text)
    if not hunks:
        return "", "diff 中未解析到 hunk"
    selected: List[str] = []
    for idx in hunk_indices:
        if not isinstance(idx, int) or isinstance(idx, bool) or idx < 0 or idx >= len(hunks):
            return "", f"hunk 序号越界: {idx}（共 {len(hunks)} 个 hunk，0-based）"
        selected.append(hunks[idx])
    return "".join(selected), None


def revert_files(
    root: str,
    paths: List[str],
    delete_untracked: bool = False,
) -> Tuple[List[str], List[Dict[str, str]]]:
    """逐文件撤销工作区改动;返回 (成功路径, 失败明细)。

    语义：``git checkout -- <path>`` 把工作区恢复到 index（无暂存则 HEAD），
    不动暂存区——用户自己暂存的内容不会被破坏。仅暂存（工作区干净）的
    文件明确报错而不是静默成功。
    """
    reverted: List[str] = []
    errors: List[Dict[str, str]] = []
    for path in paths:
        error = guard_rel_path(root, path)
        if error is not None:
            errors.append({"path": path, "error": error})
            continue

        status_out, error = _run_git(["status", "--porcelain=v1", "--", path], root)
        if error is not None:
            errors.append({"path": path, "error": error})
            continue
        lines = [line for line in (status_out or "").splitlines() if line.strip()]
        if not lines:
            errors.append({"path": path, "error": "该路径没有未提交变更"})
            continue

        entry = lines[0]
        index_status = entry[:1].strip()
        worktree_status = entry[1:2].strip()
        porcelain_path = entry[3:]
        targets = porcelain_path.split(" -> ") if " -> " in porcelain_path else [porcelain_path]

        if index_status == "?" and worktree_status == "?":
            # 未跟踪文件：git checkout 无从恢复，只能删除（显式授权）
            if not delete_untracked:
                errors.append({
                    "path": path,
                    "error": "未跟踪文件需显式 delete_untracked=true 才会删除",
                })
                continue
            try:
                Path(root, porcelain_path).unlink()
                reverted.append(path)
            except OSError as exc:
                errors.append({"path": path, "error": f"删除失败: {exc}"})
            continue

        if not worktree_status:
            errors.append({
                "path": path,
                "error": "该文件的变更只在暂存区，面板撤销只作用于工作区改动",
            })
            continue

        _, error = _run_git(["checkout", "--", *targets], root)
        if error is not None:
            errors.append({"path": path, "error": error})
            continue
        reverted.append(path)
    return reverted, errors


def revert_hunks(
    root: str,
    path: str,
    hunk_indices: List[int],
) -> Tuple[int, Optional[str]]:
    """按 hunk 子集反向应用未暂存 diff;返回 (成功 hunk 数, 错误文案)。

    序号 0-based，与 GET /changes/diff 输出的 hunk 顺序一致。git apply
    原子：失败时磁盘不动。
    """
    diff_out, error = _run_git(["diff", "--no-color", "--", path], root)
    if error is not None:
        return 0, error
    if not (diff_out or "").strip():
        return 0, "该路径没有工作区 diff（未暂存改动），无法按 hunk 撤销"

    patch, error = build_hunk_patch(diff_out, hunk_indices)
    if error is not None:
        return 0, error

    _, error = _run_git(
        ["apply", "--reverse", "--recount", "--whitespace=nowarn"],
        root,
        input_bytes=patch.encode("utf-8"),
    )
    if error is not None:
        return 0, f"git apply --reverse 失败: {error}"
    return len(hunk_indices), None


__all__ = [
    "build_hunk_patch",
    "guard_rel_path",
    "revert_files",
    "revert_hunks",
    "split_hunks",
]
