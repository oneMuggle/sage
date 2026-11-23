from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from ._shared import OfficeDocumentSummary


class PdfPageContent(BaseModel):
    """Content of one PDF page."""

    model_config = ConfigDict(extra="forbid")

    page_number: int
    text: str
    tables: List[List[List[str]]] = Field(default_factory=list)
    images: List[Dict[str, Any]] = Field(default_factory=list)
    # M6b: 页内嵌图片总数（images 列表受 include_images/预算限制可能更少；
    # embed_image_data=False 时 images 只含元数据、不含 data_url）。
    # include_images=False 时**不枚举**图片 → 该值为 0（没枚举就没有总数可言）。
    image_count: int = Field(default=0, ge=0)
    # M6c: 本页检测到但**未返回**的图片数（超出每页上限 / 解码前预检拒绝 /
    # 全文档预算放不下）。让调用方能区分「PDF 里没有图」和「有图但被裁掉」。
    images_omitted: int = Field(default=0, ge=0)
    # P4-A (office-p4a): 该页文本是否来自 OCR 兜底（SAGE_OCR=1 且 pytesseract
    # 可用时，扫描/纯图页触发）。additive 字段，前端/摘要可安全忽略。
    ocr: bool = Field(default=False, description="文本来自 OCR 兜底（扫描页）")


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
    # M6b: 返回页内嵌图片（data_url）；默认关闭，避免普通读取膨胀。
    include_images: bool = Field(default=False, description="是否返回页内嵌图片 data_url")
    max_images_per_page: int = Field(default=3, ge=0, le=10)
    # M6c: 是否把图片像素（base64 data_url）一并返回。**默认关闭** ——
    # 光是像素就可能让一次读取膨胀到几十 MB，必须由调用方显式索取。
    # False 时**完全不解码**（因此不存在解压炸弹风险），只返回宽高/数量等
    # 元数据；True 时按服务端预算（单图 ≤1.5MB base64，全文档 ≤20MB
    # base64）截断，并按过滤器白名单拒绝自带尺寸的编解码器（JPX/JBIG2/CCITT）。
    embed_image_data: bool = Field(
        default=False, description="是否把图片像素（base64 data_url）一并返回"
    )


class PdfDataRequest(BaseModel):
    """Request for the raw-PDF base64 preview (F3, office-p0).

    Serves the /office page's 原文预览 toggle: the renderer embeds the
    returned ``data:application/pdf`` URL in an iframe and Chromium's
    built-in viewer renders it — same fidelity path as the chat artifact
    viewer.
    """

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str


class PdfDataResult(BaseModel):
    """Raw-PDF base64 preview result.

    Never raises for expected conditions: oversize / escape / unreadable
    files return ``ok=False`` + a user-presentable ``error`` so the UI
    can fall back to the structured page cards.
    """

    model_config = ConfigDict(extra="forbid")

    ok: bool
    data_url: Optional[str] = None
    error: Optional[str] = None


class PdfPageSpec(BaseModel):
    """One page in a generated PDF."""

    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = None
    paragraphs: List[str] = Field(default_factory=list)
    tables: List[List[List[str]]] = Field(default_factory=list)


class PdfGenerateRequest(BaseModel):
    """Request to generate a PDF."""

    model_config = ConfigDict(extra="forbid")

    # P7 (2026-09-14): 进度追踪任务 id（前端 uuid；GET /office/progress/{id} 轮询）
    task_id: Optional[str] = Field(default=None, max_length=100)

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

