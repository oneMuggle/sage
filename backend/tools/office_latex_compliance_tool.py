# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""LaTeX compliance tool — ``office_check_latex_compliance``."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.domain.risk import RiskClass
from backend.tools.base import BaseTool, ToolResult, ToolSchema


def _require_context() -> Optional[ToolResult]:
    from backend.tools.context import current_tool_context

    if current_tool_context() is None:
        return ToolResult(success=False, error="missing_tool_context")
    return None


def _string_list(value: Any) -> List[str]:
    if not isinstance(value, (list, tuple)):  # noqa: UP038 — py38 runtime isinstance
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _positive_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


class OfficeCheckLatexComplianceTool(BaseTool):
    """Check .tex + optional PDF against an inline compliance profile (READ)."""

    risk: RiskClass = RiskClass.READ
    requires_tool_context = True

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_check_latex_compliance",
            description=(
                "按投稿规范检查工作区 .tex（可选同时检查 PDF）：必需章节/元数据、"
                "页数/页面尺寸、字体嵌入、图片 DPI、禁用命令。只读，不修改文件、"
                "不执行 TeX。返回 checks 与带文件/页码锚点的问题列表。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "tex_path": {
                        "type": "string",
                        "description": "工作区内 .tex 主文件绝对路径",
                    },
                    "pdf_path": {
                        "type": "string",
                        "description": "可选：工作区内编译后的 .pdf 绝对路径",
                    },
                    "required_sections": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "必需章节标题（如 Introduction, Conclusion）",
                    },
                    "required_metadata": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "必需元数据：document_class/title/author/abstract/"
                            "keywords/affiliation/email/date"
                        ),
                    },
                    "allowed_page_sizes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "允许的页面尺寸：A4/Letter/Legal",
                    },
                    "required_min_pages": {"type": "integer"},
                    "required_max_pages": {"type": "integer"},
                    "require_embedded_fonts": {
                        "type": "boolean",
                        "description": "是否要求全部字体嵌入（默认 true）",
                    },
                    "min_image_dpi": {
                        "type": "number",
                        "description": "图片有效 DPI 阈值（默认 150）",
                    },
                    "forbidden_commands": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "禁用命令名，不含反斜杠（如 write18、todo）",
                    },
                },
                "required": ["tex_path"],
            },
        )

    def execute(  # noqa: PLR0911
        self,
        tex_path: Optional[str] = None,
        pdf_path: Optional[str] = None,
        required_sections: Any = None,
        required_metadata: Any = None,
        allowed_page_sizes: Any = None,
        required_min_pages: Any = None,
        required_max_pages: Any = None,
        require_embedded_fonts: Any = True,
        min_image_dpi: Any = 150.0,
        forbidden_commands: Any = None,
        **kwargs: Any,
    ) -> ToolResult:
        blocked = _require_context()
        if blocked is not None:
            return blocked
        if not isinstance(tex_path, str) or not tex_path.strip():
            return ToolResult(success=False, error="tex_path_required")
        blocked = self._enforce_workspace(tex_path)
        if blocked is not None:
            return blocked
        tex = Path(tex_path).expanduser()
        if not tex.is_absolute():
            return ToolResult(success=False, error="tex_path_absolute_required")
        if tex.suffix.lower() not in (".tex", ".ltx"):
            return ToolResult(success=False, error="unsupported_file_type")
        if not tex.is_file():
            return ToolResult(success=False, error="file_not_found")

        pdf: Optional[Path] = None
        if isinstance(pdf_path, str) and pdf_path.strip():
            blocked = self._enforce_workspace(pdf_path)
            if blocked is not None:
                return blocked
            pdf = Path(pdf_path).expanduser()
            if not pdf.is_absolute():
                return ToolResult(success=False, error="pdf_path_absolute_required")
            if pdf.suffix.lower() != ".pdf":
                return ToolResult(success=False, error="unsupported_file_type")
            if not pdf.is_file():
                return ToolResult(success=False, error="file_not_found")

        try:
            dpi = float(min_image_dpi)
        except (TypeError, ValueError):
            dpi = 150.0
        dpi = max(1.0, min(dpi, 2400.0))

        profile: Dict[str, Any] = {
            "required_sections": _string_list(required_sections),
            "required_metadata": _string_list(required_metadata),
            "allowed_page_sizes": _string_list(allowed_page_sizes),
            "required_min_pages": _positive_int(required_min_pages),
            "required_max_pages": _positive_int(required_max_pages),
            "require_embedded_fonts": bool(require_embedded_fonts),
            "min_image_dpi": dpi,
            "forbidden_commands": _string_list(forbidden_commands),
        }

        from backend.office.errors import OfficeError
        from backend.office.latex.service import check_latex_compliance_service

        root = Path(self._policy.workspace_root or str(tex.parent))
        try:
            result = check_latex_compliance_service(
                tex,
                workspace=root,
                pdf_path=pdf,
                profile=profile,
            )
        except OfficeError as exc:
            return ToolResult(success=False, error=f"latex_compliance_failed: {exc}")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, error=f"latex_compliance_failed: {exc}")
        return ToolResult(success=True, content=result)


__all__ = ["OfficeCheckLatexComplianceTool"]
