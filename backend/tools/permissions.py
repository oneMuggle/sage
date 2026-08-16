"""工具权限执行层（M1 工具安全加固）。

移植 claw-code ``rust/crates/runtime/src/permission_enforcer.rs`` 与
``permissions.rs`` 的"先执行许可、后分发工具"（enforcement-before-dispatch）
设计，适配 sage 桌面 GUI 形态：

- 四种权限模式（``PermissionMode``）对应 claw 的 ReadOnly / WorkspaceWrite /
  Prompt / DangerFullAccess。
- 用户规则（``PermissionRule``，fnmatch 通配）优先于模式矩阵，顺序为
  **deny > allow > ask**（deny 永远胜出）。
- EXECUTE 类工具额外跑 bash 风险校验（``backend.tools.bash_validation``）：
  DESTRUCTIVE 命令在 READ_ONLY 下直接拒，在其它模式（含 FULL_ACCESS）
  升级为 needs_approval——这是显式 allow 规则也无法绕过的安全网。

本模块不依赖 FastAPI / asyncio，可单测。设置加载（``load_enforcer_from_settings``）
惰性导入 settings_repo，避免 tools ↔ data 循环依赖。
"""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from backend.tools.bash_validation import BashRisk, validate_bash

logger = logging.getLogger(__name__)


class PermissionMode(str, Enum):
    """全局权限模式（持久化值即枚举 value）。"""

    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    PROMPT = "prompt"
    FULL_ACCESS = "full_access"


class ToolCapability(str, Enum):
    """工具能力分级——决定模式矩阵如何适用。"""

    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"


#: 内置工具能力分类表。新增工具时应在此登记；
#: 未登记工具默认 WRITE（fail-safe：既不静默放行执行，也不过度拦截读）。
TOOL_CAPABILITIES: Dict[str, ToolCapability] = {
    "read_file": ToolCapability.READ,
    "list_dir": ToolCapability.READ,
    "memory_search": ToolCapability.READ,
    "web_search": ToolCapability.READ,
    "web_fetch": ToolCapability.READ,
    "office_list": ToolCapability.READ,
    "office_read": ToolCapability.READ,
    "calculator": ToolCapability.READ,
    # M2 agent 工具面扩展（移植 claw-code tool surface）
    "glob_search": ToolCapability.READ,
    "grep_search": ToolCapability.READ,
    # todo_write 归 READ：仅维护 agent 会话内的内部草稿状态（内存桶），
    # 对用户数据零副作用——与 claw-code 将 TodoWrite 视为非敏感工具一致。
    "todo_write": ToolCapability.READ,
    "structured_output": ToolCapability.READ,
    "write_file": ToolCapability.WRITE,
    "edit_file": ToolCapability.WRITE,
    "terminal": ToolCapability.EXECUTE,
    "repl": ToolCapability.EXECUTE,
    # M2 part B: skill 归 EXECUTE —— 技能可编排任意工具调用, SKILL.md 脚本
    # 更直接跑子进程(script_runner 沙箱内), 语义上是"执行任意动作",
    # 故按最严格能力对待, 由 M1 审批闸口按模式矩阵逐次拦截。
    "skill": ToolCapability.EXECUTE,
    # M2 part B: ask_user_question 归 READ —— 零副作用(仅渲染问题卡片 +
    # 等待用户输入); run_loop 在分发前特判该工具名并走提问闸口, 不过
    # 权限执行器, 不存在双重审批。
    "ask_user_question": ToolCapability.READ,
    # M5 (win7 移植): agent 归 EXECUTE —— 派生的子代理是一个自主 LLM 循环
    # （最多 6 轮 run_loop、发网络请求、占 worker 线程至多 SUBAGENT_TIMEOUT_S），
    # 开放性 强于 skill。虽然子代理自身只拿只读白名单
    # （agent_tool.SUBAGENT_TOOL_WHITELIST），但"派生一个自主体"这个动作本身
    # 按最严格能力对待，与上面 skill 的口径一致。
    "agent": ToolCapability.EXECUTE,
}

#: 未知工具默认能力（fail-safe）
DEFAULT_TOOL_CAPABILITY = ToolCapability.WRITE

#: PermissionRule.decision 合法取值
_VALID_RULE_DECISIONS = ("allow", "deny", "ask")


def classify_tool(tool_name: str) -> ToolCapability:
    """查表返回工具能力；未登记工具回退 ``WRITE``（fail-safe）。"""
    return TOOL_CAPABILITIES.get(tool_name, DEFAULT_TOOL_CAPABILITY)


@dataclass(frozen=True)
class PermissionDecision:
    """单次工具调用的许可结论（不可变）。

    Attributes:
        allowed:        是否允许执行。
        needs_approval: 是否需要用户审批（True 时 allowed 必为 False，
                        审批通过后由调用方放行执行）。
        reason:         人类可读原因（中文）。
    """

    allowed: bool
    needs_approval: bool
    reason: str

    def __post_init__(self) -> None:
        if self.needs_approval and self.allowed:
            raise ValueError("needs_approval=True 时 allowed 必须为 False")


@dataclass(frozen=True)
class PermissionRule:
    """用户持久化规则（不可变）。

    Attributes:
        tool_pattern: fnmatch 通配符，匹配工具名；``"*"`` 匹配任意工具。
        decision:     ``"allow"`` / ``"deny"`` / ``"ask"``。
    """

    tool_pattern: str
    decision: str

    def __post_init__(self) -> None:
        if self.decision not in _VALID_RULE_DECISIONS:
            raise ValueError(
                f"PermissionRule.decision must be one of {_VALID_RULE_DECISIONS}, got {self.decision!r}"
            )
        if not self.tool_pattern:
            raise ValueError("PermissionRule.tool_pattern must be non-empty")

    def matches(self, tool_name: str) -> bool:
        """fnmatch 大小写敏感匹配工具名。"""
        return fnmatch.fnmatchcase(tool_name, self.tool_pattern)

    def to_dict(self) -> Dict[str, str]:
        return {"tool_pattern": self.tool_pattern, "decision": self.decision}

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> PermissionRule:
        """从 JSON dict 构造；字段缺失 / 非法 → ``ValueError``。"""
        pattern = raw.get("tool_pattern")
        decision = raw.get("decision")
        if not isinstance(pattern, str) or not isinstance(decision, str):
            raise ValueError(f"rule requires string tool_pattern and decision: {raw!r}")
        return cls(tool_pattern=pattern, decision=decision)


# 便捷构造器 ---------------------------------------------------------------


def _allow(reason: str) -> PermissionDecision:
    return PermissionDecision(allowed=True, needs_approval=False, reason=reason)


def _deny(reason: str) -> PermissionDecision:
    return PermissionDecision(allowed=False, needs_approval=False, reason=reason)


def _ask(reason: str) -> PermissionDecision:
    return PermissionDecision(allowed=False, needs_approval=True, reason=reason)


class PermissionEnforcer:
    """执行许可检查：规则优先，模式矩阵兜底，bash 校验兜底中的兜底。

    Args:
        mode:           全局权限模式。
        rules:          用户规则序列（按声明顺序，但 deny 永远先于 allow/ask）。
        bash_validator: EXECUTE 工具的风险校验回调，签名
                        ``str -> BashValidationResult``；``None`` 时跳过。
    """

    def __init__(
        self,
        mode: PermissionMode,
        rules: Sequence[PermissionRule],
        bash_validator: Optional[Callable[[str], Any]] = None,
    ) -> None:
        self._mode = mode
        self._rules: Tuple[PermissionRule, ...] = tuple(rules)
        self._bash_validator = bash_validator

    @property
    def mode(self) -> PermissionMode:
        return self._mode

    @property
    def rules(self) -> Tuple[PermissionRule, ...]:
        return self._rules

    def check(self, tool_name: str, args: Optional[Dict[str, Any]] = None) -> PermissionDecision:
        """工具分发前的许可检查（同步、无副作用）。

        Args:
            tool_name: 工具名（如 ``"terminal"``）。
            args:      工具参数字典；EXECUTE 工具读 ``args["command"]`` 做
                       bash 风险校验。

        Returns:
            ``PermissionDecision``——每个分支都带人类可读 reason。
        """
        args = args or {}
        capability = classify_tool(tool_name)
        bash_result = self._validate_execute_command(capability, args)

        # --- 1. 规则层：deny 永远胜出 ----------------------------------------
        matched = self._match_rules(tool_name)
        if matched["deny"] is not None:
            return _deny(f"规则 deny '{matched['deny']}' 命中工具 {tool_name}")

        # --- 2. 破坏性命令安全网（先于 allow 规则生效） ---------------------
        if bash_result is not None and bash_result.risk is BashRisk.DESTRUCTIVE:
            return self._escalate_destructive(bash_result)

        # --- 3. 显式 allow / ask 规则 ---------------------------------------
        if matched["allow"] is not None:
            return _allow(f"规则 allow '{matched['allow']}' 命中工具 {tool_name}")
        if matched["ask"] is not None:
            return _ask(f"规则 ask '{matched['ask']}' 命中工具 {tool_name}")

        # --- 4. 模式矩阵 ----------------------------------------------------
        return self._mode_decision(tool_name, capability, bash_result)

    def _validate_execute_command(
        self, capability: ToolCapability, args: Dict[str, Any]
    ) -> Optional[Any]:
        """EXECUTE 能力工具跑 bash 风险校验；其余能力返回 None。"""
        if capability is not ToolCapability.EXECUTE or self._bash_validator is None:
            return None
        command = args.get("command")
        if isinstance(command, str) and command.strip():
            return self._bash_validator(command)
        return None

    def _match_rules(self, tool_name: str) -> Dict[str, Optional[str]]:
        """按优先级收集首个命中的 deny / allow / ask 规则 pattern。"""
        matched: Dict[str, Optional[str]] = {"deny": None, "allow": None, "ask": None}
        for rule in self._rules:
            if not rule.matches(tool_name):
                continue
            if matched[rule.decision] is None:
                matched[rule.decision] = rule.tool_pattern
        return matched

    def _escalate_destructive(self, bash_result: Any) -> PermissionDecision:
        """破坏性命令安全网: READ_ONLY 直接拒, 其它模式（含 FULL_ACCESS）升级审批。"""
        risk_reason = f"破坏性命令（{'；'.join(bash_result.reasons)}）"
        if self._mode is PermissionMode.READ_ONLY:
            return _deny(f"{risk_reason}：read_only 模式禁止执行")
        return _ask(f"{risk_reason}：即使在 {self._mode.value} 模式下也必须经用户确认")

    def _mode_decision(
        self, tool_name: str, capability: ToolCapability, bash_result: Optional[Any]
    ) -> PermissionDecision:
        """无规则命中时的模式矩阵兜底（每个分支带可读 reason）。"""
        if self._mode is PermissionMode.FULL_ACCESS:
            return _allow(f"full_access 模式：放行 {tool_name} 工具")
        if self._mode is PermissionMode.WORKSPACE_WRITE and capability in (
            ToolCapability.READ,
            ToolCapability.WRITE,
        ):
            return _allow(f"workspace_write 模式：放行 {capability.value} 能力工具 {tool_name}")
        if capability is ToolCapability.READ:  # read_only / prompt 下的只读工具
            return _allow(f"{self._mode.value} 模式：放行只读工具 {tool_name}")
        if self._mode is PermissionMode.READ_ONLY:
            return _deny(f"read_only 模式：拒绝 {capability.value} 能力工具 {tool_name} 的调用")
        # workspace_write 的 EXECUTE / prompt 的 WRITE+EXECUTE → 逐次审批
        reason = f"{self._mode.value} 模式：{capability.value} 能力工具 {tool_name} 需要用户逐次确认"
        if bash_result is not None and bash_result.risk is BashRisk.SUSPICIOUS:
            reason += f"（可疑命令：{'；'.join(bash_result.reasons)}）"
        return _ask(reason)


# ---------------------------------------------------------------------------
# 从 settings 构造 enforcer（agent 运行起点调用）
# ---------------------------------------------------------------------------

#: settings_repo key：权限模式（默认 workspace_write）
SETTINGS_KEY_MODE = "permission_mode"
#: settings_repo key：规则列表 JSON（默认 "[]"）
SETTINGS_KEY_RULES = "permission_rules"

DEFAULT_PERMISSION_MODE = PermissionMode.WORKSPACE_WRITE


def parse_rules(raw: Any) -> List[PermissionRule]:
    """把 settings 里读出的 JSON 值解析成规则列表。

    非法条目被跳过并记 warning——单条坏规则不应导致整个权限系统失效。
    非 list 的顶层值整体回退为空列表。
    """
    if not isinstance(raw, list):
        if raw not in (None, ""):
            logger.warning("permission_rules 不是 JSON list，已回退为空规则: %r", raw)
        return []
    rules: List[PermissionRule] = []
    for item in raw:
        if not isinstance(item, dict):
            logger.warning("permission_rules 含非对象条目，已跳过: %r", item)
            continue
        try:
            rules.append(PermissionRule.from_dict(item))
        except ValueError as exc:
            logger.warning("permission_rules 条目非法，已跳过: %s", exc)
    return rules


def load_enforcer_from_settings(repo: Optional[Any] = None) -> PermissionEnforcer:
    """从 settings_repo 读取模式 + 规则，构造 enforcer（注入 bash 校验器）。

    Args:
        repo: 可注入的 ``SettingsRepository``（测试用）；``None`` 时新建。

    任何读取 / 解析失败都降级为默认 enforcer（workspace_write + 无规则），
    并记 warning——权限系统失效时 fail-safe 比 fail-open 好，但也不能让
    agent 整个跑不起来。
    """
    from backend.data.settings_repo import SettingsRepository

    repo = repo if repo is not None else SettingsRepository()

    mode = DEFAULT_PERMISSION_MODE
    rules: List[PermissionRule] = []
    try:
        raw_mode = repo.get(SETTINGS_KEY_MODE)
        if raw_mode:
            try:
                mode = PermissionMode(raw_mode)
            except ValueError:
                logger.warning(
                    "未知 permission_mode=%r，回退 %s", raw_mode, DEFAULT_PERMISSION_MODE.value
                )
        rules = parse_rules(repo.get_json(SETTINGS_KEY_RULES))
    except Exception as exc:  # noqa: BLE001 — DB 故障不应阻塞 agent 启动
        logger.warning("读取权限设置失败，回退默认 enforcer: %s", exc)
        mode = DEFAULT_PERMISSION_MODE
        rules = []

    return PermissionEnforcer(mode=mode, rules=rules, bash_validator=validate_bash)


__all__ = [
    "PermissionMode",
    "ToolCapability",
    "PermissionDecision",
    "PermissionRule",
    "PermissionEnforcer",
    "TOOL_CAPABILITIES",
    "DEFAULT_TOOL_CAPABILITY",
    "SETTINGS_KEY_MODE",
    "SETTINGS_KEY_RULES",
    "DEFAULT_PERMISSION_MODE",
    "classify_tool",
    "parse_rules",
    "load_enforcer_from_settings",
]
