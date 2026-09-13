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


@router.get("/templates/export")
def export_templates() -> Dict[str, Any]:
    """R30: 导出全部模板（导入/迁移用，与 R19 记忆导出同模式）。"""
    return {
        "app": "sage",
        "kind": "prompt_templates",
        "version": 1,
        "exported_at": int(time.time() * 1000),
        "templates": _load(),
    }


class ImportEnvelope(BaseModel):
    """POST /prompts/templates/import body —— 与 export 信封对称。"""

    version: int = Field(default=1)
    # 宽松类型：单条非法条目由导入循环跳过计数，而非整体 422
    templates: List[Any] = Field(default_factory=list)
    # R32: 同名冲突处理 —— skip（默认，保留现有）/ overwrite（覆盖现有内容，
    # 保留现有 id 使斜杠映射与变量记忆不断链）
    conflict: str = Field(default="skip")


@router.post("/templates/import")
def import_templates(body: ImportEnvelope) -> Dict[str, Any]:
    """导入模板信封：同名冲突按 conflict 策略处理，单条非法跳过不中断。

    conflict=skip（默认）：同名跳过，响应带 conflicts=[同名清单] 供前端
    发起覆盖导入；conflict=overwrite：同名模板以导入内容覆盖（保留现有
    id —— 斜杠 tpl-<名称> 映射与变量记忆 key 不受影响）。
    返回 {imported, skipped, failed, conflicts, errors}；导入后总量受
    100 条上限约束，超出部分计入 skipped。
    """
    if body.version != 1:
        return JSONResponse(status_code=400, content={"error": "unsupported import version"})
    overwrite = body.conflict == "overwrite"

    templates = _load()
    existing_by_name: Dict[str, Dict[str, Any]] = {
        t.get("name"): t for t in templates if isinstance(t, dict) and t.get("name")
    }
    now = int(time.time() * 1000)
    imported = skipped = failed = 0
    conflicts: List[str] = []
    errors: List[str] = []
    changed = False
    for entry in body.templates:
        if not isinstance(entry, dict):
            failed += 1
            continue
        name = str(entry.get("name") or "").strip()
        content = str(entry.get("content") or "")
        if not name or not content.strip():
            skipped += 1
            continue
        existing = existing_by_name.get(name)
        if existing is not None and not overwrite:
            conflicts.append(name)
            skipped += 1
            continue
        if len(content) > _MAX_CONTENT_LEN or len(name) > _MAX_NAME_LEN:
            failed += 1
            if len(errors) < 10:
                errors.append(f"{name}: 长度超限")
            continue
        if len(templates) >= _MAX_TEMPLATES and existing is None:
            skipped += 1
            continue
        if existing is not None:
            # 覆盖：保留现有 id（斜杠映射/变量记忆 key 不断链）
            existing["content"] = content
            existing["description"] = str(entry.get("description") or "").strip()[:300]
            existing["updated_at"] = now
        else:
            templates.append(
                {
                    "id": f"pt-{now}-{len(templates)}",
                    "name": name,
                    "description": str(entry.get("description") or "").strip()[:300],
                    "content": content,
                    "created_at": now,
                    "updated_at": now,
                }
            )
        existing_by_name[name] = templates[-1] if existing is None else existing
        imported += 1
        changed = True
    if changed:
        _save(templates)
    return {
        "imported": imported,
        "skipped": skipped,
        "failed": failed,
        "conflicts": conflicts,
        "errors": errors,
    }


@router.delete("/templates/{template_id}")
def delete_template(template_id: str) -> Dict[str, Any]:
    templates = _load()
    remaining = [t for t in templates if t.get("id") != template_id]
    if len(remaining) == len(templates):
        return JSONResponse(status_code=404, content={"error": f"模板不存在: {template_id}"})
    _save(remaining)
    return {"ok": True}
