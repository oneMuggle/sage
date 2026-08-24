"""Settings 字段命名规范化模块。

把历史 snake_case DB 数据在 GET 时翻译成 camelCase AppSettings,
并在 PUT 时把存进 DB 的 camelCase payload 整树校验,
拒绝白名单外 / snake_case 残留字段。

纯函数, 无外部依赖, 可独立测试。
"""

from __future__ import annotations

import logging
import os
import re
import sys
from typing import Any, Dict, FrozenSet, List

logger = logging.getLogger(__name__)

# B3: DEBUG_LEGACY_POLLUTION env gate. 默认 False: 生产环境不 log snake 污染 (避免日志噪音).
# 仅在调试时开启 (DEBUG_LEGACY_POLLUTION=1 / true / yes), 且只在顶层 path=="" 时 log 一次 (子帧不再重复 log).
_DEBUG_POLLUTION = os.environ.get("DEBUG_LEGACY_POLLUTION", "").lower() in ("1", "true", "yes")

# snake_case → camelCase 字段名映射 (单源)
# 修改 AppSettings (src/entities/setting/types.ts) 字段时必须同步更新此处
ALIASES: Dict[str, str] = {
    # 顶层 snake 历史字段 (legacy schema 残留)
    "model_selections": "modelSelections",
    "max_context": "maxContext",
    "auto_memory": "autoMemory",
    "confirm_delete": "confirmDelete",
    # modelSelections 子层
    "chat_model": "chatModel",
    "vision_model": "visionModel",
    "embedding_model": "embeddingModel",
    # EndpointConfig 子层
    "base_url": "baseUrl",
    "api_key": "apiKey",
    "discovered_models": "discoveredModels",
    "last_discovered_at": "lastDiscoveredAt",
    # ModelSelection 子层
    "endpoint_id": "endpointId",
    "model_id": "modelId",
}

# AppSettings (src/entities/setting/types.ts) 锁死的白名单
LEGAL_TOP_KEYS: FrozenSet[str] = frozenset(
    {
        "streaming",
        "autoMemory",
        "confirmDelete",
        "endpoints",
        "modelSelections",
        "maxContext",
        "temperature",
        # Task 1 (2026-08-23): IANA timezone, 默认 Asia/Shanghai, 后端 zoneinfo 校验
        "timezone",
        "wiki",
        "version",
        # Wave 3 P2-9 (2026-08-14): 编排执行参数段。
        "orch",
    }
)
LEGAL_ENDPOINT_KEYS: FrozenSet[str] = frozenset(
    {
        "id",
        "name",
        "baseUrl",
        "apiKey",
        # Task 1 (2026-08-23): 新增端点协议/模型身份字段。
        # - protocol: 'openai-compatible' | 'anthropic' | 'gemini' | 'ollama',
        #   历史无 protocol 的端点经 strip_unknown_fields+迁移 fallback 默认为 'openai-compatible'.
        # - modelId: 上游模型 ID (LM Studio 用户常填的 ``qwen2.5-7b-instruct``).
        # - localModelPath: 本地模型文件路径, 与 modelId 互斥但并存以支持 hybrid (e.g.
        #   Ollama 边远端边本地).
        "protocol",
        "modelId",
        "localModelPath",
        "discoveredModels",
        "lastDiscoveredAt",
    }
)
LEGAL_MODEL_SELECTION_KEYS: FrozenSet[str] = frozenset(
    {
        "endpointId",
        "modelId",
    }
)
LEGAL_DISCOVERED_MODEL_KEYS: FrozenSet[str] = frozenset(
    {
        "id",
        "capabilities",
        "endpointId",
    }
)
LEGAL_WIKI_KEYS: FrozenSet[str] = frozenset(
    {
        "useFolderPicker",
    }
)
# modelSelections 对象的 keys (chatModel/visionModel/embeddingModel).
# Contract test (test_settings_schema_parity.py) 保证此处与前端 AppSettings.modelSelections 字段同步.
LEGAL_MODEL_SELECTIONS_KEYS: FrozenSet[str] = frozenset(
    {
        "chatModel",
        "visionModel",
        "embeddingModel",
    }
)
# orch 段 (OrchSettings + scratchRoot). 前端 interface 只暴露 6 个数值;
# scratchRoot 是后端配置 (spec 偏差, 见 Wave 3 P2-9 plan §3.3).
LEGAL_ORCH_KEYS: FrozenSet[str] = frozenset(
    {
        "maxConcurrentSubagents",
        "maxAggregateChars",
        "maxSubagentResultChars",
        "maxRetries",
        "maxLaneIterations",
        "maxSubagentIterations",
        "scratchRoot",
    }
)

# snake_case 必须含至少一个下划线 (否则只是普通单词, 不是 snake_case)
_SNAKE_RE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)+$")


def to_camel(value: Any) -> Any:
    """递归把 dict 的 snake_case key 翻译成 camelCase, list 递归."""
    if isinstance(value, dict):
        return {_translate_key(k): to_camel(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_camel(item) for item in value]
    return value


def from_camel(value: Any) -> Any:
    """反向: ALIASES 仅翻译已知 snake↔camel 对; 其它 camelCase key 原样保留."""
    if not isinstance(value, dict | list):
        return value
    inverse = {v: k for k, v in ALIASES.items()}
    if isinstance(value, dict):
        return {inverse.get(k, k): from_camel(v) for k, v in value.items()}
    return [from_camel(item) for item in value]


def _translate_key(key: str) -> str:
    return ALIASES.get(key, key)


def validate_settings_shape(settings: dict) -> None:
    """AppSettings 白名单校验. 不在白名单的字段 → raise ValueError."""
    unknown = [k for k in settings if k not in LEGAL_TOP_KEYS]
    if unknown:
        raise ValueError(
            f"unknown top-level field {unknown[0]!r}; " f"allowed: {sorted(LEGAL_TOP_KEYS)}"
        )

    for i, ep in enumerate(settings.get("endpoints") or []):
        if not isinstance(ep, dict):
            raise ValueError(f"endpoints[{i}] is not a dict")
        bad_ep = [k for k in ep if k not in LEGAL_ENDPOINT_KEYS]
        if bad_ep:
            raise ValueError(
                f"unknown endpoint field {bad_ep[0]!r} at endpoints[{i}]; "
                f"allowed: {sorted(LEGAL_ENDPOINT_KEYS)}"
            )
        for j, model in enumerate(ep.get("discoveredModels") or []):
            if not isinstance(model, dict):
                raise ValueError(f"endpoints[{i}].discoveredModels[{j}] is not a dict")
            bad = [k for k in model if k not in LEGAL_DISCOVERED_MODEL_KEYS]
            if bad:
                raise ValueError(
                    f"unknown discovered-model field {bad[0]!r} "
                    f"at endpoints[{i}].discoveredModels[{j}]; "
                    f"allowed: {sorted(LEGAL_DISCOVERED_MODEL_KEYS)}"
                )

    ms = settings.get("modelSelections") or {}
    # 校验 modelSelections 子对象 keys (chatModel/visionModel/embeddingModel);
    # 未知 key 会污染 DB, 应拒收. Contract test 保证此处与 AppSettings 同步.
    bad_ms_keys = [k for k in ms if k not in LEGAL_MODEL_SELECTIONS_KEYS]
    if bad_ms_keys:
        raise ValueError(
            f"unknown model-selections field {bad_ms_keys[0]!r}; "
            f"allowed: {sorted(LEGAL_MODEL_SELECTIONS_KEYS)}"
        )
    for sel_key in ("chatModel", "visionModel", "embeddingModel"):
        sel = ms.get(sel_key) or {}
        if not isinstance(sel, dict):
            raise ValueError(f"modelSelections.{sel_key} is not a dict")
        bad = [k for k in sel if k not in LEGAL_MODEL_SELECTION_KEYS]
        if bad:
            raise ValueError(
                f"unknown model-selection field {bad[0]!r} "
                f"in modelSelections.{sel_key}; "
                f"allowed: {sorted(LEGAL_MODEL_SELECTION_KEYS)}"
            )

    wiki = settings.get("wiki") or {}
    bad_wiki = [k for k in wiki if k not in LEGAL_WIKI_KEYS]
    if bad_wiki:
        raise ValueError(
            f"unknown wiki field {bad_wiki[0]!r}; " f"allowed: {sorted(LEGAL_WIKI_KEYS)}"
        )

    orch = settings.get("orch") or {}
    if not isinstance(orch, dict):
        raise ValueError("orch is not a dict")
    bad_orch = [k for k in orch if k not in LEGAL_ORCH_KEYS]
    if bad_orch:
        raise ValueError(
            f"unknown orch field {bad_orch[0]!r}; " f"allowed: {sorted(LEGAL_ORCH_KEYS)}"
        )


def strip_unknown_fields(settings: Any) -> Any:
    """递归剥离 AppSettings 各层白名单外的字段, 返回干净 dict。

    历史残留场景: 前端 schema 演进删除的旧字段 (compactMode / proxyMode /
    proxyUrl / tlsVersion 等) 可能残留在已持久化的 app_settings 中。PUT
    /settings 是合并式校验 (``{**existing, **payload}``), existing 里的残留
    字段会让 ``validate_settings_shape`` 对整棵合并树报 400, 阻断所有设置保存。
    本函数在合并后、校验前剥离白名单外字段 —— 残留是废弃数据, 静默丢弃,
    并在首次成功保存时自动净化 DB。

    各层白名单与 ``validate_settings_shape`` 严格一致:
    - 顶层 ``LEGAL_TOP_KEYS``
    - endpoints: ``LEGAL_ENDPOINT_KEYS`` + discoveredModels: ``LEGAL_DISCOVERED_MODEL_KEYS``
    - modelSelections: ``LEGAL_MODEL_SELECTIONS_KEYS`` + 子 ``LEGAL_MODEL_SELECTION_KEYS``
    - wiki: ``LEGAL_WIKI_KEYS`` / orch: ``LEGAL_ORCH_KEYS``
    """
    if not isinstance(settings, dict):
        return settings

    out = {k: v for k, v in settings.items() if k in LEGAL_TOP_KEYS}

    eps = out.get("endpoints")
    if isinstance(eps, list):
        cleaned_eps: List[Any] = []
        for ep in eps:
            if not isinstance(ep, dict):
                # 类型损坏的端点项 (非 dict): 保留原样, 不静默删除 —— 由
                # validate_settings_shape 报 400 暴露, 避免无审计的数据丢失。
                # 净化只针对"白名单外的未知 key", 不针对"类型损坏"。
                cleaned_eps.append(ep)
                continue
            clean_ep = {k: v for k, v in ep.items() if k in LEGAL_ENDPOINT_KEYS}
            models = clean_ep.get("discoveredModels")
            if isinstance(models, list):
                clean_ep["discoveredModels"] = [
                    {k: v for k, v in m.items() if k in LEGAL_DISCOVERED_MODEL_KEYS}
                    for m in models
                    if isinstance(m, dict)
                ]
            cleaned_eps.append(clean_ep)
        out["endpoints"] = cleaned_eps

    ms = out.get("modelSelections")
    if isinstance(ms, dict):
        clean_ms = {k: v for k, v in ms.items() if k in LEGAL_MODEL_SELECTIONS_KEYS}
        for sel_key in ("chatModel", "visionModel", "embeddingModel"):
            sel = clean_ms.get(sel_key)
            if isinstance(sel, dict):
                clean_ms[sel_key] = {
                    k: v for k, v in sel.items() if k in LEGAL_MODEL_SELECTION_KEYS
                }
        out["modelSelections"] = clean_ms

    wiki = out.get("wiki")
    if isinstance(wiki, dict):
        out["wiki"] = {k: v for k, v in wiki.items() if k in LEGAL_WIKI_KEYS}

    orch = out.get("orch")
    if isinstance(orch, dict):
        out["orch"] = {k: v for k, v in orch.items() if k in LEGAL_ORCH_KEYS}

    return out


def detect_legacy_snake_pollution(
    settings: Any,
    path: str = "",
) -> List[str]:
    """递归遍历, 返回所有 snake_case 字段路径.

    日志策略 (B3):
    - 默认不 log (生产环境避免日志噪音);
    - 仅当 env gate ``DEBUG_LEGACY_POLLUTION`` 开启且 path=="" (顶层调用) 时 log.warning 一次;
    - 子帧递归不再重复 log, 避免同一路径多帧重复输出.
    """
    polluted: List[str] = []
    if isinstance(settings, dict):
        for k, v in settings.items():
            sub_path = f"{path}.{k}" if path else k
            if isinstance(k, str) and _SNAKE_RE.match(k):
                polluted.append(sub_path)
            polluted.extend(detect_legacy_snake_pollution(v, sub_path))
    elif isinstance(settings, list):
        for i, item in enumerate(settings):
            polluted.extend(detect_legacy_snake_pollution(item, f"{path}[{i}]"))
    # 仅顶层 + gate 开启才 log; 子帧不重复
    if polluted and path == "" and _DEBUG_POLLUTION:
        logger.warning(
            "[settings_canonicalizer] legacy snake_case pollution detected: %s",
            polluted,
        )
    return polluted


# === Task 1 (2026-08-23): IANA timezone 校验 ===
#
# AppSettings.timezone 用 ``zoneinfo`` 验证 (Python 3.9+ 内置, Win7 走 backports.zoneinfo).
# ``None`` / 空字符串视为 "未设置", 由调用方决定是否补默认值; 非法字符串抛 ValueError.
#
# 注意: canonicalizer 自身只锁白名单 key, 不锁 value 语义. timezone 校验由调用方
# (hex_routes.SettingsRequest / legacy_routes.LegacySettingsRequest) 在 Pydantic
# 层 + 本 helper 在 strip_unknown_fields 之后做, 保证 422 响应一致性.

DEFAULT_TIMEZONE = "Asia/Shanghai"


def validate_timezone(value: Any) -> Any:
    """IANA timezone 校验.

    Returns:
        原样返回 ``value`` (便于 Pydantic ``validator`` 链式调用).

    Raises:
        ValueError: 非 None / 非 str / ``zoneinfo`` 不识别的字符串。
    """
    if value is None or value == "":
        return value
    if not isinstance(value, str):
        raise ValueError(f"timezone must be a string, got {type(value).__name__}")
    try:
        # 延迟导入 zoneinfo — Python 3.9+ 标准库; Win7 走 backports.zoneinfo.
        from zoneinfo import ZoneInfo
    except ImportError:  # pragma: no cover — py3.9+ always has zoneinfo
        try:
            from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]
        except ImportError as exc:  # pragma: no cover — backports is dep
            raise ValueError(
                "timezone validation requires zoneinfo or backports.zoneinfo"
            ) from exc

    try:
        ZoneInfo(value)
    except Exception as exc:  # ZoneInfoNotFoundError + 其它解析异常
        raise ValueError(f"invalid IANA timezone {value!r}: {exc}") from exc
    return value


# === Task 1 round 1 (2026-08-24): 协议枚举 + 本地路径平台校验 ===
#
# 这些校验原本散在 Pydantic ``field_validator`` 装饰器里 (hex_routes / legacy_routes
# 各自重复). Pydantic 2 的 ``field_validator`` 在 Pydantic 1 / Win7 不可用, 直接走
# 装饰器会 syntax/runtime 双重炸. 现在把它们沉到 canonicalizer 层, 路由 handler
# 在 ``validate_settings_shape`` 之前显式调用, Pydantic 1/2 都跑同一套函数.
#
# 设计原则:
# - validate_* 函数都接受 ``Any`` 输入 (None / 空串 / dict 都能容忍), 不抛 TypeError.
# - 非法值抛 ``ValueError`` — FastAPI 会通过 handler 翻译成 422.
# - 平台相关分支接受 ``platform`` 参数 (默认 ``sys.platform``), 便于测试注入.

# Endpoint.protocol 合法值 (与前端 src/entities/setting/types.ts:EndpointProtocol 同步)
LEGAL_PROTOCOLS: FrozenSet[str] = frozenset(
    {"openai-compatible", "anthropic", "gemini", "ollama"}
)
DEFAULT_PROTOCOL = "openai-compatible"


def validate_protocol(value: Any) -> Any:
    """Endpoint.protocol 枚举校验.

    - ``None`` / 空字符串视为"未设置", 由 ``_migrate_default_protocol`` 兜底补默认值.
    - 非字符串 / 不在白名单 → ValueError (handler 翻译 422).
    """
    if value is None or value == "":
        return value
    if not isinstance(value, str):
        raise ValueError(
            f"protocol must be a string, got {type(value).__name__}: {value!r}"
        )
    if value not in LEGAL_PROTOCOLS:
        raise ValueError(
            f"invalid protocol {value!r}; allowed: {sorted(LEGAL_PROTOCOLS)}"
        )
    return value


def validate_local_model_path(value: Any, platform: str | None = None) -> Any:
    """Endpoint.localModelPath 平台路径分隔符校验.

    - ``None`` / 空字符串视为"未设置", 直接返回.
    - Win32 (平台名以 ``win`` 开头) 拒绝 POSIX 分隔符 ``/`` (除 drive letter 的 ``C:`` 后).
    - POSIX (linux / darwin) 拒绝 Windows 分隔符 ``\\``.
    - 其它平台 (如 cygwin) 跳过校验, 仅作字符串处理.

    Args:
        value: 待校验的路径字符串.
        platform: 显式平台覆盖, 默认 ``sys.platform``. 用于测试跨平台行为.
    """
    if value is None or value == "":
        return value
    if not isinstance(value, str):
        raise ValueError(
            f"localModelPath must be a string, got {type(value).__name__}: {value!r}"
        )

    effective_platform = platform if platform is not None else sys.platform

    if effective_platform.startswith("win"):
        # Win32 路径用 ``\\`` 作分隔符; 拒绝裸 POSIX ``/`` (drive letter 形如 ``C:\\`` 或
        #  UNC 路径 ``\\\\server\\share``, 不含裸 ``/``).
        if "/" in value:
            raise ValueError(
                f"localModelPath must use Windows path separators on win32, "
                f"got POSIX slash in {value!r}"
            )
    elif effective_platform.startswith(("linux", "darwin")) and "\\" in value:
        # POSIX 用 ``/``; 拒绝反斜杠 (历史数据从 Windows 迁过来时常见).
            raise ValueError(
                f"localModelPath must use POSIX path separators on {effective_platform}, "
                f"got backslash in {value!r}"
            )
    # 其它平台 (cygwin / freebsd 等) 跳过, 不强校验.

    return value


def validate_endpoint_payload(ep: Any, platform: str | None = None) -> Any:
    """单条 endpoint dict 的全部字段语义校验 (protocol / localModelPath).

    在 ``validate_settings_shape`` 之前调用 — 后者只锁白名单 key, 不锁 value.
    返回原 dict (校验通过), 失败抛 ValueError.

    Args:
        ep: 单条 endpoint 字典 (camelCase).
        platform: 透传给 ``validate_local_model_path``.
    """
    if not isinstance(ep, dict):
        raise ValueError(f"endpoint payload must be a dict, got {type(ep).__name__}")
    validate_protocol(ep.get("protocol"))
    validate_local_model_path(ep.get("localModelPath"), platform=platform)
    return ep


def validate_settings_payload(
    settings: Any,
    platform: str | None = None,
) -> None:
    """顶层 settings payload 全校验 (timezone + 全部 endpoint 子项).

    在 ``validate_settings_shape`` 之前调用:
    1. ``validate_timezone`` — 顶层 IANA timezone.
    2. ``validate_endpoint_payload`` — 每个 endpoint 跑 protocol + localModelPath.

    Raises:
        ValueError: 任一字段非法.
    """
    if not isinstance(settings, dict):
        return  # 非 dict 已经在 validate_settings_shape 里挡掉
    validate_timezone(settings.get("timezone"))
    endpoints = settings.get("endpoints")
    if isinstance(endpoints, list):
        for i, ep in enumerate(endpoints):
            try:
                validate_endpoint_payload(ep, platform=platform)
            except ValueError as exc:
                # 重新包装, 带上 endpoints 索引, 便于用户定位
                raise ValueError(f"endpoints[{i}]: {exc}") from exc
