"""Sage 自身配置查询与修改工具 (read_sage_config / update_sage_config)。

提供运行时自省能力：
- ReadSageConfigTool: 允许 Agent 准确自省系统当前配置（orch 编排上限、各 Agent 迭代上限、通用设置等），
  敏感字段（如 apiKey）强制脱敏。
- UpdateSageConfigTool: 允许 Agent 在严格白名单与参数边界下修改部分配置（如调整迭代上限），
  声明为 RiskClass.WRITE_LOCAL，受权限审批控制。
"""
from __future__ import annotations

import copy
import logging
from typing import Any, Dict, List, Optional, Tuple

from backend.data.agent_repo import AgentRepository
from backend.data.settings_canonicalizer import validate_settings_payload
from backend.data.settings_repo import SettingsRepository
from backend.domain.risk import RiskClass
from backend.domain.tool_policy import ToolPolicy
from backend.tools.base import BaseTool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)

# update_sage_config 允许修改的字段白名单（严格限制）
_ALLOWED_ORCH_FIELDS = {
    "maxConcurrentSubagents",
    "maxAggregateChars",
    "maxSubagentResultChars",
    "maxRetries",
    "maxLaneIterations",
    "maxSubagentIterations",
    "runTokenBudget",
    "subagentApprovalMode",
}

_ALLOWED_AGENT_FIELDS = {
    "max_iterations",
    "temperature",
    "system_prompt",
    "description",
    "name",
    "enabled",
}

_ALLOWED_GENERAL_FIELDS = {
    "temperature",
    "streaming",
    "autoMemory",
    "confirmDelete",
    "timezone",
    "logTimezone",
    "maxContext",
    "autoContext",
    # P119 Config Advisor (Phase 1.2): LLM 重试 / 超时字段 ——
    # 让 LLM 能基于诊断数据调整自身可靠性相关参数
    "llmRetryMaxAttempts",
    "llmRetryBaseDelayS",
    "llmRetryMaxDelayS",
    "llmTotalTimeoutS",
    # 2026-10-27: 会话标题生成专用模型 id —— 空串表示回退到聊天模型。
    "titleModelId",
}

# 2026-10-28: endpoint CRUD 白名单（与 settings_canonicalizer.LEGAL_ENDPOINT_KEYS 对齐）
_ALLOWED_ENDPOINT_FIELDS = {
    "id",
    "name",
    "baseUrl",
    "apiKey",
    "protocol",
    "modelId",
    "localModelPath",
    "discoveredModels",
    "lastDiscoveredAt",
}

# 2026-10-28: model_selection 更新白名单（与 settings_canonicalizer.LEGAL_MODEL_SELECTION_KEYS 对齐）
_ALLOWED_MODEL_SELECTION_FIELDS = {"endpointId", "modelId"}

_VALID_READ_SECTIONS = {"all", "orch", "agents", "general", "model_selections", "endpoints"}
_ORCH_INTEGER_RANGES = {
    "maxConcurrentSubagents": (1, 32),
    "maxAggregateChars": (1, 10_000_000),
    "maxSubagentResultChars": (1, 10_000_000),
    "maxRetries": (0, 50),
    "maxLaneIterations": (1, 100),
    "maxSubagentIterations": (1, 100),
    "runTokenBudget": (0, 100_000_000),
}


def _prepare_settings_update(
    current_settings: Any,
    updates: Dict[str, Any],
    target: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Return a validated copy of settings before persisting an update."""
    if not isinstance(current_settings, dict):
        return None, "当前 app_settings 不是有效的对象"

    candidate = copy.deepcopy(current_settings)
    if target == "orch":
        orch = candidate.get("orch", {})
        if not isinstance(orch, dict):
            return None, "当前 orch 配置不是有效的对象"
        candidate["orch"] = {**orch, **updates}
    else:
        candidate.update(updates)

    try:
        validate_settings_payload(candidate)
    except ValueError as exc:
        return None, f"配置校验失败: {exc}"
    return candidate, None


def _validate_orch_updates(updates: Dict[str, Any]) -> Optional[str]:
    for key, value in updates.items():
        if key in _ORCH_INTEGER_RANGES:
            if isinstance(value, bool) or not isinstance(value, int):
                return f"{key} 必须是整数，收到: {value!r}"
            lower, upper = _ORCH_INTEGER_RANGES[key]
            if not lower <= value <= upper:
                return f"{key} 必须在 {lower} 到 {upper} 之间，收到: {value!r}"
        elif key == "subagentApprovalMode" and value not in {"ask", "auto"}:
            return "subagentApprovalMode 必须是 'ask' 或 'auto'"
    return None


def _validate_general_updates(updates: Dict[str, Any]) -> Optional[str]:
    if "temperature" in updates:
        value = updates["temperature"]
        if isinstance(value, bool) or not isinstance(value, (int, float)):  # noqa: UP038 — 保持 Py3.8 兼容
            return f"temperature 必须是 0 到 2 之间的数字，收到: {value!r}"
        if not 0 <= value <= 2:
            return f"temperature 必须是 0 到 2 之间的数字，收到: {value!r}"
    for key in {"streaming", "autoMemory", "confirmDelete", "autoContext"} & set(updates):
        if not isinstance(updates[key], bool):
            return f"{key} 必须是布尔值，收到: {updates[key]!r}"
    for key in {"maxContext"} & set(updates):
        value = updates[key]
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 10_000_000:
            return f"{key} 必须是 1 到 10000000 之间的整数，收到: {value!r}"
    # P119 Config Advisor (Phase 1.2): LLM 重试 / 超时字段类型与范围校验
    _llm_retry_field_errors: List[str] = []
    if "llmRetryMaxAttempts" in updates:
        v = updates["llmRetryMaxAttempts"]
        if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 20:
            _llm_retry_field_errors.append(
                f"llmRetryMaxAttempts 必须是 0 到 20 之间的整数，收到: {v!r}"
            )
    for k in ("llmRetryBaseDelayS", "llmRetryMaxDelayS"):
        if k in updates:
            v = updates[k]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 < v <= 600:  # noqa: UP038
                _llm_retry_field_errors.append(
                    f"{k} 必须是大于 0 且不超过 600 的数字，收到: {v!r}"
                )
    if "llmTotalTimeoutS" in updates:
        v = updates["llmTotalTimeoutS"]
        if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 86400:
            _llm_retry_field_errors.append(
                f"llmTotalTimeoutS 必须是 0 到 86400 之间的整数（0=不限），收到: {v!r}"
            )
    if "llmProxyTimeoutS" in updates:
        v = updates["llmProxyTimeoutS"]
        if isinstance(v, bool) or not isinstance(v, int) or not 5 <= v <= 1800:
            _llm_retry_field_errors.append(
                f"llmProxyTimeoutS 必须是 5 到 1800 之间的整数（秒），收到: {v!r}"
            )
    # 跨字段一致性：baseDelayS 不能大于 maxDelayS
    if (
        "llmRetryBaseDelayS" in updates
        and "llmRetryMaxDelayS" in updates
        and updates["llmRetryBaseDelayS"] > updates["llmRetryMaxDelayS"]
    ):
        _llm_retry_field_errors.append(
            "llmRetryBaseDelayS 不能大于 llmRetryMaxDelayS"
        )
    if _llm_retry_field_errors:
        return "; ".join(_llm_retry_field_errors)
    return _validate_title_model_id(updates)


def _validate_title_model_id(updates: Dict[str, Any]) -> Optional[str]:
    """会话标题专用模型 id —— 必须是字符串；空串 = 回退到聊天模型。"""
    if "titleModelId" not in updates:
        return None
    v = updates["titleModelId"]
    if not isinstance(v, str):
        return f"titleModelId 必须是字符串，收到: {v!r}"
    if len(v) > 200:
        return f"titleModelId 长度不能超过 200，收到: {len(v)}"
    return None


# 2026-10-28: endpoint 和 model_selection 验证函数


def _validate_endpoint_updates(updates: Dict[str, Any]) -> Optional[str]:  # noqa: PLR0911
    """验证 endpoint 字段（create/update 时调用）。"""
    # protocol 枚举校验
    if "protocol" in updates:
        protocol = updates["protocol"]
        valid_protocols = {"openai-compatible", "anthropic", "gemini", "ollama"}
        if protocol not in valid_protocols:
            return f"protocol 必须是 {sorted(valid_protocols)} 之一，收到: {protocol!r}"
    # baseUrl 格式校验（简单检查是否为字符串且非空）
    if "baseUrl" in updates:
        base_url = updates["baseUrl"]
        if not isinstance(base_url, str) or not base_url.strip():
            return "baseUrl 必须是非空字符串"
        # 简单 URL 格式检查
        if not base_url.startswith(("http://", "https://")):
            return "baseUrl 必须以 http:// 或 https:// 开头"
    # apiKey 类型校验（允许空字符串或 None）
    if "apiKey" in updates:
        api_key = updates["apiKey"]
        if api_key is not None and not isinstance(api_key, str):
            return "apiKey 必须是字符串或 null"
    # id 类型校验
    if "id" in updates:
        ep_id = updates["id"]
        if not isinstance(ep_id, str) or not ep_id.strip():
            return "id 必须是非空字符串"
    # name 类型校验
    if "name" in updates:
        name = updates["name"]
        if name is not None and not isinstance(name, str):
            return "name 必须是字符串或 null"
    return None


def _validate_model_selection_updates(task_type: str, updates: Dict[str, Any]) -> Optional[str]:
    """验证 model_selection 字段。"""
    # task_type 枚举校验
    valid_task_types = {"chatModel", "visionModel", "embeddingModel", "ttsModel", "asrModel", "imageGenModel"}
    if task_type not in valid_task_types:
        return f"task_type 必须是 {sorted(valid_task_types)} 之一，收到: {task_type!r}"
    # endpointId 类型校验
    if "endpointId" in updates:
        endpoint_id = updates["endpointId"]
        if endpoint_id is not None and not isinstance(endpoint_id, str):
            return "endpointId 必须是字符串或 null"
    # modelId 类型校验
    if "modelId" in updates:
        model_id = updates["modelId"]
        if model_id is not None and not isinstance(model_id, str):
            return "modelId 必须是字符串或 null"
    return None


def _redact_settings(data: Any) -> Any:
    """递归脱敏敏感信息（apiKey/token 等）。"""
    if not isinstance(data, (dict, list)):  # noqa: UP038 — 保持 Py3.8 兼容
        return data
    if isinstance(data, list):
        return [_redact_settings(item) for item in data]
    out = {}
    for k, v in data.items():
        if k.lower() in {"apikey", "api_key", "secret", "token", "password"}:
            out[k] = "***"
        elif isinstance(v, (dict, list)):  # noqa: UP038 — 保持 Py3.8 兼容
            out[k] = _redact_settings(v)
        else:
            out[k] = v
    return out


class ReadSageConfigTool(BaseTool):
    """读取 Sage 运行时配置工具。"""

    risk: RiskClass = RiskClass.READ

    def __init__(self, policy: Optional[ToolPolicy] = None) -> None:
        super().__init__(policy=policy)

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="read_sage_config",
            description=(
                "查询 Sage 系统的实际当前配置与运行参数，包括编排迭代上限（maxLaneIterations / "
                "maxSubagentIterations）、各智能体（primary, coder, reviewer, writer 等）"
                "的迭代上限与设定、通用设置、API 端点列表等。敏感凭证已自动脱敏。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "section": {
                        "type": "string",
                        "enum": ["all", "orch", "agents", "general", "model_selections", "endpoints"],
                        "description": (
                            "要查询的配置分类：\n"
                            "- 'orch': 编排参数（泳道迭代上限、子代理迭代上限、并发上限等）\n"
                            "- 'agents': 所有智能体档案列表（含每个智能体的最大迭代步数、角色与提示词）\n"
                            "- 'general': 通用应用设置（流式、记忆、温度、时区等）\n"
                            "- 'model_selections': 各任务当前绑定的模型配置\n"
                            "- 'endpoints': API 端点列表（apiKey 已脱敏）\n"
                            "- 'all': 包含以上全部配置"
                        ),
                    }
                },
                "required": ["section"],
            },
        )

    def execute(self, section: str = "all", **kwargs: Any) -> ToolResult:
        if section not in _VALID_READ_SECTIONS:
            return ToolResult(
                success=False,
                error=f"不支持的 section: {section!r}，必须为 {sorted(_VALID_READ_SECTIONS)}",
            )
        try:
            raw_settings = SettingsRepository().get_json("app_settings") or {}
            clean_settings = _redact_settings(copy.deepcopy(raw_settings))

            result_data: Dict[str, Any] = {}
            summary_lines: List[str] = []

            if section in {"all", "orch"}:
                orch = clean_settings.get("orch", {})
                result_data["orch"] = orch
                summary_lines.append(
                    f"【编排参数 (orch)】Lane迭代上限={orch.get('maxLaneIterations', 8)}, "
                    f"子代理迭代上限={orch.get('maxSubagentIterations', 6)}, "
                    f"最大并发子代理={orch.get('maxConcurrentSubagents', 4)}, "
                    f"重试上限={orch.get('maxRetries', 2)}"
                )

            if section in {"all", "agents"}:
                agents = AgentRepository().list_all()
                clean_agents = _redact_settings(copy.deepcopy(agents))
                result_data["agents"] = clean_agents
                agent_summaries = [
                    f"{a.get('name', a.get('id'))}(id={a.get('id')}, "
                    f"max_iterations={a.get('max_iterations', 10)}, "
                    f"enabled={a.get('enabled', True)})"
                    for a in clean_agents
                ]
                summary_lines.append(
                    f"【智能体 (agents)】共 {len(clean_agents)} 个：{'; '.join(agent_summaries)}"
                )

            if section in {"all", "general"}:
                general = {
                    k: v
                    for k, v in clean_settings.items()
                    if k not in {"orch", "endpoints", "modelSelections"}
                }
                result_data["general"] = general
                summary_lines.append(f"【通用设置 (general)】{general}")

            if section in {"all", "model_selections"}:
                models = clean_settings.get("modelSelections", {})
                result_data["modelSelections"] = models
                summary_lines.append(f"【模型绑定 (modelSelections)】{models}")

            # 2026-10-28: 新增 endpoints section
            if section in {"all", "endpoints"}:
                endpoints = clean_settings.get("endpoints", [])
                result_data["endpoints"] = endpoints
                endpoint_summaries = [
                    f"{ep.get('name', 'N/A')}(id={ep.get('id')}, protocol={ep.get('protocol', 'N/A')})"
                    for ep in endpoints
                ]
                summary_lines.append(f"【API 端点 (endpoints)】共 {len(endpoints)} 个：{'; '.join(endpoint_summaries)}")

            if section == "all":
                result_data["settings"] = clean_settings

            summary_text = "\n".join(summary_lines)
            return ToolResult(
                success=True,
                content={
                    "section": section,
                    "summary": summary_text,
                    "data": result_data if section not in {"orch", "agents"} else result_data.get(section, result_data),
                },
                output=summary_text,
            )
        except Exception as exc:
            logger.exception("read_sage_config 执行异常: %s", exc)
            return ToolResult(success=False, error=f"读取系统配置失败: {exc}")


class UpdateSageConfigTool(BaseTool):
    """修改 Sage 系统配置工具。"""

    risk: RiskClass = RiskClass.WRITE_LOCAL

    def __init__(self, policy: Optional[ToolPolicy] = None) -> None:
        super().__init__(policy=policy)

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="update_sage_config",
            description=(
                "安全修改 Sage 自身的配置参数。支持修改：编排参数（orch）、智能体配置（agent）、"
                "通用设置（general）、API 端点（endpoint，CRUD）、模型绑定（model_selection）。"
                "受严格安全白名单保护，敏感凭证自动加密存储。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "enum": ["orch", "agent", "general", "endpoint", "model_selection"],
                        "description": (
                            "修改目标类型：\n"
                            "- 'orch': 编排参数（迭代上限、并发上限等）\n"
                            "- 'agent': 指定智能体属性（max_iterations, temperature 等）\n"
                            "- 'general': 全局设置（temperature, streaming, autoMemory 等）\n"
                            "- 'endpoint': API 端点 CRUD（需配合 action 参数）\n"
                            "- 'model_selection': 模型绑定（chatModel, visionModel 等）"
                        ),
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "当 target='agent' 时必填，指定智能体 ID（如 'primary', 'coder', 'reviewer', 'writer' 等）",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["list", "get", "create", "update", "delete"],
                        "description": "当 target='endpoint' 时必填，指定 CRUD 操作类型",
                    },
                    "endpoint_id": {
                        "type": "string",
                        "description": "当 target='endpoint' 且 action 为 get/update/delete 时必填",
                    },
                    "task_type": {
                        "type": "string",
                        "enum": ["chatModel", "visionModel", "embeddingModel", "ttsModel", "asrModel", "imageGenModel"],
                        "description": "当 target='model_selection' 时必填，指定任务类型",
                    },
                    "updates": {
                        "type": "object",
                        "description": (
                            "待更新的参数键值对：\n"
                            "- target='orch' 时允许: maxLaneIterations, maxSubagentIterations, maxConcurrentSubagents, maxRetries 等\n"
                            "- target='agent' 时允许: max_iterations (1~50), temperature, system_prompt, description 等\n"
                            "- target='general' 时允许: temperature, streaming, autoMemory, confirmDelete 等\n"
                            "- target='general' 时允许: titleModelId (会话标题专用模型 id，空串=回退聊天模型)\n"
                            "- target='endpoint' 且 action='create/update' 时允许: name, baseUrl, apiKey, protocol, modelId 等\n"
                            "- target='model_selection' 时允许: endpointId, modelId"
                        ),
                    },
                },
                "required": ["target"],
            },
        )

    def execute(  # noqa: PLR0911, PLR0912, PLR0915 — 目标分发与防御性拦截多出口
        self,
        target: str,
        updates: Optional[Dict[str, Any]] = None,
        agent_id: Optional[str] = None,
        action: Optional[str] = None,
        endpoint_id: Optional[str] = None,
        task_type: Optional[str] = None,
        **kwargs: Any,
    ) -> ToolResult:
        # endpoint 的 list/get/delete action 不需要 updates
        if target == "endpoint" and action in {"list", "get", "delete"}:
            pass  # 允许 updates 为空
        elif not isinstance(updates, dict) or not updates:
            return ToolResult(success=False, error="updates 必须为非空字典")

        try:
            # ===== 2026-10-28 新增：endpoint CRUD =====
            if target == "endpoint":
                return self._handle_endpoint_action(action, endpoint_id, updates or {})

            # ===== 2026-10-28 新增：model_selection 更新 =====
            if target == "model_selection":
                return self._handle_model_selection_update(task_type, updates)

            # ===== 原有 target: orch / agent / general =====
            if target == "orch":
                forbidden = set(updates.keys()) - _ALLOWED_ORCH_FIELDS
                if forbidden:
                    return ToolResult(
                        success=False,
                        error=f"禁止修改 orch 越权字段: {sorted(forbidden)}。仅允许: {sorted(_ALLOWED_ORCH_FIELDS)}",
                    )
                validation_error = _validate_orch_updates(updates)
                if validation_error:
                    return ToolResult(success=False, error=validation_error)

                repo = SettingsRepository()
                current_settings = repo.get_json("app_settings") or {}
                candidate, settings_error = _prepare_settings_update(
                    current_settings, updates, target="orch"
                )
                if settings_error:
                    return ToolResult(success=False, error=settings_error)
                repo.set_json("app_settings", candidate)

                return ToolResult(
                    success=True,
                    content={
                        "message": "成功更新编排设置 (orch)",
                        "target": "orch",
                        "updated_fields": updates,
                    },
                    output=f"已成功更新 orch 配置: {updates}",
                )

            elif target == "agent":
                if not agent_id:
                    return ToolResult(success=False, error="target 为 'agent' 时必须提供 agent_id")

                forbidden = set(updates.keys()) - _ALLOWED_AGENT_FIELDS
                if forbidden:
                    return ToolResult(
                        success=False,
                        error=f"禁止修改 agent 越权字段: {sorted(forbidden)}。仅允许: {sorted(_ALLOWED_AGENT_FIELDS)}",
                    )

                if "max_iterations" in updates:
                    val = updates["max_iterations"]
                    if not isinstance(val, int) or isinstance(val, bool) or not (1 <= val <= 50):
                        return ToolResult(
                            success=False,
                            error=f"max_iterations 必须是 1 到 50 之间的整数，收到: {val}",
                        )
                if "temperature" in updates:
                    value = updates["temperature"]
                    if isinstance(value, bool) or not isinstance(value, (int, float)):  # noqa: UP038 — 保持 Py3.8 兼容
                        return ToolResult(
                            success=False,
                            error=f"temperature 必须是 0 到 2 之间的数字，收到: {value!r}",
                        )
                    if not 0 <= value <= 2:
                        return ToolResult(
                            success=False,
                            error=f"temperature 必须是 0 到 2 之间的数字，收到: {value!r}",
                        )

                agent_repo = AgentRepository()
                current_agent = agent_repo.get(agent_id)
                if not current_agent:
                    return ToolResult(success=False, error=f"未找到 ID 为 '{agent_id}' 的智能体")

                agent_updates = dict(updates)
                if "temperature" in agent_updates:
                    model_config = dict(current_agent.get("model_config") or {})
                    model_config["temperature"] = agent_updates.pop("temperature")
                    agent_updates["model_config"] = model_config
                if not agent_updates:
                    return ToolResult(success=False, error="没有可持久化的 agent 配置字段")
                if not agent_repo.update(agent_id, agent_updates):
                    return ToolResult(success=False, error=f"更新智能体 '{agent_id}' 失败")
                return ToolResult(
                    success=True,
                    content={
                        "message": f"成功更新智能体 '{agent_id}' 配置",
                        "target": "agent",
                        "agent_id": agent_id,
                        "updated_fields": updates,
                    },
                    output=f"智能体 '{agent_id}' 配置更新成功: {updates}",
                )

            elif target == "general":
                forbidden = set(updates.keys()) - _ALLOWED_GENERAL_FIELDS
                if forbidden:
                    return ToolResult(
                        success=False,
                        error=f"禁止修改 general 越权字段: {sorted(forbidden)}。仅允许: {sorted(_ALLOWED_GENERAL_FIELDS)}",
                    )
                validation_error = _validate_general_updates(updates)
                if validation_error:
                    return ToolResult(success=False, error=validation_error)

                repo = SettingsRepository()
                current_settings = repo.get_json("app_settings") or {}
                candidate, settings_error = _prepare_settings_update(
                    current_settings, updates, target="general"
                )
                if settings_error:
                    return ToolResult(success=False, error=settings_error)
                repo.set_json("app_settings", candidate)

                return ToolResult(
                    success=True,
                    content={
                        "message": "成功更新通用设置 (general)",
                        "target": "general",
                        "updated_fields": updates,
                    },
                    output=f"通用设置更新成功: {updates}",
                )

            else:
                return ToolResult(
                    success=False,
                    error=f"不支持的 target: '{target}'，必须为 'orch', 'agent', 'general', 'endpoint' 或 'model_selection'",
                )

        except Exception as exc:
            logger.exception("update_sage_config 执行异常: %s", exc)
            return ToolResult(success=False, error=f"修改配置失败: {exc}")

    # ===== 2026-10-28 新增辅助方法 =====

    def _handle_endpoint_action(  # noqa: PLR0911
        self,
        action: Optional[str],
        endpoint_id: Optional[str],
        updates: Dict[str, Any],
    ) -> ToolResult:
        """处理 endpoint CRUD 操作。"""
        if not action:
            return ToolResult(success=False, error="target='endpoint' 时必须指定 action 参数")

        valid_actions = {"list", "get", "create", "update", "delete"}
        if action not in valid_actions:
            return ToolResult(
                success=False,
                error=f"action 必须是 {sorted(valid_actions)} 之一，收到: {action!r}",
            )

        repo = SettingsRepository()
        try:
            settings = repo.get_json("app_settings") or {}
            endpoints = list(settings.get("endpoints", []))
        except Exception as exc:
            logger.exception("读取 endpoints 失败: %s", exc)
            return ToolResult(success=False, error=f"读取配置失败: {exc}")

        # ===== list: 返回所有 endpoints（脱敏） =====
        if action == "list":
            redacted_endpoints = _redact_settings(endpoints)
            return ToolResult(
                success=True,
                content={"endpoints": redacted_endpoints, "count": len(redacted_endpoints)},
                output=f"共 {len(redacted_endpoints)} 个端点",
            )

        # ===== get: 返回单个 endpoint（脱敏） =====
        if action == "get":
            if not endpoint_id:
                return ToolResult(success=False, error="action='get' 时必须指定 endpoint_id")
            ep = next((e for e in endpoints if e.get("id") == endpoint_id), None)
            if not ep:
                return ToolResult(success=False, error=f"未找到 ID 为 '{endpoint_id}' 的端点")
            return ToolResult(
                success=True,
                content=_redact_settings(ep),
                output=f"端点 '{endpoint_id}': {ep.get('name', 'N/A')}",
            )

        # ===== create: 新增 endpoint =====
        if action == "create":
            # 白名单检查
            forbidden = set(updates.keys()) - _ALLOWED_ENDPOINT_FIELDS
            if forbidden:
                return ToolResult(
                    success=False,
                    error=f"禁止设置越权字段: {sorted(forbidden)}。仅允许: {sorted(_ALLOWED_ENDPOINT_FIELDS)}",
                )
            # 验证
            validation_error = _validate_endpoint_updates(updates)
            if validation_error:
                return ToolResult(success=False, error=validation_error)
            # baseUrl 必填
            if not updates.get("baseUrl"):
                return ToolResult(success=False, error="创建端点时 baseUrl 为必填字段")
            # 生成 id（若未提供）
            if "id" not in updates or not updates["id"]:
                import time
                updates["id"] = f"ep_{int(time.time() * 1000)}"
            # 检查 id 唯一性
            if any(e.get("id") == updates["id"] for e in endpoints):
                return ToolResult(success=False, error=f"端点 ID '{updates['id']}' 已存在")
            # 添加并保存
            endpoints.append(dict(updates))
            settings["endpoints"] = endpoints
            repo.set_json("app_settings", settings)
            return ToolResult(
                success=True,
                content={"message": "端点创建成功", "endpoint_id": updates["id"]},
                output=f"端点 '{updates['id']}' 创建成功",
            )

        # ===== update: 修改现有 endpoint =====
        if action == "update":
            if not endpoint_id:
                return ToolResult(success=False, error="action='update' 时必须指定 endpoint_id")
            # 白名单检查
            forbidden = set(updates.keys()) - _ALLOWED_ENDPOINT_FIELDS
            if forbidden:
                return ToolResult(
                    success=False,
                    error=f"禁止修改越权字段: {sorted(forbidden)}。仅允许: {sorted(_ALLOWED_ENDPOINT_FIELDS)}",
                )
            # 验证
            validation_error = _validate_endpoint_updates(updates)
            if validation_error:
                return ToolResult(success=False, error=validation_error)
            # 查找 endpoint
            ep = next((e for e in endpoints if e.get("id") == endpoint_id), None)
            if not ep:
                return ToolResult(success=False, error=f"未找到 ID 为 '{endpoint_id}' 的端点")
            # 不允许修改 id
            if "id" in updates and updates["id"] != endpoint_id:
                return ToolResult(success=False, error="不允许修改端点 ID")
            # 合并更新
            ep.update({k: v for k, v in updates.items() if k != "id"})
            settings["endpoints"] = endpoints
            repo.set_json("app_settings", settings)
            return ToolResult(
                success=True,
                content={"message": f"端点 '{endpoint_id}' 更新成功", "updated_fields": list(updates.keys())},
                output=f"端点 '{endpoint_id}' 更新成功",
            )

        # ===== delete: 删除 endpoint =====
        if action == "delete":
            if not endpoint_id:
                return ToolResult(success=False, error="action='delete' 时必须指定 endpoint_id")
            new_endpoints = [e for e in endpoints if e.get("id") != endpoint_id]
            if len(new_endpoints) == len(endpoints):
                return ToolResult(success=False, error=f"未找到 ID 为 '{endpoint_id}' 的端点")
            settings["endpoints"] = new_endpoints
            repo.set_json("app_settings", settings)
            return ToolResult(
                success=True,
                content={"message": f"端点 '{endpoint_id}' 已删除"},
                output=f"端点 '{endpoint_id}' 已删除",
            )

        # 不应到达此处
        return ToolResult(success=False, error=f"未处理的 action: {action!r}")

    def _handle_model_selection_update(
        self,
        task_type: Optional[str],
        updates: Dict[str, Any],
    ) -> ToolResult:
        """处理 model_selection 更新。"""
        if not task_type:
            return ToolResult(
                success=False,
                error="target='model_selection' 时必须指定 task_type 参数",
            )

        # 白名单检查
        forbidden = set(updates.keys()) - _ALLOWED_MODEL_SELECTION_FIELDS
        if forbidden:
            return ToolResult(
                success=False,
                error=f"禁止修改越权字段: {sorted(forbidden)}。仅允许: {sorted(_ALLOWED_MODEL_SELECTION_FIELDS)}",
            )

        # 验证
        validation_error = _validate_model_selection_updates(task_type, updates)
        if validation_error:
            return ToolResult(success=False, error=validation_error)

        repo = SettingsRepository()
        try:
            settings = repo.get_json("app_settings") or {}
            selections = dict(settings.get("modelSelections", {}))
        except Exception as exc:
            logger.exception("读取 modelSelections 失败: %s", exc)
            return ToolResult(success=False, error=f"读取配置失败: {exc}")

        # 引用完整性检查：endpointId 必须存在
        if "endpointId" in updates and updates["endpointId"]:
            endpoints = settings.get("endpoints", [])
            ep = next((e for e in endpoints if e.get("id") == updates["endpointId"]), None)
            if not ep:
                return ToolResult(
                    success=False,
                    error=f"引用的端点 '{updates['endpointId']}' 不存在，请先创建该端点",
                )
            # 可选：检查 modelId 是否在 discoveredModels 中（仅警告，不阻断）
            if "modelId" in updates and updates["modelId"]:
                discovered = ep.get("discoveredModels", [])
                if discovered and not any(m.get("id") == updates["modelId"] for m in discovered):
                    logger.warning(
                        "model '%s' 不在端点 '%s' 的 discoveredModels 中",
                        updates["modelId"],
                        updates["endpointId"],
                    )

        # 更新
        selections[task_type] = {**selections.get(task_type, {}), **updates}
        settings["modelSelections"] = selections
        repo.set_json("app_settings", settings)

        return ToolResult(
            success=True,
            content={
                "message": f"{task_type} 绑定更新成功",
                "task_type": task_type,
                "updated_fields": list(updates.keys()),
            },
            output=f"{task_type} 绑定更新成功: {updates}",
        )


def _build_diagnosis_summary(
    config: Dict[str, Any],
    metrics: Dict[str, Any],
) -> str:
    """基于配置 + 指标生成人类可读的诊断摘要（注入 ``ToolResult.output``）。

    不做建议性判断 —— 建议交给 LLM 结合用户上下文生成。这里只汇总客观数据，
    避免规则硬编码误导（如"成功率<80% 就提示调 maxRetries" 不一定对）。
    """
    lines: List[str] = ["【诊断摘要】"]
    window = metrics.get("window", {})
    run_count = window.get("run_count", 0)
    if run_count == 0:
        lines.append("  - 近期无 run 记录，无法生成诊断")
        return "\n".join(lines)

    from_iso = window.get("from", "?")
    to_iso = window.get("to", "?")
    lines.append(f"  - 最近 {run_count} 次 run: {from_iso} ~ {to_iso}")

    c = metrics["completion"]
    total = c["success"] + c["failed"] + c["cancelled"] + c["other"]
    success_rate = (c["success"] / total * 100) if total else 0
    lines.append(
        "  - 成功率: {:.0f}% ({} success / {} failed / {} cancelled)".format(
            success_rate, c["success"], c["failed"], c["cancelled"]
        )
    )

    fk = metrics["failure_kind"]
    if fk:
        fk_str = ", ".join(f"{k}={v}" for k, v in fk.items())
        lines.append(f"  - 失败分类: {fk_str}")

    retries = metrics["retries"]
    lines.append(
        f"  - 重试: 平均 {retries['mean_per_task']:.2f}/任务, "
        f"含重试任务 {retries['tasks_with_retry_pct']:.1f}%"
    )

    tokens = metrics["tokens"]
    if tokens["task_count_with_tokens"] > 0:
        lines.append(
            f"  - Token: 平均 {tokens['mean_per_task']}/任务, "
            f"总计 {tokens['total']} "
            f"(基于 {tokens['task_count_with_tokens']} 个有数据的任务)"
        )

    latency = metrics["latency_ms"]
    if latency["mean"] > 0:
        lines.append(
            f"  - 延迟: 平均 {latency['mean']}ms, "
            f"p50={latency['p50']}ms, p95={latency['p95']}ms"
        )

    return "\n".join(lines)


class DiagnoseSageConfigTool(BaseTool):
    """诊断 Sage 配置 + 运行指标工具（P119 Config Advisor Phase 2.2）。

    合并"当前配置"与"最近 N 次 run 的运行指标"，作为 LLM 给出配置优化建议
    的完整数据基础。声明为 ``RiskClass.READ``（纯只读，无需用户审批）。

    输出包括：
    - ``configuration``: 脱敏后的 ``app_settings`` 全量（与 ``read_sage_config``
      ``section='all'`` 等价）
    - ``recent_metrics``: ``OrchRunMetrics.aggregate_recent()`` 返回的指标结构
    - ``summary``: 人类可读的诊断摘要（注入 ``ToolResult.output``）
    """

    risk: RiskClass = RiskClass.READ

    def __init__(self, policy: Optional[ToolPolicy] = None) -> None:
        super().__init__(policy=policy)

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="diagnose_sage_config",
            description=(
                "返回当前配置 + 最近 N 次 run 的运行指标聚合（completion、failure_kind、"
                "tokens、latency、retries），用于诊断性能或失败原因。基于数据给出配置"
                "优化建议（如'你最近 10 次 run 有 4 次因 max_iterations=10 截断，"
                "建议调到 25'）。只读，无需用户审批。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "window_runs": {
                        "type": "integer",
                        "description": (
                            "聚合最近多少次 run 的指标（默认 20，范围 1-200）。"
                            "窗口过小统计意义不足；过大则响应慢"
                        ),
                    }
                },
                "required": [],
            },
        )

    def execute(self, window_runs: int = 20, **kwargs: Any) -> ToolResult:
        if isinstance(window_runs, bool) or not isinstance(window_runs, int):
            return ToolResult(success=False, error="window_runs 必须为正整数")
        if not 1 <= window_runs <= 200:
            return ToolResult(
                success=False, error="window_runs 必须在 1 到 200 之间"
            )

        # 1. 读配置（复用 _redact_settings，与 ReadSageConfigTool 脱敏一致）
        try:
            raw_settings = SettingsRepository().get_json("app_settings") or {}
            config = _redact_settings(copy.deepcopy(raw_settings))
        except Exception as exc:  # noqa: BLE001 — 配置读取失败即终止
            logger.exception("diagnose_sage_config: 读取配置失败: %s", exc)
            return ToolResult(success=False, error=f"读取配置失败: {exc}")

        # 2. 取运行指标（OrchRunMetrics 内部 fail-safe，不会抛）
        try:
            from backend.data.orch_run_metrics import OrchRunMetrics

            recent_metrics = OrchRunMetrics.aggregate_recent(limit=window_runs)
        except Exception as exc:  # noqa: BLE001 — 兜底防御，不应触发
            logger.exception("diagnose_sage_config: 获取运行指标失败: %s", exc)
            return ToolResult(success=False, error=f"获取运行指标失败: {exc}")

        summary = _build_diagnosis_summary(config, recent_metrics)
        return ToolResult(
            success=True,
            content={
                "configuration": config,
                "recent_metrics": recent_metrics,
                "summary": summary,
            },
            output=summary,
        )
