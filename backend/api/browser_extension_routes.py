"""外部日常浏览器扩展桥 — HTTP 路由。

两组路径，鉴权口径不同：

- ``/api/v1/web-access/extension/*``：扩展直接调用。``LocalAuthMiddleware``
  对这些路径放行，因为扩展无法持有 Electron 注入的本地 capability；每个
  端点在这里校验 ``X-Sage-Extension-Token``（配对端点用一次性配对码）。
- ``/api/v1/web-access/browser-extension/*``：设置页管理端点，仍受
  ``LocalAuthMiddleware`` 保护，并复用 Origin 守卫。

所有处理函数都是同步 ``def``：轮询会阻塞最多 20 秒，FastAPI 会把它们放到
线程池执行，避免占住事件循环。
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Extra, Field

from backend.api.permission_routes import forbidden_origin_response
from backend.services.browser_extension_bridge import (
    MAX_RESULT_BYTES,
    BrowserExtensionError,
    CommandTimeoutError,
    ExtensionAuthError,
    PairingError,
    SharedTabError,
    UnsupportedCommandError,
    browser_extension_bridge,
    extension_directory,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["browser-extension"])


class ExtensionPairBody(BaseModel):
    code: str = Field(max_length=64)
    label: str = Field(default="", max_length=128)

    class Config:
        extra = Extra.forbid


class ExtensionTabBody(BaseModel):
    id: Any = None
    url: str = Field(default="", max_length=4096)
    title: str = Field(default="", max_length=512)

    class Config:
        extra = Extra.forbid


class ExtensionPollBody(BaseModel):
    tab: Optional[ExtensionTabBody] = None

    class Config:
        extra = Extra.forbid


class ExtensionResultBody(BaseModel):
    command_id: str = Field(max_length=128)
    ok: bool
    result: Any = None
    error: Optional[Dict[str, Any]] = None

    class Config:
        extra = Extra.forbid


class ExtensionDetachBody(BaseModel):
    reason: str = Field(default="user", max_length=128)

    class Config:
        extra = Extra.forbid


class ExtensionSyncBody(BaseModel):
    url: str = Field(max_length=4096)
    cookies: List[Dict[str, Any]] = Field(default_factory=list)
    origins: List[Dict[str, Any]] = Field(default_factory=list)

    class Config:
        extra = Extra.forbid


def _error_response(exc: BrowserExtensionError) -> JSONResponse:
    if isinstance(exc, ExtensionAuthError):
        status = 401
    elif isinstance(exc, PairingError):
        status = 403
    elif isinstance(exc, SharedTabError):
        status = 409
    elif isinstance(exc, CommandTimeoutError):
        status = 504
    elif isinstance(exc, UnsupportedCommandError):
        status = 422
    else:
        status = 400
    return JSONResponse(
        status_code=status,
        content={"ok": False, "error": exc.code, "message": str(exc)[:500]},
    )


def _backend_base_url() -> str:
    raw_port = os.environ.get("PYTHON_BACKEND_PORT", "8765").strip()
    try:
        port = int(raw_port)
    except ValueError:
        port = 8765
    if not 0 < port < 65536:
        port = 8765
    return f"http://127.0.0.1:{port}"


def _extension_origin_guard(request: Request) -> Any:
    """Reject drive-by browser requests from ordinary web pages.

    Extension service-worker fetches carry either no Origin or a
    ``chrome-extension://`` origin; any http(s) Origin is a web page and must
    not be able to pair/guess codes or poll with a stolen token.
    """
    origin = request.headers.get("origin") or ""
    if origin.startswith(("http://", "https://")):
        return JSONResponse(
            status_code=403,
            content={"ok": False, "error": "forbidden_origin"},
        )
    return None


# ---------------------------------------------------------------------------
# Extension-facing endpoints (device token / pairing code)
# ---------------------------------------------------------------------------


@router.post("/web-access/extension/pair")
def pair_extension(request: Request, body: ExtensionPairBody) -> Any:
    """Exchange a one-time pairing code for a device token."""
    guard = _extension_origin_guard(request)
    if guard:
        return guard
    try:
        result = browser_extension_bridge.pair(body.code, body.label)
    except BrowserExtensionError as exc:
        return _error_response(exc)
    return {
        "ok": True,
        "device_id": result["device_id"],
        "device_token": result["device_token"],
        "label": result["label"],
        "base_url": _backend_base_url(),
    }


@router.post("/web-access/extension/poll")
def poll_extension(
    request: Request,
    body: ExtensionPollBody,
    token: str = Header("", alias="X-Sage-Extension-Token"),
) -> Any:
    """Long-poll for one command; ``tab`` reports the currently shared tab."""
    guard = _extension_origin_guard(request)
    if guard:
        return guard
    tab = None
    if body.tab is not None:
        tab = {"id": body.tab.id, "url": body.tab.url, "title": body.tab.title}
    try:
        command = browser_extension_bridge.poll(token, tab)
    except BrowserExtensionError as exc:
        return _error_response(exc)
    return {"ok": True, "command": command}


@router.post("/web-access/extension/result")
def extension_result(
    request: Request,
    body: ExtensionResultBody,
    token: str = Header("", alias="X-Sage-Extension-Token"),
) -> Any:
    """Resolve a pending command with the extension's result/error."""
    guard = _extension_origin_guard(request)
    if guard:
        return guard
    if body.result is not None:
        try:
            encoded = json.dumps(body.result, ensure_ascii=False).encode("utf-8")
        except (TypeError, ValueError):
            return JSONResponse(
                status_code=422,
                content={"ok": False, "error": "invalid_result_payload"},
            )
        if len(encoded) > MAX_RESULT_BYTES:
            return JSONResponse(
                status_code=413,
                content={"ok": False, "error": "result_too_large"},
            )
    try:
        accepted = browser_extension_bridge.submit_result(
            token, body.command_id, body.ok, body.result, body.error
        )
    except BrowserExtensionError as exc:
        return _error_response(exc)
    return {"ok": True, "accepted": accepted}


@router.post("/web-access/extension/detach")
def detach_extension(
    request: Request,
    body: ExtensionDetachBody,
    token: str = Header("", alias="X-Sage-Extension-Token"),
) -> Any:
    """Stop sharing from the extension side (user clicked stop / tab closed)."""
    guard = _extension_origin_guard(request)
    if guard:
        return guard
    try:
        browser_extension_bridge.detach(token, reason=body.reason or "user")
    except BrowserExtensionError as exc:
        return _error_response(exc)
    return {"ok": True}


@router.post("/web-access/extension/sync-session")
def sync_extension_session(
    request: Request,
    body: ExtensionSyncBody,
    token: str = Header("", alias="X-Sage-Extension-Token"),
) -> Any:
    """Save the shared tab's cookies + localStorage into the encrypted vault."""
    guard = _extension_origin_guard(request)
    if guard:
        return guard
    try:
        result = browser_extension_bridge.sync_session(
            token,
            {"url": body.url, "cookies": body.cookies, "origins": body.origins},
        )
    except BrowserExtensionError as exc:
        return _error_response(exc)
    except ValueError as exc:
        return JSONResponse(
            status_code=422, content={"ok": False, "error": str(exc)[:200]}
        )
    return {"ok": True, **result}


# ---------------------------------------------------------------------------
# Settings-facing endpoints (LocalAuthMiddleware + Origin guard)
# ---------------------------------------------------------------------------


@router.post("/web-access/browser-extension/pairing-code")
def create_pairing_code(request: Request) -> Any:
    guard = forbidden_origin_response(request)
    if guard:
        return guard
    try:
        code = browser_extension_bridge.issue_pairing_code()
    except BrowserExtensionError as exc:
        return _error_response(exc)
    return {
        "ok": True,
        "code": code["code"],
        "expires_at": code["expires_at"],
        "base_url": _backend_base_url(),
        "extension_dir": extension_directory(),
    }


@router.get("/web-access/browser-extension/status")
def extension_status(request: Request) -> Any:
    guard = forbidden_origin_response(request)
    if guard:
        return guard
    devices = browser_extension_bridge.list_devices()
    return {
        "ok": True,
        "devices": devices,
        "connected": any(item.get("connected") for item in devices),
        "shared": browser_extension_bridge.shared_summary(),
        "base_url": _backend_base_url(),
        "extension_dir": extension_directory(),
    }


@router.delete("/web-access/browser-extension/devices/{device_id}")
def revoke_extension_device(request: Request, device_id: str) -> Any:
    guard = forbidden_origin_response(request)
    if guard:
        return guard
    if not browser_extension_bridge.revoke_device(device_id):
        return JSONResponse(
            status_code=404, content={"ok": False, "error": "device_not_found"}
        )
    return {"ok": True}
