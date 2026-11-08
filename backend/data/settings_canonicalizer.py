"""Settings 字段命名规范化模块。

把历史 snake_case DB 数据在 GET 时翻译成 camelCase AppSettings,
并在 PUT 时把存进 DB 的 camelCase payload 整树校验,
拒绝白名单外 / snake_case 残留字段。

纯函数, 无外部依赖, 可独立测试。
"""

from __future__ import annotations
from typing import Optional

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
    "auto_context": "autoContext",
    # 2026-10-28: 输出长度上限（单次回答最大生成 token 数）
    "max_output_tokens": "maxOutputTokens",
    "auto_memory": "autoMemory",
    "confirm_delete": "confirmDelete",
    # modelSelections 子层
    "chat_model": "chatModel",
    "vision_model": "visionModel",
    "embedding_model": "embeddingModel",
    "tts_model": "ttsModel",
    "asr_model": "asrModel",
    "image_gen_model": "imageGenModel",
    # EndpointConfig 子层
    "base_url": "baseUrl",
    "api_key": "apiKey",
    # 2026-11-08: 内网救援工具写入时间戳 (ms epoch). relay 会把它转
    # snake_case, 缺别名时翻不回 camel, validate_settings_shape 400.
    "api_key_updated_at": "apiKeyUpdatedAt",
    "discovered_models": "discoveredModels",
    "last_discovered_at": "lastDiscoveredAt",
    # 2026-11-03: 思考过程参数 —— relay 的 camelToSnakeKeys 会把 endpoint 内的
    # camelCase 键整体转 snake, 缺别名时翻不回 camel → validate_settings_shape
    # 报 400, 前端 saveSettings 静默吞掉, 用户看到"改了没生效"。
    "reasoning_effort": "reasoningEffort",
    "thinking_budget": "thinkingBudget",
    # 2026-09-14: local_model_path 历史残留 (win7 安装包迁移数据), 不翻译会导致
    # validate_settings_shape 报 400 (field 不在 LEGAL_ENDPOINT_KEYS 白名单).
    "local_model_path": "localModelPath",
    # quota 子层 (2026-09-18 端点限额): 与前端 EndpointQuota 字段同步.
    "daily_tokens": "dailyTokens",
    "monthly_budget_usd": "monthlyBudgetUsd",
    # ModelSelection 子层
    "endpoint_id": "endpointId",
    "model_id": "modelId",
    # orch 子层 (2026-09 修复): relay 的 camelToSnakeKeys 会把前端发送的
    # orch 对象整体转成 snake, ALIASES 缺对的话 _translate_key 翻不回 camel,
    # validate_settings_shape 白名单报 400 —— 设置页编排段任一保存都失败。
    "max_concurrent_subagents": "maxConcurrentSubagents",
    "max_aggregate_chars": "maxAggregateChars",
    "max_subagent_result_chars": "maxSubagentResultChars",
    "max_retries": "maxRetries",
    "max_lane_iterations": "maxLaneIterations",
    "max_subagent_iterations": "maxSubagentIterations",
    "worktree_isolation": "worktreeIsolation",
    "subagent_approval_mode": "subagentApprovalMode",
    "run_token_budget": "runTokenBudget",
    "scratch_root": "scratchRoot",
    # Round 1/3 (2026-09-19) 计划前置旋钮（orch_settings.plan_*_enabled）。
    "plan_preflight_enabled": "planPreflightEnabled",
    "plan_scout_enabled": "planScoutEnabled",
    # RD15 (2026-09): 守门三键透出设置页, 同款 snake→camel 翻译必须同步。
    "run_wall_clock_limit_minutes": "runWallClockLimitMinutes",
    "subagent_task_timeout_s": "subagentTaskTimeoutS",
    "max_retry_of_chains": "maxRetryOfChains",
    # 2026-10-27: 工具预算 + 计划前置迭代预算。maxToolCallsPerRun 早于本
    # 日期进入 OrchSettings/UI，但白名单与 ALIASES 均漏加，导致编排段
    # 任一保存 400（前端静默吞错）；本次一并补齐。
    "max_tool_calls_per_run": "maxToolCallsPerRun",
    "max_scout_iterations": "maxScoutIterations",
    "max_planner_iterations": "maxPlannerIterations",
    # 2026-10-27 (code review 复现): relay 往返丢键 —— electron 的
    # camelToSnakeKeys 把前端 camelCase 键整体转 snake, ALIASES 缺别名时
    # to_camel 翻不回 camel → validate_settings_shape 报 400, 前端
    # saveSettings 的 catch{} 静默吞掉, 用户无感知。
    # - maxIterations: 编排 Tab 每次保存都整体 spread 提交 orch 段
    #   (含该键) → 编排段任一保存必 400, 本次两个新旋钮也因此无法落库。
    # - logTimezone / useFolderPicker: 通用 Tab / Wiki Tab 保存 400
    #   (同类 pre-existing 回归, 一并补齐)。
    "max_iterations": "maxIterations",
    # 2026-11-01: 动态迭代预算（OrchSettings P1）。relay 会把 orch 子层整体
    # 转 snake，缺别名时保存 400 被前端静默吞掉。
    "dynamic_budget_enabled": "dynamicBudgetEnabled",
    # 2026-11-04: 预算模式显式开关 —— 漏别名时 relay snake 往返 400
    # （test_legal_keys_survive_relay_snake_roundtrip 自动派生 snake 名兜底）。
    "budget_mode": "budgetMode",
    "budget_simple": "budgetSimple",
    "budget_medium": "budgetMedium",
    "budget_complex": "budgetComplex",
    "budget_long": "budgetLong",
    "budget_hard_cap": "budgetHardCap",
    "budget_max_extensions": "budgetMaxExtensions",
    "log_timezone": "logTimezone",
    "use_folder_picker": "useFolderPicker",
    # 2026-10-25: LLM 重试参数 — 前端发送 camelCase，但某些中间层可能转成 snake_case，
    # 需要 ALIASES 映射回 camelCase 以通过白名单校验。
    "llm_retry_max_attempts": "llmRetryMaxAttempts",
    "llm_retry_base_delay_s": "llmRetryBaseDelayS",
    "llm_retry_max_delay_s": "llmRetryMaxDelayS",
    # 2026-10-30: 自动重试总时长预算（秒，0 = 不限）。
    "llm_retry_total_budget_s": "llmRetryTotalBudgetS",
    "llm_total_timeout_s": "llmTotalTimeoutS",
    # 2026-10-28: ask_user_question 工具的可配置限制。
    "max_consecutive_unanswered_questions": "maxConsecutiveUnansweredQuestions",
    "min_options_per_question": "minOptionsPerQuestion",
    "max_options_per_question": "maxOptionsPerQuestion",
    "max_clarify_questions_in_prompt": "maxClarifyQuestionsInPrompt",
    "max_clarify_questions_per_round": "maxClarifyQuestionsPerRound",
    # 2026-10-28: LLM 代理上游超时（秒）— 前端「LLM 代理超时」设置。
    # 缺别名时 relay 的 camelToSnake 往返后翻不回 camel，保存 400 被静默吞掉。
    "llm_proxy_timeout_s": "llmProxyTimeoutS",
    # 2026-10-27: 会话标题专用模型 id — 与后端 title_model_factory.load_title_llm_config 对齐。
    "title_model_id": "titleModelId",
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
        # Task 5 (2026-09-15): auto context window toggle.
        "autoContext",
        # 2026-10-28: 输出长度上限（单次回答最大生成 token 数）— 前端默认 4096,
        # 透传后端覆盖 LLMConfig.max_tokens 默认值。
        "maxOutputTokens",
        "temperature",
        # Task 1 (2026-08-23): IANA timezone, 默认 Asia/Shanghai, 后端 zoneinfo 校验
        "timezone",
        # 日志时区 (2026-09-17): 'UTC' | 'local' | IANA; 校验下沉到 validate_log_timezone().
        "logTimezone",
        "wiki",
        "version",
        # Wave 3 P2-9 (2026-08-14): 编排执行参数段。
        "orch",
        # 2026-10-21: LLM 自动重试参数 — 前端用户配置必须透传, 否则 sanitizeForBackend
        # 丢弃后后端永远用默认值 (max_attempts=3, base_delay=1.0, max_delay=15.0).
        "llmRetryMaxAttempts",
        "llmRetryBaseDelayS",
        "llmRetryMaxDelayS",
        # 2026-10-30: 自动重试总时长预算（秒）— 0 = 不限；UI 可配置，
        # _retry_settings() 函数式读取，改后下一次 LLM 请求即生效。
        "llmRetryTotalBudgetS",
        # 2026-10-22: 整轮任务 wall-clock 上限（秒）— 0 = 不限；函数式读取
        # 立即生效，无须重启后端。前端 DEFAULT_SETTINGS = 1800。
        "llmTotalTimeoutS",
        # 2026-10-28: LLM 代理上游超时（秒）。backend/api/llm_proxy_routes.py
        # 函数式读取，改后下一个请求即生效。
        "llmProxyTimeoutS",
        # Task 9 (2026-10-28): 智能路由模式 {'mode': 'auto' | 'manual'}。
        # 缺省 = manual（现行为）。llm_factory.load_routing_config() 读取。
        "routing",
        # 2026-10-27: 会话标题生成专用模型 id（顶层扁平键，与 chatModel 同风格）。
        # 值为模型 id 字符串；留空表示回退到聊天模型。后端
        # title_model_factory.load_title_llm_config() 读取此键。
        "titleModelId",
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
        # DEPRECATED 2027-01-28: discoveredModels 仅作离线回退；
        # catalog-first 读取方应改用 model-catalog (Task 12)，本键仍留在白名单以兼容旧数据.
        "discoveredModels",
        "lastDiscoveredAt",
        # 2026-11-03: 思考过程参数 —— per-endpoint 配置, 前端读到后放进
        # ChatConfig 随聊天请求透传上游 LLM。
        # - reasoningEffort: 'low' | 'medium' | 'high' (OpenAI reasoning_effort)
        # - thinkingBudget: int (Anthropic thinking.budget_tokens / DeepSeek thinking_budget)
        # 两者缺省 = 不发送该键 (上游不进入思考模式)。
        "reasoningEffort",
        "thinkingBudget",
        # 2026-11-08: Rescue CLI 写入时间戳 —— 端点最后一次被救援工具修改 apiKey
        # 的时间（毫秒 Unix epoch）。前端 ``restoreRedactedApiKeys`` 用它与 localStorage
        # 缓存时间戳比较，避免远程已更新的 key 被旧本地缓存覆盖（§144 内网救援
        # 工具）。非救援工具路径不写此字段，缺省为 null。
        "apiKeyUpdatedAt",
        # 2026-09-18 (端点限额): 可选嵌套配额对象 {dailyTokens, monthlyBudgetUsd}.
        "quota",
    }
)
# EndpointConfig.quota 子层白名单 (2026-09-18). 值语义校验见 validate_quota.
LEGAL_QUOTA_KEYS: FrozenSet[str] = frozenset(
    {
        "dailyTokens",
        "monthlyBudgetUsd",
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
        "ttsModel",
        "asrModel",
        "imageGenModel",
    }
)
# orch 段 (OrchSettings). 白名单必须与前端 OrchSettings interface
# (src/entities/setting/types.ts DEFAULT_ORCH_SETTINGS) 逐键同步。
# 2026-09 修复: 补齐 worktreeIsolation / subagentApprovalMode / runTokenBudget;
# RD15 (round25) 透出 runWallClockLimitMinutes / subagentTaskTimeoutS /
# maxRetryOfChains 三键后白名单未跟, 导致编排段任一保存都 400 且被前端
# 静默吞掉——再次复发同款事故。
LEGAL_ORCH_KEYS: FrozenSet[str] = frozenset(
    {
        "maxConcurrentSubagents",
        "maxAggregateChars",
        "maxSubagentResultChars",
        "maxRetries",
        "maxLaneIterations",
        "maxSubagentIterations",
        "worktreeIsolation",
        "subagentApprovalMode",
        "runTokenBudget",
        "scratchRoot",
        # Round 1/3 (2026-09-19) 计划前置旋钮 —— 白名单缺失会让设置页编排段
        # 任一保存 400 invalid_settings_shape（round26 同款回归,前端静默吞错）。
        "planPreflightEnabled",
        "planScoutEnabled",
        "runWallClockLimitMinutes",
        "subagentTaskTimeoutS",
        "maxRetryOfChains",
        # 2026-10-20 全局迭代上限 (0=按各 agent 分别设置)
        "maxIterations",
        # 2026-11-01: 动态迭代预算（P1 设置页暴露）。
        "dynamicBudgetEnabled",
        # 2026-11-04: 预算模式显式开关（auto | fixed），取代 maxIterations==25 哨兵。
        "budgetMode",
        "budgetSimple",
        "budgetMedium",
        "budgetComplex",
        "budgetLong",
        "budgetHardCap",
        "budgetMaxExtensions",
        # 2026-10-27: 单 run 工具调用上限 (已在 OrchSettings/UI/ALIASES, 白名单
        # 漏加 → 编排段任一保存 400) + 计划前置/Planner 迭代预算。
        "maxToolCallsPerRun",
        "maxScoutIterations",
        "maxPlannerIterations",
        # 2026-10-28: ask_user_question 工具的可配置限制。
        "maxConsecutiveUnansweredQuestions",
        "minOptionsPerQuestion",
        "maxOptionsPerQuestion",
        "maxClarifyQuestionsInPrompt",
        "maxClarifyQuestionsPerRound",
    }
)

# routing 段 (RoutingSettings). 2026-10-28 智能路由: 目前只有 ``mode``
# (``auto`` | ``manual``). 白名单必须与前端 ``RoutingSettings``
# (src/entities/setting/types.ts) 同步 —— 漏加会让设置页保存 400。
LEGAL_ROUTING_KEYS: FrozenSet[str] = frozenset({"mode"})

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
    if not isinstance(value, (dict, list)):  # noqa: UP038 — py38 运行时 isinstance 不支持 union
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

    endpoints = settings.get("endpoints")
    if endpoints is not None and not isinstance(endpoints, list):
        raise ValueError("endpoints must be a list")
    for i, ep in enumerate(endpoints or []):
        if not isinstance(ep, dict):
            raise ValueError(f"endpoints[{i}] is not a dict")
        bad_ep = [k for k in ep if k not in LEGAL_ENDPOINT_KEYS]
        if bad_ep:
            raise ValueError(
                f"unknown endpoint field {bad_ep[0]!r} at endpoints[{i}]; "
                f"allowed: {sorted(LEGAL_ENDPOINT_KEYS)}"
            )
        discovered_models = ep.get("discoveredModels")
        if discovered_models is not None and not isinstance(discovered_models, list):
            raise ValueError(f"endpoints[{i}].discoveredModels must be a list")
        quota = ep.get("quota")
        if quota is not None and not isinstance(quota, dict):
            raise ValueError(f"endpoints[{i}].quota must be an object")
        if isinstance(quota, dict):
            bad_quota = [k for k in quota if k not in LEGAL_QUOTA_KEYS]
            if bad_quota:
                raise ValueError(
                    f"unknown quota field {bad_quota[0]!r} at endpoints[{i}].quota; "
                    f"allowed: {sorted(LEGAL_QUOTA_KEYS)}"
                )
        for j, model in enumerate(discovered_models or []):
            if not isinstance(model, dict):
                raise ValueError(f"endpoints[{i}].discoveredModels[{j}] is not a dict")
            bad = [k for k in model if k not in LEGAL_DISCOVERED_MODEL_KEYS]
            if bad:
                raise ValueError(
                    f"unknown discovered-model field {bad[0]!r} "
                    f"at endpoints[{i}].discoveredModels[{j}]; "
                    f"allowed: {sorted(LEGAL_DISCOVERED_MODEL_KEYS)}"
                )

    ms = settings.get("modelSelections")
    if ms is not None and not isinstance(ms, dict):
        raise ValueError("modelSelections must be a dict")
    ms = ms or {}
    # 校验 modelSelections 子对象 keys (chatModel/visionModel/embeddingModel);
    # 未知 key 会污染 DB, 应拒收. Contract test 保证此处与 AppSettings 同步.
    bad_ms_keys = [k for k in ms if k not in LEGAL_MODEL_SELECTIONS_KEYS]
    if bad_ms_keys:
        raise ValueError(
            f"unknown model-selections field {bad_ms_keys[0]!r}; "
            f"allowed: {sorted(LEGAL_MODEL_SELECTIONS_KEYS)}"
        )
    for sel_key in ("chatModel", "visionModel", "embeddingModel"):
        sel = ms.get(sel_key)
        if sel is not None and not isinstance(sel, dict):
            raise ValueError(f"modelSelections.{sel_key} is not a dict")
        sel = sel or {}
        bad = [k for k in sel if k not in LEGAL_MODEL_SELECTION_KEYS]
        if bad:
            raise ValueError(
                f"unknown model-selection field {bad[0]!r} "
                f"in modelSelections.{sel_key}; "
                f"allowed: {sorted(LEGAL_MODEL_SELECTION_KEYS)}"
            )

    wiki = settings.get("wiki")
    if wiki is not None and not isinstance(wiki, dict):
        raise ValueError("wiki must be a dict")
    wiki = wiki or {}
    bad_wiki = [k for k in wiki if k not in LEGAL_WIKI_KEYS]
    if bad_wiki:
        raise ValueError(
            f"unknown wiki field {bad_wiki[0]!r}; " f"allowed: {sorted(LEGAL_WIKI_KEYS)}"
        )

    orch = settings.get("orch")
    if orch is not None and not isinstance(orch, dict):
        raise ValueError("orch is not a dict")
    orch = orch or {}
    bad_orch = [k for k in orch if k not in LEGAL_ORCH_KEYS]
    if bad_orch:
        raise ValueError(
            f"unknown orch field {bad_orch[0]!r}; " f"allowed: {sorted(LEGAL_ORCH_KEYS)}"
        )

    routing = settings.get("routing")
    if routing is not None and not isinstance(routing, dict):
        raise ValueError("routing is not a dict")
    routing = routing or {}
    bad_routing = [k for k in routing if k not in LEGAL_ROUTING_KEYS]
    if bad_routing:
        raise ValueError(
            f"unknown routing field {bad_routing[0]!r}; "
            f"allowed: {sorted(LEGAL_ROUTING_KEYS)}"
        )


# Credential names are matched against a normalized spelling so legacy
# aliases such as ``api_key`` and ``API-KEY`` have the same treatment as
# ``apiKey``.  These are intentionally anchored rules: substring matching
# would redact ordinary settings such as ``tokenization`` or ``passwordPolicy``.
_SECRET_KEY_NAMES = frozenset({"apikey", "authorization", "token", "secret", "password"})
_SECRET_SUFFIXES = frozenset({"password", "secret", "token", "apikey"})
# A bare ``key`` suffix is too broad (for example, ``publicKey`` is not a
# credential).  Restrict it to prefixes whose names unambiguously describe a
# private credential; broader suffix rules above remain safe and auditable.
_PRIVATE_KEY_PREFIXES = frozenset({"api", "private", "secret"})


def _is_secret_key(key: Any) -> bool:
    """Return whether *key* names a credential in a settings object.

    Names are compared as lowercase alphanumeric strings, making common
    snake_case, kebab-case, and acronym aliases equivalent.  Exact names and
    credential suffixes are matched as whole names only; the narrow ``*key``
    rule prevents false positives for ordinary configuration fields.
    """
    if not isinstance(key, str):
        return False
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    if normalized in _SECRET_KEY_NAMES:
        return True
    # ``hasApiKey`` is response metadata, not the credential itself; retain it
    # so repeated redaction remains idempotent and endpoint state is preserved.
    if normalized in {"hasapikey", "haskey"}:
        return False
    if any(normalized.endswith(suffix) for suffix in _SECRET_SUFFIXES):
        return True
    return normalized.endswith("key") and any(
        normalized == f"{prefix}key" for prefix in _PRIVATE_KEY_PREFIXES
    )


def parse_app_settings_object(value: Any) -> Dict[str, Any]:
    """Parse an ``app_settings`` preference and require a JSON object.

    This is intentionally separate from :func:`redact_secrets_json`: the
    latter is a defensive response helper whose non-string/scalar contract is
    used by generic callers, while preference PUT must reject invalid data
    before it reaches storage.
    """
    import json as _json

    try:
        parsed = _json.loads(value)
    except (ValueError, TypeError):
        raise ValueError("app_settings must be a JSON object") from None
    if not isinstance(parsed, dict):
        raise ValueError("app_settings must be a JSON object")
    return parsed


def redact_secrets(settings: Any) -> Any:
    """剥离 settings 中的敏感字段 (endpoint.apiKey), 替换为 ``hasApiKey`` 标记。

    背景 (2026-08-26):
    - 真实 Electron 验证中发现 GET /api/v1/settings 明文回传端点 apiKey,
      导致 settingsClient.getSettings() 把真实凭据写入 React state / localStorage
      / 日志 / IPC 响应, 不符合 OWASP A02:2021 (Cryptographic Failures)。
    - 修复: GET 响应里 apiKey 字段统一置空 (或 None), 同时增加
      ``hasApiKey: bool`` 标记供前端识别 "该端点是否配置了真实 key"。
    - 真实 key 仅在 PUT 接收并持久化到 SQLite preferences, 不再以任何形式
      经 HTTP response / IPC 返回。

    Args:
        settings: 已经经过 ``to_camel`` + ``strip_unknown_fields`` 的 settings dict.
            可以为 None, 非 dict, 或 dict — 全部走安全路径.

    Returns:
        与输入同构的新 dict, 但 endpoint.apiKey 被剥离并标记 hasApiKey.
    """
    if isinstance(settings, list):
        return [redact_secrets(item) for item in settings]
    if not isinstance(settings, dict):
        return settings

    out: Dict[Any, Any] = {}
    for key, value in settings.items():
        out[key] = "" if _is_secret_key(key) else redact_secrets(value)

    endpoints = settings.get("endpoints")
    if isinstance(endpoints, list):
        cleaned: List[Any] = []
        for ep in endpoints:
            if not isinstance(ep, dict):
                cleaned.append(redact_secrets(ep))
                continue
            new_ep = redact_secrets(ep)
            original_key = ep.get("apiKey")
            existing_flag = new_ep.get("hasApiKey")
            # 幂等性 (2026-08-26): 若输入已带 hasApiKey 标记 (即二次过
            # canonicalizer, 如 preference GET round-trip / cache replay),
            # 保留原标志 — 不从已被清空的 apiKey 重新计算, 否则 ``True``
            # 会翻成 ``False``, 让前端误以为用户从未设置过 key, 下次启动
            # 后 deepMerge remote-wins 用 ``""`` 覆盖本地真实 key。
            if isinstance(existing_flag, bool):
                has_key = existing_flag
            else:
                has_key = isinstance(original_key, str) and original_key != ""
            new_ep["apiKey"] = ""
            new_ep["hasApiKey"] = has_key
            cleaned.append(new_ep)
        out["endpoints"] = cleaned

    return out


def redact_secrets_json(value: Any) -> Any:
    """``redact_secrets`` 的 JSON 字符串版本 — 适用于 preference GET 返回字符串 value。

    当 preference key='app_settings' 且 value 是合法 JSON 字符串时, 解析 +
    脱敏 + 重新序列化。非 JSON / 非 dict 直接原样返回。
    """
    if not isinstance(value, str):
        return value
    try:
        import json as _json

        parsed = _json.loads(value)
    except (ValueError, TypeError):
        # Never return malformed input: it may contain an unparseable credential.
        return "{}"
    if not isinstance(parsed, dict):
        # Preference GET is a settings-object response.  Historical rows may
        # contain valid JSON scalars or lists; never echo them, since a scalar
        # string can itself be a credential.
        return "{}"
    redacted = redact_secrets(parsed)
    import json as _json

    return _json.dumps(redacted, ensure_ascii=False)


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
    - wiki: ``LEGAL_WIKI_KEYS`` / orch: ``LEGAL_ORCH_KEYS`` / routing: ``LEGAL_ROUTING_KEYS``
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
            quota = clean_ep.get("quota")
            if isinstance(quota, dict):
                clean_ep["quota"] = {
                    k: v for k, v in quota.items() if k in LEGAL_QUOTA_KEYS
                }
            models = clean_ep.get("discoveredModels")
            if isinstance(models, list):
                clean_models: List[Any] = []
                for model in models:
                    if not isinstance(model, dict):
                        # Preserve malformed items so validation exposes the bad
                        # persisted data instead of silently dropping it.
                        clean_models.append(model)
                        continue
                    clean_models.append(
                        {k: v for k, v in model.items() if k in LEGAL_DISCOVERED_MODEL_KEYS}
                    )
                clean_ep["discoveredModels"] = clean_models
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

    routing = out.get("routing")
    if isinstance(routing, dict):
        out["routing"] = {k: v for k, v in routing.items() if k in LEGAL_ROUTING_KEYS}

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
# 日志时区 (2026-09-17): 允许 'UTC' | 'local' | IANA 时区字符串.
# 'UTC' 保持历史行为; 'local' 用系统本地时区; 其他走 zoneinfo.
DEFAULT_LOG_TIMEZONE = "UTC"
# 日志时区保留关键字 (非 IANA, 不需要 zoneinfo 校验).
LOG_TIMEZONE_RESERVED: FrozenSet[str] = frozenset({"UTC", "utc", "local"})


def validate_log_timezone(value: Any) -> Any:
    """日志时区校验 (2026-09-17).

    允许的值:
    - ``None`` / 空字符串: 视为"未设置", 由 ``_migrate_default_log_timezone`` 兜底补 ``DEFAULT_LOG_TIMEZONE`` (``UTC``).
    - ``'UTC'`` / ``'utc'``: 关键字, 走 UTC, 不走 zoneinfo.
    - ``'local'``: 关键字, 走系统本地时区, 不走 zoneinfo.
    - 其他字符串: IANA 时区, 用 ``zoneinfo`` 校验 (Py3.9+ 标准库, Py3.8 走 backports.zoneinfo).

    非法字符串抛 ``ValueError`` —— FastAPI 通过 handler 翻译成 422.
    """
    if value is None or value == "":
        return value
    if not isinstance(value, str):
        raise ValueError(
            f"logTimezone must be a string, got {type(value).__name__}: {value!r}"
        )
    if value in LOG_TIMEZONE_RESERVED:
        # 标准化 'utc' → 'UTC' (大小写不敏感, 写入 DB 时用 'UTC' 大写)
        if value == "utc":
            return "UTC"
        if value == "local":
            return "local"
        return value
    try:
        # 延迟导入 zoneinfo — Python 3.9+ 标准库; Win7 走 backports.zoneinfo.
        from zoneinfo import ZoneInfo  # py38-ok except ImportError 守卫 + backports 兜底
    except ImportError:  # pragma: no cover — py3.9+ always has zoneinfo
        try:
            from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]
        except ImportError as exc:  # pragma: no cover — backports is dep
            raise ValueError(
                "logTimezone validation requires zoneinfo or backports.zoneinfo"
            ) from exc

    try:
        ZoneInfo(value)
    except Exception as exc:  # ZoneInfoNotFoundError + 其它解析异常
        raise ValueError(f"invalid logTimezone {value!r}: {exc}") from exc
    return value


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
        from zoneinfo import ZoneInfo  # py38-ok except ImportError 守卫 + backports 兜底
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


# 2026-11-03: Endpoint.reasoningEffort 合法值 (与前端 types.ts 的
# 'low' | 'medium' | 'high' | null 同步). 透传给上游 OpenAI ``reasoning_effort``.
LEGAL_REASONING_EFFORTS: FrozenSet[str] = frozenset({"low", "medium", "high"})


def validate_reasoning_effort(value: Any) -> Any:
    """Endpoint.reasoningEffort 枚举校验.

    - ``None`` / 空字符串视为"未设置" —— 不发送该键, 上游不进入思考模式.
    - 非字符串 / 不在白名单 → ValueError (handler 翻译 422).
    """
    if value is None or value == "":
        return value
    if not isinstance(value, str):
        raise ValueError(
            f"reasoningEffort must be a string, got {type(value).__name__}"
        )
    if value not in LEGAL_REASONING_EFFORTS:
        raise ValueError(
            f"invalid reasoningEffort {value!r}; "
            f"allowed: {sorted(LEGAL_REASONING_EFFORTS)}"
        )
    return value


def validate_thinking_budget(value: Any) -> Any:
    """Endpoint.thinkingBudget 整数校验.

    - ``None`` 视为"未设置" —— 不发送该键, 上游用默认思考预算.
    - 非整数 / 小于 -1 → ValueError (handler 翻译 422).
    - ``0`` = 关闭思考, ``-1`` = 动态预算 (与 ``LLMConfig.thinking_budget`` 语义一致).
    """
    if value is None:
        return value
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            f"thinkingBudget must be an integer, got {type(value).__name__}"
        )
    if value < -1:
        raise ValueError(f"thinkingBudget must be >= -1, got {value}")
    return value


def validate_quota(value: Any) -> Any:
    """Endpoint.quota 值语义校验 (2026-09-18 端点限额).

    - ``None`` 视为"未配置限额", 直接返回。
    - 必须是 dict; 每个已知字段值必须是 None 或非负数字 (bool 拒收)。
    - 未知键抛 ValueError (白名单最终由 validate_settings_shape 兜底)。
    """
    if value is None:
        return value
    if not isinstance(value, dict):
        raise ValueError(f"quota must be an object, got {type(value).__name__}")
    for k, v in value.items():
        if k not in LEGAL_QUOTA_KEYS:
            raise ValueError(f"unknown quota field {k!r}; allowed: {sorted(LEGAL_QUOTA_KEYS)}")
        if v is None:
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
            raise ValueError(f"quota.{k} must be a non-negative number, got {v!r}")
    return value


def validate_api_key_updated_at(value: Any) -> Any:
    """Endpoint.apiKeyUpdatedAt 校验 (2026-11-08 内网救援工具).

    - ``None`` 视为"未设置" (默认), 直接返回。
    - 必须是非负整数 (毫秒 Unix epoch)。bool 拒收。
    """
    if value is None:
        return value
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            f"apiKeyUpdatedAt must be an integer (ms epoch), got {type(value).__name__}"
        )
    if value < 0:
        raise ValueError(f"apiKeyUpdatedAt must be >= 0, got {value}")
    return value


def validate_local_model_path(value: Any, platform: Optional[str] = None) -> Any:
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


def validate_endpoint_payload(ep: Any, platform: Optional[str] = None) -> Any:
    """单条 endpoint dict 的全部字段语义校验 (protocol / localModelPath /
    reasoningEffort / thinkingBudget).

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
    # 2026-11-03: 思考过程参数 —— 值域校验, 防止非法值被原样透传给上游。
    validate_reasoning_effort(ep.get("reasoningEffort"))
    validate_thinking_budget(ep.get("thinkingBudget"))
    validate_quota(ep.get("quota"))
    # 2026-11-08: 内网救援工具写入时间戳 (ms epoch 或 null)
    validate_api_key_updated_at(ep.get("apiKeyUpdatedAt"))
    return ep


def validate_settings_payload(
    settings: Any,
    platform: Optional[str] = None,
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
    # 日志时区 (2026-09-17): 与顶层 timezone 同样的校验路径, 但允许 'UTC' | 'local' 关键字.
    validate_log_timezone(settings.get("logTimezone"))
    endpoints = settings.get("endpoints")
    if isinstance(endpoints, list):
        for i, ep in enumerate(endpoints):
            try:
                validate_endpoint_payload(ep, platform=platform)
            except ValueError as exc:
                # 重新包装, 带上 endpoints 索引, 便于用户定位
                raise ValueError(f"endpoints[{i}]: {exc}") from exc


def validate_retry_settings_payload(settings: Any, effective_settings: Any = None) -> None:
    """校验本次提交的 LLM 重试参数取值域（只查本次 payload，不查存量）。

    刻意不并入 ``validate_settings_payload`` —— 后者拿到的是与存量合并后的
    整棵树，历史存量的非法值会把用户锁死在设置页外（改一个无关字段也
    提交不了）。取值域定义见 ``backend.core.retry_defaults.RETRY_RANGES``，
    与运行时回退共用同一份定义。

    ``effective_settings`` 是合并后的整棵树，仅用于 ``base_delay <= max_delay``
    交叉校验的另一半：用户只改基数时也能发现它与存量上限冲突。

    Raises:
        RetrySettingsValueError: 越界 / 类型非法（``.field`` 指出错的键）。
    """
    if not isinstance(settings, dict):
        return
    from backend.core.retry_defaults import validate_retry_values

    validate_retry_values(settings, effective_settings)


def classify_settings_validation_error(exc: ValueError) -> str:
    """Return a non-sensitive field category for a settings validation error.

    Validation exceptions remain detailed for internal callers; HTTP handlers
    must not serialize those messages because they can contain user-controlled
    protocols, paths, or other secrets.

    Exceptions carrying an explicit ``field`` attribute (e.g. retry range
    violations) report that field name directly — it is a fixed literal from
    our own code, never user input.
    """
    field = getattr(exc, "field", None)
    if isinstance(field, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", field):
        return field
    message = str(exc)
    for field in (
        "timezone",
        "logTimezone",
        "protocol",
        "localModelPath",
        "reasoningEffort",
        "thinkingBudget",
    ):
        if field in message:
            return field
    return "value"


def classify_settings_shape_error(exc: ValueError) -> str:
    """Return a coarse, non-sensitive category for a shape validation error."""
    message = str(exc)
    if "top-level" in message:
        return "top_level"
    if "endpoints" in message:
        return "endpoints"
    if "model-selection" in message or "modelSelections" in message:
        return "modelSelections"
    if "wiki" in message:
        return "wiki"
    if "orch" in message:
        return "orch"
    return "settings"


def classify_settings_shape_field(exc: ValueError) -> str:
    """Return the offending schema field name without exposing its value."""
    message = str(exc)
    match = re.search(
        r"unknown (?:top-level|endpoint|discovered-model|model-selections|model-selection|wiki|orch) field '([^']+)'",
        message,
    )
    if match and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", match.group(1)):
        return match.group(1)
    return classify_settings_shape_error(exc)


def preserve_endpoint_api_keys(
    merged: Dict[Any, Any], existing: Dict[str, Any]
) -> Dict[Any, Any]:
    """Keep stored endpoint apiKeys when a PUT blanks them.

    GET responses redact ``apiKey`` to ``""`` (``hasApiKey`` marks presence),
    so a client that edits any other endpoint field round-trips an empty
    apiKey. Treat empty/missing as "unchanged" here; otherwise the redacted
    round-trip would erase the credential from the database.
    """
    if not isinstance(merged, dict) or not isinstance(existing, dict):
        return merged
    merged_eps = merged.get("endpoints")
    existing_eps = existing.get("endpoints")
    if not isinstance(merged_eps, list) or not isinstance(existing_eps, list):
        return merged
    stored: Dict[Any, str] = {}
    for ep in existing_eps:
        if not isinstance(ep, dict):
            continue
        key = ep.get("apiKey")
        if isinstance(key, str) and key.strip():
            stored[ep.get("id")] = key
    if not stored:
        return merged
    preserved: List[Any] = []
    changed = False
    for ep in merged_eps:
        if not isinstance(ep, dict):
            preserved.append(ep)
            continue
        key = ep.get("apiKey")
        if (key is None or key == "") and ep.get("id") in stored:
            preserved.append({**ep, "apiKey": stored[ep.get("id")]})
            changed = True
        else:
            preserved.append(ep)
    if not changed:
        return merged
    return {**merged, "endpoints": preserved}
