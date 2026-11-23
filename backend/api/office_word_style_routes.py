"""Word 样式模板路由（命名预设 / 已有文档套用 / 规则包转换）。

挂载于 ``backend.api.office_routes`` 的聚合 router 下，本模块 prefix 为
``/word``，实际路径为 ``/api/v1/office/word/style-*`` 与
``/api/v1/office/word/style/apply|from-rulepack``。
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.office.word_style_presets import list_style_presets

router = APIRouter(prefix="/word", tags=["office"])


@router.get("/style-presets")
def list_style_presets_endpoint() -> dict:
    """列出内置命名样式预设（id/name/description）。

    生成接口的 ``format_spec_preset`` 接受这里返回的 id；前端与 LLM 工具
    可据此提供版式选择。
    """
    return {"ok": True, "presets": list_style_presets()}


__all__ = ["router"]
