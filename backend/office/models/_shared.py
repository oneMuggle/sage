from __future__ import annotations

import logging
from enum import Enum
<<<<<<< HEAD
from typing import ForwardRef, List, Optional

from pydantic import BaseModel, Field, conlist

# field_validator 仅作为公开重导出（__init__.py __all__ 包含），
# 实际使用方是 _word_gen.py（自带 try/except 导入）。
from backend.compat.win7.pydantic_compat import (
    ConfigDict,
    field_validator,  # noqa: F401
)
=======
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, conlist

# Pydantic v1/v2 compatibility (matches backend/plugins/manifest.py idiom).
try:
    # Pydantic v2
    from pydantic import field_validator
except ImportError:  # pragma: no cover — release/win7 runs v1
    # Pydantic v1 fallback
    from pydantic import validator as field_validator  # type: ignore  # noqa: F401
>>>>>>> origin/main

logger = logging.getLogger(__name__)


def _constrained_list(item_type, *, min_length=None, max_length=None):
    """Build a list constraint compatible with Pydantic v1 and v2."""
<<<<<<< HEAD
    # pydantic v1 的 conlist 不接受字符串类型；包装成 ForwardRef 延迟解析，
    # 由模块末尾的 model_rebuild()/update_forward_refs() 守卫收口。
    if isinstance(item_type, str):
        item_type = ForwardRef(item_type)
=======
>>>>>>> origin/main
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
    # M2.5: 文档级规范书绑定。NULL 表示跟随工作区默认规范书。
    active_spec_id: Optional[str] = Field(
        default=None,
        description=(
            "ID of the bound spec document (office_spec_documents.id). "
            "NULL → workspace default applies."
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


class WordMetadataSpec(BaseModel):
    """文档核心属性（Round 49）——Word「文件 → 信息」面板可见。

    title 恒取请求 title，不在此重复；其余显式传入才写（不臆造作者）。
    """

    model_config = ConfigDict(extra="forbid")

    author: Optional[str] = Field(default=None, max_length=100)
    subject: Optional[str] = Field(default=None, max_length=200)
    keywords: Optional[str] = Field(
        default=None, max_length=200, description="关键词（分号分隔）"
    )
    comments: Optional[str] = Field(default=None, max_length=500)
    category: Optional[str] = Field(default=None, max_length=100)


class OfficePptReadResult(BaseModel):
    """Result of POST /api/v1/office/ppt/read."""

    model_config = ConfigDict(extra="forbid")

    summary: OfficeDocumentSummary
    slides: List[PptSlideContent]
    # Round 52：core properties 回读（文档无属性时为 None）。
    metadata: Optional[WordMetadataSpec] = None


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
class ImageSourceSpec(BaseModel):
    """一张待嵌入图片的来源描述（Word 段落图片 / PPT slide 图片共用）。

    ``source`` 二选一：``data:image/...`` base64 data URI 或工作区/本地
    图片文件路径。解码后强制 ≤10MB（与 word_template._MAX_IMAGE_BYTES 对齐）。
    """

    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=20_000_000)
    width_inches: Optional[float] = Field(default=None, gt=0, le=24)
    height_inches: Optional[float] = Field(default=None, gt=0, le=24)

