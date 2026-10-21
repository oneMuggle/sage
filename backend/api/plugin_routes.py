# ruff: noqa: UP006, UP007, UP035
"""插件生命周期与进程外 runtime REST 路由（R82/R83）。

R82 把既有的 :class:`PluginLifecycleManager` 记录面接出来；R83 在同一
router 上增加显式 runtime start/stop/restart/invoke。安装与启用记录都
不会自动执行插件代码，子进程只由 runtime start 显式拉起。

安全约束沿用高权限路由的既有做法：

- 所有端点先过 Origin 守卫，挡住第三方网页的 drive-by 请求；
- 安装时若 manifest 声明了权限，后端强制要求显式确认。缺少确认时
  返回 409 并不落库，因此不能绕过 UI 直接调用 API 偷偷安装。
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from backend.api.permission_routes import forbidden_origin_response
from backend.plugins.host import (
    PluginHostError,
    PluginHostManager,
    PluginRuntimeStatus,
    get_plugin_host_manager,
)
from backend.plugins.lifecycle import (
    PluginAlreadyExistsError,
    PluginLifecycleError,
    PluginLifecycleManager,
    PluginNotFoundError,
    PluginRecord,
    PluginStateError,
    PluginStatus,
)
from backend.plugins.manifest import PluginManifest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plugins", tags=["plugins"])


class InstallPluginBody(BaseModel):
    """安装插件请求体。"""

    manifest: Dict[str, Any]
    install_path: str = Field(..., min_length=1)
    confirm_permissions: bool = False


class UpdatePluginConfigBody(BaseModel):
    """更新插件配置请求体（全量替换）。"""

    config: Dict[str, Any] = Field(default_factory=dict)


class InvokePluginBody(BaseModel):
    """调用一个已加载插件 tool 的请求体。"""

    capability: str = Field(..., min_length=1)
    arguments: Dict[str, Any] = Field(default_factory=dict)


def _manager() -> PluginLifecycleManager:
    """每个请求构造新的生命周期管理器。

    不复用模块级单例，是为了避免单例缓存的 SQLite 连接跨数据库残留
    （特别是测试会切换应用数据库）。
    """

    return PluginLifecycleManager()


def _host_manager() -> PluginHostManager:
    """Return the process-wide out-of-process plugin host."""

    return get_plugin_host_manager()


async def _run_host(function: Callable[..., Any], *args: Any) -> Any:
    """Run synchronous process supervision in a thread, not the event loop."""

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, functools.partial(function, *args))


def _normalize_name(name: str) -> str:
    return name.strip().lower()


def _model_to_dict(model: Any) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(key, default)
    return getattr(item, key, default)


def _permission_groups(capabilities: Iterable[Any]) -> Tuple[List[str], List[Dict[str, Any]]]:
    flattened: List[str] = []
    seen = set()
    groups: List[Dict[str, Any]] = []

    for capability in capabilities or []:
        raw_permissions = _value(capability, "permissions") or []
        if isinstance(raw_permissions, str):
            raw_permissions = [raw_permissions]

        permissions: List[str] = []
        capability_seen = set()
        for raw_permission in raw_permissions:
            permission = str(raw_permission).strip()
            if not permission or permission in capability_seen:
                continue
            capability_seen.add(permission)
            permissions.append(permission)
            if permission not in seen:
                seen.add(permission)
                flattened.append(permission)

        if not permissions:
            continue

        capability_type = _value(capability, "type")
        groups.append(
            {
                "capability": str(_value(capability, "name") or ""),
                "type": str(getattr(capability_type, "value", capability_type)),
                "description": str(_value(capability, "description") or ""),
                "entry_point": _value(capability, "entry_point"),
                "permissions": permissions,
            }
        )

    return flattened, groups


def _permission_summary(manifest: Any) -> Tuple[List[str], List[Dict[str, Any]]]:
    return _permission_groups(_value(manifest, "capabilities") or [])


def _runtime_view(
    plugin_name: str,
    runtime: Optional[PluginRuntimeStatus] = None,
) -> Dict[str, Any]:
    return (runtime or _host_manager().status(plugin_name)).to_dict()


def _record_view(
    record: PluginRecord,
    runtime: Optional[PluginRuntimeStatus] = None,
) -> Dict[str, Any]:
    view = _model_to_dict(record)
    manifest = record.manifest if isinstance(record.manifest, dict) else {}
    metadata = manifest.get("metadata") if isinstance(manifest.get("metadata"), dict) else {}
    permissions, by_capability = _permission_summary(manifest)

    view["manifest"] = manifest
    view["display_name"] = str(metadata.get("display_name") or record.name)
    view["description"] = str(metadata.get("description") or "")
    view["permissions"] = permissions
    view["by_capability"] = by_capability
    view["runtime"] = _runtime_view(record.name, runtime)
    return view


def _error(
    status_code: int,
    error: str,
    detail: str,
    **extra: Any,
) -> JSONResponse:
    content: Dict[str, Any] = {"ok": False, "error": error, "detail": detail}
    content.update(extra)
    return JSONResponse(status_code=status_code, content=content)


def _lifecycle_error_response(exc: PluginLifecycleError) -> JSONResponse:
    if isinstance(exc, PluginNotFoundError):
        return _error(404, "plugin_not_found", str(exc))
    if isinstance(exc, PluginAlreadyExistsError):
        return _error(409, "plugin_already_exists", str(exc))
    if isinstance(exc, PluginStateError):
        return _error(409, "invalid_plugin_state", str(exc))

    logger.error("插件生命周期操作失败: %s", exc)
    return _error(500, "plugin_lifecycle_error", str(exc))


def _host_error_response(
    exc: PluginHostError,
    plugin_name: str,
    runtime: Optional[PluginRuntimeStatus] = None,
) -> JSONResponse:
    return _error(
        exc.status_code,
        exc.code.lower(),
        exc.message,
        code=exc.code,
        runtime=_runtime_view(plugin_name, runtime),
    )


def _record_or_error(
    manager: PluginLifecycleManager,
    plugin_name: str,
) -> Tuple[Optional[PluginRecord], Optional[JSONResponse]]:
    try:
        return manager.get_plugin(plugin_name), None
    except PluginLifecycleError as exc:
        return None, _lifecycle_error_response(exc)


def _stop_runtime_sync(
    manager: PluginLifecycleManager,
    plugin_name: str,
    reason: str,
) -> PluginRuntimeStatus:
    host = _host_manager()
    before = host.status(plugin_name)
    if before.state.value == "pending":
        return before
    stopped = host.stop(plugin_name)
    manager.record_event(plugin_name, "runtime_stopped", reason[:500])
    return stopped


async def _stop_runtime(
    manager: PluginLifecycleManager,
    plugin_name: str,
    reason: str,
) -> PluginRuntimeStatus:
    return await _run_host(_stop_runtime_sync, manager, plugin_name, reason)


def _blocked_origin(request: Request) -> Optional[JSONResponse]:
    return forbidden_origin_response(request)


@router.get("")
async def list_plugins(request: Request, status: str = ""):
    """列出插件生命周期记录，可按状态过滤。"""

    blocked = _blocked_origin(request)
    if blocked is not None:
        return blocked

    status_filter: Optional[PluginStatus] = None
    if status:
        try:
            status_filter = PluginStatus(status)
        except ValueError:
            return _error(422, "invalid_status", f"未知插件状态: {status}")

    try:
        records = _manager().list_plugins(status=status_filter)
    except PluginLifecycleError as exc:
        return _lifecycle_error_response(exc)

    return {"plugins": [_record_view(record) for record in records]}


@router.get("/logs")
async def list_all_plugin_logs(request: Request, limit: int = 100):
    """列出全部插件的最近生命周期事件。"""

    blocked = _blocked_origin(request)
    if blocked is not None:
        return blocked

    try:
        events = _manager().list_events(limit=limit)
    except PluginLifecycleError as exc:
        return _lifecycle_error_response(exc)

    return {"logs": [_model_to_dict(event) for event in events]}


@router.post("", status_code=201)
async def install_plugin(request: Request, body: InstallPluginBody):
    """安装一个插件记录。

    若 manifest 声明了权限而请求未显式确认，返回 409 并不落库。
    """

    blocked = _blocked_origin(request)
    if blocked is not None:
        return blocked

    install_path = body.install_path.strip()
    if not install_path:
        return _error(422, "invalid_install_path", "install_path 不能为空")

    try:
        manifest = PluginManifest.from_json(
            json.dumps(body.manifest, ensure_ascii=False)
        )
    except (ValidationError, ValueError, TypeError) as exc:
        return _error(422, "invalid_manifest", str(exc))

    permissions, by_capability = _permission_summary(manifest)
    if permissions and not body.confirm_permissions:
        return _error(
            409,
            "permissions_confirmation_required",
            "插件声明了权限，安装前必须显式确认",
            plugin=manifest.name,
            permissions=permissions,
            by_capability=by_capability,
        )

    try:
        record = _manager().install(manifest, install_path)
    except PluginLifecycleError as exc:
        return _lifecycle_error_response(exc)

    return JSONResponse(status_code=201, content={"plugin": _record_view(record)})


@router.get("/{name}")
async def get_plugin(request: Request, name: str):
    blocked = _blocked_origin(request)
    if blocked is not None:
        return blocked

    try:
        record = _manager().get_plugin(_normalize_name(name))
    except PluginLifecycleError as exc:
        return _lifecycle_error_response(exc)

    return {"plugin": _record_view(record)}


@router.get("/{name}/permissions")
async def get_plugin_permissions(request: Request, name: str):
    blocked = _blocked_origin(request)
    if blocked is not None:
        return blocked

    try:
        record = _manager().get_plugin(_normalize_name(name))
    except PluginLifecycleError as exc:
        return _lifecycle_error_response(exc)

    view = _record_view(record)
    return {
        "plugin": record.name,
        "permissions": view["permissions"],
        "by_capability": view["by_capability"],
    }


@router.get("/{name}/logs")
async def list_plugin_logs(request: Request, name: str, limit: int = 100):
    blocked = _blocked_origin(request)
    if blocked is not None:
        return blocked

    plugin_name = _normalize_name(name)
    try:
        manager = _manager()
        manager.get_plugin(plugin_name)
        events = manager.list_events(plugin_name, limit=limit)
    except PluginLifecycleError as exc:
        return _lifecycle_error_response(exc)

    return {"logs": [_model_to_dict(event) for event in events]}


@router.get("/{name}/runtime")
async def get_plugin_runtime(request: Request, name: str):
    blocked = _blocked_origin(request)
    if blocked is not None:
        return blocked

    plugin_name = _normalize_name(name)
    record, error = _record_or_error(_manager(), plugin_name)
    if error is not None:
        return error

    runtime = _host_manager().status(plugin_name)
    return {"plugin": _record_view(record, runtime), "runtime": runtime.to_dict()}


async def _runtime_start(request: Request, name: str, *, restart: bool):
    blocked = _blocked_origin(request)
    if blocked is not None:
        return blocked

    plugin_name = _normalize_name(name)
    manager = _manager()
    record, error = _record_or_error(manager, plugin_name)
    if error is not None:
        return error

    host = _host_manager()
    operation = host.restart if restart else host.start
    try:
        runtime = await _run_host(operation, record)
    except PluginHostError as exc:
        manager.record_event(plugin_name, "runtime_failed", exc.code)
        return _host_error_response(exc, plugin_name)

    event = "runtime_restarted" if restart else "runtime_started"
    manager.record_event(plugin_name, event, f"pid={runtime.pid}")
    return {"plugin": _record_view(record, runtime), "runtime": runtime.to_dict()}


@router.post("/{name}/runtime/start")
async def start_plugin_runtime(request: Request, name: str):
    return await _runtime_start(request, name, restart=False)


@router.post("/{name}/runtime/restart")
async def restart_plugin_runtime(request: Request, name: str):
    return await _runtime_start(request, name, restart=True)


@router.post("/{name}/runtime/stop")
async def stop_plugin_runtime(request: Request, name: str):
    blocked = _blocked_origin(request)
    if blocked is not None:
        return blocked

    plugin_name = _normalize_name(name)
    manager = _manager()
    record, error = _record_or_error(manager, plugin_name)
    if error is not None:
        return error

    runtime = await _stop_runtime(manager, plugin_name, "manual")
    return {"plugin": _record_view(record, runtime), "runtime": runtime.to_dict()}


@router.post("/{name}/runtime/invoke")
async def invoke_plugin_runtime(
    request: Request,
    name: str,
    body: InvokePluginBody,
):
    blocked = _blocked_origin(request)
    if blocked is not None:
        return blocked

    plugin_name = _normalize_name(name)
    capability = body.capability.strip()
    if not capability:
        return _error(422, "invalid_capability", "capability 不能为空")

    manager = _manager()
    _, error = _record_or_error(manager, plugin_name)
    if error is not None:
        return error

    try:
        result = await _run_host(
            _host_manager().invoke,
            plugin_name,
            capability,
            body.arguments,
        )
    except PluginHostError as exc:
        manager.record_event(
            plugin_name,
            "runtime_invoke_failed",
            f"{capability}:{exc.code}"[:500],
        )
        return _host_error_response(exc, plugin_name)

    manager.record_event(plugin_name, "runtime_invoked", capability[:500])
    runtime = _host_manager().status(plugin_name)
    return {
        "plugin_name": plugin_name,
        "capability": capability,
        "result": result,
        "runtime": runtime.to_dict(),
    }


def _run_action(
    name: str,
    action: str,
    manager: Optional[PluginLifecycleManager] = None,
) -> JSONResponse:
    manager = manager or _manager()
    try:
        if action == "enable":
            record = manager.enable(name)
        elif action == "disable":
            record = manager.disable(name)
        elif action == "restore":
            record = manager.restore(name)
        else:
            manager.uninstall(name)
            record = manager.get_plugin(name)
    except PluginLifecycleError as exc:
        return _lifecycle_error_response(exc)

    return JSONResponse(content={"plugin": _record_view(record)})


@router.post("/{name}/enable")
async def enable_plugin(request: Request, name: str):
    blocked = _blocked_origin(request)
    if blocked is not None:
        return blocked

    return _run_action(_normalize_name(name), "enable")


@router.post("/{name}/disable")
async def disable_plugin(request: Request, name: str):
    blocked = _blocked_origin(request)
    if blocked is not None:
        return blocked

    plugin_name = _normalize_name(name)
    manager = _manager()
    _, error = _record_or_error(manager, plugin_name)
    if error is not None:
        return error

    await _stop_runtime(manager, plugin_name, "disabled")
    return _run_action(plugin_name, "disable", manager)


@router.post("/{name}/restore")
async def restore_plugin(request: Request, name: str):
    blocked = _blocked_origin(request)
    if blocked is not None:
        return blocked

    return _run_action(_normalize_name(name), "restore")


@router.delete("/{name}")
async def uninstall_plugin(request: Request, name: str):
    blocked = _blocked_origin(request)
    if blocked is not None:
        return blocked

    plugin_name = _normalize_name(name)
    manager = _manager()
    _, error = _record_or_error(manager, plugin_name)
    if error is not None:
        return error

    await _stop_runtime(manager, plugin_name, "uninstalled")
    return _run_action(plugin_name, "uninstall", manager)


@router.patch("/{name}/config")
async def update_plugin_config(
    request: Request,
    name: str,
    body: UpdatePluginConfigBody,
):
    blocked = _blocked_origin(request)
    if blocked is not None:
        return blocked

    plugin_name = _normalize_name(name)
    manager = _manager()
    _, error = _record_or_error(manager, plugin_name)
    if error is not None:
        return error

    # Runtime config is supplied at worker initialize; stop first so a running
    # worker cannot keep executing with stale config after this update.
    runtime = await _stop_runtime(manager, plugin_name, "config_updated")
    try:
        record = manager.update_config(plugin_name, body.config)
    except PluginLifecycleError as exc:
        return _lifecycle_error_response(exc)

    return {"plugin": _record_view(record, runtime)}
