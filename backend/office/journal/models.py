"""期刊子系统的 Pydantic 模型 (main+win7 双兼容)。

设计要点：
- 同时支持 Pydantic v1 (release/win7 + Python 3.8) 与 v2 (main + Python 3.10)
- 使用 ConfigDict(extra="forbid") (v2) / class Config (v1) 防字段蔓延；
- 时间戳统一 epoch ms（与 office.models 一致）；
- enums 继承 str 兼容 sqlite 存储；
- JournalSpec 暴露 validate_content(content) 自检方法，generator/validator 复用。
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

try:  # Pydantic v2 (main, Python 3.10+)
    from pydantic import BaseModel, ConfigDict, Field, field_validator

    _PYDANTIC_V2 = True
except ImportError:  # Pydantic v1 (release/win7, Python 3.8)
    from pydantic import BaseModel, Field, validator as field_validator  # type: ignore[no-redef]

    _PYDANTIC_V2 = False

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
    if _PYDANTIC_V2:
        model_config = ConfigDict(extra="forbid")
    else:
        class Config:
            extra = "forbid"

    family: str
    ascii_family: Optional[str] = None
    eastasia: Optional[str] = None


class HeadingSpec(BaseModel):
    if _PYDANTIC_V2:
        model_config = ConfigDict(extra="forbid")
    else:
        class Config:
            extra = "forbid"

    keyword: str
    # Field(ge=..., le=...) 在 v1/v2 均支持数值约束
    level: int = Field(ge=1, le=6)
    expected_pt: float = Field(gt=0)


class JournalSpec(BaseModel):
    """由 parser 从 OOXML 自动抽取的期刊格式规范。"""

    if _PYDANTIC_V2:
        model_config = ConfigDict(extra="forbid")
    else:
        class Config:
            extra = "forbid"

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

    if _PYDANTIC_V2:
        model_config = ConfigDict(extra="forbid")
    else:
        class Config:
            extra = "forbid"

    # v1 不支持 str 上的 min_length/max_length — 改用 validator 兜底
    title: str = ""
    abstract: str = ""
    sections: Dict[str, str] = Field(default_factory=dict)  # section_key → text
    references: List[str] = Field(default_factory=list)
    citations: List[str] = Field(default_factory=list)

    if not _PYDANTIC_V2:
        @field_validator("title")  # type: ignore[misc]
        @classmethod
        def _check_title(cls, v: str) -> str:
            if not v:
                raise ValueError("title 不能为空")
            if len(v) > 200:
                raise ValueError("title 长度不能超过 200")
            return v


class JournalViolation(BaseModel):
    """单条规则违规 + 修复建议。"""

    if _PYDANTIC_V2:
        model_config = ConfigDict(extra="forbid")
    else:
        class Config:
            extra = "forbid"

    rule_id: str
    severity: ViolationSeverity
    message: str
    location: str = ""  # 段落/章节/全文
    suggestion: str = ""  # 修复建议


class JournalGenerationRecord(BaseModel):
    """SQLite 元数据记录（office_journal_generations 行）。"""

    if _PYDANTIC_V2:
        model_config = ConfigDict(extra="forbid")
    else:
        class Config:
            extra = "forbid"

    gen_id: str
    spec_id: str
    output_path: str
    mode: str  # "structured_fill" | "llm_generate"
    created_at: int = Field(ge=0)  # epoch ms
    llm_model: Optional[str] = None
    bytes_written: int = Field(default=0, ge=0)
    extra: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("mode")  # type: ignore[misc]
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
    "to_jsonable",
    "to_json_str",
    "parse_obj",
    "parse_raw",
]


# ---- v1/v2 模型序列化辅助 ----
def to_jsonable(model: BaseModel) -> Dict[str, Any]:
    """Pydantic v1/v2 双兼容:返回可 JSON 序列化的 dict。

    - v2: model.model_dump(mode="json")
    - v1: model.dict()
    """
    if _PYDANTIC_V2:
        return model.model_dump(mode="json")
    return model.dict()  # type: ignore[no-any-return]


def to_json_str(model: BaseModel, **kwargs: Any) -> str:
    """Pydantic v1/v2 双兼容:返回 JSON 字符串。

    - v2: model.model_dump_json(**kwargs)（支持 indent 等）
    - v1: model.json(**kwargs)
    """
    if _PYDANTIC_V2:
        return model.model_dump_json(**kwargs)  # type: ignore[no-any-return]
    return model.json(**kwargs)  # type: ignore[no-any-return]


def parse_obj(model_cls: type, data: Any) -> BaseModel:
    """Pydantic v1/v2 双兼容:从 dict 创建模型实例。

    - v2: cls.model_validate(data)
    - v1: cls.parse_obj(data)
    """
    if _PYDANTIC_V2:
        return model_cls.model_validate(data)  # type: ignore[no-any-return]
    return model_cls.parse_obj(data)  # type: ignore[no-any-return]


def parse_raw(model_cls: type, data: str | bytes) -> BaseModel:
    """Pydantic v1/v2 双兼容:从 JSON 字符串创建模型实例。

    - v2: cls.model_validate_json(data)
    - v1: cls.parse_raw(data)
    """
    if _PYDANTIC_V2:
        return model_cls.model_validate_json(data)  # type: ignore[no-any-return]
    return model_cls.parse_raw(data)  # type: ignore[no-any-return]