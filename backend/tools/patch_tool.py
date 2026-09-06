"""多文件原子编辑工具（对标增强 Phase-2 T5，docs/plans/2026-09-06 G10）。

对标 Codex ``apply_patch``：一次调用内对**多个文件**（或同一文件多处）做
精确替换，**先整体校验、后统一落盘** —— 任一补丁校验失败则全部不写，
不会留下半套改动。单文件场景请用 ``edit_file``；本工具的价值在原子性与
跨文件一致性（重命名引用、接口变更等需要同时改多处才成立的编辑）。

复用 ``edit_tool`` 的既有加固设施：精确匹配 + 唯一性检查、写 10 MiB
限额、二进制嗅探、BOM 识别回写、``newline=""`` 行尾保留（CRLF 不被
静默改写）。同一文件出现多个补丁时按顺序链式生效（后一个匹配前一个
的产出）。文件创建仍归 ``write_file`` —— 不存在的路径整批拒绝。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.domain.risk import RiskClass

from .base import BaseTool, ToolResult, ToolSchema
from .edit_tool import (
    _count_logical_lines,
    _resolve_matches,
    _validate_edit_params,
    _validate_target_file,
)
from .file_tool import MAX_WRITE_SIZE_BYTES, detect_bom_encoding

logger = logging.getLogger(__name__)

_PATCH_KEYS = {"file_path", "old_string", "new_string", "replace_all"}

#: 单次 apply_patch 的补丁条数上限（防失控批量改写）
MAX_PATCHES_PER_CALL = 32


class _PlannedEdit:
    """校验通过的单文件编辑计划：同一文件的多个补丁链式叠加后的终态。"""

    __slots__ = ("path", "encoding", "updated", "replacements", "lines_added", "lines_removed")

    def __init__(self, path: Path, encoding: str, updated: str) -> None:
        self.path = path
        self.encoding = encoding
        self.updated = updated
        self.replacements = 0
        self.lines_added = 0
        self.lines_removed = 0


class ApplyPatchTool(BaseTool):
    """多文件原子精确编辑 —— 全部校验通过才落盘，任一失败整批放弃。"""

    risk = RiskClass.WRITE_LOCAL

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="apply_patch",
            description=(
                "对多个文件（或同一文件多处）原子化应用精确替换补丁："
                "所有补丁先整体校验（存在性/匹配唯一性/边界），任一失败则"
                "全部不写。每项 {file_path, old_string, new_string, replace_all?}，"
                "语义与 edit_file 一致；同一文件多项按顺序链式生效。"
                "批量改写前建议先 checkpoint_create 建检查点。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "patches": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "file_path": {"type": "string"},
                                "old_string": {"type": "string"},
                                "new_string": {"type": "string"},
                                "replace_all": {"type": "boolean"},
                            },
                            "required": ["file_path", "old_string", "new_string"],
                        },
                        "description": f"补丁列表（上限 {MAX_PATCHES_PER_CALL} 项）",
                    },
                },
                "required": ["patches"],
            },
        )

    def execute(self, patches: Optional[List[Dict[str, Any]]] = None, **kwargs: Any) -> ToolResult:
        if kwargs:
            return ToolResult(
                success=False,
                error=f"未知参数: {', '.join(sorted(kwargs))}（合法参数: patches）",
            )
        if not isinstance(patches, list) or not patches:
            return ToolResult(success=False, error="patches 必须是非空列表")
        if len(patches) > MAX_PATCHES_PER_CALL:
            return ToolResult(
                success=False,
                error=f"补丁数量 {len(patches)} 超过单次上限 {MAX_PATCHES_PER_CALL}",
            )

        root = self._policy.workspace_root
        if not root:
            return ToolResult(
                success=False, error="apply_patch 需要绑定工作区（workspace）"
            )

        plan, rejection = self._validate_plan(root, patches)
        if rejection is not None:
            return rejection
        return self._write_all(plan)

    def _validate_plan(
        self, root: str, patches: List[Dict[str, Any]]
    ) -> Tuple[List[_PlannedEdit], Optional[ToolResult]]:
        """只读校验阶段：全部补丁在内存中推演终态，任何失败整批拒绝。

        相对路径一律按工作区根解析（与 bash 的 cwd 参数同口径），不按
        进程 CWD —— 后者随启动目录漂移。
        """
        planned: Dict[str, _PlannedEdit] = {}

        for index, patch in enumerate(patches):
            rejection = self._validate_patch_shape(index, patch)
            if rejection is not None:
                return [], rejection

            file_path: str = patch["file_path"]
            old_string: str = patch["old_string"]
            new_string: str = patch["new_string"]
            replace_all = bool(patch.get("replace_all", False))

            param_error = _validate_edit_params(old_string, new_string)
            if param_error is not None:
                return [], self._with_index(index, param_error)

            absolute = os.path.abspath(os.path.join(root, file_path))
            blocked = self._enforce_workspace(absolute)
            if blocked is not None:
                return [], self._with_index(index, blocked)

            planned_edit = planned.get(absolute)
            if planned_edit is None:
                target = Path(absolute)
                load_error, original, encoding = self._load_original(target, file_path)
                if load_error is not None:
                    return [], self._with_index(index, load_error)
                planned_edit = _PlannedEdit(target, encoding, original or "")
                planned[absolute] = planned_edit

            match_count, match_error = _resolve_matches(
                planned_edit.updated, old_string, replace_all
            )
            if match_error is not None:
                return [], self._with_index(index, match_error)

            replacements = match_count if replace_all else 1
            planned_edit.updated = planned_edit.updated.replace(
                old_string, new_string
            ) if replace_all else planned_edit.updated.replace(old_string, new_string, 1)
            planned_edit.replacements += replacements
            planned_edit.lines_added += _count_logical_lines(new_string) * replacements
            planned_edit.lines_removed += _count_logical_lines(old_string) * replacements

        return list(planned.values()), None

    @staticmethod
    def _load_original(
        target: Path, file_path: str
    ) -> Tuple[Optional[ToolResult], Optional[str], Optional[str]]:
        """读取原文件（edit_tool 同款前置检查 + BOM 感知 + 行尾保留）。

        返回 ``(拒绝结果, 原文, 编码)``；拒绝时后两者为 None。
        """
        file_error = _validate_target_file(target, file_path)
        if file_error is not None:
            return file_error, None, None
        encoding = detect_bom_encoding(target) or "utf-8"
        try:
            # newline="" 关闭通用换行转换：CRLF / CR / LF 原样保留，
            # 回写不做换行翻译（read_text 默认会把整个 CRLF 文件静默改成 LF）
            with open(str(target), encoding=encoding, newline="") as handle:
                return None, handle.read(), encoding
        except UnicodeDecodeError as exc:
            return (
                ToolResult(success=False, error=f"文件解码失败（{encoding}）: {exc}"),
                None,
                None,
            )
        except OSError as exc:
            return ToolResult(success=False, error=f"读取失败: {exc}"), None, None

    @staticmethod
    def _validate_patch_shape(index: int, patch: Any) -> Optional[ToolResult]:
        """单条补丁的形态检查：dict / 必需键 / 类型 / 未登记键。"""
        if not isinstance(patch, dict):
            return ApplyPatchTool._with_index(
                index, ToolResult(success=False, error="补丁必须是对象 {file_path, old_string, new_string}")
            )
        unknown = set(patch) - _PATCH_KEYS
        if unknown:
            return ApplyPatchTool._with_index(
                index,
                ToolResult(
                    success=False,
                    error=f"未知字段: {', '.join(sorted(unknown))}（合法字段: "
                    "file_path, old_string, new_string, replace_all）",
                ),
            )
        for key in ("file_path", "old_string", "new_string"):
            if key not in patch or not isinstance(patch[key], str):
                return ApplyPatchTool._with_index(
                    index, ToolResult(success=False, error=f"缺少必需字段 {key}（或其不是字符串）")
                )
        if "file_path" in patch and not patch["file_path"].strip():
            return ApplyPatchTool._with_index(
                index, ToolResult(success=False, error="file_path 不能为空")
            )
        if "replace_all" in patch and not isinstance(patch["replace_all"], bool):
            return ApplyPatchTool._with_index(
                index, ToolResult(success=False, error="replace_all 必须是布尔值")
            )
        return None

    @staticmethod
    def _with_index(index: int, rejection: ToolResult) -> ToolResult:
        """把失败的补丁序号拼进错误信息（LLM 可定位第几条出问题）。"""
        return ToolResult(
            success=False,
            error=f"patches[{index}] 校验失败，整批未写入: {rejection.error}",
        )

    def _write_all(self, plan: List[_PlannedEdit]) -> ToolResult:
        """校验通过后的落盘阶段；写失败的文件如实上报（校验阶段已排除绝大多数风险）。"""
        written: List[Dict[str, Any]] = []
        for planned_edit in plan:
            updated_bytes = planned_edit.updated.encode(planned_edit.encoding)
            if len(updated_bytes) > MAX_WRITE_SIZE_BYTES:
                return ToolResult(
                    success=False,
                    error=(
                        f"content_too_large: {planned_edit.path} 编辑后 "
                        f"{len(updated_bytes)} 字节超过写入上限 "
                        f"{MAX_WRITE_SIZE_BYTES} 字节 (10 MiB)"
                    ),
                )
            try:
                planned_edit.path.write_bytes(updated_bytes)
            except OSError as exc:
                return ToolResult(
                    success=False,
                    error=(
                        f"写入失败（{planned_edit.path}）: {exc}；"
                        f"已写入 {len(written)}/{len(plan)} 个文件，"
                        "可用 checkpoint_restore 恢复"
                    ),
                )
            written.append(
                {
                    "path": str(planned_edit.path.resolve()),
                    "replacements": planned_edit.replacements,
                    "lines_added": planned_edit.lines_added,
                    "lines_removed": planned_edit.lines_removed,
                }
            )
        return ToolResult(
            success=True,
            content={"files_changed": written, "count": len(written)},
        )


__all__ = ["ApplyPatchTool", "MAX_PATCHES_PER_CALL"]
