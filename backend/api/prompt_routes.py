"""Prompt 模板库路由（R27-A）。

用户自定义提示词模板的 CRUD。存储走 preferences KV 模式
（``SettingsRepository`` 键 ``prompt_templates``，JSON 列表），上限
100 条防膨胀。与 system_routes 同口径：router 无条件 include。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.data.settings_repo import SettingsRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/prompts", tags=["prompts"])

_KV_KEY = "prompt_templates"
_MAX_TEMPLATES = 100
_MAX_NAME_LEN = 60
_MAX_CONTENT_LEN = 8000


class PromptTemplateIn(BaseModel):
    """POST /prompts/templates body。"""

    name: str = Field(min_length=1, max_length=_MAX_NAME_LEN)
    content: str = Field(min_length=1, max_length=_MAX_CONTENT_LEN)
    description: str = Field(default="", max_length=300)


class PromptTemplateUpdate(BaseModel):
    """PUT /prompts/templates/{id} body —— 部分更新，全字段可选。"""

    name: Optional[str] = Field(default=None, min_length=1, max_length=_MAX_NAME_LEN)
    content: Optional[str] = Field(default=None, min_length=1, max_length=_MAX_CONTENT_LEN)
    description: Optional[str] = Field(default="", max_length=300)


def _load() -> List[Dict[str, Any]]:
    try:
        raw = SettingsRepository().get_json(_KV_KEY)
    except Exception as exc:  # noqa: BLE001 — KV 不可达按空库处理
        logger.warning("prompt templates load failed: %s", exc)
        return []
    return raw if isinstance(raw, list) else []


def _save(templates: List[Dict[str, Any]]) -> None:
    SettingsRepository().set_json(_KV_KEY, templates)


@router.get("/templates")
def list_templates() -> Dict[str, Any]:
    """列出全部模板（按更新时间新→旧）。"""
    templates = sorted(_load(), key=lambda t: t.get("updated_at", 0), reverse=True)
    return {"templates": templates}


@router.post("/templates")
def create_template(body: PromptTemplateIn) -> Dict[str, Any]:
    templates = _load()
    if len(templates) >= _MAX_TEMPLATES:
        return JSONResponse(
            status_code=400,
            content={"error": f"模板数量已达上限（{_MAX_TEMPLATES} 条），请先删除部分模板"},
        )
    now = int(time.time() * 1000)
    template = {
        "id": f"pt-{now}-{len(templates)}",
        "name": body.name.strip(),
        "description": body.description.strip(),
        "content": body.content,
        "created_at": now,
        "updated_at": now,
    }
    templates.append(template)
    _save(templates)
    return {"template": template}


@router.put("/templates/{template_id}")
def update_template(template_id: str, body: PromptTemplateUpdate) -> Dict[str, Any]:
    templates = _load()
    for template in templates:
        if template.get("id") == template_id:
            if body.name is not None:
                template["name"] = body.name.strip()
            if body.content is not None:
                template["content"] = body.content
            template["description"] = (body.description or "").strip()
            template["updated_at"] = int(time.time() * 1000)
            _save(templates)
            return {"template": template}
    return JSONResponse(status_code=404, content={"error": f"模板不存在: {template_id}"})


@router.delete("/templates/{template_id}")
def delete_template(template_id: str) -> Dict[str, Any]:
    templates = _load()
    remaining = [t for t in templates if t.get("id") != template_id]
    if len(remaining) == len(templates):
        return JSONResponse(status_code=404, content={"error": f"模板不存在: {template_id}"})
    _save(remaining)
    return {"ok": True}
