"""Word 样式模板路由（命名预设 / 已有文档套用 / 规则包转换）。

挂载于 ``backend.api.office_routes`` 的聚合 router 下，本模块 prefix 为
``/word``，实际路径为 ``/api/v1/office/word/style-*`` 与
``/api/v1/office/word/style/apply|from-rulepack``。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from backend.office.errors import OfficeGenerateError
from backend.office.models import WordFormatSpec
from backend.office.storage import validate_workspace
from backend.office.word_rulepack_models import (
    WordRulePack,
    WordStyleProfileConversion,
)
from backend.office.word_rulepack_store import DEFAULT_RULEPACK_ID, load_rulepack
from backend.office.word_style_apply import apply_style_to_document
from backend.office.word_style_presets import (
    list_style_presets,
    resolve_effective_format_spec,
)
from backend.office.word_style_profile import format_spec_from_rulepack

router = APIRouter(prefix="/word", tags=["office"])


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
    format_spec_preset: Optional[str] = Field(default=None, max_length=80)
    format_spec: Optional[WordFormatSpec] = None
    clear_direct_formatting: bool = False
    overwrite: bool = False
    output_filename: Optional[str] = Field(default=None, max_length=200)
    dry_run: bool = False


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


@router.post("/style/apply")
def apply_style_endpoint(req: WordStyleApplyRequest) -> dict:
    """给已有 .docx 套用样式画像（默认输出 ``<stem>-styled.docx``）。

    只应用样式定义（页面/正文/标题），不改写正文与页眉页脚文本；
    ``clear_direct_formatting`` 可清除 run 级直接字体格式（保留加粗/斜体）；
    ``dry_run`` 只返回将变化的样式，不落盘。
    """
    spec = resolve_effective_format_spec(req.format_spec_preset, req.format_spec)
    if spec is None:
        raise OfficeGenerateError(
            "style/apply 需要 format_spec_preset 或 format_spec"
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


__all__ = ["router"]
