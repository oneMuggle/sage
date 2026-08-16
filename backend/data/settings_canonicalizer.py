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
# orch 段 (OrchSettings + scratchRoot). 前端 interface 只暴露 5 个数值;
# scratchRoot 是后端配置 (spec 偏差, 见 Wave 3 P2-9 plan §3.3).
LEGAL_ORCH_KEYS: FrozenSet[str] = frozenset(
    {
        "maxConcurrentSubagents",
        "maxAggregateChars",
        "maxSubagentResultChars",
        "maxRetries",
        "maxLaneIterations",
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
    """反向: ALIASES 仅翻译已知 snake↔camel 对; 其它 camelCase key 原样保留.

    win7 Note: Python 3.8 不支持 ``dict | list`` PEP 604 union syntax 在
    runtime isinstance 检查（即使 ``from __future__ import annotations`` 也
    只注解层, runtime 表达式仍要 3.10+）。用 tuple form ``(dict, list)`` 兼容。
    """
    if not isinstance(value, (dict, list)):
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
