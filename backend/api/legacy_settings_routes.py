# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""settings / preferences 路由组（C1d，DSH 对标 R25，自 legacy_routes.py 迁出）。

- ``GET/PUT /settings``：应用设置读写（camelCase 翻译 + 白名单校验 + 脱敏）
- ``GET/PUT /preferences/{key}``：通用 KV 读写（白名单限定 key）

路径与前缀保持不变（router 无 prefix，经 legacy_router include 后仍为
/api/v1/settings 等）——纯物理拆分，零行为变更。依赖经 legacy_router 的
include 链挂载（main.py 不直接感知本文件）。

设置三模型（LegacySettingsRequest/Response、LegacyPreferenceItem）定义
仍在 legacy_skills_routes.py（C1b R15 的既有格局），本模块与其同样按需
导入，不搬动模型归属。
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException

from backend.api.legacy_skills_routes import (
    LegacyPreferenceItem,
    LegacySettingsRequest,
    LegacySettingsResponse,
)
from backend.api.settings_models import model_dump_compat
from backend.data.database import make_with_db_lock

logger = logging.getLogger(__name__)


def with_db_lock(func):
    """装饰器：把 sync 函数包在全局 `_SQLITE_LOCK` 内,串行化 SQLite 访问。

    D3 同款（镜像 orch_routes / legacy_memory_routes）：make_with_db_lock
    把 wrapper 的 __globals__ 重绑到本模块（FastAPI 字符串注解须在本模块
    解析，body 模型如 LegacySettingsRequest），_SQLITE_LOCK 经 import
    共享同一对象，与 legacy_routes 的锁语义一致。
    """
    return make_with_db_lock(globals())(func)


router = APIRouter()


@router.get("/settings")
@with_db_lock
def legacy_get_settings() -> Optional[Dict]:
    """读取持久化的 settings；不存在返回 null。

    翻译历史 snake_case 残留到 camelCase 返回，与 AppSettings 类型对齐。
    JSON 损坏 / 顶层非 dict (list / scalar) → null fallback，不抛 500，与 hex GET 对齐。
    """
    from backend.data.settings_canonicalizer import (
        detect_legacy_snake_pollution,
        redact_secrets,
        strip_unknown_fields,
        to_camel,
    )
    from backend.data.settings_repo import SettingsRepository

    repo = SettingsRepository()
    try:
        raw = repo.get_json("app_settings")
    except (ValueError, TypeError):
        logger.warning("[LEGACY] /settings: corrupted app_settings JSON, returning null")
        return None
    if raw is None:
        return None
    if not isinstance(raw, dict):
        # get_json 可返回任意合法 JSON; app_settings 必须是 dict; 与 hex GET 对齐。
        logger.warning("[LEGACY] /settings: top-level non-dict JSON, returning null")
        return None
    detect_legacy_snake_pollution(raw)
    translated = to_camel(raw)
    # Task 1 (2026-08-23): 历史 endpoints[*] 无 protocol 字段 (旧 schema 没这层)
    # → 迁移默认值 ``openai-compatible`` (OpenAI 兼容端点是最常见的 LM Studio /
    # Ollama / OpenAI 替代品). 这样旧客户端无需再写一次 PUT 就能看到正确 protocol.
    _migrate_default_protocol(translated)
    # 2026-08-26: 边界净化白名单外字段 + 脱敏 apiKey, 防止历史残留
    # (memory_server_sync / local_model_path 等) 重新污染 GET 响应,
    # 同时保证明文凭据不通过 HTTP 回前端 (OWASP A02:2021).
    cleaned = strip_unknown_fields(translated)
    return redact_secrets(cleaned)


def _migrate_default_protocol(settings: dict) -> None:
    """把 DB 中无 ``protocol`` 字段的 endpoint 默认填 ``openai-compatible``.

    仅在 GET 路径走 — 不写回 DB (避免无谓 IO); 用户下次 PUT 时如果设置里仍无
    protocol 字段, 由 handler 在写库前再补一遍默认值.
    """
    endpoints = settings.get("endpoints")
    if not isinstance(endpoints, list):
        return
    for ep in endpoints:
        if isinstance(ep, dict) and "protocol" not in ep:
            ep["protocol"] = "openai-compatible"


@router.put("/settings", response_model=LegacySettingsResponse)
@with_db_lock
def legacy_update_settings(req: LegacySettingsRequest) -> LegacySettingsResponse:
    """持久化 settings 到 preferences 表。

    v3.1 修复：合并而非覆盖。
    LegacySettingsRequest 只有 api_base_url/api_key/model 三个字段，
    如果直接替换，会丢失 endpoints、model_selections 等其他数据。
    修复策略：先读现有 settings，再把请求字段 merge 进去。

    Task 2 (settings-schema-canonicalization):
    - 整树翻译到 camelCase (to_camel)
    - 白名单校验 (validate_settings_shape) 拒绝白名单外字段 → 400
    """
    from backend.data.settings_canonicalizer import (
        classify_settings_shape_field,
        classify_settings_validation_error,
        strip_unknown_fields,
        to_camel,
        validate_settings_payload,
        validate_settings_shape,
    )
    from backend.data.settings_repo import SettingsRepository

    repo = SettingsRepository()
    try:
        existing = repo.get_json("app_settings") or {}
    except (ValueError, TypeError):
        # DB 行 JSON 损坏 → 当空树处理, 避免 500 阻断合法的 PUT
        existing = {}
    if not isinstance(existing, dict):
        # existing 是 list/scalar (脏数据) → 用空树, 不阻断合法 PUT; 与 hex PUT 对齐.
        existing = {}

    # LegacySettingsRequest 是 extra="allow", model_dump(exclude_none=True) 会包含所有 set 字段
    # (含 extras, 如 streaming/foo/endpoints) — 这是设计: 旧客户端 PUT schema 之外字段不丢。
    payload = model_dump_compat(req, exclude_none=True)

    # 剥离 legacy compatibility 3 字段: api_base_url / api_key / model.
    # 这 3 字段不进 DB (与 hex PUT 对齐, 见 eebbedd), 仅用于审计和 changed_fields.
    # 原因: 这 3 个 snake 字段通过 to_camel 翻译后 (apiKey) 或原样保留 (api_base_url/model)
    # 都不在 LEGAL_TOP_KEYS, 会触发 validate_settings_shape 400, 但它们是合法 legacy schema 字段.
    legacy_compat_fields = {"api_base_url", "api_key", "model"}
    legacy_compat_payload = {k: payload.pop(k) for k in list(payload) if k in legacy_compat_fields}

    # existing 里的历史残留字段（compactMode / proxyMode 等前端已删）会让
    # validate_settings_shape 对整棵合并树报 400。只剥离 existing 侧的残留，
    # payload 侧的未知字段仍原样保留并触发 400（与 hex PUT 对齐）。
    camel_existing = strip_unknown_fields(to_camel(existing))
    camel_merged = {**camel_existing, **to_camel(payload)}
    # Task 1 (2026-08-23): 写入前给旧 endpoints (无 protocol) 补默认值, 与 GET 路径对齐.
    _migrate_default_protocol(camel_merged)
    # Task 1 round 1 (2026-08-24): 显式跑 timezone / protocol / localModelPath
    # value 校验 (Pydantic 装饰器不可用, 这里下沉到 canonicalizer 层).
    try:
        validate_settings_payload(camel_merged)
    except ValueError as exc:
        field = classify_settings_validation_error(exc)
        logger.warning(
            "[LEGACY] /settings rejected: error_type=invalid_settings_payload field=%s",
            field,
        )
        raise HTTPException(
            status_code=422,
            detail={
                "type": "invalid_settings_payload",
                "message": "设置内容无效，请检查字段格式",
                "field": field,
            },
        ) from exc
    try:
        validate_settings_shape(camel_merged)
    except ValueError as exc:
        field = classify_settings_shape_field(exc)
        logger.warning(
            "[LEGACY] /settings rejected: error_type=invalid_settings_shape field=%s",
            field,
        )
        raise HTTPException(
            status_code=400,
            detail={
                "type": "invalid_settings_shape",
                "message": "设置结构无效，请检查字段",
                "field": field,
            },
        ) from exc
    repo.set_json("app_settings", camel_merged, category="general")
    changed_fields = [k for k in payload if k != "api_key"]
    if "api_key" in payload:
        changed_fields.append("api_key")
    # 同时把 legacy 兼容字段记进 changed_fields (审计可见), 即使不进 DB
    changed_fields.extend(k for k in legacy_compat_payload if k not in changed_fields)
    logger.info(f"[LEGACY] /settings updated: changed={changed_fields}")
    return LegacySettingsResponse(status="ok", changed_fields=changed_fields)


@router.get("/preferences/{key}", response_model=LegacyPreferenceItem)
@with_db_lock
def legacy_get_preference(key: str) -> LegacyPreferenceItem:
    """通用 KV 读取（白名单限定 key）。

    2026-08-26: 当 key=='app_settings' 时, 对 value (JSON 字符串) 做
    ``redact_secrets_json`` —— 把 endpoint.apiKey 替换为 hasApiKey 标记,
    防止明文凭据通过 preference GET 返回前端 (OWASP A02:2021).
    """
    from backend.data.settings_canonicalizer import redact_secrets_json
    from backend.data.settings_repo import SettingsRepository

    if key not in SettingsRepository.KEYS:
        raise HTTPException(status_code=400, detail=f"key {key!r} not in whitelist")
    val = SettingsRepository().get(key)
    if key == "app_settings":
        val = redact_secrets_json(val)
    return LegacyPreferenceItem(value=val)


@router.put("/preferences/{key}", response_model=LegacyPreferenceItem)
@with_db_lock
def legacy_put_preference(key: str, item: LegacyPreferenceItem) -> LegacyPreferenceItem:
    """通用 KV 写入（白名单限定 key）。"""
    from backend.data.settings_canonicalizer import (
        parse_app_settings_object,
        redact_secrets_json,
    )
    from backend.data.settings_repo import SettingsRepository

    if key not in SettingsRepository.KEYS:
        raise HTTPException(status_code=400, detail=f"key {key!r} not in whitelist")
    if key == "app_settings" and item.value is not None:
        try:
            parse_app_settings_object(item.value)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="app_settings must be a JSON object") from exc
    if item.value is not None:
        SettingsRepository().set(
            key, item.value, value_type=item.value_type, category=item.category
        )
    if key == "app_settings":
        return LegacyPreferenceItem(
            value=redact_secrets_json(item.value),
            value_type=item.value_type,
            category=item.category,
        )
    return item
