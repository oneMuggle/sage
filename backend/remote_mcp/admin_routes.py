"""远程工作区管理 API（挂在主 API 上，受 local_auth 保护，仅本机 UI 可调用）。

前缀：``/api/v1/remote-mcp``。token 只在 ``connection-url`` 端点里以完整
URL 形式返回（供 Electron 写入剪贴板），列表与状态接口永不包含 token。
"""

from __future__ import annotations

import re
import threading
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import DEFAULT_PORT
from .approval import GateApprover, capture_main_loop
from .listener import LOOPBACK, Listener
from .protocol import RemoteMcpService
from .store import StoreError, WorkspaceStore


async def _capture_loop() -> None:
    """async 依赖在主事件循环里运行：记录主循环供远程审批跨线程提交（M5a）。"""
    capture_main_loop()


router = APIRouter(prefix="/remote-mcp", tags=["remote-mcp"], dependencies=[Depends(_capture_loop)])

_PUBLIC_BASE = re.compile(r"^https://[a-z0-9-]+\.trycloudflare\.com$")

_state_lock = threading.Lock()
_service: Optional[RemoteMcpService] = None
_listener: Optional[Listener] = None


def get_runtime() -> Tuple[RemoteMcpService, Listener]:
    """惰性创建单例（首次访问管理 API 时才读取配置文件）。"""
    global _service, _listener
    with _state_lock:
        if _service is None:
            try:
                store = WorkspaceStore()
            except (StoreError, ValueError) as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc
            _service = RemoteMcpService(store, approver=GateApprover())
            for w in store.list_public():
                if w.get("token_reset"):
                    _service.audit.record("workspace.token_reset", w["id"])
            _listener = Listener(_service)
        assert _listener is not None
        return _service, _listener


def configure_for_tests(service: Optional[RemoteMcpService], listener: Optional[Listener]) -> None:
    global _service, _listener
    with _state_lock:
        _service, _listener = service, listener


class StartBody(BaseModel):
    port: int = DEFAULT_PORT


class CreateBody(BaseModel):
    name: str
    root: str


class UpdateBody(BaseModel):
    enabled: Optional[bool] = None
    permissions: Optional[Dict[str, bool]] = None
    approval: Optional[str] = None


class UrlBody(BaseModel):
    public_base: Optional[str] = None


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def _state() -> Dict[str, Any]:
    service, listener = get_runtime()
    workspaces = []
    for w in service.store.list_public():
        w["sessions"] = service.session_count(w["id"])
        workspaces.append(w)
    return {
        "listener": {"running": listener.running, "port": listener.port, "error": listener.error,
                     "host": LOOPBACK},
        "paused": service.paused,
        "running_commands": service.jobs.running_count(),
        "workspaces": workspaces,
        "audit": service.audit.recent(),
    }


@router.get("/state")
def get_state() -> Dict[str, Any]:
    return _state()


@router.post("/listener/start")
def start_listener(body: StartBody) -> Dict[str, Any]:
    _service_, listener = get_runtime()
    if not 1024 <= body.port <= 65535:
        raise HTTPException(status_code=400, detail="端口必须在 1024-65535 之间")
    try:
        listener.start(body.port)
    except OSError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _state()


@router.post("/listener/stop")
def stop_listener() -> Dict[str, Any]:
    service, listener = get_runtime()
    for w in service.store.list_public():
        service.revoke(w["id"], reason="listener_stopped")
    listener.stop()
    return _state()


@router.post("/workspaces")
def create_workspace(body: CreateBody) -> Dict[str, Any]:
    service, _ = get_runtime()
    try:
        service.store.create(body.name, body.root)
    except StoreError as exc:
        raise _bad(exc) from exc
    return _state()


@router.patch("/workspaces/{workspace_id}")
def update_workspace(workspace_id: str, body: UpdateBody) -> Dict[str, Any]:
    service, _ = get_runtime()
    before = service.store.get(workspace_id)
    try:
        after = service.store.update(workspace_id, enabled=body.enabled, permissions=body.permissions,
                                     approval=body.approval)
    except StoreError as exc:
        raise _bad(exc) from exc
    narrowed = (before or {}).get("enabled") and not after["enabled"]
    for key, value in (body.permissions or {}).items():
        if not value and (before or {}).get("permissions", {}).get(key):
            narrowed = True
    if narrowed:
        service.revoke(workspace_id, reason="permission_revoked")
    service.audit.record("workspace.updated", workspace_id)
    return _state()


@router.post("/workspaces/{workspace_id}/rotate")
def rotate_workspace(workspace_id: str) -> Dict[str, Any]:
    service, _ = get_runtime()
    try:
        service.store.rotate(workspace_id)
    except StoreError as exc:
        raise _bad(exc) from exc
    service.revoke(workspace_id, reason="token_rotated")
    service.audit.record("workspace.rotated", workspace_id)
    return _state()


@router.delete("/workspaces/{workspace_id}")
def remove_workspace(workspace_id: str) -> Dict[str, Any]:
    service, _ = get_runtime()
    service.revoke(workspace_id, reason="removed")
    try:
        service.store.remove(workspace_id)
    except StoreError as exc:
        raise _bad(exc) from exc
    service.audit.record("workspace.removed", workspace_id)
    return _state()


@router.post("/workspaces/{workspace_id}/connection-url")
def connection_url(workspace_id: str, body: UrlBody) -> Dict[str, str]:
    """返回含 token 的完整 MCP 地址（仅供本机 UI 复制到剪贴板，勿记录日志）。"""
    service, listener = get_runtime()
    if service.paused:
        raise HTTPException(status_code=409, detail="已急停，请先恢复服务")
    if body.public_base:
        base = body.public_base.rstrip("/")
        if not _PUBLIC_BASE.match(base):
            raise HTTPException(status_code=400, detail="public_base 必须是 https://*.trycloudflare.com")
    else:
        if not listener.running:
            raise HTTPException(status_code=409, detail="请先启动 MCP 监听器")
        base = f"http://{LOOPBACK}:{listener.port}"
    try:
        token = service.store.connection_token(workspace_id)
    except StoreError as exc:
        raise _bad(exc) from exc
    return {"url": f"{base}/mcp/{token}"}


@router.post("/emergency-stop")
def emergency_stop() -> Dict[str, Any]:
    service, _ = get_runtime()
    service.pause()
    return _state()


@router.post("/resume")
def resume() -> Dict[str, Any]:
    service, _ = get_runtime()
    service.resume()
    return _state()


__all__ = ["configure_for_tests", "get_runtime", "router"]
