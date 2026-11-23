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

from backend.office.storage import validate_workspace
from backend.office.word_rulepack_models import (
    WordRulePack,
    WordStyleProfileConversion,
)
from backend.office.word_rulepack_store import DEFAULT_RULEPACK_ID, load_rulepack
from backend.office.word_style_presets import list_style_presets
from backend.office.word_style_profile import format_spec_from_rulepack

router = APIRouter(prefix="/word", tags=["office"])


class WordStyleFromRulepackRequest(BaseModel):
    """POST /office/word/style/from-rulepack body。"""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str = ""
    rulepack_id: Optional[str] = Field(default=None, max_length=80)
    rulepack: Optional[WordRulePack] = None


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


__all__ = ["router"]
