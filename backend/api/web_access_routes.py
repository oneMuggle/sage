"""网页访问凭据 / 配置 REST 路由（Round 12 凭据管理 UI）。

前端契约（设置→网络"网站凭据"区块）:

- ``GET /api/v1/web-access/credentials``
    → ``{"credentials": [CredentialRecord, ...]}``（脱敏：只含 domain /
    kind / 名字列表 / 时效 / encrypted / source_profile，无任何值）。

- ``DELETE /api/v1/web-access/credentials/{domain}``
    → ``{"ok": true}``；无档案 → 404。

- ``GET /api/v1/web-access/config``
    → ``{"render_persistent": bool, "auto_refresh_credentials": bool}``
    （缺省键按 False 补齐）。

- ``PUT /api/v1/web-access/config``
    body 仅接受上述两个 bool 键（未知键 422）→ 与现有值合并写回。

安全口径（沿用 permission_routes 约定）：

- 全部端点自带定向 Origin 守卫（``forbidden_origin_response``）：后端
  CORS 全开的背景下挡住第三方网页的 drive-by 读取 / 删除。
- list / config 永不回显 cookie 值或加密体；删除不可逆，前端二次确认。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Extra

from backend.api.permission_routes import forbidden_origin_response
from backend.api.settings_models import model_dump_compat
from backend.data.settings_repo import SettingsRepository
from backend.tools.credential_vault import delete_credential, list_credentials

logger = logging.getLogger(__name__)

router = APIRouter(tags=["web-access"])

#: preferences 表里渲染 / 自动刷新配置的 key（web_render 同款）
SETTINGS_KEY_WEB_ACCESS_CONFIG = "web_access_config"

#: PUT config 允许的键 → 类型（未知键一律 422，防误写）
_CONFIG_BOOL_KEYS = ("render_persistent", "auto_refresh_credentials")


class WebAccessConfigBody(BaseModel):
    """PUT config 请求体：两个可选 bool，禁止额外键。"""

    render_persistent: Optional[bool] = None
    auto_refresh_credentials: Optional[bool] = None

    class Config:
        extra = Extra.forbid


def _origin_guard(request: Request) -> Optional[JSONResponse]:
    return forbidden_origin_response(request)


def _load_config_dict() -> Dict[str, Any]:
    try:
        raw = SettingsRepository().get(SETTINGS_KEY_WEB_ACCESS_CONFIG)
        parsed = json.loads(raw) if raw else {}
        return parsed if isinstance(parsed, dict) else {}
    except Exception:  # noqa: BLE001 — 读失败按默认配置
        return {}


@router.get("/web-access/credentials")
async def list_web_credentials(request: Request) -> Dict[str, Any]:
    guard = _origin_guard(request)
    if guard:
        return guard
    return {"credentials": list_credentials()}


@router.delete("/web-access/credentials/{domain}")
async def delete_web_credential(request: Request, domain: str) -> Dict[str, Any]:
    guard = _origin_guard(request)
    if guard:
        return guard
    deleted = delete_credential(domain)
    if not deleted:
        return JSONResponse(status_code=404, content={"ok": False, "error": "not_found"})
    return {"ok": True}


@router.get("/web-access/config")
async def get_web_access_config(request: Request) -> Dict[str, Any]:
    guard = _origin_guard(request)
    if guard:
        return guard
    data = _load_config_dict()
    return {
        "render_persistent": bool(data.get("render_persistent")),
        "auto_refresh_credentials": bool(data.get("auto_refresh_credentials")),
    }


@router.put("/web-access/config")
async def put_web_access_config(request: Request, body: WebAccessConfigBody) -> Dict[str, Any]:
    guard = _origin_guard(request)
    if guard:
        return guard
    data = _load_config_dict()
    updates = model_dump_compat(body, exclude_none=True)
    data.update(updates)
    try:
        SettingsRepository().set(
            SETTINGS_KEY_WEB_ACCESS_CONFIG, json.dumps(data, ensure_ascii=False)
        )
    except Exception as exc:  # noqa: BLE001 — 写失败透出给 UI
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)[:200]})
    return {
        "ok": True,
        "render_persistent": bool(data.get("render_persistent")),
        "auto_refresh_credentials": bool(data.get("auto_refresh_credentials")),
    }
