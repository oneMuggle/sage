"""Word 样式模板路由（命名预设 / 已有文档套用 / 规则包转换）。

挂载于 ``backend.api.office_routes`` 的聚合 router 下，本模块 prefix 为
``/word``，实际路径为 ``/api/v1/office/word/style-*`` 与
``/api/v1/office/word/style/apply|from-rulepack``。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.data.database import get_database
from backend.office.errors import OfficeGenerateError, OfficeParseError
from backend.office.models import WordFormatSpec
from backend.office.storage import validate_workspace
from backend.office.style_template_models import (
    OfficeStyleTemplate,
    OfficeStyleTemplateDetailResult,
    OfficeStyleTemplateListResult,
)
from backend.office.style_template_store import (
    create_style_template,
    delete_style_template,
    get_style_template,
    list_style_templates,
    set_default_style_template,
)
from backend.office.word_rulepack_models import (
    WordRulePack,
    WordStyleProfileConversion,
)
from backend.office.word_rulepack_store import DEFAULT_RULEPACK_ID, load_rulepack
from backend.office.word_style_apply import apply_style_to_document
from backend.office.word_style_presets import (
    list_style_presets,
    merge_template_with_spec,
    resolve_effective_format_spec,
)
from backend.office.word_style_profile import format_spec_from_rulepack

router = APIRouter(prefix="/word", tags=["office"])


def _conn():
    return get_database().get_connection()


class WordStyleFromRulepackRequest(BaseModel):
    """POST /office/word/style/from-rulepack body。"""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str = ""
    rulepack_id: Optional[str] = Field(default=None, max_length=80)
    rulepack: Optional[WordRulePack] = None


class WordStyleApplyRequest(BaseModel):
    """POST /office/word/style/apply body。"""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str = ""
    file_path: str = Field(min_length=1, max_length=2000)
    style_template_id: Optional[str] = Field(default=None, max_length=80)
    format_spec_preset: Optional[str] = Field(default=None, max_length=80)
    format_spec: Optional[WordFormatSpec] = None
    clear_direct_formatting: bool = False
    overwrite: bool = False
    output_filename: Optional[str] = Field(default=None, max_length=200)
    dry_run: bool = False


class WordStyleTemplateSaveRequest(BaseModel):
    """POST /office/word/style-templates body。

    三种来源（规则包 / 预设+画像 / 纯画像）二选一；保存的是转换后的
    画像快照，后续规则包修改不会静默改写已保存模板。
    """

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    name: str = Field(min_length=1, max_length=200)
    rulepack_id: Optional[str] = Field(default=None, max_length=80)
    rulepack: Optional[WordRulePack] = None
    format_spec_preset: Optional[str] = Field(default=None, max_length=80)
    format_spec: Optional[WordFormatSpec] = None
    source_ref: Optional[str] = Field(default=None, max_length=2000)
    is_default: bool = False


class WordStyleTemplateActivateRequest(BaseModel):
    """POST /office/word/style-templates/{id}/activate body。"""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str


@router.get("/style-presets")
def list_style_presets_endpoint() -> dict:
    """列出内置命名样式预设（id/name/description）。

    生成接口的 ``format_spec_preset`` 接受这里返回的 id；前端与 LLM 工具
    可据此提供版式选择。
    """
    return {"ok": True, "presets": list_style_presets()}


@router.post("/style/from-rulepack")
def from_rulepack_endpoint(
    req: WordStyleFromRulepackRequest,
) -> WordStyleProfileConversion:
    """把规则包/规范书编译为生成侧样式画像。

    未传内联规则包时按 ``rulepack_id``（缺省默认规则包）从工作区加载；
    返回的 ``format_spec`` 可直接用于生成（``format_spec`` 字段）或
    已有文档套用。
    """
    workspace = (
        validate_workspace(Path(req.workspace_path)) if req.workspace_path else None
    )
    if req.rulepack is not None:
        pack = req.rulepack
    else:
        loaded = load_rulepack(workspace, req.rulepack_id or DEFAULT_RULEPACK_ID)
        pack = loaded["pack"]
    return format_spec_from_rulepack(pack)


def _template_spec_or_raise(
    template_id: str, workspace_path: str
) -> Optional[WordFormatSpec]:
    """读取工作区样式模板的画像快照（跨工作区/不存在 → OfficeParseError）。"""
    if not workspace_path:
        raise OfficeParseError("style_template_id 需要同时提供 workspace_path")
    workspace = validate_workspace(Path(workspace_path))
    row = get_style_template(_conn(), template_id, workspace_path=str(workspace))
    if row is None:
        raise OfficeParseError(f"样式模板不存在: {template_id}")
    try:
        return WordFormatSpec(**row["format_spec"])
    except ValidationError as exc:
        raise OfficeParseError(f"样式模板画像无效: {template_id}") from exc


@router.post("/style/apply")
def apply_style_endpoint(req: WordStyleApplyRequest) -> dict:
    """给已有 .docx 套用样式画像（默认输出 ``<stem>-styled.docx``）。

    合并链：工作区样式模板 < 命名预设 < 显式 format_spec（逐字段深合并）。
    只应用样式定义（页面/正文/标题），不改写正文与页眉页脚文本；
    ``clear_direct_formatting`` 可清除 run 级直接字体格式（保留加粗/斜体）；
    ``dry_run`` 只返回将变化的样式，不落盘。
    """
    template_spec = (
        _template_spec_or_raise(req.style_template_id, req.workspace_path)
        if req.style_template_id
        else None
    )
    spec = merge_template_with_spec(
        template_spec, req.format_spec_preset, req.format_spec
    )
    if spec is None:
        raise OfficeGenerateError(
            "style/apply 需要 style_template_id、format_spec_preset 或 "
            "format_spec 至少一项"
        )
    return apply_style_to_document(
        Path(req.file_path),
        spec,
        workspace_path=req.workspace_path or None,
        clear_direct_formatting=req.clear_direct_formatting,
        dry_run=req.dry_run,
        overwrite=req.overwrite,
        output_filename=req.output_filename,
    )


# ── 工作区样式模板库（M2）─────────────────────────────────────────────


@router.get("/style-templates", response_model=OfficeStyleTemplateListResult)
def list_style_templates_endpoint(
    workspace_path: Optional[str] = None,
) -> OfficeStyleTemplateListResult:
    """列出工作区样式模板（默认模板置顶）。"""
    if not workspace_path:
        return OfficeStyleTemplateListResult(ok=True, workspace_path="", templates=[])
    workspace = validate_workspace(Path(workspace_path))
    rows = list_style_templates(_conn(), str(workspace))
    return OfficeStyleTemplateListResult(
        ok=True,
        workspace_path=str(workspace),
        templates=[OfficeStyleTemplate(**row) for row in rows],
    )


@router.post("/style-templates", response_model=OfficeStyleTemplateDetailResult)
def create_style_template_endpoint(
    req: WordStyleTemplateSaveRequest,
) -> OfficeStyleTemplateDetailResult:
    """保存一份样式模板（规则包 / 预设+画像 / 纯画像 三选一）.

    ``rulepack``/``rulepack_id`` 走 from-rulepack 转换；``format_spec_preset``
    与 ``format_spec`` 可同时给出（逐字段深合并）。保存的是转换后的画像
    快照——规则包后续修改不会静默改写已保存模板。
    """
    workspace = validate_workspace(Path(req.workspace_path))
    has_pack_source = req.rulepack is not None or req.rulepack_id is not None
    has_spec_source = (
        req.format_spec is not None or req.format_spec_preset is not None
    )
    if has_pack_source and has_spec_source:
        raise OfficeParseError(
            "样式模板来源二选一：规则包或（预设 + 画像），不能混用"
        )
    if has_pack_source:
        if req.rulepack is not None:
            pack = req.rulepack
        else:
            loaded = load_rulepack(
                workspace, req.rulepack_id or DEFAULT_RULEPACK_ID
            )
            pack = loaded["pack"]
        format_spec = format_spec_from_rulepack(pack).format_spec
        source_kind = "rulepack"
        source_ref = req.source_ref or pack.id
    elif has_spec_source:
        resolved = resolve_effective_format_spec(
            req.format_spec_preset, req.format_spec
        )
        if resolved is None:  # pragma: no cover — has_spec_source 保证非 None
            raise OfficeParseError("样式画像解析结果为空")
        format_spec = resolved
        source_kind = "preset" if req.format_spec_preset else "manual"
        source_ref = req.source_ref or req.format_spec_preset
    else:
        raise OfficeParseError(
            "创建样式模板需要 format_spec / format_spec_preset / "
            "rulepack_id / rulepack 之一"
        )
    row = create_style_template(
        _conn(),
        workspace_path=str(workspace),
        name=req.name,
        format_spec=format_spec.model_dump(exclude_none=True),
        source_kind=source_kind,
        source_ref=source_ref,
        is_default=req.is_default,
    )
    return OfficeStyleTemplateDetailResult(
        ok=True, template=OfficeStyleTemplate(**row)
    )


# NOTE: 静态路径必须声明在 /style-templates/{template_id} 之前，否则
# FastAPI 会把 "default" 当作 template_id 匹配到删除端点。
@router.delete("/style-templates/default")
def clear_default_style_template_endpoint(workspace_path: str) -> dict:
    """清除工作区默认样式模板（生成接口不会隐式应用默认模板）."""
    workspace = validate_workspace(Path(workspace_path))
    set_default_style_template(_conn(), str(workspace), None)
    return {"ok": True, "workspace_path": str(workspace)}


@router.delete("/style-templates/{template_id}")
def delete_style_template_endpoint(template_id: str, workspace_path: str) -> dict:
    """删除一行样式模板（仅限该工作区）."""
    workspace = validate_workspace(Path(workspace_path))
    deleted = delete_style_template(
        _conn(), template_id, workspace_path=str(workspace)
    )
    if not deleted:
        raise OfficeParseError(f"样式模板不存在: {template_id}")
    return {
        "ok": True,
        "template_id": template_id,
        "workspace_path": str(workspace),
    }


@router.post(
    "/style-templates/{template_id}/activate",
    response_model=OfficeStyleTemplateDetailResult,
)
def activate_style_template_endpoint(
    template_id: str, req: WordStyleTemplateActivateRequest
) -> OfficeStyleTemplateDetailResult:
    """设置为工作区默认样式模板（仅用于前端下拉预选）."""
    workspace = validate_workspace(Path(req.workspace_path))
    row = set_default_style_template(_conn(), str(workspace), template_id)
    if row is None:  # pragma: no cover — store 已对不存在抛错
        raise OfficeParseError(f"样式模板不存在: {template_id}")
    return OfficeStyleTemplateDetailResult(
        ok=True, template=OfficeStyleTemplate(**row)
    )


__all__ = [
    "WordStyleApplyRequest",
    "WordStyleFromRulepackRequest",
    "WordStyleTemplateActivateRequest",
    "WordStyleTemplateSaveRequest",
    "activate_style_template_endpoint",
    "apply_style_endpoint",
    "clear_default_style_template_endpoint",
    "create_style_template_endpoint",
    "delete_style_template_endpoint",
    "from_rulepack_endpoint",
    "list_style_presets_endpoint",
    "list_style_templates_endpoint",
    "router",
]
