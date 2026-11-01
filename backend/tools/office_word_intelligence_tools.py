# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Word rule-pack tools (M6): audit / fix / extract / revise.

All tools require an active ToolExecutionContext and enforce the bound
workspace with ``_enforce_workspace`` + absolute .docx paths, matching the
existing office_lint_word / office_repair_word posture.

Risk classes:
- ``office_audit_word`` / ``office_extract_rules``: READ
- ``office_fix_word`` / ``office_revise_word``: WRITE_LOCAL
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from backend.domain.risk import RiskClass
from backend.tools.base import BaseTool, ToolResult, ToolSchema

_MAX_ISSUES_IN_TOOL = 200
_MAX_CANDIDATES_IN_TOOL = 100
_MAX_CHANGES_IN_TOOL = 200


def _workspace_root(policy: Any) -> Optional[str]:
    root = getattr(policy, "workspace_root", None)
    return str(root) if root else None


class _WordToolBase(BaseTool):
    requires_tool_context = True

    def _guard(self) -> Optional[ToolResult]:
        if self.requires_tool_context:
            from backend.tools.context import current_tool_context

            if current_tool_context() is None:
                return ToolResult(success=False, error="missing_tool_context")
        return None

    def _resolve_target(
        self, file_path: Any
    ) -> Tuple[Optional[Path], Optional[ToolResult]]:
        if not isinstance(file_path, str) or not file_path.strip():
            return None, ToolResult(success=False, error="file_path_required")
        blocked = self._enforce_workspace(file_path)
        if blocked is not None:
            return None, blocked
        target = Path(file_path).expanduser()
        if not target.is_absolute():
            return None, ToolResult(
                success=False, error="file_path_absolute_required: 请传绝对路径"
            )
        if target.suffix.lower() != ".docx":
            return None, ToolResult(
                success=False, error="unsupported_file_type: 仅支持 .docx"
            )
        if not target.is_file():
            return None, ToolResult(success=False, error="file_not_found")
        return target, None

    def _resolve_pack(
        self, rulepack: Any, rulepack_id: Any
    ) -> Tuple[Optional[Any], Optional[ToolResult]]:
        from pydantic import ValidationError

        from backend.office.errors import OfficeError
        from backend.office.word_rulepack_models import WordRulePack
        from backend.office.word_rulepack_store import (
            DEFAULT_RULEPACK_ID,
            load_rulepack,
        )

        if rulepack is not None:
            if not isinstance(rulepack, dict):
                return None, ToolResult(success=False, error="rulepack_invalid")
            try:
                return WordRulePack(**rulepack), None
            except ValidationError as exc:
                return None, ToolResult(
                    success=False, error=f"rulepack_invalid: {exc}"
                )
        root = _workspace_root(self._policy)
        try:
            loaded = load_rulepack(
                Path(root) if root else None,
                rulepack_id or DEFAULT_RULEPACK_ID,
            )
        except OfficeError as exc:
            return None, ToolResult(success=False, error=f"rulepack_load_failed: {exc}")
        return loaded["pack"], None


class OfficeAuditWordTool(_WordToolBase):
    """Deterministic rule-pack audit for a workspace .docx (READ)."""

    risk: RiskClass = RiskClass.READ

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_audit_word",
            description=(
                "用规则包对工作区内的 .docx 做确定性审校，返回带锚点/期望/实测/"
                "修复建议的问题清单。适合交付前自检或按期刊/公文规范检查；"
                "rulepack 可内联，否则使用 rulepack_id（缺省 general-quality）。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "工作区内 .docx 绝对路径",
                    },
                    "rulepack_id": {
                        "type": "string",
                        "description": "工作区/内置规则包 id",
                    },
                    "rulepack": {
                        "type": "object",
                        "description": "内联规则包（优先于 rulepack_id）",
                    },
                },
                "required": ["file_path"],
            },
        )

    def execute(
        self,
        file_path: Optional[str] = None,
        rulepack_id: Optional[str] = None,
        rulepack: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> ToolResult:
        blocked = self._guard()
        if blocked is not None:
            return blocked
        target, error = self._resolve_target(file_path)
        if error is not None:
            return error
        pack, error = self._resolve_pack(rulepack, rulepack_id)
        if error is not None:
            return error
        from backend.office.errors import OfficeError
        from backend.office.word_audit import audit_word_document

        root = _workspace_root(self._policy) or str(target.parent)
        try:
            result = audit_word_document(target, pack, workspace_path=root)
        except OfficeError as exc:
            return ToolResult(success=False, error=f"audit_failed: {exc}")
        data = result.model_dump()
        if len(data["issues"]) > _MAX_ISSUES_IN_TOOL:
            data["issues"] = data["issues"][:_MAX_ISSUES_IN_TOOL]
            data["issues_truncated"] = result.summary.issue_count - _MAX_ISSUES_IN_TOOL
        return ToolResult(success=True, content=data)


class OfficeFixWordTool(_WordToolBase):
    """Deterministic mechanical fixes + recheck (WRITE_LOCAL)."""

    risk: RiskClass = RiskClass.WRITE_LOCAL

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_fix_word",
            description=(
                "按规则包自动修复 .docx 可机械修复的违规（页面/样式/空段落），"
                "修复后用同一规则包复检。默认写 <stem>-fixed.docx 新文件；"
                "overwrite=true 才原子覆盖原文件。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "工作区内 .docx 绝对路径",
                    },
                    "rulepack_id": {"type": "string", "description": "规则包 id"},
                    "rulepack": {"type": "object", "description": "内联规则包（优先）"},
                    "output_filename": {
                        "type": "string",
                        "description": "输出文件名（默认 <stem>-fixed.docx）",
                    },
                    "overwrite": {"type": "boolean", "default": False},
                },
                "required": ["file_path"],
            },
        )

    def execute(
        self,
        file_path: Optional[str] = None,
        rulepack_id: Optional[str] = None,
        rulepack: Optional[Dict[str, Any]] = None,
        output_filename: Optional[str] = None,
        overwrite: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        blocked = self._guard()
        if blocked is not None:
            return blocked
        target, error = self._resolve_target(file_path)
        if error is not None:
            return error
        pack, error = self._resolve_pack(rulepack, rulepack_id)
        if error is not None:
            return error
        from backend.office.errors import OfficeError
        from backend.office.word_fix import fix_word_document

        root = _workspace_root(self._policy) or str(target.parent)
        try:
            result = fix_word_document(
                target,
                pack,
                output_filename,
                overwrite=bool(overwrite),
                workspace_path=root,
            )
        except OfficeError as exc:
            return ToolResult(success=False, error=f"fix_failed: {exc}")
        data = result.model_dump()
        remaining = data.get("remaining") or {}
        issues = remaining.get("issues") or []
        if len(issues) > _MAX_ISSUES_IN_TOOL:
            remaining["issues"] = issues[:_MAX_ISSUES_IN_TOOL]
            remaining["issues_truncated"] = len(issues) - _MAX_ISSUES_IN_TOOL
        return ToolResult(success=True, content=data)


class OfficeExtractRulesTool(_WordToolBase):
    """Deterministic rule extraction from a spec/template document (READ)."""

    risk: RiskClass = RiskClass.READ

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_extract_rules",
            description=(
                "从规范文档（.docx/.txt/.md）或 .docx 范本抽取候选规则包，"
                "返回规则、来源、置信度、冲突与 warning。抽取只读，不保存；"
                "确认后可用返回值作为 office_audit_word 的内联 rulepack。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "工作区内规范/范本文件绝对路径",
                    },
                    "file_type": {
                        "type": "string",
                        "enum": ["spec", "template"],
                        "default": "spec",
                    },
                    "pack_id": {"type": "string", "default": "extracted-pack"},
                    "pack_name": {"type": "string"},
                },
                "required": ["file_path"],
            },
        )

    def execute(  # noqa: PLR0911 — 逐项参数校验早退
        self,
        file_path: Optional[str] = None,
        file_type: str = "spec",
        pack_id: str = "extracted-pack",
        pack_name: Optional[str] = None,
        **kwargs: Any,
    ) -> ToolResult:
        blocked = self._guard()
        if blocked is not None:
            return blocked
        if not isinstance(file_path, str) or not file_path.strip():
            return ToolResult(success=False, error="file_path_required")
        blocked = self._enforce_workspace(file_path)
        if blocked is not None:
            return blocked
        target = Path(file_path).expanduser()
        if not target.is_absolute():
            return ToolResult(
                success=False, error="file_path_absolute_required: 请传绝对路径"
            )
        if target.suffix.lower() not in (".docx", ".txt", ".md"):
            return ToolResult(
                success=False, error="unsupported_file_type: 仅支持 .docx/.txt/.md"
            )
        if not target.is_file():
            return ToolResult(success=False, error="file_not_found")
        from backend.office.errors import OfficeError
        from backend.office.word_rule_extract import extract_word_rules

        root = _workspace_root(self._policy) or str(target.parent)
        try:
            result = extract_word_rules(
                target,
                file_type=file_type,
                pack_id=pack_id,
                pack_name=pack_name,
                workspace_path=root,
            )
        except OfficeError as exc:
            return ToolResult(success=False, error=f"extract_failed: {exc}")
        data = result.model_dump()
        if len(data.get("candidates") or []) > _MAX_CANDIDATES_IN_TOOL:
            data["candidates"] = data["candidates"][:_MAX_CANDIDATES_IN_TOOL]
        return ToolResult(success=True, content=data)


class OfficeReviseWordTool(_WordToolBase):
    """Write native tracked revisions/comments and re-audit (WRITE_LOCAL)."""

    risk: RiskClass = RiskClass.WRITE_LOCAL

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_revise_word",
            description=(
                "把规则包审校结果写成 Word 原生修订（w:ins/w:del）并可附批注，"
                "修订后用同一规则包复检。默认写 <stem>-revised.docx 新文件；"
                "overwrite=true 才原子覆盖。changes 可显式指定 find/replace，"
                "省略时自动生成（术语/日期等 fixable 项）。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "工作区内 .docx 绝对路径",
                    },
                    "rulepack_id": {"type": "string"},
                    "rulepack": {"type": "object"},
                    "changes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "find": {"type": "string"},
                                "replace": {"type": "string"},
                                "comment": {"type": "string"},
                                "rule_id": {"type": "string"},
                            },
                            "required": ["find"],
                        },
                    },
                    "output_filename": {"type": "string"},
                    "overwrite": {"type": "boolean", "default": False},
                    "add_comments": {"type": "boolean", "default": True},
                    "author": {"type": "string", "default": "Sage"},
                },
                "required": ["file_path"],
            },
        )

    def execute(  # noqa: PLR0911 — 逐项参数校验早退
        self,
        file_path: Optional[str] = None,
        rulepack_id: Optional[str] = None,
        rulepack: Optional[Dict[str, Any]] = None,
        changes: Optional[list] = None,
        output_filename: Optional[str] = None,
        overwrite: bool = False,
        add_comments: bool = True,
        author: str = "Sage",
        **kwargs: Any,
    ) -> ToolResult:
        blocked = self._guard()
        if blocked is not None:
            return blocked
        target, error = self._resolve_target(file_path)
        if error is not None:
            return error
        pack, error = self._resolve_pack(rulepack, rulepack_id)
        if error is not None:
            return error
        from backend.office.errors import OfficeError
        from backend.office.word_audit import audit_word_document
        from backend.office.word_revision_writer import (
            apply_word_revisions,
            build_revision_plan,
        )

        root = _workspace_root(self._policy) or str(target.parent)
        if changes is None:
            try:
                audit = audit_word_document(target, pack, workspace_path=root)
            except OfficeError as exc:
                return ToolResult(success=False, error=f"audit_failed: {exc}")
            raw_changes = build_revision_plan(audit.issues, pack)
        else:
            if not isinstance(changes, list):
                return ToolResult(success=False, error="changes_invalid")
            raw_changes = [change for change in changes if isinstance(change, dict)]
        if not raw_changes:
            return ToolResult(success=False, error="no_revisions_available")
        try:
            result = apply_word_revisions(
                target,
                raw_changes[:_MAX_CHANGES_IN_TOOL],
                output_filename,
                overwrite=bool(overwrite),
                author=author or "Sage",
                workspace_path=root,
                rule_pack_id=pack.id,
                add_comments=bool(add_comments),
            )
            output = (
                target if result.overwritten else Path(root) / Path(result.output_path)
            )
            remaining = audit_word_document(output, pack, workspace_path=root)
        except OfficeError as exc:
            return ToolResult(success=False, error=f"revise_failed: {exc}")
        data = result.model_copy(
            update={"remaining": remaining, "ok": remaining.ok}
        ).model_dump()
        issues = (data.get("remaining") or {}).get("issues") or []
        if len(issues) > _MAX_ISSUES_IN_TOOL:
            data["remaining"]["issues"] = issues[:_MAX_ISSUES_IN_TOOL]
            data["remaining"]["issues_truncated"] = (
                len(issues) - _MAX_ISSUES_IN_TOOL
            )
        return ToolResult(success=True, content=data)


__all__ = [
    "OfficeAuditWordTool",
    "OfficeExtractRulesTool",
    "OfficeFixWordTool",
    "OfficeReviseWordTool",
]
