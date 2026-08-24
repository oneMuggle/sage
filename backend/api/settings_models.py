"""Shared Pydantic models for /settings endpoint payloads.

Task 1 round 1 (2026-08-24): ``EndpointPayload`` + ``SettingsPayload`` 必须
**Pydantic 1 / Pydantic 2 双兼容**:

- main 分支跑 Python 3.11 + Pydantic 2.5 (用 ``model_config`` + ``field_validator``)
- release/win7 分支跑 Python 3.8 + Pydantic 1.10 (用 ``class Config`` + ``validator``)

策略:

- 字段声明两边都能跑 (``Optional[X]`` 是 typing 写法, Pydantic 1/2 都支持)
- ``protocol`` 字段用 ``Literal[...]`` (typing 标准, Pydantic 1/2 都识别)
- 配置用 ``class Config`` (Pydantic 1 原生; Pydantic 2 通过 ``Config`` 兼容层读取,
  会发 ``PydanticDeprecatedSince20`` 警告但仍生效) —— 比 ``model_config`` + 条件
  if-else 简单, 不会被 ``class`` 体内的条件 ``if`` 影响
- 所有值校验 (``timezone`` / ``protocol`` / ``localModelPath``) **不**用
  ``@field_validator`` 装饰器, 而是在 route handler 里显式调
  ``backend.data.settings_canonicalizer.validate_settings_payload`` —— 完全
  避开 Pydantic 1 vs 2 装饰器语法差异
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel

# Task 1 round 1: ``protocol`` 字段用 ``Literal`` 收紧 — 与前端
# ``src/entities/setting/types.ts:EndpointProtocol`` 同步. Pydantic 1.10+
# 与 Pydantic 2 都识别 typing.Literal, 校验逻辑等价于枚举.
# 4 个值与 ``backend.data.settings_canonicalizer.LEGAL_PROTOCOLS`` 对齐,
# 后者是 canonicalizer 层的最终守门 (handler 在 Pydantic 校验后兜底再校一遍).
EndpointProtocolLiteral = Literal[
    "openai-compatible", "anthropic", "gemini", "ollama"
]


def model_dump_compat(model: BaseModel, **kwargs: Any) -> Dict[str, Any]:
    """Serialize a Pydantic model on both v1 and v2.

    Pydantic 2 exposes ``model_dump`` while Pydantic 1 only provides ``dict``.
    Keeping this boundary helper beside the shared request models prevents route
    handlers from accidentally reintroducing a v2-only call on the Win7 path.
    """
    dump = getattr(model, "model_dump", None)
    if callable(dump):
        return dump(**kwargs)
    return model.dict(**kwargs)


# --------------------------------------------------------------------------
# EndpointPayload — Task 1 (2026-08-23): 含 4 协议 + modelId + localModelPath.
# --------------------------------------------------------------------------

class EndpointPayload(BaseModel):
    """单条 endpoint 配置 payload.

    字段顺序与 ``backend/data/settings_canonicalizer.py:LEGAL_ENDPOINT_KEYS``
    一致 (便于 contract test 对比). 字段命名走 camelCase (与前端 AppSettings
    TypeScript interface 字段一一对齐).

    ``extra = "allow"`` intentionally preserves unknown endpoint keys until the
    canonicalizer runs.  The canonicalizer owns the legacy contract and translates
    unknown nested keys to the endpoint's historical HTTP 400 response instead of
    Pydantic's pre-handler 422.  This is required for both legacy clients and the
    hex route's existing schema-drift diagnostics.
    """

    # --- Pydantic 1 + 2 双兼容 config ---
    # ``class Config`` 在 Pydantic 2 是 deprecated 但仍可用 (兼容层). Pydantic 1
    # 原生支持. 这是最简洁的跨版本写法, 不需要条件 ``if`` 分支.
    class Config:  # noqa: D401 — Pydantic 1/2 双兼容配置
        extra = "allow"

    # ----- EndpointConfig 字段 (与 types.ts:EndpointConfig 同步) -----
    id: Optional[str] = None
    name: Optional[str] = None
    baseUrl: Optional[str] = None  # noqa: N815 — camelCase 对齐前端
    apiKey: Optional[str] = None  # noqa: N815
    # Task 1 (2026-08-23): 协议枚举 + 模型身份.
    # Literal 在 Pydantic 1.10+ 与 2 都生效; 非法值 → Pydantic 422.
    protocol: Optional[EndpointProtocolLiteral] = None  # noqa: N815
    modelId: Optional[str] = None  # noqa: N815
    localModelPath: Optional[str] = None  # noqa: N815
    discoveredModels: Optional[List[dict]] = None  # noqa: N815
    lastDiscoveredAt: Optional[int] = None  # noqa: N815


# --------------------------------------------------------------------------
# SettingsPayload — Task 1 round 1: 顶层 settings PUT body, 用 List[EndpointPayload].
# --------------------------------------------------------------------------

class SettingsPayload(BaseModel):
    """Hex / legacy 路径的 PUT /settings 请求体 (共享).

    ``endpoints`` 使用 ``List[EndpointPayload]`` 而不是 ``List[dict]``,
    让 shared contract 在 Pydantic 1/2 中都保持显式。
    """

    class Config:  # noqa: D401 — Pydantic 1/2 双兼容
        extra = "forbid"

    # ----- AppSettings 顶层字段 (与 types.ts:AppSettings 同步) -----
    streaming: Optional[bool] = None
    autoMemory: Optional[bool] = None  # noqa: N815
    confirmDelete: Optional[bool] = None  # noqa: N815
    # Task 1 round 1: 强类型而非 List[dict]
    endpoints: Optional[List[EndpointPayload]] = None
    modelSelections: Optional[dict] = None  # noqa: N815
    maxContext: Optional[int] = None  # noqa: N815
    temperature: Optional[float] = None
    # Task 1 (2026-08-23): IANA timezone 字符串 — 校验下沉到 canonicalizer.
    timezone: Optional[str] = None
    wiki: Optional[dict] = None
    version: Optional[str] = None
    orch: Optional[dict] = None

    # ----- Legacy fields (兼容旧客户端, 不写入存储) -----
    api_base_url: Optional[str] = None
    api_key: Optional[str] = None  # noqa: S105 — 字段名占位; 不存储
    model: Optional[str] = None


# --------------------------------------------------------------------------
# LegacySettingsPayload — legacy 路径用, ``extra="allow"`` 兼容旧客户端.
# --------------------------------------------------------------------------

class LegacySettingsPayload(BaseModel):
    """Legacy 路径的 PUT /settings 请求体 (``extra="allow"`` 兼容旧客户端).

    ``extra = "allow"`` intentionally preserves unknown endpoint keys until the
    canonicalizer runs. The canonicalizer owns the legacy contract and translates
    unknown nested keys to the endpoint's historical HTTP 400 response instead of
    Pydantic's pre-handler 422. This is required for legacy clients and the hex
    route's existing schema-drift diagnostics.

    ``endpoints`` remains ``List[EndpointPayload]`` for the shared typed contract.
    """

    class Config:  # noqa: D401 — Pydantic 1/2 双兼容
        extra = "allow"

    # ----- AppSettings 顶层字段 (与 types.ts:AppSettings 同步) -----
    streaming: Optional[bool] = None
    autoMemory: Optional[bool] = None  # noqa: N815
    confirmDelete: Optional[bool] = None  # noqa: N815
    # Task 1 round 1: 强类型而非 List[dict]
    endpoints: Optional[List[EndpointPayload]] = None
    modelSelections: Optional[dict] = None  # noqa: N815
    maxContext: Optional[int] = None  # noqa: N815
    temperature: Optional[float] = None
    # Task 1 (2026-08-23): IANA timezone 字符串 — 校验下沉到 canonicalizer.
    timezone: Optional[str] = None
    wiki: Optional[dict] = None
    version: Optional[str] = None
    orch: Optional[dict] = None

    # ----- Legacy fields (deprecated, 兼容旧客户端, 不写入存储) -----
    api_base_url: Optional[str] = None
    api_key: Optional[str] = None  # noqa: S105 — 字段名占位; 不存储
    model: Optional[str] = None

