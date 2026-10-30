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
from typing import Any, Dict, List, Optional
<<<<<<< HEAD
from urllib.parse import urlsplit
=======
>>>>>>> origin/main

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Extra

from backend.api.permission_routes import forbidden_origin_response
from backend.api.settings_models import model_dump_compat
from backend.data.settings_repo import SettingsRepository
<<<<<<< HEAD
from backend.services.site_login_jobs import site_login_jobs
from backend.services.site_login_templates import (
    SITE_LOGIN_TEMPLATES,
    display_name_for_host,
    login_url_for_host,
)
=======
>>>>>>> origin/main
from backend.tools.credential_vault import (
    delete_credential,
    list_credentials,
    save_credential,
    save_header_credential,
)

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


class HeaderCredentialBody(BaseModel):
    """POST header 凭据请求体（Round 14：凭据 UI header 型新增）。"""

    domain: str
    header_name: str
    value: str

    class Config:
        extra = Extra.forbid


class CookieCredentialBody(BaseModel):
    """POST cookie credential request; values are validated again by the vault."""

    domain: str
    cookies: List[Dict[str, Any]]

    class Config:
        extra = Extra.forbid


<<<<<<< HEAD
class SiteLoginBody(BaseModel):
    """POST /web-access/sites/login：用户选定的登录入口 URL。"""

    url: str

    class Config:
        extra = Extra.forbid


=======
>>>>>>> origin/main
def _origin_guard(request: Request) -> Optional[JSONResponse]:
    return forbidden_origin_response(request)


def _metrics_snapshot() -> Dict[str, Any]:
    from backend.tools import tls_transport, web_metrics

    snapshot = web_metrics.snapshot()
    # R28：AB3 指纹通道使用计数（未启用/未使用时计数为 0，键恒存在）
    snapshot["tls_fingerprint"] = tls_transport.stats()
    return snapshot


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


@router.post("/web-access/credentials/header")
async def create_header_credential(request: Request, body: HeaderCredentialBody) -> Dict[str, Any]:
    """新增 header 型凭据（Round 14：凭据 UI header 型新增入口）。

    名/值校验沿用 save_header_credential（token 文法 / 禁传输头 / 拒换行）；
    非法 → 422。Origin 守卫同全路由口径。
    """
    guard = _origin_guard(request)
    if guard:
        return guard
    try:
        save_header_credential(
            body.domain.strip().lower(), {body.header_name: body.value}
        )
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"ok": False, "error": str(exc)[:200]})
    return {"ok": True}


@router.post("/web-access/credentials/cookie")
async def create_cookie_credential(
    request: Request, body: CookieCredentialBody
) -> Dict[str, Any]:
    """新增 cookie 型凭据，沿用凭据库校验并隐藏请求内容。"""
    guard = _origin_guard(request)
    if guard:
        return guard
<<<<<<< HEAD
    if len(body.cookies) > 500:
        return JSONResponse(
            status_code=422, content={"ok": False, "error": "too_many_cookies"}
        )
=======
>>>>>>> origin/main
    try:
        save_credential(body.domain.strip().lower(), body.cookies)
    except ValueError:
        return JSONResponse(
            status_code=422,
            content={"ok": False, "error": "invalid_cookie_credential"},
        )
    return {"ok": True}


<<<<<<< HEAD
@router.get("/web-access/site-templates")
async def get_site_login_templates(request: Request) -> Dict[str, Any]:
    """常见站点登录模板（展示名 / 登录入口 / 登录方式提示）。"""
    guard = _origin_guard(request)
    if guard:
        return guard
    return {"templates": SITE_LOGIN_TEMPLATES}


@router.get("/web-access/sites")
async def get_sites(request: Request) -> Dict[str, Any]:
    """已登录的网站（脱敏）：仅 cookie/header 档案的展示信息，不含任何值。"""
    guard = _origin_guard(request)
    if guard:
        return guard
    sites: List[Dict[str, Any]] = []
    for record in list_credentials():
        domain = str(record.get("domain") or "")
        host = domain.lstrip(".")
        if not host:
            continue
        sites.append(
            {
                "domain": domain,
                "display_name": display_name_for_host(host),
                "login_url": login_url_for_host(host),
                "kind": record.get("kind", "cookie"),
                "status": "expired" if record.get("expired") else "logged_in",
                "expires_in_seconds": record.get("expires_in_seconds"),
                "has_local_storage": bool(record.get("has_storage")),
                "origin_count": int(record.get("origin_count") or 0),
                "saved_at": record.get("saved_at"),
                "source_profile": record.get("source_profile"),
            }
        )
    return {"sites": sites}


@router.post("/web-access/sites/login")
async def start_site_login(  # noqa: PLR0911 — 各拒绝路径独立 return，扁平更直读
    request: Request, body: SiteLoginBody
) -> Dict[str, Any]:
    """启动后台登录任务；返回 job_id，前端轮询状态。"""
    guard = _origin_guard(request)
    if guard:
        return guard
    url = (body.url or "").strip()
    if not url.startswith(("http://", "https://")):
        return JSONResponse(
            status_code=422,
            content={"ok": False, "error": "invalid_url_scheme"},
        )
    if not urlsplit(url).hostname:
        return JSONResponse(status_code=422, content={"ok": False, "error": "invalid_url"})
    parsed_url = urlsplit(url)
    if parsed_url.username or parsed_url.password:
        # 拒绝把账号密码嵌在 URL 里（会随响应/任务记录回显）
        return JSONResponse(
            status_code=422, content={"ok": False, "error": "url_userinfo_not_allowed"}
        )
    # 与 web_fetch / browser_navigate 同口径：离线 / 白名单模式不得绕过门禁
    from backend.tools.network_config import load_network_policy

    rejection = load_network_policy().check_host(url)
    if rejection:
        return JSONResponse(status_code=403, content={"ok": False, "error": rejection})
    try:
        job_id = site_login_jobs.start(url)
    except ValueError as exc:
        in_progress = str(exc) == "login_in_progress"
        return JSONResponse(
            status_code=409 if in_progress else 422,
            content={"ok": False, "error": str(exc)[:200]},
        )
    return {"job_id": job_id, "url": url}


@router.get("/web-access/sites/login/{job_id}")
async def get_site_login_job(request: Request, job_id: str) -> Dict[str, Any]:
    guard = _origin_guard(request)
    if guard:
        return guard
    job = site_login_jobs.get(job_id)
    if job is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": "job_not_found"})
    return job


@router.delete("/web-access/sites/{domain}")
async def delete_site_session(request: Request, domain: str) -> Dict[str, Any]:
    guard = _origin_guard(request)
    if guard:
        return guard
    if not delete_credential(domain):
        return JSONResponse(status_code=404, content={"ok": False, "error": "not_found"})
    return {"ok": True}


=======
>>>>>>> origin/main
@router.get("/web-access/metrics")
async def get_web_metrics(request: Request) -> Dict[str, Any]:
    """Per-host 出网指标（Round 15 X2 延伸；进程内存态，重启清零）。"""
    guard = _origin_guard(request)
    if guard:
        return guard
    return {"metrics": _metrics_snapshot()}


@router.put("/web-access/metrics/reset")
async def reset_web_metrics(request: Request) -> Dict[str, Any]:
    guard = _origin_guard(request)
    if guard:
        return guard
    from backend.tools import web_metrics

    web_metrics.reset()
    return {"ok": True}
