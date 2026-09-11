"""Office document Pydantic models.

Defines request/response models for the office API. All models are Pydantic v2
to match FastAPI 0.109 + pydantic 2.5 already pinned in requirements.txt.

Frontend IPC contracts (in src/shared/api/types.ts) MUST stay in sync with
the response shapes defined here.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, conlist

logger = logging.getLogger(__name__)


def _constrained_list(item_type, *, min_length=None, max_length=None):
    """Build a list constraint compatible with Pydantic v1 and v2."""
    kwargs = {}
    if min_length is not None:
        kwargs["min_length"] = min_length
    if max_length is not None:
        kwargs["max_length"] = max_length
    try:
        return conlist(item_type, **kwargs)
    except TypeError:
        if "min_length" in kwargs:
            kwargs["min_items"] = kwargs.pop("min_length")
        if "max_length" in kwargs:
            kwargs["max_items"] = kwargs.pop("max_length")
        return conlist(item_type, **kwargs)


class OfficeDocType(str, Enum):
    """Document type discriminator."""

    PPT = "ppt"
    WORD = "word"
    EXCEL = "excel"
    PDF = "pdf"  # Phase 2: PDF support


class OfficeDocStatus(str, Enum):
    """Lifecycle status of an office document in the workspace."""

    PARSED = "parsed"  # read from an uploaded user file
    GENERATED = "generated"  # created from scratch via the generator
    EDITED = "edited"  # read + modified + saved as new file


# ──────────────────────────────────────────────────────────────────────
# Metadata
# ──────────────────────────────────────────────────────────────────────


class OfficeDocumentMetadata(BaseModel):
    """Per-document metadata captured at read/generate time."""

    model_config = ConfigDict(extra="forbid")

    page_count: Optional[int] = Field(
        default=None, description="Slide count (PPT) or page count (Word)"
    )
    sheet_count: Optional[int] = Field(default=None, description="Sheet count (Excel)")
    paragraph_count: Optional[int] = Field(default=None, description="Paragraph count (Word)")
    table_count: Optional[int] = Field(default=None, description="Table count (Word/PPT)")
    file_size_bytes: int = Field(ge=0, description="Output file size in bytes")


class OfficeDocumentSummary(BaseModel):
    """Compact document record — used in list API and as a sub-field in read results."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="UUIDv4 assigned by storage layer")
    workspace_path: str = Field(description="Absolute path to the user's workspace dir")
    doc_type: OfficeDocType
    original_filename: Optional[str] = Field(
        default=None, description="User's uploaded filename (None when generated from scratch)"
    )
    generated_filename: str = Field(description="On-disk filename in workspace/office/<id>/")
    status: OfficeDocStatus
    created_at: int = Field(description="Unix timestamp in milliseconds")
    updated_at: int = Field(description="Unix timestamp in milliseconds")
    metadata: OfficeDocumentMetadata
    # M0 Task 3: nullable lineage + soft-delete columns. Both default to
    # ``None`` so Phase 1.2 callers (which only know status + paths) keep
    # working without supplying the extra fields.
    derived_from: Optional[str] = Field(
        default=None,
        description=(
            "Source document id for edited/copied documents. NULL when this row "
            "is a fresh read or generation with no upstream parent."
        ),
    )
    archived_at: Optional[int] = Field(
        default=None,
        description=(
            "Unix timestamp (ms) when the document was soft-deleted. When set, "
            "list_documents(include_archived=False) hides the row."
        ),
    )


# ──────────────────────────────────────────────────────────────────────
# Read results — content extracted from a file
# ──────────────────────────────────────────────────────────────────────


class PptSlideContent(BaseModel):
    """One PPT slide's extracted content."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    title: Optional[str] = None
    text_blocks: List[str] = Field(default_factory=list)
    table_count: int = Field(ge=0, default=0)
    image_count: int = Field(ge=0, default=0)
    notes: Optional[str] = None


class OfficePptReadResult(BaseModel):
    """Result of POST /api/v1/office/ppt/read."""

    model_config = ConfigDict(extra="forbid")

    summary: OfficeDocumentSummary
    slides: List[PptSlideContent]


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


class ExcelSheetContent(BaseModel):
    """One Excel sheet."""

    model_config = ConfigDict(extra="forbid")

    name: str
    rows: List[List[str]]
    max_row: int = Field(ge=0)
    max_col: int = Field(ge=0)
    # Item 1.4 公式视图：仅 read_xlsx(include_formulas=True) 时填充，默认
    # None 保持既有 IPC 契约不变（additive 字段，前端可忽略）。
    formulas: Optional[List[str]] = Field(
        default=None,
        description=(
            "公式单元格列表，格式 'B4=SUM(B2:B3)'；有缓存值时为 "
            "'B4=SUM(B2:B3) → 30'。None 表示未启用公式视图或无公式。"
        ),
    )
    note: Optional[str] = Field(
        default=None,
        description="公式缺缓存值时的一行提示（openpyxl 无法计算公式）。",
    )


class OfficeExcelReadResult(BaseModel):
    """Result of POST /api/v1/office/excel/read."""

    model_config = ConfigDict(extra="forbid")

    summary: OfficeDocumentSummary
    sheets: List[ExcelSheetContent]


# ──────────────────────────────────────────────────────────────────────
# Read requests
# ──────────────────────────────────────────────────────────────────────


class OfficeReadRequest(BaseModel):
    """Common shape for all three read endpoints."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str = Field(description="Absolute path to the workspace dir")
    file_path: str = Field(description="Absolute path to the .pptx/.docx/.xlsx file to read")
    # Optional size limit for early rejection. Default 50MB per plan §6 R1.
    max_size_bytes: int = Field(
        default=50 * 1024 * 1024, ge=1024, description="Reject files larger than this"
    )
    # M0 Task 3: optional original (uploaded) filename. When the caller has
    # already imported an external file into the managed directory this is
    # the user-visible name; ``None`` keeps the Phase 1.2 contract for
    # back-compat with tests and existing IPC callers that don't track it.
    original_filename: Optional[str] = Field(
        default=None,
        description=(
            "User's original filename (before managed import). When None the "
            "summary's original_filename column stays NULL."
        ),
    )


# ──────────────────────────────────────────────────────────────────────
# Generate requests
# ──────────────────────────────────────────────────────────────────────


class PptLayoutName(str, Enum):
    """批次 2.3：幻灯片版式（映射默认模板的 slide layout）。

    不传（None）时保持既有行为：Blank layout + 手工文本框几何。
    """

    TITLE = "title"
    TITLE_CONTENT = "title_content"
    BLANK = "blank"


class ImageSourceSpec(BaseModel):
    """一张待嵌入图片的来源描述（Word 段落图片 / PPT slide 图片共用）。

    ``source`` 二选一：``data:image/...`` base64 data URI 或工作区/本地
    图片文件路径。解码后强制 ≤10MB（与 word_template._MAX_IMAGE_BYTES 对齐）。
    """

    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=20_000_000)
    width_inches: Optional[float] = Field(default=None, gt=0, le=24)
    height_inches: Optional[float] = Field(default=None, gt=0, le=24)


class WordImageSpec(ImageSourceSpec):
    """Word 文档插图（Round 8）：在 ImageSourceSpec 基础上支持行内放置与题注。

    ``after_paragraph`` 为 ``paragraphs`` 的 0-based 下标，图片插入到该段落
    之后；None = 文末追加（Round 7 之前的既有行为）。越界在生成期钳到末尾。
    ``caption`` 非空时生成居中题注（"图N　caption"），图号全文独立计数。
    """

    model_config = ConfigDict(extra="forbid")

    caption: Optional[str] = Field(default=None, max_length=200)
    after_paragraph: Optional[int] = Field(default=None, ge=0)


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


class OfficePptGenerateRequest(BaseModel):
    """POST /api/v1/office/ppt/generate."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    filename: str = Field(
        min_length=1,
        max_length=200,
        description="Output filename (without .pptx extension is OK; we'll add it)",
    )
    slides: _constrained_list(PptSlideSpec, min_length=1, max_length=100)


class WordParagraphSpec(BaseModel):
    """One paragraph in a generated Word document."""

    model_config = ConfigDict(extra="forbid")

    heading: Optional[str] = Field(default=None, description="'h1' | 'h2' | 'h3' or None")
    style: Optional[Literal["bullet", "numbered"]] = Field(
        default=None,
        description="'bullet' 或 'numbered' 列表样式（与 heading 二选一）",
    )
    text: str = Field(min_length=1, max_length=10000)
    # 批次 2.3 样式分级（round a）：作用于该段落全部 runs 的可选样式。
    font_size: Optional[float] = Field(default=None, gt=0, le=400, description="磅值，如 12 / 14.5")
    bold: Optional[bool] = None
    italic: Optional[bool] = None
    color: Optional[str] = Field(
        default=None,
        description="字体颜色，6 位 RGB 十六进制（如 'FF0000'，可带 #）",
    )
    align: Optional[Literal["left", "center", "right", "justify"]] = None


class WordCellMergeSpec(BaseModel):
    """表格合并区域（Round 8）：0-based 含端点矩形（与 rows/headers 下标
    心智模型一致，区别于 ExcelCellRange 的 1-based）。生成期校验越界。"""

    model_config = ConfigDict(extra="forbid")

    min_row: int = Field(ge=0)
    max_row: int = Field(ge=0)
    min_col: int = Field(ge=0)
    max_col: int = Field(ge=0)


class WordTableSpec(BaseModel):
    """One table in a generated Word document.

    Round 8 新增：表题注（自动 "表N　caption"）、三线表样式、表头跨页
    重复、列宽、合并单元格；全部可选，None/false 保持既有默认网格行为。
    """

    model_config = ConfigDict(extra="forbid")

    headers: _constrained_list(str, min_length=1, max_length=50)
    rows: _constrained_list(_constrained_list(str), max_length=1000) = Field(default_factory=list)
    caption: Optional[str] = Field(default=None, max_length=200)
    style: Optional[Literal["grid", "three_line"]] = Field(
        default=None,
        description="None/'grid' = 默认网格；'three_line' = 学术三线表",
    )
    header_repeat: bool = Field(default=False, description="表头跨页重复")
    column_widths_cm: Optional[_constrained_list(float, max_length=50)] = Field(
        default=None,
        description="各列列宽（厘米）；None 不设置，长度须等于列数",
    )
    merges: _constrained_list(WordCellMergeSpec, max_length=200) = Field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────
# Word 版式规范（Round 7 FormatSpec —— "版式即配置"）
#
# 设计约定：
# - 所有字段 Optional，None = 该项不设置（生成器保持既有默认行为），
#   保证不传 ``format_spec`` 时生成结果与历史版本逐字节等价；
# - 模型只依赖 pydantic（不含 docx），维持
#   ``scripts/verify-office-paths.py`` canary "models 仅依赖 pydantic"
#   的前提；docx 侧的应用逻辑在 ``word_layout.py``；
# - 长度/数值边界为合理性钳制（防 LLM 传 9999 磅字号），不是排版学约束。
# ──────────────────────────────────────────────────────────────────────


class WordPageMarginsSpec(BaseModel):
    """页边距（厘米）。None 的边保持 Word 默认。"""

    model_config = ConfigDict(extra="forbid")

    top: Optional[float] = Field(default=None, ge=0.0, le=10.0)
    bottom: Optional[float] = Field(default=None, ge=0.0, le=10.0)
    left: Optional[float] = Field(default=None, ge=0.0, le=10.0)
    right: Optional[float] = Field(default=None, ge=0.0, le=10.0)


class WordPageSetupSpec(BaseModel):
    """页面设置：纸张/方向/页边距。"""

    model_config = ConfigDict(extra="forbid")

    size: Optional[Literal["A4", "letter"]] = Field(default=None)
    orientation: Optional[Literal["portrait", "landscape"]] = Field(default=None)
    margins_cm: Optional[WordPageMarginsSpec] = Field(default=None)


class WordBodyStyleSpec(BaseModel):
    """正文（Normal 样式）默认排版。行距为倍数（如 1.5 倍）。"""

    model_config = ConfigDict(extra="forbid")

    font_size_pt: Optional[float] = Field(default=None, ge=1.0, le=72.0)
    line_spacing: Optional[float] = Field(default=None, ge=1.0, le=3.0)
    first_line_indent_cm: Optional[float] = Field(default=None, ge=0.0, le=5.0)
    space_after_pt: Optional[float] = Field(default=None, ge=0.0, le=48.0)
    align: Optional[Literal["left", "center", "right", "justify"]] = None


class WordHeadingStyleSpec(BaseModel):
    """标题样式覆盖（作用于 Title / Heading 1-3 样式定义本身）。"""

    model_config = ConfigDict(extra="forbid")

    font_size_pt: Optional[float] = Field(default=None, ge=1.0, le=72.0)
    bold: Optional[bool] = None
    color: Optional[str] = Field(
        default=None,
        description="字体颜色，6 位 RGB 十六进制（如 '2F5496'，可带 #）",
        pattern=r"^#?[0-9A-Fa-f]{6}$",
        max_length=7,
    )
    align: Optional[Literal["left", "center", "right", "justify"]] = None
    space_before_pt: Optional[float] = Field(default=None, ge=0.0, le=96.0)
    space_after_pt: Optional[float] = Field(default=None, ge=0.0, le=96.0)


class WordHeaderFooterSpec(BaseModel):
    """页眉/页脚设置。``page_number`` 仅在 footer 上生效（居中 PAGE 域）。"""

    model_config = ConfigDict(extra="forbid")

    text: Optional[str] = Field(default=None, max_length=200)
    align: Optional[Literal["left", "center", "right", "justify"]] = None
    page_number: bool = False


class WordFormatSpec(BaseModel):
    """Word 文档版式规范。

    传入 ``generate_docx`` 后由 ``word_layout.apply_format_spec`` 以确定性
    代码注入 styles.xml / document.xml —— 格式要求不再依赖 LLM 在 prompt
    里"口头约定"。全字段可选，None 项不触碰。
    """

    model_config = ConfigDict(extra="forbid")

    page: Optional[WordPageSetupSpec] = None
    body: Optional[WordBodyStyleSpec] = None
    headings: Optional[Dict[Literal["h1", "h2", "h3"], WordHeadingStyleSpec]] = None
    title: Optional[WordHeadingStyleSpec] = None
    header: Optional[WordHeaderFooterSpec] = None
    footer: Optional[WordHeaderFooterSpec] = None
    # Round 8：多级标题自动编号（h1/h2/h3 计数器，字面 "N.M.K" 文本前缀）。
    numbering: bool = Field(default=False, description="为 h1/h2/h3 生成 1 / 1.1 / 1.1.1 编号前缀")


class OfficeWordGenerateRequest(BaseModel):
    """POST /api/v1/office/word/generate."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    filename: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    paragraphs: _constrained_list(WordParagraphSpec, max_length=5000) = Field(default_factory=list)
    tables: _constrained_list(WordTableSpec, max_length=100) = Field(default_factory=list)
    # 批次 2.1：可选插图。Round 8 起为 WordImageSpec——支持行内放置
    # （after_paragraph）与题注（caption）；旧 payload（仅 source/宽高）兼容。
    images: _constrained_list(WordImageSpec, max_length=20) = Field(default_factory=list)
    # Round 7 FormatSpec：显式版式（页边距/正文/标题/页眉页脚）。
    format_spec: Optional[WordFormatSpec] = Field(
        default=None,
        description="版式规范；None 保持默认版式（行为与历史版本一致）",
    )
    font_family: Optional[str] = Field(
        default=None,
        description="中文正文字体名（如'宋体'/'微软雅黑'/'等线'），默认宋体",
    )
    ascii_font: Optional[str] = Field(
        default=None,
        description="西文字体名，默认 Times New Roman",
    )


class ExcelSheetSpec(BaseModel):
    """One sheet in a generated Excel workbook."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=31, description="Excel sheet name max length")
    headers: _constrained_list(str, max_length=100) = Field(default_factory=list)
    rows: _constrained_list(_constrained_list(str), max_length=10000) = Field(default_factory=list)
    # 批次 2.3：按列序号给出列宽（index 0 = A 列），单位为 Excel 字符宽度。
    column_widths: Optional[_constrained_list(float, max_length=200)] = Field(
        default=None,
        description="列宽列表，如 [20, 12, 30] 对应 A/B/C 列；None 不设置",
    )


class ExcelCellRange(BaseModel):
    """openpyxl Reference 风格的矩形单元格区域（1-based，含端点）。"""

    model_config = ConfigDict(extra="forbid")

    min_col: int = Field(ge=1, le=16384)
    min_row: int = Field(ge=1, le=1048576)
    max_col: int = Field(ge=1, le=16384)
    max_row: int = Field(ge=1, le=1048576)


class ExcelChartSpec(BaseModel):
    """批次 2.1：生成 xlsx 时挂载的 Excel 原生图表（openpyxl Chart）。

    ``sheet`` 缺省挂到第一个 sheet；``data_ref`` 指向图表数据矩形
    （``titles_from_data=True`` 时首行/首列按 ``from_rows`` 解释为系列名）。
    """

    model_config = ConfigDict(extra="forbid")

    sheet: Optional[str] = Field(default=None, max_length=31)
    type: Literal["line", "bar", "pie"]
    anchor: str = Field(min_length=2, max_length=10, description="左上角锚点单元格，如 'A10'")
    data_ref: ExcelCellRange
    titles_from_data: bool = False
    from_rows: bool = False
    categories_ref: Optional[ExcelCellRange] = None
    title: Optional[str] = Field(default=None, max_length=200)


class OfficeExcelGenerateRequest(BaseModel):
    """POST /api/v1/office/excel/generate."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    filename: str = Field(min_length=1, max_length=200)
    sheets: _constrained_list(ExcelSheetSpec, min_length=1, max_length=50)
    # 批次 2.1：数据写完后统一挂载的原生图表。
    charts: _constrained_list(ExcelChartSpec, max_length=20) = Field(default_factory=list)


class ChartSeriesSpec(BaseModel):
    """matplotlib 图表的一条数据系列。``x`` 可省略（bar/pie 用 labels 补位）。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    x: Optional[List[Union[str, float]]] = Field(
        default=None,
        description="横轴取值（数值或类别文本）；bar/pie 常省略",
    )
    y: _constrained_list(float, min_length=1, max_length=10000)


class ChartSpec(BaseModel):
    """批次 2.1：matplotlib 图表渲染规格（render_chart_png 输入）。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["line", "bar", "hbar", "pie"]
    title: Optional[str] = Field(default=None, max_length=200)
    series: _constrained_list(ChartSeriesSpec, min_length=1, max_length=10)
    labels: Optional[_constrained_list(str, max_length=10000)] = Field(
        default=None,
        description="类别标签（bar/hbar/pie 或 line 分类轴）；series 无 x 时必选",
    )


# ──────────────────────────────────────────────────────────────────────
# List / delete endpoints
# ──────────────────────────────────────────────────────────────────────


class OfficeDocumentListResponse(BaseModel):
    """GET /api/v1/office/documents."""

    model_config = ConfigDict(extra="forbid")

    documents: List[OfficeDocumentSummary]
    total: int = Field(ge=0)


class OfficeDeleteResponse(BaseModel):
    """DELETE /api/v1/office/documents/{id}."""

    model_config = ConfigDict(extra="forbid")

    id: str
    deleted: bool


class OfficeSnapshotInfo(BaseModel):
    """One pre-edit snapshot file under ``<managed_dir>/.snapshots/``."""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: str = Field(
        description="快照文件名 '<ms>-<generated_filename>'，restore 时原样回传"
    )
    size_bytes: int = Field(ge=0)
    created_at: int = Field(description="快照时间，Unix 毫秒时间戳（取自文件名前缀）")


class OfficeSnapshotListResponse(BaseModel):
    """GET /api/v1/office/doc/{doc_id}/snapshots."""

    model_config = ConfigDict(extra="forbid")

    snapshots: List[OfficeSnapshotInfo]
    total: int = Field(ge=0)


class OfficeDocumentActionResponse(BaseModel):
    """POST /doc/{doc_id}/archive | /restore | /snapshots/{sid}/restore."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    summary: OfficeDocumentSummary


# ──────────────────────────────────────────────────────────────────────
# Word Template models (Phase 2)
# ──────────────────────────────────────────────────────────────────────


class TemplatePlaceholderType(str, Enum):
    """Type of placeholder in a Word template."""

    TEXT = "text"
    IMAGE = "image"
    TABLE = "table"
    DATE = "date"
    RICH_TEXT = "rich_text"


class PlaceholderLocation(str, Enum):
    """Location of placeholder in the document."""

    BODY = "body"
    TABLE = "table"
    HEADER = "header"
    FOOTER = "footer"
    TEXT_BOX = "text_box"


class TemplatePlaceholder(BaseModel):
    """One placeholder found in a Word template."""

    model_config = ConfigDict(extra="forbid")

    name: str
    raw_tag: str
    type: TemplatePlaceholderType
    location: PlaceholderLocation
    paragraph_index: Optional[int] = None
    table_index: Optional[int] = None
    row_index: Optional[int] = None
    col_index: Optional[int] = None
    format_hint: Optional[str] = None


class WordTemplateAnalysis(BaseModel):
    """Result of analyzing a Word template."""

    model_config = ConfigDict(extra="forbid")

    file_path: str
    placeholders: List[TemplatePlaceholder]
    summary: OfficeDocumentSummary
    has_jinja_control: bool = False


class WordTemplateAnalyzeRequest(BaseModel):
    """Request to analyze a Word template."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    template_path: str


class WordTemplateFillRequest(BaseModel):
    """Request to fill a Word template with data."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    template_path: str
    output_filename: str
    data: Dict[str, Any]
    images: Optional[Dict[str, str]] = None


class WordTemplateFillResult(BaseModel):
    """Result of filling a Word template."""

    model_config = ConfigDict(extra="forbid")

    output_path: str
    filename: str
    file_size_bytes: int
    filled_count: int
    unfilled_placeholders: List[str]


# ──────────────────────────────────────────────────────────────────────
# Template library models (Office parity batch 3 — Item 3.2)
# ──────────────────────────────────────────────────────────────────────


class TemplateLibraryPlaceholder(BaseModel):
    """One placeholder advertised by a template-library entry."""

    model_config = ConfigDict(extra="forbid")

    name: str
    type: TemplatePlaceholderType
    description: str = Field(default="", description="占位符用途说明（中文，展示给用户）")


class TemplateLibraryEntry(BaseModel):
    """One template in the library: builtin 中文办公模板 or workspace user template."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        description=(
            "builtin: stable id matching ^[a-z0-9_]{1,64}$; "
            "workspace: 'ws_'-prefixed sanitized filename stem"
        )
    )
    name: str = Field(description="展示名称（中文）")
    description: str = ""
    doc_type: OfficeDocType = OfficeDocType.WORD
    placeholders: List[TemplateLibraryPlaceholder] = Field(default_factory=list)
    source: Literal["builtin", "workspace"]
    filename: Optional[str] = Field(
        default=None,
        description=(
            "workspace 模板专用：office/templates/ 下的文件名；"
            "builtin 模板为 None（按 id 实例化）"
        ),
    )


class TemplateLibraryResponse(BaseModel):
    """GET /api/v1/office/templates."""

    model_config = ConfigDict(extra="forbid")

    templates: List[TemplateLibraryEntry]


class OfficeTemplateInstantiateRequest(BaseModel):
    """POST /api/v1/office/templates/instantiate.

    ``template_id``（builtin）与 ``workspace_template``（office/templates/ 下的
    文件名）二选一；同时给出报 400。round 3 N2 起 builtin 模板覆盖 word /
    excel / ppt 三种 doc_type，输出文件名扩展名须与模板类型一致。
    """

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    template_id: Optional[str] = Field(
        default=None, description="builtin 模板 id，如 'weekly_report'（word）、'budget_sheet'（excel）、'kickoff_deck'（ppt）"
    )
    workspace_template: Optional[str] = Field(
        default=None,
        description=(
            "workspace 模板文件名（office/templates/ 内，支持 .docx/.xlsx/.pptx；"
            "省略扩展名时按 docx→xlsx→pptx 顺序匹配）"
        ),
    )
    filename: str = Field(
        min_length=1,
        max_length=200,
        description="输出文件名（缺扩展名时自动补全，须与模板 doc_type 一致：.docx/.xlsx/.pptx）",
    )
    data: Dict[str, Any] = Field(default_factory=dict)
    images: Optional[Dict[str, str]] = Field(
        default=None,
        description="占位符名 → 图片路径或 data:image URI（与 /word/fill-template 一致，≤10MB）",
    )


# ──────────────────────────────────────────────────────────────────────
# PDF models (Phase 2)
# ──────────────────────────────────────────────────────────────────────


class PdfPageContent(BaseModel):
    """Content of one PDF page."""

    model_config = ConfigDict(extra="forbid")

    page_number: int
    text: str
    tables: List[List[List[str]]] = Field(default_factory=list)
    images: List[Dict[str, Any]] = Field(default_factory=list)


class PdfReadResult(BaseModel):
    """Result of reading a PDF file."""

    model_config = ConfigDict(extra="forbid")

    summary: OfficeDocumentSummary
    pages: List[PdfPageContent]
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PdfReadRequest(BaseModel):
    """Request to read a PDF file."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str


class PdfPageSpec(BaseModel):
    """One page in a generated PDF."""

    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = None
    paragraphs: List[str] = Field(default_factory=list)
    tables: List[List[List[str]]] = Field(default_factory=list)


class PdfGenerateRequest(BaseModel):
    """Request to generate a PDF."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    filename: str
    pages: List[PdfPageSpec]
    page_size: str = "A4"
    orientation: str = "portrait"


class PdfGenerateResult(BaseModel):
    """Result of generating a PDF."""

    model_config = ConfigDict(extra="forbid")

    output_path: str
    filename: str
    file_size_bytes: int
    page_count: int


class PdfFormField(BaseModel):
    """One PDF form field."""

    model_config = ConfigDict(extra="forbid")

    name: str
    type: str
    value: Optional[Any] = None
    options: Optional[List[str]] = None
    required: bool = False
    read_only: bool = False


class PdfFormReadResult(BaseModel):
    """Result of reading PDF form fields."""

    model_config = ConfigDict(extra="forbid")

    file_path: str
    fields: List[PdfFormField]
    has_xfa: bool = False


class PdfFormReadRequest(BaseModel):
    """Request to read PDF form fields."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str


class PdfFormFillRequest(BaseModel):
    """Request to fill a PDF form."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    template_path: str
    output_filename: str
    data: Dict[str, Any]
    flatten: bool = False


class PdfFormFillResult(BaseModel):
    """Result of filling a PDF form."""

    model_config = ConfigDict(extra="forbid")

    output_path: str
    filename: str
    file_size_bytes: int
    filled_count: int
