"""
LLM factory for the orchestration layer.

Builds an ``LLMClient`` from the user's persisted endpoint configuration
(``app_settings`` in the preferences table), following the same pattern as
``backend/scheduler/evolution.py``: callers accept an *injected* client and
fall back to a settings-derived default when none is provided.

Resolution order for the endpoint:

1. ``modelSelections.chatModel.{endpointId, modelId}`` — the endpoint the
   user selected for chat, with the selected model.
2. The first endpoint in ``endpoints`` that carries a non-empty ``apiKey``,
   with its first discovered model (if any).

If no usable endpoint exists (no settings / no endpoints / no apiKey), the
factory returns ``None`` and callers degrade gracefully (single-task
planner fallback, clean ``ToolResult`` error for the agent tool).

All functions are defensive: any settings corruption (non-dict payloads,
missing keys, snake_case residue) yields ``None`` rather than raising.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from backend.routing.routing_engine import RoutingEngine

logger = logging.getLogger(__name__)

# Default model when an endpoint has no discovered models recorded.
DEFAULT_MODEL = "gpt-3.5-turbo"


def load_llm_config_from_settings() -> Optional[Dict[str, Any]]:
    """Resolve an ``LLMConfig``-compatible dict from persisted app_settings.

    Returns:
        A dict suitable for ``LLMConfig(**cfg)`` (provider/api_key/base_url/
        model/temperature), or ``None`` when no usable endpoint is configured.
    """
    try:
        from backend.data.settings_canonicalizer import to_camel
        from backend.data.settings_repo import SettingsRepository

        raw = SettingsRepository().get_json("app_settings")
    except Exception as exc:  # DB unavailable / corrupted — degrade
        logger.warning("llm_factory: failed to read app_settings: %s", exc)
        return None

    if not isinstance(raw, dict):
        return None

    # Normalize legacy snake_case residue to camelCase before reading.
    settings = to_camel(raw)

    endpoints = settings.get("endpoints") or []
    if not isinstance(endpoints, list) or not endpoints:
        return None

    selections = settings.get("modelSelections") or {}
    chat_selection = selections.get("chatModel") if isinstance(selections, dict) else None

    endpoint = None
    model_id = None
    if isinstance(chat_selection, dict) and chat_selection.get("endpointId"):
        endpoint = next(
            (
                ep
                for ep in endpoints
                if isinstance(ep, dict) and ep.get("id") == chat_selection.get("endpointId")
            ),
            None,
        )
        model_id = chat_selection.get("modelId") or None

    # Fallback: first endpoint with a usable apiKey.
    if endpoint is None:
        endpoint = next(
            (ep for ep in endpoints if isinstance(ep, dict) and ep.get("apiKey")),
            None,
        )

    if (
        not isinstance(endpoint, dict)
        or (endpoint.get("protocol") or "openai-compatible") not in _SUPPORTED_PROTOCOLS
        or (not endpoint.get("apiKey") and endpoint.get("protocol") not in {"ollama", "openai-compatible"})
        or not endpoint.get("baseUrl")
    ):
        return None

    if not model_id:
        discovered = endpoint.get("discoveredModels") or []
        if isinstance(discovered, list) and discovered and isinstance(discovered[0], dict):
            model_id = discovered[0].get("id")
    if not model_id:
        model_id = DEFAULT_MODEL

    result = {
        "provider": "custom",
        "api_key": endpoint["apiKey"],
        "base_url": endpoint["baseUrl"],
        "model": model_id,
        "temperature": 0.3,
    }
    # Task 5: include endpoint_id for usage attribution
    ep_id = endpoint.get("id")
    if isinstance(ep_id, str) and ep_id.strip():
        result["endpoint_id"] = ep_id
    # 2026-10-28: 输出长度 — 读全局设置 maxOutputTokens，覆盖 LLMConfig 默认 4096。
    # 缺失/非法时不写入，留 LLMConfig 默认值；有效范围 512–32768，越界夹紧。
    max_output = _clamp_max_output_tokens(settings.get("maxOutputTokens"))
    if max_output is not None:
        result["max_tokens"] = max_output
    return result


#: 单次回答的最大输出 token 上限区间（与前端 ModelsTab 输入框一致）
MIN_MAX_OUTPUT_TOKENS = 512
MAX_MAX_OUTPUT_TOKENS = 32768

#: ``profile.model_config.max_tokens`` 的种子默认值 —— 与 ``AgentModelConfig``
#: 默认一致，无法区分「用户有意设置」与「建号默认」，统一视为未设置。
_PROFILE_MAX_TOKENS_PLACEHOLDER = 4096


def _clamp_max_output_tokens(value: Any) -> Optional[int]:
    """把候选输出上限夹紧到 [512, 32768]；非正整数 / 非 int 返回 None。"""
    # bool 是 int 子类，显式排除 True/False
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return max(MIN_MAX_OUTPUT_TOKENS, min(value, MAX_MAX_OUTPUT_TOKENS))


def load_max_output_tokens_from_settings() -> Optional[int]:
    """读取全局设置 ``maxOutputTokens``；缺失 / 非法 / DB 不可用 → None。

    None 表示调用方沿用 ``LLMConfig.max_tokens`` 默认值（4096）。
    """
    try:
        from backend.data.settings_canonicalizer import to_camel
        from backend.data.settings_repo import SettingsRepository

        raw = SettingsRepository().get_json("app_settings")
    except Exception as exc:  # DB unavailable / corrupted — degrade
        logger.warning("llm_factory: failed to read maxOutputTokens: %s", exc)
        return None
    if not isinstance(raw, dict):
        return None
    return _clamp_max_output_tokens(to_camel(raw).get("maxOutputTokens"))


def resolve_max_output_tokens(
    profile_max_tokens: Optional[int] = None,
    request_max_tokens: Optional[int] = None,
) -> Optional[int]:
    """解析聊天链路的输出上限，优先级：request > profile > 全局设置。

    ``profile_max_tokens`` 等于占位默认 4096 时视为未设置，让全局设置生效。
    返回 None 表示三者都未提供，调用方沿用 LLMConfig 默认 4096。
    """
    resolved = _clamp_max_output_tokens(request_max_tokens)
    if resolved is not None:
        return resolved
    profile_value = _clamp_max_output_tokens(profile_max_tokens)
    if profile_value is not None and profile_value != _PROFILE_MAX_TOKENS_PLACEHOLDER:
        return profile_value
    return load_max_output_tokens_from_settings()


def _endpoint_has_required_api_key(
    endpoint: Dict[str, Any], *, protocol: Optional[str] = None
) -> bool:
    """Return whether an endpoint satisfies its protocol's auth contract."""
    endpoint_protocol = protocol or endpoint.get("protocol") or "openai-compatible"
    if endpoint_protocol in {"ollama", "openai-compatible"}:
        return True
    return bool(endpoint.get("apiKey"))


_SUPPORTED_PROTOCOLS = frozenset({"anthropic", "gemini", "ollama", "openai-compatible"})


def resolve_model_from_settings() -> Optional[str]:  # noqa: PLR0911
    """Resolve the selected model, falling back to the endpoint's discovered model.

    The endpoint and model are resolved together so callers cannot submit a
    model selected from another endpoint. Unknown protocols fail closed rather
    than being treated as OpenAI-compatible.

    L3 (P8): 原 "构造 ProviderClient 再取 model" 的实现已删除（该家族未接
    入生产装配），本函数直接解析模型名；协议校验退化为白名单成员检查。
    """
    try:
        from backend.data.settings_canonicalizer import to_camel
        from backend.data.settings_repo import SettingsRepository

        raw = SettingsRepository().get_json("app_settings")
        if not isinstance(raw, dict):
            return None
        settings = to_camel(raw)
        endpoints = settings.get("endpoints") or []
        if not isinstance(endpoints, list):
            return None
        selections = settings.get("modelSelections") or {}
        selection = selections.get("chatModel") if isinstance(selections, dict) else None
        selection = selection if isinstance(selection, dict) else {}
        # 无 endpointId 的纯 modelId 选择 (注入/测试场景) 直接采纳,
        # 不要求 endpoints 存在 (原 resolve_model_from_settings 的语义)。
        if not selection.get("endpointId"):
            model = selection.get("modelId")
            if isinstance(model, str) and model.strip():
                return model.strip()
        endpoint_id = selection.get("endpointId")
        endpoint = next(
            (ep for ep in endpoints if isinstance(ep, dict) and endpoint_id and ep.get("id") == endpoint_id),
            None,
        )
        if endpoint_id and endpoint is None:
            return None
        if endpoint is None:
            endpoint = next(
                (
                    ep for ep in endpoints
                    if isinstance(ep, dict)
                    and (ep.get("protocol") or "openai-compatible") in _SUPPORTED_PROTOCOLS
                    and ep.get("baseUrl")
                    and _endpoint_has_required_api_key(ep)
                ),
                None,
            )
        if not isinstance(endpoint, dict) or not endpoint.get("baseUrl"):
            return None

        protocol = endpoint.get("protocol") or "openai-compatible"
        if protocol not in _SUPPORTED_PROTOCOLS or not _endpoint_has_required_api_key(
            endpoint, protocol=protocol
        ):
            return None
        discovered = endpoint.get("discoveredModels") or []
        discovered_model = (
            discovered[0].get("id")
            if isinstance(discovered, list)
            and discovered
            and isinstance(discovered[0], dict)
            else None
        )
        model = selection.get("modelId") or discovered_model
        if not isinstance(model, str) or not model.strip():
            return None
        return model.strip()
    except Exception as exc:
        logger.warning("llm_factory: failed to resolve selected model: %s", exc)
        return None


def build_llm_client_from_settings() -> Optional[Any]:
    """Build an ``LLMClient`` from persisted settings, or ``None``.

    Never raises — construction failures are logged and return ``None`` so
    callers can degrade (planner falls back to single-task decomposition).
    """
    cfg = load_llm_config_from_settings()
    if cfg is None:
        return None
    try:
        from backend.core.legacy.llm_client import LLMClient, LLMConfig

        return LLMClient(LLMConfig(**cfg))
    except Exception as exc:
        logger.warning("llm_factory: failed to build LLMClient: %s", exc)
        return None


# ---------------------------------------------------------------------------
# G5 会话级模型覆盖（2026-09-06 对标增强 Phase-2，docs/plans §2.1）
# ---------------------------------------------------------------------------

#: preferences KV key：{session_id: model_id} 的 JSON 映射（会话 → 模型）。
#: 用户在某个会话里切换模型后，该会话固定用选定模型，不影响其他会话。
SESSION_MODEL_OVERRIDES_KEY = "session_model_overrides"

#: profile.model_config.model 的种子默认占位值 —— 无法区分"用户有意设置"
#: 与"create_default_agents 的默认"，统一视为未设置，不参与路由。
_PROFILE_MODEL_PLACEHOLDERS = frozenset(
    {"gpt-4", "gpt-3.5-turbo", "gpt-4-turbo-preview"}
)


def load_session_model_overrides() -> Dict[str, str]:
    """读取会话 → 模型覆盖映射；任何失败返回空 dict（fail-safe）。"""
    try:
        from backend.data.settings_repo import SettingsRepository

        raw = SettingsRepository().get_json(SESSION_MODEL_OVERRIDES_KEY)
    except Exception as exc:  # DB unavailable — degrade
        logger.warning("llm_factory: failed to read session model overrides: %s", exc)
        return {}
    if not isinstance(raw, dict):
        return {}
    # 只保留非空 str→非空 str；畸形条目静默丢弃而非整体失败
    return {
        sid: model
        for sid, model in raw.items()
        if isinstance(sid, str) and sid.strip()
        and isinstance(model, str) and model.strip()
    }


def resolve_chat_model(
    session_id: Optional[str], profile_model: Optional[str] = None
) -> Optional[str]:
    """按「会话覆盖 > profile 声明（非占位）」解析模型；都不命中返回 None。

    返回 None 表示沿用全局选择（app_settings.modelSelections）——
    调用方据此不覆盖 load_llm_config_from_settings 的结果。
    """
    if session_id:
        override = load_session_model_overrides().get(session_id)
        if override:
            return override
    if (
        isinstance(profile_model, str)
        and profile_model.strip()
        and profile_model not in _PROFILE_MODEL_PLACEHOLDERS
    ):
        return profile_model.strip()
    return None


# ---------------------------------------------------------------------------
# Task 9: auto-routing activation (settings key ``routing.mode``)
# ---------------------------------------------------------------------------

_ROUTING_AUTO = "auto"
_DEFAULT_CHAT_CONTEXT = 4096


def load_routing_config() -> Tuple[str, int]:
    """Return ``(mode, context_length)`` from app_settings.

    Fail-safe: any read error, non-dict payload, or unknown mode yields
    ``("manual", 4096)`` so callers keep the settings-derived model.
    """
    try:
        from backend.data.settings_canonicalizer import to_camel
        from backend.data.settings_repo import SettingsRepository

        raw = SettingsRepository().get_json("app_settings")
        if not isinstance(raw, dict):
            return "manual", _DEFAULT_CHAT_CONTEXT
        settings = to_camel(raw)
        routing = settings.get("routing")
        mode = routing.get("mode") if isinstance(routing, dict) else None
        mode = _ROUTING_AUTO if mode == _ROUTING_AUTO else "manual"
        max_context = settings.get("maxContext")
        if isinstance(max_context, bool) or not isinstance(max_context, int) or max_context <= 0:
            max_context = _DEFAULT_CHAT_CONTEXT
        return mode, max_context
    except Exception as exc:  # fail-safe: routing is optional
        logger.debug("llm_factory: routing config unavailable (%s); manual", exc)
        return "manual", _DEFAULT_CHAT_CONTEXT


def apply_auto_routing_overlay(
    cfg: Optional[Dict[str, Any]],
    task_type: Optional[str] = None,
    session_id: Optional[str] = None,
    profile_model: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """In auto mode, replace ``cfg['model']`` with the catalog-routed model.

    Returns ``cfg`` unchanged when: not a dict, mode is manual, the user made an
    explicit pick (session override / profile model — R23), or routing yields
    nothing. Selection is scoped to ``cfg['endpoint_id']`` so the model keeps
    that endpoint's credentials (Task 5 rationale).
    """
    if not isinstance(cfg, dict):
        return cfg
    mode, context_length = load_routing_config()
    if mode != _ROUTING_AUTO:
        return cfg
    if resolve_chat_model(session_id, profile_model):
        return cfg
    routed = resolve_routed_chat_model(
        task_type=(task_type or "chat"),
        context_length=context_length,
        endpoint_id=cfg.get("endpoint_id"),
    )
    if not routed:
        return cfg
    return {**cfg, "model": routed}


def load_llm_config_for_chat(
    session_id: Optional[str] = None,
    profile_model: Optional[str] = None,
    profile_max_tokens: Optional[int] = None,
    task_type: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """全局端点配置 + 会话/profile 模型覆盖 → LLMConfig 兼容 dict。

    端点（api_key/base_url/provider）恒取全局选择 —— 会话级只覆盖模型名，
    不换端点（换端点属全局设置页职责）。无可用端点 → None（调用方降级）。

    2026-10-28: 新增 ``profile_max_tokens`` 兜底 —— 当 agent profile 显式设置了
    ``model_config.max_tokens``（且非默认 4096）时，用它覆盖全局设置值。优先级：
    ChatRequest.max_tokens（调用方单独合并）> profile_max_tokens > maxOutputTokens > 4096。
    任务 9：``routing.mode == "auto"`` 时再叠加目录路由（显式选择优先）。
    """
    base = load_llm_config_from_settings()
    if base is None:
        return None
    merged = dict(base)
    override = resolve_chat_model(session_id, profile_model)
    if override:
        merged["model"] = override
    # profile max_tokens 作为次高优先级（在 ChatRequest 之上、全局设置之下）。
    # base 已带全局 maxOutputTokens，仅在 profile 有「非占位」显式值时覆盖。
    profile_value = _clamp_max_output_tokens(profile_max_tokens)
    if profile_value is not None and profile_value != _PROFILE_MAX_TOKENS_PLACEHOLDER:
        merged["max_tokens"] = profile_value
    return apply_auto_routing_overlay(
        merged, task_type=task_type, session_id=session_id, profile_model=profile_model
    )


# ---------------------------------------------------------------------------
# Task 5: endpoint-scoped advisory routing helper
# ---------------------------------------------------------------------------

def resolve_routed_chat_model(
    task_type: str,
    context_length: int = 4096,
    required_capabilities: Optional[List[str]] = None,
    endpoint_id: Optional[str] = None,
    catalog_repository: Optional[Any] = None,
) -> Optional[str]:
    """Return the catalog-selected model id for *task_type*, or ``None``.

    Advisory overlay on top of the settings-derived model: callers keep their
    existing model whenever this returns ``None``.

    ``endpoint_id`` scopes selection to one endpoint. This matters because the
    factory pairs a model id with exactly one endpoint's credentials; a model
    bound to a different endpoint would be sent to the wrong host with the
    wrong key. Callers that already resolved an endpoint (e.g. via
    ``load_llm_config_from_settings()["endpoint_id"]``) should pass it.

    Fail-safe: any catalog/routing failure returns ``None`` instead of raising.
    """
    try:
        repo = catalog_repository
        if repo is None:
            from backend.data.database import get_database
            from backend.model_catalog.repository import CatalogRepository

            repo = CatalogRepository(get_database())
        result = RoutingEngine(repo).route(
            task_type=task_type,
            context_length=context_length,
            required_capabilities=required_capabilities,
            endpoint_id=endpoint_id,
        )
    except Exception as exc:  # fail-safe by design: routing is optional
        logger.debug(
            "llm_factory: routing unavailable (%s); keeping settings model", exc
        )
        return None
    model_key = result.selected_model.model_key
    return model_key.model_id if model_key is not None else None
