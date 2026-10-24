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
}

_VALID_READ_SECTIONS = {"all", "orch", "agents", "general", "model_selections"}
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
                "的迭代上限与设定、通用设置等。敏感凭证已自动脱敏。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "section": {
                        "type": "string",
                        "enum": ["all", "orch", "agents", "general", "model_selections"],
                        "description": (
                            "要查询的配置分类：\n"
                            "- 'orch': 编排参数（泳道迭代上限、子代理迭代上限、并发上限等）\n"
                            "- 'agents': 所有智能体档案列表（含每个智能体的最大迭代步数、角色与提示词）\n"
                            "- 'general': 通用应用设置（流式、记忆、温度、时区等）\n"
                            "- 'model_selections': 各任务当前绑定的模型配置\n"
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
                "安全修改 Sage 自身的部分参数配置（如调整主助手或子代理的迭代上限、"
                "温度等）。受严格安全白名单保护，严禁修改敏感端点凭证或工具权限。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "enum": ["orch", "agent", "general"],
                        "description": "修改目标类型：'orch'(编排参数), 'agent'(指定智能体属性), 'general'(全局设置)",
                    },
                    "agent_id": {
                        "type": "string",
                        "description": "当 target='agent' 时必填，指定智能体 ID（如 'primary', 'coder', 'reviewer', 'writer' 等）",
                    },
                    "updates": {
                        "type": "object",
                        "description": (
                            "待更新的参数键值对：\n"
                            "- target='orch' 时允许: maxLaneIterations, maxSubagentIterations, maxConcurrentSubagents, maxRetries 等\n"
                            "- target='agent' 时允许: max_iterations (1~50), temperature, system_prompt, description 等\n"
                            "- target='general' 时允许: temperature, streaming, autoMemory, confirmDelete 等"
                        ),
                    },
                },
                "required": ["target", "updates"],
            },
        )

    def execute(  # noqa: PLR0911 — 目标分发与防御性拦截多出口
        self,
        target: str,
        updates: Dict[str, Any],
        agent_id: Optional[str] = None,
        **kwargs: Any,
    ) -> ToolResult:
        if not isinstance(updates, dict) or not updates:
            return ToolResult(success=False, error="updates 必须为非空字典")

        try:
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
                    error=f"不支持的 target: '{target}'，必须为 'orch', 'agent' 或 'general'",
                )

        except Exception as exc:
            logger.exception("update_sage_config 执行异常: %s", exc)
            return ToolResult(success=False, error=f"修改配置失败: {exc}")


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
