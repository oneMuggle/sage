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
from typing import Any, Dict, FrozenSet, List

logger = logging.getLogger(__name__)

# B3: DEBUG_LEGACY_POLLUTION env gate. 默认 False: 生产环境不 log snake 污染 (避免日志噪音).
# 仅在调试时开启 (DEBUG_LEGACY_POLLUTION=1 / true / yes), 且只在顶层 path=="" 时 log 一次 (子帧不再重复 log).
_DEBUG_POLLUTION = os.environ.get("DEBUG_LEGACY_POLLUTION", "").lower() in ("1", "true", "yes")

# snake_case → camelCase 字段名映射 (单源)
# 修改 AppSettings (src/entities/setting/types.ts) 字段时必须同步更新此处
ALIASES: Dict[str, str] = {
    # 顶层 8 个 snake 历史字段 (legacy schema 残留)
    "model_selections": "modelSelections",
    "max_context": "maxContext",
    "proxy_mode": "proxyMode",
    "proxy_url": "proxyUrl",
    "tls_version": "tlsVersion",
    "auto_memory": "autoMemory",
    "confirm_delete": "confirmDelete",
    "compact_mode": "compactMode",
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
        "compactMode",
        "endpoints",
        "modelSelections",
        "maxContext",
        "temperature",
        "proxyMode",
        "proxyUrl",
        "tlsVersion",
        "wiki",
        "version",
    }
)
LEGAL_ENDPOINT_KEYS: FrozenSet[str] = frozenset(
    {
        "id",
        "name",
        "baseUrl",
        "apiKey",
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
