"""Office create tool for the LLM tool loop.

``office_create`` lets the LLM generate a Word / Excel / PPT document to an
arbitrary (trusted) target directory -- e.g. the user's Desktop. Unlike the
existing ``office_list`` / ``office_read`` (which need an @-mention to bind a
``ToolExecutionContext``), ``requires_tool_context = False`` so the tool is
always visible and a plain question ("create a word doc on my desktop") can
trigger it directly.

Writing outside the session workspace is gated by two complementary layers:
(1) ``path_boundary_validator`` in the M1 ``PermissionEnforcer`` (see
permissions.py) upgrades a cross-workspace write to approval in the legacy
agent chain; (2) ``BaseTool._enforce_workspace`` in ``execute()`` rejects the
write outright when ``policy.workspace_root`` is bound (the hex chain).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from backend.domain.risk import RiskClass
from backend.office.excel import generate_xlsx
from backend.office.models import (
    OfficeDocType,
    OfficeExcelGenerateRequest,
    OfficePptGenerateRequest,
    OfficeWordGenerateRequest,
)
from backend.office.path_safety import OfficePathError, validate_supported_filename
from backend.office.ppt import generate_ppt
from backend.office.word import generate_docx
from backend.tools.base import BaseTool, ToolResult, ToolSchema
from backend.tools.file_tool import _record_artifact_safely

#: doc_type 参数合法取值（与 models.OfficeDocType 对齐）
_VALID_DOC_TYPES = tuple(t.value for t in OfficeDocType)


class OfficeCreateTool(BaseTool):
    """Generate an Office document (word/excel/ppt) to a target directory."""

    requires_tool_context = False
    risk = RiskClass.WRITE_LOCAL

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_create",
            description=(
                "Create a new Office document (Word/Excel/PPT) and write it to "
                "a target directory. Use when the user asks to create / generate "
                "a .docx/.xlsx/.pptx file (e.g. on their Desktop). `content` is "
                "an object whose shape depends on `doc_type`: word → "
                "{title, paragraphs:[{text, heading?}], tables:[{headers, rows[]}]}, "
                "excel → {sheets:[{name, headers[], rows[]}]}, ppt → "
                "{slides:[{title, bullets[], notes?}]}."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "doc_type": {
                        "type": "string",
                        "enum": list(_VALID_DOC_TYPES),
                        "description": "Document type to create.",
                    },
                    "output_dir": {
                        "type": "string",
                        "description": (
                            "Target directory (absolute or ~-prefixed, e.g. "
                            "~/Desktop). Directory is created if missing."
                        ),
                    },
                    "filename": {
                        "type": "string",
                        "description": (
                            "Output filename. Extension is appended if missing "
                            "(.docx/.xlsx/.pptx); a wrong extension is rejected."
                        ),
                    },
                    "content": {
                        "type": "object",
                        "description": "Structured content keyed by doc_type.",
                    },
                },
                "required": ["doc_type", "output_dir", "filename", "content"],
            },
        )

    def execute(
        self,
        doc_type: Optional[str] = None,
        output_dir: Optional[str] = None,
        filename: Optional[str] = None,
        content: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> ToolResult:
        # --- 参数校验（fail-fast） -----------------------------------------
        if doc_type not in _VALID_DOC_TYPES:
            return ToolResult(success=False, error=f"unsupported_doc_type: {doc_type}")
        if not isinstance(output_dir, str) or not output_dir.strip():
            return ToolResult(success=False, error="output_dir_required")
        if not isinstance(filename, str) or not filename.strip():
            return ToolResult(success=False, error="filename_required")
        if not isinstance(content, dict) or not content:
            return ToolResult(success=False, error="content_required")

        # --- 工作区边界：policy.workspace_root 绑定（hex 链）时拒绝越界写入 ----
        # 未绑定（legacy 链）时 ``_enforce_workspace`` 返回 None，零行为变化。
        blocked = self._enforce_workspace(output_dir)
        if blocked is not None:
            return blocked

        doc_type_enum = OfficeDocType(doc_type)

        # --- 路径守卫：目录必须是目录；目标文件已存在则拒绝（不覆盖） ------
        target_dir = Path(output_dir).expanduser().resolve()
        if target_dir.exists() and not target_dir.is_dir():
            return ToolResult(success=False, error="output_dir_not_directory")
        try:
            safe_name = validate_supported_filename(filename, doc_type_enum)
        except OfficePathError as exc:
            return ToolResult(success=False, error=str(exc))
        target_file = target_dir / safe_name
        if target_file.exists():
            return ToolResult(
                success=False,
                error=f"file_exists: {target_file} 已存在，请更换文件名",
            )

        # --- 构造生成请求并执行（复用生成器 + Pydantic 校验） --------------
        payload: Dict[str, Any] = dict(content)
        payload["workspace_path"] = ""
        payload["filename"] = filename
        try:
            if doc_type_enum is OfficeDocType.WORD:
                req = OfficeWordGenerateRequest(**payload)
                output = generate_docx(req, output_dir=str(target_dir))
            elif doc_type_enum is OfficeDocType.EXCEL:
                req = OfficeExcelGenerateRequest(**payload)
                output = generate_xlsx(req, output_dir=str(target_dir))
            else:
                req = OfficePptGenerateRequest(**payload)
                output = generate_ppt(req, output_dir=str(target_dir))
        except Exception as exc:
            return ToolResult(success=False, error=f"generate_failed: {exc}")

        stat = output.stat()

        # --- 记录 Artifacts（无 tool_context 时静默跳过，不阻断结果） ------
        # ``_record_artifact_safely`` 内部已吞掉一切异常，无需再包一层。
        _record_artifact_safely(str(output), stat.st_size)

        return ToolResult(
            success=True,
            content={
                "path": str(output),
                "filename": output.name,
                "bytes": stat.st_size,
            },
        )


__all__ = ["OfficeCreateTool"]
