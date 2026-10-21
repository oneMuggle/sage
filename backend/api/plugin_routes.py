# ruff: noqa: UP006, UP007, UP035
"""插件生命周期 REST 路由（R82）。

这一层只把既有的 :class:`PluginLifecycleManager` 记录面接出来：
列出、安装、启停、配置、卸载/恢复以及事件日志。插件代码本身的加载与
托管属于 R83；这里不会读取或执行 ``install_path`` 下的任何代码。

安全约束沿用高权限路由的既有做法：

- 所有端点先过 Origin 守卫，挡住第三方网页的 drive-by 请求；
- 安装时若 manifest 声明了权限，后端强制要求显式确认。缺少确认时
  返回 409 并不落库，因此不能绕过 UI 直接调用 API 偷偷安装。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from backend.api.permission_routes import forbidden_origin_response
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


def _manager() -> PluginLifecycleManager:
    """每个请求构造新的生命周期管理器。

    不复用模块级单例，是为了避免单例缓存的 SQLite 连接跨数据库残留
    （特别是测试会切换应用数据库）。
    """

    return PluginLifecycleManager()


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


def _record_view(record: PluginRecord) -> Dict[str, Any]:
    view = _model_to_dict(record)
    manifest = record.manifest if isinstance(record.manifest, dict) else {}
    metadata = manifest.get("metadata") if isinstance(manifest.get("metadata"), dict) else {}
    permissions, by_capability = _permission_summary(manifest)

    view["manifest"] = manifest
    view["display_name"] = str(metadata.get("display_name") or record.name)
    view["description"] = str(metadata.get("description") or "")
    view["permissions"] = permissions
    view["by_capability"] = by_capability
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


def _run_action(name: str, action: str) -> JSONResponse:
    manager = _manager()
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

    return _run_action(_normalize_name(name), "disable")


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

    return _run_action(_normalize_name(name), "uninstall")


@router.patch("/{name}/config")
async def update_plugin_config(
    request: Request,
    name: str,
    body: UpdatePluginConfigBody,
):
    blocked = _blocked_origin(request)
    if blocked is not None:
        return blocked

    try:
        record = _manager().update_config(_normalize_name(name), body.config)
    except PluginLifecycleError as exc:
        return _lifecycle_error_response(exc)

    return {"plugin": _record_view(record)}
