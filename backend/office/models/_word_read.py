from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from ._shared import OfficeDocumentSummary, WordMetadataSpec


class WordParagraphContent(BaseModel):
    """One Word paragraph."""

    model_config = ConfigDict(extra="forbid")

    style: str = Field(description="Paragraph style name, e.g. 'Normal', 'Heading 1'")
    text: str
    level: int = Field(ge=0, description="Heading level (0 for body text)")


class WordTableContent(BaseModel):
    """One Word table."""

    model_config = ConfigDict(extra="forbid")

    rows: List[List[str]]


class WordCommentContent(BaseModel):
    """One Word comment.

    Moved here in round 2 — 批次 3.3 originally defined it in word.py because
    models.py was owned by another agent at the time. ``id`` matches the
    ``w:id`` of the ``w:commentRangeStart/End`` pair and ``w:commentReference``
    in document.xml; ``anchor_text`` is the body text inside the anchored
    range, falling back to the anchor's paragraph text when the range is empty.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="批注 id（w:comment/@w:id，十进制字符串）")
    author: Optional[str] = Field(default=None, description="批注作者（w:author）")
    date: Optional[str] = Field(default=None, description="ISO 8601 时间（w:date）")
    text: str = Field(description="批注正文（w:comment 内各段文本）")
    anchor_text: str = Field(default="", description="批注锚定的正文文本")


class WordCommentsResult(BaseModel):
    """Result of :func:`backend.office.word.read_docx_comments`.

    Standalone envelope kept for the dedicated comments reader;
    :class:`OfficeWordReadResult` embeds the same
    :class:`WordCommentContent` items directly via its ``comments`` field.
    """

    model_config = ConfigDict(extra="forbid")

    comments: List[WordCommentContent] = Field(default_factory=list)


class WordHeaderFooterContent(BaseModel):
    """单节的页眉/页脚提取结果（section 为 1-based 节号）。"""

    model_config = ConfigDict(extra="forbid")

    section: int = Field(ge=1)
    header_text: str = ""
    footer_text: str = ""
    has_page_number_field: bool = False


class OfficeWordReadResult(BaseModel):
    """Result of POST /api/v1/office/word/read."""

    model_config = ConfigDict(extra="forbid")

    summary: OfficeDocumentSummary
    paragraphs: List[WordParagraphContent]
    tables: List[WordTableContent]
    images: int = Field(ge=0, default=0)
    # Round 2 (R3): comments merged into the read result. ``default_factory``
    # keeps payloads produced before this field existed valid under
    # ``extra="forbid"`` (old consumers may ignore the field entirely).
    comments: List[WordCommentContent] = Field(default_factory=list)
    # Round 51：core properties 回读（生成器 metadata 的对偶；文档无
    # 属性时为 None）。
    metadata: Optional[WordMetadataSpec] = None
    # Round 15：每节的页眉/页脚文本与页码域标记（生成器对偶——
    # format_spec.header/footer 写入的元素读取侧可见）。
    headers_footers: List[WordHeaderFooterContent] = Field(default_factory=list)
    # Round 57：脚注文本清单（footnotes part 回读；无脚注为空表）。
    footnotes: List[str] = Field(default_factory=list)
    # Round 59：尾注文本清单（endnotes part 回读；无尾注为空表）。
    endnotes: List[str] = Field(default_factory=list)
    # Round 15：文档中的目录域 instr 列表。
    toc_fields: List[str] = Field(default_factory=list)
    # Office display round C (P4)：内嵌图片缩略预览。additive field ——
    # default_factory 保持旧 payload 在 extra="forbid" 下有效（win7 回流
    # 与旧客户端可整体忽略）。上限/降级策略见 word._extract_image_previews。
    image_previews: List[WordImagePreview] = Field(default_factory=list)


class WordImagePreview(BaseModel):
    """One inline image thumbnail for preview (office display round C, P4).

    ``data_url`` 是缩略后的 base64 data URL（Pillow 可用时最长边缩到
    480px；不可用时仅 ≤150KB 的原图直接内联）。超限/无法内联的图片不产
    生条目 —— ``OfficeWordReadResult.images``（总数）与
    ``len(image_previews)`` 的差即被省略的数量。
    """

    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0, description="文内出现顺序（0-based）")
    content_type: str = Field(description="MIME，如 image/png")
    data_url: str = Field(description="data:<mime>;base64,… 缩略图")
    thumbnail: bool = Field(
        default=False, description="True=经 Pillow 缩略；False=原图直接内联"
    )


if hasattr(OfficeWordReadResult, "model_rebuild"):
    OfficeWordReadResult.model_rebuild()
else:  # pragma: no cover — release/win7 runs pydantic v1
    OfficeWordReadResult.update_forward_refs()

