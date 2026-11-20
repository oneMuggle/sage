"""浏览器多账号 REST 路由（2026-11-20 browser-multi-account）。

前端契约（设置→网络→账号管理区块 / AI 切换确认弹窗）:

- ``GET /api/v1/browser-accounts?domain=``
    → ``{"accounts": [AccountRecord, ...]}``（账号 ID / 名称 / 域名 / 颜色 /
    是否默认 / 时间戳，无任何凭据值）。

- ``POST /api/v1/browser-accounts``
    body ``{label, domain, color?, notes?, is_default?}`` → 新建账号。

- ``PUT /api/v1/browser-accounts/{account_id}``
    body 可选键 ``{label?, color?, notes?, is_default?}`` → 更新账号。

- ``DELETE /api/v1/browser-accounts/{account_id}``
    → ``{"ok": true}``；同时删除该账号的 vault 凭据。

- ``POST /api/v1/browser-accounts/switch``
    body ``{account_id, browser_id?}`` → 触发 Cookie State Swap。

- ``POST /api/v1/browser-accounts/login``
    body ``{url, account_id?, account_label?, approved?}`` → 启动后台登录任务
    （job_id 轮询，复用 web-access 登录任务表）。

安全口径（沿用 web-access 约定）：

- 全部端点自带定向 Origin 守卫（``forbidden_origin_response``）。
- list 永不回显 cookie 值；delete 不可逆，前端二次确认。
- 切换 / 登录属于对外部网站的身份操作，UI 侧需用户显式确认。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Extra

from backend.api.permission_routes import forbidden_origin_response
from backend.services.browser_account_service import browser_account_service
from backend.services.site_login_jobs import site_login_jobs

logger = logging.getLogger(__name__)

router = APIRouter(tags=["browser-accounts"])


class CreateAccountBody(BaseModel):
    """POST /browser-accounts：新建账号。"""

    label: str
    domain: str
    color: Optional[str] = None
    notes: Optional[str] = None
    is_default: bool = False

    class Config:
        extra = Extra.forbid


class UpdateAccountBody(BaseModel):
    """PUT /browser-accounts/{id}：更新账号元数据（全部可选）。"""

    label: Optional[str] = None
    color: Optional[str] = None
    notes: Optional[str] = None
    is_default: Optional[bool] = None

    class Config:
        extra = Extra.forbid


class SwitchAccountBody(BaseModel):
    """POST /browser-accounts/switch：切换到目标账号。"""

    account_id: str
    browser_id: Optional[str] = None

    class Config:
        extra = Extra.forbid


class AccountLoginBody(BaseModel):
    """POST /browser-accounts/login：带账号登录。"""

    url: str
    account_id: Optional[str] = None
    account_label: Optional[str] = None
    approved: bool = False

    class Config:
        extra = Extra.forbid


def _origin_guard(request: Request) -> Optional[JSONResponse]:
    return forbidden_origin_response(request)


@router.get("/browser-accounts")
async def list_accounts(request: Request, domain: str = "") -> Dict[str, Any]:
    """列出账号（可按 domain 过滤，含懒迁移默认账号）。"""
    guard = _origin_guard(request)
    if guard:
        return guard
    try:
        accounts = browser_account_service.list_accounts(domain or None)
    except Exception as exc:  # noqa: BLE001 — 列表失败如实回传
        logger.warning("列出浏览器账号失败", exc_info=True)
        return JSONResponse(
            status_code=500, content={"ok": False, "error": str(exc)[:300]}
        )
    return {"accounts": [a.to_dict() for a in accounts]}


@router.post("/browser-accounts")
async def create_account(request: Request, body: CreateAccountBody) -> Any:
    """新建账号；同 domain + label 重复 → 409。"""
    guard = _origin_guard(request)
    if guard:
        return guard
    try:
        account = browser_account_service.create_account(
            label=body.label,
            domain=body.domain,
            color=body.color,
            notes=body.notes,
            is_default=body.is_default,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=409, content={"ok": False, "error": str(exc)[:300]}
        )
    return {"ok": True, "account": account.to_dict()}


@router.put("/browser-accounts/{account_id}")
async def update_account(
    request: Request, account_id: str, body: UpdateAccountBody
) -> Any:
    """更新账号元数据；不存在 → 404。"""
    guard = _origin_guard(request)
    if guard:
        return guard
    try:
        account = browser_account_service.update_account(
            account_id,
            label=body.label,
            color=body.color,
            notes=body.notes,
            is_default=body.is_default,
        )
    except KeyError:
        return JSONResponse(status_code=404, content={"ok": False, "error": "not_found"})
    except ValueError as exc:
        return JSONResponse(
            status_code=409, content={"ok": False, "error": str(exc)[:300]}
        )
    return {"ok": True, "account": account.to_dict()}


@router.delete("/browser-accounts/{account_id}")
async def delete_account(request: Request, account_id: str) -> Any:
    """删除账号（含其 vault 凭据）；不存在 → 404。"""
    guard = _origin_guard(request)
    if guard:
        return guard
    if not browser_account_service.delete_account(account_id):
        return JSONResponse(status_code=404, content={"ok": False, "error": "not_found"})
    return {"ok": True}


@router.post("/browser-accounts/switch")
async def switch_account(request: Request, body: SwitchAccountBody) -> Any:
    """切换到目标账号（Cookie State Swap）；失败返回可读原因。"""
    guard = _origin_guard(request)
    if guard:
        return guard
    result = browser_account_service.switch_account(
        body.account_id, browser_id=(body.browser_id or None)
    )
    if not result.ok:
        return JSONResponse(
            status_code=409, content={"ok": False, "error": result.message[:300]}
        )
    return {"ok": True, **result.to_dict()}


@router.post("/browser-accounts/login")
async def login_with_account(  # noqa: PLR0911 — 各拒绝路径独立 return，扁平更直读
    request: Request, body: AccountLoginBody
) -> Any:
    """启动带账号的登录任务（job_id 轮询，复用 site_login_jobs）。"""
    guard = _origin_guard(request)
    if guard:
        return guard
    url = (body.url or "").strip()
    if not url.startswith(("http://", "https://")):
        return JSONResponse(
            status_code=422, content={"ok": False, "error": "invalid_url_scheme"}
        )
    parsed_url = urlsplit(url)
    if not parsed_url.hostname:
        return JSONResponse(status_code=422, content={"ok": False, "error": "invalid_url"})
    if parsed_url.username or parsed_url.password:
        return JSONResponse(
            status_code=422, content={"ok": False, "error": "url_userinfo_not_allowed"}
        )
    from backend.tools.network_config import load_network_policy

    rejection = load_network_policy().check_host(url)
    if rejection:
        return JSONResponse(status_code=403, content={"ok": False, "error": rejection})

    account_id = (body.account_id or "").strip() or None
    account_label = (body.account_label or "").strip() or None
    if account_id and account_label:
        return JSONResponse(
            status_code=422,
            content={"ok": False, "error": "account_id 与 account_label 只能二选一"},
        )
    if account_id and browser_account_service.get_account(account_id) is None:
        return JSONResponse(
            status_code=404, content={"ok": False, "error": "account_not_found"}
        )
    if account_label and not account_id:
        # 先建账号（domain 取目标站点 host），再以 account_id 启动登录
        try:
            account = browser_account_service.create_account(
                label=account_label, domain=(parsed_url.hostname or "").lower()
            )
        except ValueError as exc:
            return JSONResponse(
                status_code=409, content={"ok": False, "error": str(exc)[:300]}
            )
        account_id = account.id

    try:
        job_id = site_login_jobs.start(url, account_id=account_id)
    except ValueError as exc:
        in_progress = str(exc) == "login_in_progress"
        return JSONResponse(
            status_code=409 if in_progress else 422,
            content={"ok": False, "error": str(exc)[:200]},
        )
    return {"job_id": job_id, "url": url, "account_id": account_id}


__all__ = ["router"]
