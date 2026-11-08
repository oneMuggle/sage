# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容
"""M2.5 格式规范书库路由（CRUD、提取、激活、绑定）.

挂载在 ``/office``（由 ``office_routes.py`` 做 ``include_router``）；路径全部
在路由模块内显式写出，不使用 ``APIRouter(prefix=...)``，避免和 ``/office``
叠加时重复前缀。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.compat.win7.pydantic_compat import ConfigDict
from backend.data.database import get_database
from backend.office.errors import OfficeError, OfficeParseError, OfficePathError
from backend.office.path_safety import resolve_within
from backend.office.spec_library import (
    create_spec,
    delete_spec,
    get_default_spec,
    get_document_spec_id,
    get_spec,
    list_specs,
    resolve_effective_spec,
    set_default_spec,
    update_document_spec,
    update_spec,
)
from backend.office.spec_models import (
    OfficeSpecBindingResult,
    OfficeSpecDetailResult,
    OfficeSpecDocument,
    OfficeSpecListResult,
    OfficeSpecSaveResult,
)
from backend.office.storage import validate_workspace
from backend.office.word_rule_extract import (
    extract_word_rules,
    extract_word_rules_async,
)
from backend.office.word_rulepack_models import (
    WordRuleExtractionResult,
    WordRulePack,
)
from backend.office.word_rulepack_store import (
    load_rulepack,
    save_rulepack,
)

router = APIRouter(tags=["office"])


# ── request models ────────────────────────────────────────────────────


class SpecSaveRequest(BaseModel):
    """POST /office/specs body."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    name: str = Field(min_length=1, max_length=200)
    rulepack_id: Optional[str] = Field(default=None, max_length=80)
    pack: Optional[WordRulePack] = None
    source_file_path: Optional[str] = Field(default=None, max_length=2000)
    source_content_hash: Optional[str] = Field(default=None, max_length=200)
    is_default: bool = False


class SpecUpdateRequest(BaseModel):
    """PATCH /office/specs/{id} body."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    name: Optional[str] = Field(default=None, max_length=200)
    pack: Optional[WordRulePack] = None
    source_file_path: Optional[str] = Field(default=None, max_length=2000)
    source_content_hash: Optional[str] = Field(default=None, max_length=200)


class SpecExtractRequest(BaseModel):
    """POST /office/specs/extract body — LLM 提取草稿规则包."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str = Field(min_length=1, max_length=2000)
    pack_id: str = Field(default="extracted-spec-pack", min_length=1, max_length=80)
    pack_name: Optional[str] = Field(default=None, max_length=200)
    use_llm: bool = False
    max_size_bytes: int = Field(
        default=50 * 1024 * 1024, ge=1024, le=200 * 1024 * 1024
    )


class SpecActivateRequest(BaseModel):
    """POST /office/specs/{id}/activate body."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str


class SpecBindRequest(BaseModel):
    """POST /office/doc/{doc_id}/spec body."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    spec_id: Optional[str] = Field(default=None, max_length=80)


# ── helpers ───────────────────────────────────────────────────────────


def _conn():
    return get_database().get_connection()


def _pack_or_raise(workspace: Path, rulepack_id: str) -> WordRulePack:
    """Resolve rulepack (raises OfficeError → mapped by office handler)."""
    return load_rulepack(workspace, rulepack_id)["pack"]


def _ensure_saveable_pack(pack: WordRulePack) -> None:
    missing = [
        rule.id for rule in pack.rules if not (rule.source or "").strip()
    ]
    if missing:
        raise OfficeParseError(
            "以下规则缺少来源，不能保存到规范书库: " + ", ".join(missing[:10])
        )


def _build_detail(workspace: Path, spec_row: dict) -> OfficeSpecDetailResult:
    try:
        loaded = load_rulepack(workspace, spec_row["rulepack_id"])
        rulepack = loaded["pack"]
    except OfficeError:
        rulepack = None
    return OfficeSpecDetailResult(
        ok=True,
        spec=OfficeSpecDocument(**spec_row),
        rulepack=rulepack,
    )


# ── endpoints ─────────────────────────────────────────────────────────


@router.get("/specs", response_model=OfficeSpecListResult)
def list_specs_endpoint(
    workspace_path: Optional[str] = None,
) -> OfficeSpecListResult:
    """列出工作区所有规范书."""
    if not workspace_path:
        return OfficeSpecListResult(ok=True, workspace_path="", specs=[])
    workspace = validate_workspace(Path(workspace_path))
    rows = list_specs(_conn(), str(workspace))
    return OfficeSpecListResult(
        ok=True, workspace_path=str(workspace), specs=[OfficeSpecDocument(**row) for row in rows]
    )


@router.get("/specs/{spec_id}", response_model=OfficeSpecDetailResult)
def get_spec_endpoint(
    spec_id: str, workspace_path: str
) -> OfficeSpecDetailResult:
    """取一行规范书元数据 + 对应的 live rule pack.

    ``workspace_path`` 必填：规范书按工作区隔离，跨工作区查询一律 404。
    """
    workspace = validate_workspace(Path(workspace_path))
    row = get_spec(_conn(), spec_id, workspace_path=str(workspace))
    if row is None:
        raise OfficeParseError(f"规范书不存在: {spec_id}")
    return _build_detail(workspace, row)


@router.post("/specs", response_model=OfficeSpecSaveResult)
def create_spec_endpoint(req: SpecSaveRequest) -> OfficeSpecSaveResult:
    """新建一份规范书.

    两种来源二选一:
      * ``pack`` — 前端在提取对话框确认后提交草稿；要求每条规则有来源段落；
        保存为规则包后创建一行元数据；
      * ``rulepack_id`` — 引用已存在的规则包（内置/工作区皆可）。
    """
    workspace = validate_workspace(Path(req.workspace_path))
    if req.pack is not None:
        _ensure_saveable_pack(req.pack)
        saved_pack = save_rulepack(workspace, req.pack)
        rulepack_id = saved_pack.id
    elif req.rulepack_id:
        _pack_or_raise(workspace, req.rulepack_id)
        rulepack_id = req.rulepack_id
    else:
        raise OfficeParseError("创建规范书必须提供 pack 或 rulepack_id")
    new = create_spec(
        _conn(),
        workspace_path=str(workspace),
        name=req.name,
        rulepack_id=rulepack_id,
        source_file_path=req.source_file_path,
        source_content_hash=req.source_content_hash,
        is_default=req.is_default,
    )
    detail = _build_detail(workspace, new)
    return OfficeSpecSaveResult(ok=True, spec=detail.spec, rulepack=detail.rulepack)


@router.patch("/specs/{spec_id}", response_model=OfficeSpecSaveResult)
def update_spec_endpoint(
    spec_id: str, req: SpecUpdateRequest
) -> OfficeSpecSaveResult:
    """部分更新一份规范书.可选先保存一份新的规则包，再绑定上去."""
    workspace = validate_workspace(Path(req.workspace_path))
    if req.pack is not None:
        _ensure_saveable_pack(req.pack)
        saved_pack = save_rulepack(workspace, req.pack)
        rulepack_id = saved_pack.id
    else:
        rulepack_id = None
    updated = update_spec(
        _conn(),
        spec_id,
        workspace_path=str(workspace),
        name=req.name,
        rulepack_id=rulepack_id,
        source_file_path=req.source_file_path,
        source_content_hash=req.source_content_hash,
    )
    if updated is None:
        raise OfficeParseError(f"规范书不存在: {spec_id}")
    detail = _build_detail(workspace, updated)
    return OfficeSpecSaveResult(ok=True, spec=detail.spec, rulepack=detail.rulepack)


# NOTE: 静态路径必须声明在 /specs/{spec_id} 之前，否则 FastAPI 会把
# "default" 当作 spec_id 匹配到 delete_spec_endpoint。
@router.delete("/specs/default")
def clear_default_spec_endpoint(
    workspace_path: str,
) -> dict:
    """清除工作区默认规范书."""
    workspace = validate_workspace(Path(workspace_path))
    set_default_spec(_conn(), str(workspace), None)
    default = get_default_spec(_conn(), str(workspace))
    return {"ok": True, "default": default}


@router.delete("/specs/{spec_id}")
def delete_spec_endpoint(
    spec_id: str, workspace_path: str
) -> dict:
    """删除一行规范书元数据；不删除其规则包文件（规则包可在「审校与规范」页复用）."""
    workspace = validate_workspace(Path(workspace_path))
    row = get_spec(_conn(), spec_id, workspace_path=str(workspace))
    if row is None:
        raise OfficeParseError(f"规范书不存在: {spec_id}")
    deleted = delete_spec(_conn(), spec_id, workspace_path=str(workspace))
    return {"ok": deleted, "spec_id": spec_id, "workspace_path": str(workspace)}


@router.post("/specs/extract", response_model=WordRuleExtractionResult)
def extract_spec_endpoint(
    req: SpecExtractRequest,
) -> WordRuleExtractionResult:
    """从 Word 说明文件草稿提取规则包（LLM 可选）.

    结果只作为草稿：前端在提取对话框展示/编辑后再调
    ``POST /office/specs`` 提交 ``pack``。
    """
    workspace = validate_workspace(Path(req.workspace_path))
    file_path = resolve_within(workspace, Path(req.file_path))
    if not file_path.is_file():
        raise OfficePathError(
            f"file_path is not a regular file: {req.file_path}",
            file_path=file_path,
        )
    if file_path.stat().st_size > req.max_size_bytes:
        raise OfficeParseError(
            f"说明文件超过大小上限 {req.max_size_bytes} 字节"
        )
    if req.use_llm:
        return asyncio.run(
            extract_word_rules_async(
                file_path,
                file_type="spec",
                pack_id=req.pack_id,
                pack_name=req.pack_name,
                workspace_path=str(workspace),
                use_llm=True,
            )
        )
    return extract_word_rules(
        file_path,
        file_type="spec",
        pack_id=req.pack_id,
        pack_name=req.pack_name,
        workspace_path=str(workspace),
    )


@router.post("/specs/{spec_id}/activate")
def activate_spec_endpoint(
    spec_id: str, req: SpecActivateRequest
) -> OfficeSpecDocument:
    """设置为工作区默认规范书."""
    workspace = validate_workspace(Path(req.workspace_path))
    row = set_default_spec(_conn(), str(workspace), spec_id)
    if row is None:
        raise OfficeParseError(f"规范书不存在: {spec_id}")
    return OfficeSpecDocument(**row)


@router.get(
    "/doc/{doc_id}/spec", response_model=OfficeSpecBindingResult
)
def get_doc_spec_endpoint(
    doc_id: str, workspace_path: str
) -> OfficeSpecBindingResult:
    """查询文档级规范书绑定 + 当前生效规范书."""
    workspace = validate_workspace(Path(workspace_path))
    bound = get_document_spec_id(
        _conn(), doc_id, workspace_path=str(workspace)
    )
    effective = resolve_effective_spec(
        _conn(),
        workspace_path=str(workspace),
        doc_id=doc_id,
        spec_id=bound,
    )
    return OfficeSpecBindingResult(
        ok=True,
        doc_id=doc_id,
        spec_id=bound,
        effective_spec=(
            OfficeSpecDocument(**effective) if effective is not None else None
        ),
    )


@router.post(
    "/doc/{doc_id}/spec", response_model=OfficeSpecBindingResult
)
def bind_doc_spec_endpoint(
    doc_id: str, req: SpecBindRequest
) -> OfficeSpecBindingResult:
    """设置/解除文档级规范书绑定（spec_id=None 解绑，跟随工作区默认）."""
    workspace = validate_workspace(Path(req.workspace_path))
    update_document_spec(
        _conn(), doc_id, req.spec_id, workspace_path=str(workspace)
    )
    effective = resolve_effective_spec(
        _conn(),
        workspace_path=str(workspace),
        doc_id=doc_id,
        spec_id=req.spec_id,
    )
    return OfficeSpecBindingResult(
        ok=True,
        doc_id=doc_id,
        spec_id=req.spec_id,
        effective_spec=(
            OfficeSpecDocument(**effective) if effective is not None else None
        ),
    )


__all__ = [
    "SpecActivateRequest",
    "SpecBindRequest",
    "SpecExtractRequest",
    "SpecSaveRequest",
    "SpecUpdateRequest",
    "activate_spec_endpoint",
    "bind_doc_spec_endpoint",
    "clear_default_spec_endpoint",
    "create_spec_endpoint",
    "delete_spec_endpoint",
    "extract_spec_endpoint",
    "get_doc_spec_endpoint",
    "get_spec_endpoint",
    "list_specs_endpoint",
    "router",
    "update_spec_endpoint",
]
