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

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Extra

from backend.api.permission_routes import forbidden_origin_response
from backend.services.browser_control import (
    ACTION_TO_STATE,
    VALID_CONTROL_ACTIONS,
    get_browser_control,
)
from backend.tools.browser_cdp import get_browser_manager

router = APIRouter(tags=["browser-use"])


class BrowserControlActionBody(BaseModel):
    """POST control 请求体：单个 action，禁止额外键。"""

    action: str

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
