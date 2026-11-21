"""OOXML maintenance tool (M5) — ``office_ooxml``.

Actions:
- ``validate``: structural validation + optional xml:space repair
- ``merge_runs``: coalesce adjacent same-format runs in a .docx

file_path 模式沿用 office 工具的工作区围栏（policy workspace_root /
session binding），绝对路径 + 后缀白名单。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from backend.domain.risk import RiskClass
from backend.tools.base import BaseTool, ToolResult, ToolSchema


class OfficeOoxmlTool(BaseTool):
    """OOXML validate / merge-runs maintenance (WRITE_LOCAL)."""

    risk: RiskClass = RiskClass.WRITE_LOCAL
    requires_tool_context = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_ooxml",
            description=(
                "OOXML 维护工具。action=validate：校验 docx/xlsx/pptx 的 ZIP 结构、"
                "必需部件、XML 合法性与 DTD 拒绝；auto_repair=true 时修复缺失的 "
                "xml:space 并输出 <stem>-repaired.<ext>。action=merge_runs：合并 "
                "docx 中相邻且格式相同的 run（提升 find/replace 与文本锚点可靠性），"
                "默认输出 <stem>-merged.docx（overwrite=true 才原地替换）。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["validate", "merge_runs"],
                    },
                    "file_path": {
                        "type": "string",
                        "description": "工作区内 .docx/.xlsx/.pptx 的绝对路径",
                    },
                    "auto_repair": {
                        "type": "boolean",
                        "description": "validate 时修复 xml:space 缺失并输出新文件",
                    },
                    "output_filename": {
                        "type": "string",
                        "description": "merge_runs 的输出文件名（默认 <stem>-merged.docx）",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": "merge_runs 时原地替换源文件",
                    },
                },
                "required": ["action", "file_path"],
            },
        )

    def execute(  # noqa: PLR0911 — 参数/围栏/动作分派逐条早退
        self,
        action: Optional[str] = None,
        file_path: Optional[str] = None,
        auto_repair: bool = False,
        output_filename: Optional[str] = None,
        overwrite: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        from backend.tools.context import current_tool_context

        if current_tool_context() is None:
            return ToolResult(success=False, error="missing_tool_context")
        action_value = str(action or "").strip().lower()
        if action_value not in ("validate", "merge_runs"):
            return ToolResult(success=False, error="action_invalid: validate|merge_runs")
        if not isinstance(file_path, str) or not file_path.strip():
            return ToolResult(success=False, error="file_path_required")

        blocked = self._enforce_workspace(file_path)
        if blocked is not None:
            return blocked
        target = Path(file_path).expanduser()
        if not target.is_absolute():
            return ToolResult(success=False, error="file_path_absolute_required")
        if target.suffix.lower() not in (".docx", ".xlsx", ".pptx"):
            return ToolResult(success=False, error="unsupported_file_type")
        if not target.is_file():
            return ToolResult(success=False, error="file_not_found")

        workspace = self._workspace_for(target)
        from backend.office.errors import OfficeError
        from backend.office.ooxml import (
            OoxmlMergeRunsRequest,
            OoxmlValidateRequest,
            merge_docx_runs,
            validate_ooxml,
        )

        try:
            if action_value == "validate":
                result = validate_ooxml(
                    OoxmlValidateRequest(
                        workspace_path=str(workspace),
                        file_path=str(target),
                        auto_repair=bool(auto_repair),
                    )
                )
                return ToolResult(success=result.valid, content=result.model_dump())
            if target.suffix.lower() != ".docx":
                return ToolResult(success=False, error="merge_runs_requires_docx")
            merge_result = merge_docx_runs(
                OoxmlMergeRunsRequest(
                    workspace_path=str(workspace),
                    file_path=str(target),
                    output_filename=output_filename,
                    overwrite=bool(overwrite),
                )
            )
            return ToolResult(success=True, content=merge_result.model_dump())
        except OfficeError as exc:
            return ToolResult(success=False, error=f"ooxml_failed: {exc}")
        except Exception as exc:  # noqa: BLE001 — 其余异常折叠为工具错误
            return ToolResult(success=False, error=f"ooxml_failed: {type(exc).__name__}")

    def _workspace_for(self, target: Path) -> Path:
        root = getattr(self._policy, "workspace_root", None)
        if root:
            return Path(root)
        from backend.tools.context import current_tool_context

        ctx = current_tool_context()
        if ctx is not None and ctx.session_id:
            try:
                from backend.data.database import get_database
                from backend.office.session_workspace import get_active_workspace

                binding = get_active_workspace(
                    get_database().get_connection(),
                    ctx.session_id,
                    expected_generation=ctx.binding_generation,
                )
                if binding is not None:
                    return Path(binding.workspace_path)
            except Exception:  # noqa: BLE001 — 无绑定/DB 异常回退文件父目录
                pass
        return target.parent
