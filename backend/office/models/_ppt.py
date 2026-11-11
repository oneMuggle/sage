from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from ._shared import ImageSourceSpec, WordMetadataSpec, _constrained_list


class PptLayoutName(str, Enum):
    """批次 2.3：幻灯片版式（映射默认模板的 slide layout）。

    不传（None）时保持既有行为：Blank layout + 手工文本框几何。
    """

    TITLE = "title"
    TITLE_CONTENT = "title_content"
    BLANK = "blank"


class PptSlideSpec(BaseModel):
    """One slide to generate in a PPT."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    bullets: _constrained_list(str, max_length=20) = Field(default_factory=list)
    notes: Optional[str] = Field(default=None, max_length=2000)
    # 批次 2.3：版式选择。None 保持既有 Blank+文本框行为不变。
    layout: Optional[PptLayoutName] = Field(
        default=None,
        description="'title' | 'title_content' | 'blank'；模板中找不到对应版式时回退现有几何",
    )
    # 批次 2.1：可选插图（追加在文本之后）。
    image: Optional[ImageSourceSpec] = None


#: Round 52：PPT 与 Word/Excel 的核心属性字段同一集合（别名复用）。
PptMetadataSpec = WordMetadataSpec


class OfficePptGenerateRequest(BaseModel):
    """POST /api/v1/office/ppt/generate."""

    model_config = ConfigDict(extra="forbid")

    # P7 (2026-09-14): 进度追踪任务 id（前端 uuid；GET /office/progress/{id} 轮询）
    task_id: Optional[str] = Field(default=None, max_length=100)

    workspace_path: str
    filename: str = Field(
        min_length=1,
        max_length=200,
        description="Output filename (without .pptx extension is OK; we'll add it)",
    )
    slides: _constrained_list(PptSlideSpec, min_length=1, max_length=100)
    # Round 52：文档核心属性（与 Word/Excel 对称）。
    metadata: Optional[PptMetadataSpec] = Field(
        default=None,
        description="文档核心属性；None 不写（不臆造作者）",
    )
