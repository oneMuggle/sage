"""受控浏览器控制面 REST 路由（M3）。

前端契约：

- ``GET /api/v1/browser/control``
    → ``{"sessions": [{"session_id", "state", "alive", "browser_type",
    "headless"}, ...]}``（列举 manager 中的会话，未记录的状态按 agent）。
- ``GET /api/v1/browser/control/{session_id}``
    → ``{"session_id", "state", "known"}``；``known`` 表示 manager 或注册表
    认识该会话。
- ``POST /api/v1/browser/control/{session_id}`` body ``{"action"}``：
    ``pause`` / ``resume`` / ``takeover`` / ``return`` → 更新注册表并回
    ``{"session_id", "state"}``；非法 action → 400；未知会话 → 404。

安全口径沿用 ``web_access_routes``：全部端点带定向 Origin 守卫，且与其它
API 一样受 ``LocalAuthMiddleware`` 保护。状态本体存在进程内存
（``backend.services.browser_control``），浏览器关闭时由工具层 reset。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Extra

from backend.api.permission_routes import forbidden_origin_response
from backend.data import browser_action_repo
from backend.data.settings_repo import SettingsRepository
from backend.services import browser_safety
from backend.services.browser_control import (
    ACTION_TO_STATE,
    VALID_CONTROL_ACTIONS,
    BrowserControlState,
    get_browser_control,
)
from backend.tools.browser_cdp import get_browser_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["browser-use"])

#: 使用偏好设置键（"1" 开 / "0" 关；缺省按开启）
SETTINGS_KEY_DEFAULT_VISIBLE = "browser_use_default_visible"
SETTINGS_KEY_STEP_THUMBNAILS = "browser_step_thumbnails"

_VALID_DECISIONS = ("session", "always", "approve", "deny")


class BrowserControlActionBody(BaseModel):
    """POST control 请求体：单个 action，禁止额外键。"""

    action: str

    class Config:
        extra = Extra.forbid


class BrowserUseConfigBody(BaseModel):
    """PUT use-config 请求体：两个可选布尔开关，禁止额外键。"""

    default_visible: Optional[bool] = None
    step_thumbnails: Optional[bool] = None

    class Config:
        extra = Extra.forbid


class SitePolicyBody(BaseModel):
    """PUT site-policies 请求体：allow / block。"""

    mode: str

    class Config:
        extra = Extra.forbid


class ConfirmationDecisionBody(BaseModel):
    """POST confirmations 请求体：session / always / approve / deny。"""

    decision: str

    class Config:
        extra = Extra.forbid


def _origin_guard(request: Request) -> Optional[JSONResponse]:
    return forbidden_origin_response(request)


def _browser_type_value(session: Any) -> str:
    browser_type = getattr(session, "browser_type", None)
    value = getattr(browser_type, "value", browser_type)
    return str(value or "unknown")


def _session_entry(session: Any) -> Dict[str, Any]:
    registry = get_browser_control()
    try:
        alive = bool(session.is_alive())
    except Exception:  # noqa: BLE001 — 存活探测失败不影响列举
        alive = False
    return {
        "session_id": session.browser_id,
        "state": registry.get_state(session.browser_id).value,
        "alive": alive,
        "browser_type": _browser_type_value(session),
        "headless": bool(getattr(session, "headless", False)),
    }


def _known_session(session_id: str) -> bool:
    if get_browser_manager().get(session_id) is not None:
        return True
    return session_id in get_browser_control().snapshot()


def _invalid_action_response(action: str) -> JSONResponse:
    allowed = "|".join(VALID_CONTROL_ACTIONS)
    return JSONResponse(
        status_code=400,
        content={"ok": False, "error": f"invalid action: {action}（合法值：{allowed}）"},
    )


@router.get("/browser/control")
def list_browser_control(request: Request) -> Any:
    """列举 manager 中的浏览器会话及其实时控制状态。"""
    guard = _origin_guard(request)
    if guard is not None:
        return guard
    sessions: List[Dict[str, Any]] = [
        _session_entry(session) for session in get_browser_manager().all_sessions()
    ]
    return {"sessions": sessions}


@router.get("/browser/control/{session_id}")
def get_browser_control_state(request: Request, session_id: str) -> Any:
    """查询单个会话的控制状态（未知会话也返回 200 + agent）。"""
    guard = _origin_guard(request)
    if guard is not None:
        return guard
    return {
        "session_id": session_id,
        "state": get_browser_control().get_state(session_id).value,
        "known": _known_session(session_id),
    }


@router.post("/browser/control/{session_id}")
def set_browser_control_state(
    request: Request, session_id: str, body: BrowserControlActionBody
) -> Any:
    """pause / resume / takeover / return：更新会话控制状态。"""
    guard = _origin_guard(request)
    if guard is not None:
        return guard
    action = (body.action or "").strip().lower()
    state = ACTION_TO_STATE.get(action)
    if state is None:
        return _invalid_action_response(action)
    if not _known_session(session_id):
        return JSONResponse(
            status_code=404,
            content={"ok": False, "error": "session_not_found"},
        )
    get_browser_control().set_state(session_id, state)
    return {"session_id": session_id, "state": state.value}


# ---------------------------------------------------------------------------
# M4：使用偏好 / 站点策略 / 待确认 / 审计
# ---------------------------------------------------------------------------


def _read_bool_setting(key: str) -> bool:
    """读取布尔开关设置；缺省与读取失败均按开启。"""
    try:
        raw = SettingsRepository().get(key)
    except Exception:  # noqa: BLE001 — 设置读取失败按缺省开启
        logger.debug("读取设置 %s 失败", key, exc_info=True)
        return True
    if raw is None:
        return True
    return str(raw).strip() != "0"


def _write_bool_setting(key: str, value: bool) -> None:
    SettingsRepository().set(key, "1" if value else "0")


@router.get("/browser/use-config")
def get_browser_use_config(request: Request) -> Any:
    """读取受控浏览器使用偏好（默认可见 / 步骤缩略图）。"""
    guard = _origin_guard(request)
    if guard is not None:
        return guard
    return {
        "default_visible": _read_bool_setting(SETTINGS_KEY_DEFAULT_VISIBLE),
        "step_thumbnails": _read_bool_setting(SETTINGS_KEY_STEP_THUMBNAILS),
    }


@router.put("/browser/use-config")
def update_browser_use_config(request: Request, body: BrowserUseConfigBody) -> Any:
    """更新使用偏好；未提供的字段保持不变，返回更新后的完整配置。"""
    guard = _origin_guard(request)
    if guard is not None:
        return guard
    try:
        if body.default_visible is not None:
            _write_bool_setting(SETTINGS_KEY_DEFAULT_VISIBLE, bool(body.default_visible))
        if body.step_thumbnails is not None:
            _write_bool_setting(SETTINGS_KEY_STEP_THUMBNAILS, bool(body.step_thumbnails))
    except Exception:  # noqa: BLE001 — 设置写入失败按 500 返回，不泄露内部细节
        logger.warning("写入受控浏览器偏好失败", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "settings_write_failed"},
        )
    return {
        "default_visible": _read_bool_setting(SETTINGS_KEY_DEFAULT_VISIBLE),
        "step_thumbnails": _read_bool_setting(SETTINGS_KEY_STEP_THUMBNAILS),
    }


@router.get("/browser/site-policies")
def list_browser_site_policies(request: Request) -> Any:
    """列举持久站点策略（allow / block）。"""
    guard = _origin_guard(request)
    if guard is not None:
        return guard
    return {"policies": browser_safety.list_site_policies()}


@router.put("/browser/site-policies/{domain}")
def set_browser_site_policy(request: Request, domain: str, body: SitePolicyBody) -> Any:
    """写入一条持久站点策略（allow / block）。"""
    guard = _origin_guard(request)
    if guard is not None:
        return guard
    try:
        return browser_safety.set_site_policy(domain, body.mode)
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": str(exc)},
        )


@router.delete("/browser/site-policies/{domain}")
def delete_browser_site_policy(request: Request, domain: str) -> Any:
    """删除持久站点策略；不存在 → 404。"""
    guard = _origin_guard(request)
    if guard is not None:
        return guard
    if not browser_safety.remove_site_policy(domain):
        return JSONResponse(
            status_code=404,
            content={"ok": False, "error": "policy_not_found"},
        )
    return {"ok": True, "domain": browser_safety.normalize_domain(domain)}


@router.get("/browser/confirmations")
def list_browser_confirmations(request: Request, session_id: str = "") -> Any:
    """列举待确认项（可按会话过滤）。"""
    guard = _origin_guard(request)
    if guard is not None:
        return guard
    items = browser_safety.get_confirmation_registry().list(session_id or None)
    return {"confirmations": [item.to_public_dict() for item in items]}


@router.post("/browser/confirmations/{confirmation_id}")
def resolve_browser_confirmation(  # noqa: PLR0911 — 每个校验门一个返回是显式设计
    request: Request, confirmation_id: str, body: ConfirmationDecisionBody
) -> Any:
    """裁决一条待确认项；恢复控制状态为 agent。"""
    guard = _origin_guard(request)
    if guard is not None:
        return guard
    decision = (body.decision or "").strip().lower()
    if decision not in _VALID_DECISIONS:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": f"invalid decision: {decision}"},
        )
    registry = browser_safety.get_confirmation_registry()
    pending = registry.get(confirmation_id)
    if pending is None:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "error": "confirmation_not_found"},
        )
    options = (
        browser_safety.SITE_ACCESS_OPTIONS
        if pending.kind == "site_access"
        else browser_safety.SENSITIVE_ACTION_OPTIONS
    )
    if decision not in options:
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "error": f"decision {decision} 不适用于 {pending.kind}（合法值：{'|'.join(options)}）",
            },
        )
    resolved = registry.resolve(confirmation_id, decision)
    if resolved is None:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "error": "confirmation_not_found"},
        )
    if pending.kind == "site_access" and decision in ("session", "always"):
        try:
            browser_safety.grant_site(pending.session_id, pending.domain, decision)
        except ValueError as exc:
            return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})
    get_browser_control().set_state(pending.session_id, BrowserControlState.AGENT)
    return {
        "confirmation_id": resolved.id,
        "kind": resolved.kind,
        "decision": decision,
        "control_state": BrowserControlState.AGENT.value,
    }


@router.get("/browser/audit")
def list_browser_audit(request: Request, session_id: str = "", limit: int = 50) -> Any:
    """读取最近的浏览器动作审计（倒序）。"""
    guard = _origin_guard(request)
    if guard is not None:
        return guard
    return {"entries": browser_action_repo.list_recent(session_id or None, limit)}
