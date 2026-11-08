"""Rescue config wizard — 端点/模型配置的离线读写。

不依赖后端/uvicorn：直写 SQLite，复用 ``SettingsRepository`` 与 SecretBox（加密透明），
复用 ``settings_canonicalizer`` 的校验函数（保证写出的 JSON 与后端 PUT 路径兼容）。

写入契约（所有写 DB 的函数遵守）：

- 写前备份 ``backup_service.create_backup("rescue")``；
- 写前调用 ``validate_settings_shape`` + ``validate_settings_payload``；
- 写入后调用 ``reconcile_endpoint_bindings`` 同步 catalog；
- 修改 apiKey 时同步更新 ``apiKeyUpdatedAt``（毫秒 Unix epoch）；
- 输出一律脱敏（``mask_secret``）。

幂等性：

- ``merge_endpoint`` 纯函数、不修改入参；
- ``save_endpoint`` 幂等：相同 id + 相同字段 = 相同结果；
- ``import_bundle`` 对已存在的端点按 id 覆盖，对缺失的追加。

错误处理：

- 所有公开函数抛出 :class:`RescueConfigError`，消息面向用户（中文 + 英文错误码）；
- 不吞异常；不静默失败。
"""
from __future__ import annotations

import contextlib
import copy
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from backend.data.settings_canonicalizer import (
    validate_settings_payload,
    validate_settings_shape,
)
from backend.data.settings_repo import SettingsRepository
from backend.services.backup_service import create_backup
from backend.services.rescue.paths import resolve_db_path

logger = logging.getLogger(__name__)


class RescueConfigError(Exception):
    """救援配置操作的统一错误类型。"""


#: 协议白名单（与后端 canonicalizer / 前端 types 同步）
VALID_PROTOCOLS = frozenset({"openai-compatible", "anthropic", "gemini", "ollama"})

#: 端点必填字段（创建时）
REQUIRED_CREATE = ("baseUrl",)

#: 新建端点时的默认字段（与前端 DEFAULT_ENDPOINT 同步，除 id 外）
DEFAULT_ENDPOINT: Dict[str, Any] = {
    "name": "",
    "protocol": "openai-compatible",
    "modelId": "",
    "localModelPath": "",
    "discoveredModels": [],
    "lastDiscoveredAt": None,
    "reasoningEffort": None,
    "thinkingBudget": None,
    "quota": None,
}

#: 允许从外部输入 merge 的字段（与 canonicalizer LEGAL_ENDPOINT_KEYS 对齐）。
#: 任何不在白名单的键（如 hasApiKey / 历史残留）在 merge 前丢弃，避免写坏 DB。
ALLOWED_INPUT_KEYS = frozenset(
    {
        "id",
        "name",
        "baseUrl",
        "apiKey",
        "protocol",
        "modelId",
        "localModelPath",
        "discoveredModels",
        "lastDiscoveredAt",
        "reasoningEffort",
        "thinkingBudget",
        "quota",
        "apiKeyUpdatedAt",
    }
)


# ============================================================
# 脱敏
# ============================================================


def mask_secret(value: Optional[str]) -> str:
    """脱敏 API key —— 保留前 3 字节 + ``***`` + 末 4 字节。

    空串 / ``None`` / 长度 ≤ 4 → 返回 ``"***"`` 或空串。
    """
    if not value:
        return ""
    if len(value) <= 4:
        return "***"
    return f"{value[:3]}***{value[-4:]}"


def redact_endpoint(ep: Dict[str, Any]) -> Dict[str, Any]:
    """端点脱敏副本。apiKey 替换为 ``***``，并附加 ``hasApiKey`` 标记。"""
    if not isinstance(ep, dict):
        return ep
    out = dict(ep)
    raw_key = out.get("apiKey")
    out["apiKey"] = mask_secret(raw_key) if raw_key else ""
    out["hasApiKey"] = bool(raw_key)
    return out


def redact_settings(settings: Any) -> Any:
    """递归脱敏整个 settings 树（端点 + 其它敏感字段）。"""
    if isinstance(settings, list):
        return [redact_settings(x) for x in settings]
    if isinstance(settings, dict):
        out = {}
        for k, v in settings.items():
            if isinstance(k, str) and k.lower() in {"apikey", "api_key", "secret", "token", "password"}:
                # 非字符串敏感值（dict/list）也整体替换，避免原样透出。
                out[k] = mask_secret(v) if isinstance(v, str) else "***"
            else:
                out[k] = redact_settings(v)
        return out
    return settings


# ============================================================
# 纯函数：settings 合并
# ============================================================


def _new_endpoint_id() -> str:
    import secrets

    return f"ep_{int(time.time() * 1000)}_{secrets.token_hex(3)}"


def _validate_input(input_ep: Dict[str, Any]) -> None:
    """校验输入字段（白名单 + 值类型），抛 ``RescueConfigError``。

    ``baseUrl`` 在创建时必填（由 :func:`merge_endpoint` 的 create 分支检查），
    在更新时可选；这里只校验"如果提供了就必须合法"。
    """
    base_url = input_ep.get("baseUrl")
    if base_url is not None:
        if not isinstance(base_url, str) or not base_url.strip():
            raise RescueConfigError("baseUrl 必须是非空字符串")
        if not base_url.startswith(("http://", "https://")):
            raise RescueConfigError(f"baseUrl 必须以 http:// 或 https:// 开头，收到: {base_url!r}")
        try:
            parsed = urlparse(base_url)
            if not parsed.hostname:
                raise ValueError("no hostname")
        except Exception:
            raise RescueConfigError(f"baseUrl 格式非法: {base_url!r}")

    # 协议枚举
    if "protocol" in input_ep and input_ep["protocol"] not in VALID_PROTOCOLS:
        raise RescueConfigError(
            f"protocol 必须是 {sorted(VALID_PROTOCOLS)} 之一，收到: {input_ep['protocol']!r}"
        )

    # apiKey 类型
    if "apiKey" in input_ep:
        v = input_ep["apiKey"]
        if v is not None and not isinstance(v, str):
            raise RescueConfigError("apiKey 必须是字符串或 null")

    # id 类型
    if "id" in input_ep:
        v = input_ep["id"]
        if not isinstance(v, str) or not v.strip():
            raise RescueConfigError("id 必须是非空字符串")

    # name 类型
    if "name" in input_ep:
        v = input_ep["name"]
        if v is not None and not isinstance(v, str):
            raise RescueConfigError("name 必须是字符串或 null")


def _generate_default_name(base_url: str) -> str:
    try:
        host = urlparse(base_url).hostname
        return host or base_url
    except Exception:
        return base_url


def merge_endpoint(
    settings: Dict[str, Any],
    input_ep: Dict[str, Any],
    *,
    mode: str = "upsert",
) -> Tuple[Dict[str, Any], str]:
    """合并一个 endpoint 到 settings。

    Args:
        settings: 当前 settings dict（不可变输入）
        input_ep: 用户输入；可包含 id / name / baseUrl / apiKey / protocol / modelId 等
        mode: ``"upsert"``（默认，存在即更新、不存在即创建）/ ``"create"``（id 已存在则报错）
            / ``"update"``（id 不存在则报错）

    Returns:
        (new_settings, mode)，mode 为 ``"created"`` / ``"updated"``

    Raises:
        RescueConfigError: 输入非法 / 模式冲突 / 更新时 id 不存在
    """
    if mode not in {"upsert", "create", "update"}:
        raise RescueConfigError(f"mode 必须是 upsert/create/update 之一，收到: {mode!r}")
    if not isinstance(settings, dict):
        raise RescueConfigError("settings 必须是 dict")
    if not isinstance(input_ep, dict):
        raise RescueConfigError("input 必须是 dict")
    # 白名单过滤：丢弃 hasApiKey / 历史残留字段，避免写出不合规 JSON。
    input_ep = {k: v for k, v in input_ep.items() if k in ALLOWED_INPUT_KEYS}
    _validate_input(input_ep)

    new_settings = copy.deepcopy(settings)
    endpoints = new_settings.setdefault("endpoints", [])
    if not isinstance(endpoints, list):
        raise RescueConfigError("settings['endpoints'] 必须是 list")

    existing_id = input_ep.get("id")
    existing_idx: Optional[int] = None
    if existing_id:
        for i, ep in enumerate(endpoints):
            if isinstance(ep, dict) and ep.get("id") == existing_id:
                existing_idx = i
                break

    if existing_idx is not None:
        if mode == "create":
            raise RescueConfigError(f"端点 id 已存在: {existing_id!r}")
        # 更新：保留原字段，仅覆盖输入字段
        target = dict(endpoints[existing_idx])
        for k, v in input_ep.items():
            if k == "id":
                continue
            target[k] = v
        # apiKey 保留/更新规则
        if "apiKey" not in input_ep:
            # 未提供 apiKey，保留原 key 与时间戳
            pass
        elif not input_ep["apiKey"]:
            # 显式清空 apiKey —— 保留原 key（与 preserve_endpoint_api_keys 语义一致）
            # 并保留时间戳（不视为修改）
            pass
        else:
            target["apiKeyUpdatedAt"] = int(time.time() * 1000)
        endpoints[existing_idx] = target
        return new_settings, "updated"

    # 新建
    if mode == "update":
        raise RescueConfigError(f"端点 id 不存在: {existing_id!r}")
    if not input_ep.get("baseUrl"):
        raise RescueConfigError("创建端点时 baseUrl 为必填字段")
    new_ep: Dict[str, Any] = copy.deepcopy(DEFAULT_ENDPOINT)
    for k, v in input_ep.items():
        if v is not None:
            new_ep[k] = v
    if not new_ep.get("id"):
        new_ep["id"] = _new_endpoint_id()
    if not new_ep.get("name"):
        new_ep["name"] = _generate_default_name(new_ep["baseUrl"])
    if new_ep.get("apiKey"):
        new_ep["apiKeyUpdatedAt"] = int(time.time() * 1000)
    endpoints.append(new_ep)
    return new_settings, "created"


def merge_model_selection(
    settings: Dict[str, Any],
    task_type: str,
    endpoint_id: Optional[str],
    model_id: Optional[str],
) -> Dict[str, Any]:
    """设置某一 task_type 的 modelSelection。

    Args:
        task_type: chatModel / visionModel / embeddingModel / ttsModel / asrModel / imageGenModel
        endpoint_id: 目标端点 id（必须存在）；None 表示清空绑定
        model_id: 模型 id（任意字符串，可不存在）

    Raises:
        RescueConfigError: task_type 非法；endpoint_id 非空但 settings 里不存在
    """
    valid = {"chatModel", "visionModel", "embeddingModel", "ttsModel", "asrModel", "imageGenModel"}
    if task_type not in valid:
        raise RescueConfigError(
            f"task_type 必须是 {sorted(valid)} 之一，收到: {task_type!r}"
        )
    if endpoint_id:
        endpoints = settings.get("endpoints") or []
        if not any(
            isinstance(ep, dict) and ep.get("id") == endpoint_id for ep in endpoints
        ):
            raise RescueConfigError(f"端点 id {endpoint_id!r} 不存在")
    new_settings = copy.deepcopy(settings)
    selections = new_settings.setdefault("modelSelections", {})
    if not isinstance(selections, dict):
        raise RescueConfigError("settings['modelSelections'] 必须是 dict")
    if endpoint_id is None and model_id is None:
        selections.pop(task_type, None)
    else:
        selections[task_type] = {"endpointId": endpoint_id, "modelId": model_id}
    return new_settings


# ============================================================
# 数据库写入（依赖 SettingsRepository + backup_service）
# ============================================================


def _get_db_path(db_path: Optional[str]) -> str:
    return str(db_path or resolve_db_path())


def _backup_db_path(db_path: Optional[str]) -> str:
    """备份目标路径：显式 db_path 优先；否则用全局 Database 的真实路径。

    注意不能直接用 ``resolve_db_path()``：dev/测试环境下全局 Database 可能
    指向仓库 ``data/sage.db`` 而不是 ``~/.sage/sage.db``。
    """
    if db_path is not None:
        return str(db_path)
    from backend.data.database import get_database

    return str(get_database().db_path)


def save_endpoint(
    endpoint: Dict[str, Any],
    *,
    mode: str = "upsert",
    backup: bool = True,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """保存（新建/更新）一个 endpoint 到 DB。

    ``mode`` 语义与 :func:`merge_endpoint` 一致（默认 upsert）。
    返回 ``{"mode": "created"|"updated", "endpoint": <redacted>}``。
    """
    from backend.data.database import Database, get_database
    from backend.model_catalog.discovery_ingest import reconcile_endpoint_bindings
    from backend.model_catalog.repository import CatalogRepository

    resolved_db = _get_db_path(db_path)
    # 若未传 db_path，使用全局 Database；否则新建（测试场景）
    if db_path is not None:
        db = Database(db_path=resolved_db)
        repo = SettingsRepository(db)
    else:
        repo = SettingsRepository()

    if backup and create_backup("rescue", db_path=_backup_db_path(db_path)) is None:
        raise RescueConfigError("数据库备份失败，已中止写入")

    settings = repo.get_json("app_settings") or {"version": 1, "endpoints": [], "modelSelections": {}}
    new_settings, result_mode = merge_endpoint(settings, endpoint, mode=mode)

    # 校验整棵树（包括新插入/更新的 endpoint）
    try:
        validate_settings_shape(new_settings)
        validate_settings_payload(new_settings)
    except ValueError as exc:
        raise RescueConfigError(f"校验失败: {exc}") from exc

    repo.set_json("app_settings", new_settings)

    # 同步 catalog（可选端点 id，失败不影响写入）
    try:
        cat = CatalogRepository(db) if db_path is not None else CatalogRepository(get_database())
        reconcile_endpoint_bindings(cat, new_settings, endpoint_id=endpoint.get("id"))
    except Exception:
        logger.warning("rescue: reconcile_endpoint_bindings failed", exc_info=True)

    if db_path is not None:
        db.close()

    # 找出刚合并的端点（按 id 或最新一条）
    target_id = endpoint.get("id")
    merged_ep: Dict[str, Any] = {}
    for ep in new_settings["endpoints"]:
        if not isinstance(ep, dict):
            continue
        if target_id and ep.get("id") == target_id:
            merged_ep = ep
            break
    else:
        if new_settings["endpoints"]:
            merged_ep = new_settings["endpoints"][-1] if isinstance(new_settings["endpoints"][-1], dict) else {}

    return {
        "mode": result_mode,
        "endpoint": redact_endpoint(merged_ep),
    }


def save_model_selection(
    task_type: str,
    endpoint_id: Optional[str],
    model_id: Optional[str],
    *,
    backup: bool = True,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """保存 model selection。返回脱敏后的新 settings。"""
    from backend.data.database import Database

    resolved_db = _get_db_path(db_path)
    if db_path is not None:
        db = Database(db_path=resolved_db)
        repo = SettingsRepository(db)
    else:
        repo = SettingsRepository()

    if backup and create_backup("rescue", db_path=_backup_db_path(db_path)) is None:
        raise RescueConfigError("数据库备份失败，已中止写入")

    settings = repo.get_json("app_settings") or {"version": 1, "endpoints": [], "modelSelections": {}}
    new_settings = merge_model_selection(settings, task_type, endpoint_id, model_id)

    try:
        validate_settings_shape(new_settings)
        validate_settings_payload(new_settings)
    except ValueError as exc:
        raise RescueConfigError(f"校验失败: {exc}") from exc

    repo.set_json("app_settings", new_settings)
    if db_path is not None:
        db.close()

    return redact_settings(new_settings)


# ============================================================
# 列表 / 查询
# ============================================================


def list_endpoints(
    *,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """列出所有端点（脱敏）。"""
    resolved_db = _get_db_path(db_path)
    if db_path is not None:
        from backend.data.database import Database
        db = Database(db_path=resolved_db)
        repo = SettingsRepository(db)
    else:
        repo = SettingsRepository()
    try:
        settings = repo.get_json("app_settings") or {}
        endpoints = settings.get("endpoints") or []
        return [redact_endpoint(ep) for ep in endpoints if isinstance(ep, dict)]
    finally:
        if db_path is not None:
            db.close()


def get_endpoint(
    endpoint_id: str,
    *,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """读取单个端点（**含明文 apiKey**，仅供内部探测使用，不要直接打印）。"""
    resolved_db = _get_db_path(db_path)
    if db_path is not None:
        from backend.data.database import Database
        db = Database(db_path=resolved_db)
        repo = SettingsRepository(db)
    else:
        repo = SettingsRepository()
    try:
        settings = repo.get_json("app_settings") or {}
        endpoints = settings.get("endpoints") or []
        for ep in endpoints:
            if isinstance(ep, dict) and ep.get("id") == endpoint_id:
                return dict(ep)
        return None
    finally:
        if db_path is not None:
            db.close()


def delete_endpoint(
    endpoint_id: str,
    *,
    backup: bool = True,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """删除端点，并清理指向它的 modelSelections。"""
    from backend.data.database import Database
    from backend.services.backup_service import create_backup

    resolved_db = _get_db_path(db_path)
    if db_path is not None:
        db = Database(db_path=resolved_db)
        repo = SettingsRepository(db)
    else:
        repo = SettingsRepository()

    if backup and create_backup("rescue", db_path=_backup_db_path(db_path)) is None:
        raise RescueConfigError("数据库备份失败，已中止写入")

    settings = repo.get_json("app_settings") or {"version": 1, "endpoints": [], "modelSelections": {}}
    endpoints = list(settings.get("endpoints") or [])
    kept = [ep for ep in endpoints if not (isinstance(ep, dict) and ep.get("id") == endpoint_id)]
    if len(kept) == len(endpoints):
        raise RescueConfigError(f"端点 id 不存在: {endpoint_id!r}")
    settings["endpoints"] = kept
    selections = settings.get("modelSelections") or {}
    for key in list(selections.keys()):
        sel = selections[key]
        if isinstance(sel, dict) and sel.get("endpointId") == endpoint_id:
            selections.pop(key, None)
    settings["modelSelections"] = selections

    try:
        validate_settings_shape(settings)
        validate_settings_payload(settings)
    except ValueError as exc:
        raise RescueConfigError(f"校验失败: {exc}") from exc

    repo.set_json("app_settings", settings)
    if db_path is not None:
        db.close()
    return {"deleted": endpoint_id}


# ============================================================
# 配置包导入/导出
# ============================================================


@dataclass
class BundleMetadata:
    schema: int
    exported_at: str
    endpoints_count: int


def export_bundle(
    output_path: Path,
    *,
    include_secrets: bool = False,
    db_path: Optional[str] = None,
) -> Path:
    """导出端点 + modelSelections 为 JSON bundle。

    Args:
        output_path: 输出路径（建议 ``.json``）
        include_secrets: 是否包含明文 apiKey；默认脱敏
        db_path: 可选显式 DB 路径

    Returns:
        输出路径
    """
    resolved_db = _get_db_path(db_path)
    if db_path is not None:
        from backend.data.database import Database
        db = Database(db_path=resolved_db)
        repo = SettingsRepository(db)
    else:
        repo = SettingsRepository()
    try:
        settings = repo.get_json("app_settings") or {}
        endpoints = list(settings.get("endpoints") or [])
        model_selections = dict(settings.get("modelSelections") or {})
    finally:
        if db_path is not None:
            db.close()

    bundle_endpoints: List[Dict[str, Any]] = []
    for ep in endpoints:
        if not isinstance(ep, dict):
            continue
        if include_secrets:
            bundle_endpoints.append(dict(ep))
        else:
            bundle_endpoints.append(redact_endpoint(ep))

    bundle = {
        "schema": 1,
        "exportedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "includeSecrets": include_secrets,
        "endpoints": bundle_endpoints,
        "modelSelections": model_selections,
    }
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    if include_secrets:
        with contextlib.suppress(OSError):
            output_path.chmod(0o600)
    return output_path


def import_bundle(
    bundle_path: Path,
    *,
    include_secrets: bool = False,
    backup: bool = True,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """导入 bundle.json，返回 ``{"endpoints_imported": N, "model_selections_imported": M}``。"""
    from backend.data.database import Database, get_database
    from backend.model_catalog.discovery_ingest import reconcile_endpoint_bindings
    from backend.model_catalog.repository import CatalogRepository

    bundle_path = Path(bundle_path)
    data = json.loads(bundle_path.read_text(encoding="utf-8"))
    if data.get("schema") != 1:
        raise RescueConfigError(f"bundle schema 不兼容: {data.get('schema')!r}")
    # 只有“调用方显式要求”且“bundle 自身声明含明文”时才导入 apiKey；
    # 否则丢弃（包括脱敏占位 "***"），保留 DB 中已有 key。
    secrets_allowed = bool(include_secrets) and data.get("includeSecrets") is True

    resolved_db = _get_db_path(db_path)
    if db_path is not None:
        db = Database(db_path=resolved_db)
        repo = SettingsRepository(db)
    else:
        repo = SettingsRepository()

    if backup and create_backup("rescue", db_path=_backup_db_path(db_path)) is None:
        raise RescueConfigError("数据库备份失败，已中止写入")

    try:
        settings = repo.get_json("app_settings") or {"version": 1, "endpoints": [], "modelSelections": {}}

        imported = 0
        for ep in data.get("endpoints", []):
            if not isinstance(ep, dict):
                continue
            ep_id = ep.get("id")
            if not isinstance(ep_id, str):
                continue
            # hasApiKey 是 GET/导出脱敏标记，不属于合法 endpoint 字段。
            effective = dict(ep)
            effective.pop("hasApiKey", None)
            key = effective.get("apiKey")
            if (
                not secrets_allowed
                or not isinstance(key, str)
                or not key
                or "***" in key
            ):
                effective.pop("apiKey", None)
                effective.pop("apiKeyUpdatedAt", None)
            settings, _ = merge_endpoint(settings, effective)
            imported += 1

        # 覆盖 modelSelections（必须为 dict，null/数组视为非法 bundle）
        selections_data = data.get("modelSelections") or {}
        if not isinstance(selections_data, dict):
            raise RescueConfigError("bundle.modelSelections 必须是对象")
        selections = dict(settings.get("modelSelections") or {})
        for k, v in selections_data.items():
            if isinstance(v, dict):
                selections[k] = v
        settings["modelSelections"] = selections

        try:
            validate_settings_shape(settings)
            validate_settings_payload(settings)
        except ValueError as exc:
            raise RescueConfigError(f"校验失败: {exc}") from exc

        repo.set_json("app_settings", settings)

        try:
            cat = CatalogRepository(db) if db_path is not None else CatalogRepository(get_database())
            reconcile_endpoint_bindings(cat, settings)
        except Exception:
            logger.warning("rescue: reconcile_endpoint_bindings failed", exc_info=True)
    finally:
        if db_path is not None:
            db.close()

    return {
        "endpoints_imported": imported,
        "model_selections_imported": len(data.get("modelSelections") or {}),
    }


# ============================================================
# 连通性测试（轻量级）
# ============================================================


def probe_connectivity(  # noqa: PLR0911 — 连通性分类天然多分支
    endpoint: Dict[str, Any],
    *,
    timeout_s: float = 5.0,
) -> Dict[str, Any]:
    """测试端点连通性。

    返回 ``{"ok": bool, "category": "ok"|"auth"|"dns"|"connection_refused"|"timeout"|"http_error"|"other",
    "status_code": int|None, "message": str, "models": list[str]}``。

    - TCP 连接失败分类为 dns / connection_refused / timeout；
    - HTTP 成功解析 JSON 列表中的模型 id；
    - 401/403 → auth；其它 HTTP 错误 → http_error。
    """
    import socket

    base_url = endpoint.get("baseUrl") or ""
    if not base_url:
        return {"ok": False, "category": "other", "status_code": None, "message": "baseUrl 为空", "models": []}
    try:
        parsed = urlparse(base_url)
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        sock = socket.create_connection((host, port), timeout=min(3.0, timeout_s))
        sock.close()
    except socket.gaierror as exc:
        return {"ok": False, "category": "dns", "status_code": None, "message": f"DNS 解析失败: {exc}", "models": []}
    except (socket.timeout, TimeoutError):  # noqa: UP041 — py38: socket.timeout 不是 TimeoutError 子类
        return {"ok": False, "category": "timeout", "status_code": None, "message": "TCP 连接超时", "models": []}
    except ConnectionRefusedError:
        return {"ok": False, "category": "connection_refused", "status_code": None, "message": "连接被拒绝", "models": []}
    except OSError as exc:
        return {"ok": False, "category": "other", "status_code": None, "message": f"网络错误: {exc}", "models": []}

    # HTTP 尝试各协议的模型列表端点
    protocol = endpoint.get("protocol") or "openai-compatible"
    api_key = endpoint.get("apiKey") or ""
    base = base_url.rstrip("/")
    if protocol == "ollama":
        url = base + "/api/tags"
    elif base.endswith(("/v1", "/v1beta", "/api/v1")):
        # baseUrl 已包含版本前缀（Sage 端点约定）→ 只追加 /models
        url = base + "/models"
    elif protocol == "gemini":
        url = base + "/v1beta/models"
    else:
        url = base + "/v1/models"

    try:
        import urllib.request
        req = urllib.request.Request(url, method="GET")
        if api_key:
            if protocol == "gemini":
                req.add_header("x-goog-api-key", api_key)
            elif protocol == "anthropic":
                req.add_header("x-api-key", api_key)
                req.add_header("anthropic-version", "2023-06-01")
            else:
                req.add_header("Authorization", f"Bearer {api_key}")
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = resp.read().decode("utf-8", errors="replace")[:4096]
            status_code = resp.status
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            body = ""
        if exc.code in (401, 403):
            return {"ok": False, "category": "auth", "status_code": exc.code, "message": f"认证失败: {exc}", "models": []}
        return {"ok": False, "category": "http_error", "status_code": exc.code, "message": f"HTTP {exc.code}: {body}", "models": []}
    except Exception as exc:
        return {"ok": False, "category": "other", "status_code": None, "message": f"请求失败: {exc}", "models": []}

    # 解析模型列表
    try:
        data = json.loads(body)
    except Exception:
        return {"ok": True, "category": "ok", "status_code": status_code, "message": "响应非 JSON", "models": []}

    if protocol in ("ollama", "gemini"):
        models = [m.get("name") for m in (data.get("models") or []) if isinstance(m, dict)]
    else:
        models = [m.get("id") for m in (data.get("data") or []) if isinstance(m, dict)]
    return {"ok": True, "category": "ok", "status_code": status_code, "message": "连通", "models": models}
