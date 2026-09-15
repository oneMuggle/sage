# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""BibTeX 解析工具（Round 9）—— ``office_parse_bibtex``。

把用户的 .bib 文件内容解析为结构化 ReferenceSpec 列表，供 LLM 后续把
条目（含 key）装进 ``office_create`` 的 ``references`` + 段落
``citations`` 完成引用闭环。纯文本解析（:mod:`backend.office.bibtex`），
无文件系统访问、无网络：

- ``requires_tool_context = False``（与 office_read_pdf 等工作区读工具
  不同：入参是文本本身，不触工作区/文件系统，schema 常驻可见）；
- ``risk = READ``：解析不落盘；
- 输出为 references 的 JSON 数组（含 key/type/authors 等全字段），
  LLM 可直接取 ``content.references`` 传回 office_create。

Public surface:

    OfficeBibTexTool(policy=None)   # name="office_parse_bibtex"
"""

from __future__ import annotations

from typing import Any, Optional

from backend.domain.risk import RiskClass
from backend.tools.base import BaseTool, ToolResult, ToolSchema


class OfficeBibTexTool(BaseTool):
    """解析 BibTeX 文本为结构化参考文献（READ，无副作用）。"""

    risk: RiskClass = RiskClass.READ
    # 纯文本解析：不读工作区/文件系统/网络，无需 ToolExecutionContext
    # （区别于 office_read_pdf 等按 doc_id/file_path 访问工作区的读工具）。
    requires_tool_context = False

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="office_parse_bibtex",
            description=(
                "解析 BibTeX(.bib) 文本为结构化参考文献列表（零外发、不落盘）。"
                "用户给你 .bib 内容或文件内容时先调本工具，再把返回的 "
                "references 条目传入 office_create 的 content.references，"
                "并在段落 citations 里用条目 key 回链生成文中 [N] 标记与"
                "文末参考文献表。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "BibTeX 文本（.bib 文件的完整内容）",
                    },
                },
                "required": ["text"],
            },
        )

    def execute(self, text: Optional[str] = None, **kwargs: Any) -> ToolResult:
        if not isinstance(text, str) or not text.strip():
            return ToolResult(success=False, error="text_required")
        try:
            from backend.office.bibtex import parse_bibtex

            references = parse_bibtex(text)
        except Exception as exc:
            return ToolResult(success=False, error=f"parse_failed: {exc}")
        return ToolResult(
            success=True,
            content={
                "count": len(references),
                # ReferenceSpec → dict（pydantic v2），JSON 安全直接回显
                "references": [ref.model_dump() for ref in references],
            },
        )
