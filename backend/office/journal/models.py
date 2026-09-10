"""期刊子系统的 Pydantic v2 模型。

设计要点：
- 使用 ConfigDict(extra="forbid") 防止字段蔓延；
- 时间戳统一 epoch ms（与 office.models 一致）；
- enums 继承 str 兼容 sqlite 存储；
- JournalSpec 暴露 validate_content(content) 自检方法，generator/validator 复用。
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.office.journal.errors import JournalContentShapeError


class ViolationSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class CitationStyle(str, Enum):
    NUMERIC = "numeric"
    NUMERIC_PAREN = "numeric_paren"
    NUMERIC_CIRCLE = "numeric_circle"
    AUTHOR_YEAR = "author_year"
    AUTHOR_YEAR_PAREN = "author_year_paren"
    GB_T_7714 = "gb_t_7714"
    UNKNOWN = "unknown"


class FontFamily(BaseModel):
    model_config = ConfigDict(extra="forbid")
    family: str
    ascii_family: Optional[str] = None
    eastasia: Optional[str] = None


class HeadingSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keyword: str
    level: int = Field(ge=1, le=6)
    expected_pt: float = Field(gt=0)


class JournalSpec(BaseModel):
    """由 parser 从 OOXML 自动抽取的期刊格式规范。"""

    model_config = ConfigDict(extra="forbid")

    spec_id: str
    template_sha256: str
    template_filename: str
    font_body: FontFamily
    font_heading: FontFamily
    body_pt: float = Field(gt=0)
    heading_pt: float = Field(gt=0)
    line_spacing: float = Field(gt=0)
    margins_cm: float = Field(gt=0)
    headings: List[HeadingSpec]
    citation_style: CitationStyle = CitationStyle.UNKNOWN
    page_size: str = "A4"
    extra: Dict[str, Any] = Field(default_factory=dict)

    def validate_content(self, content: JournalContent) -> None:
        """校验 content 形状是否可用于 fill。缺 abstract/任何 keyword 标题 → 抛 JournalContentShapeError。"""
        if not content.abstract:
            raise JournalContentShapeError("content.abstract 不能为空")
        for h in self.headings:
            if h.keyword in {"摘要", "Abstract"} and not content.abstract:
                raise JournalContentShapeError(f"content 缺 '{h.keyword}' 段落")
        # keywords 必填
        kw = content.sections.get("keywords", "") or content.sections.get("关键词", "")
        if not kw.strip():
            raise JournalContentShapeError("content.sections['keywords'] 不能为空")


class JournalContent(BaseModel):
    """用户提交的论文内容（结构化）。"""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    abstract: str = Field(default="")
    sections: Dict[str, str] = Field(default_factory=dict)  # section_key → text
    references: List[str] = Field(default_factory=list)
    citations: List[str] = Field(default_factory=list)


class JournalViolation(BaseModel):
    """单条规则违规 + 修复建议。"""

    model_config = ConfigDict(extra="forbid")

    rule_id: str
    severity: ViolationSeverity
    message: str
    location: str = ""  # 段落/章节/全文
    suggestion: str = ""  # 修复建议


class JournalGenerationRecord(BaseModel):
    """SQLite 元数据记录（office_journal_generations 行）。"""

    model_config = ConfigDict(extra="forbid")

    gen_id: str
    spec_id: str
    output_path: str
    mode: str  # "structured_fill" | "llm_generate"
    created_at: int = Field(ge=0)  # epoch ms
    llm_model: Optional[str] = None
    bytes_written: int = Field(default=0, ge=0)
    extra: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("mode")
    @classmethod
    def _check_mode(cls, v: str) -> str:
        if v not in {"structured_fill", "llm_generate"}:
            raise ValueError(f"mode 必须是 structured_fill | llm_generate, 收到 {v!r}")
        return v


__all__ = [
    "ViolationSeverity",
    "CitationStyle",
    "FontFamily",
    "HeadingSpec",
    "JournalSpec",
    "JournalContent",
    "JournalViolation",
    "JournalGenerationRecord",
]
