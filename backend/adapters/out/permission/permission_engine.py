"""权限引擎 — 对每次工具调用裁决 allow / deny / ask-user（A1，来自 OpenWorker）。

数据驱动：工具风险来自注册表收集的 ``RiskClass`` 声明（``BaseTool.risk``），
引擎不再携带 ``WRITE_TOOLS`` / ``SHELL_TOOL`` 之类的名字集合。

模式语义（``PermissionMode``）：

- DISCUSS / PLAN：只读 — 任何 consequential 调用直接拒绝（不询问）
- INTERACTIVE：读放行；写/执行/出网询问用户（默认）
- AUTO：完全放行（写入仍受 workspace 路径边界约束）
- CUSTOM：INTERACTIVE + ``auto_allow_tools`` 白名单自动放行

参数模式精化：写入的 ``path`` 必须为绝对路径且落在 ``workspace_root``
内（所有模式）；命令 allowlist 采用 token 精确前缀匹配，且拒绝携带
shell 操作符的命令（操作符定义与 A7 ``BashTool`` / ``bash_validation``
同源，见 ``backend.domain.shell``）。

引擎**只做裁决**；上层（ChatService / agent loop）负责把 ``needs_user``
裁决路由到 UI 审批，并经 ``allow_*_for_session`` 记录用户选择。
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from backend.domain.permission import READ_ONLY_MODES, Decision, PermissionMode
from backend.domain.risk import RiskClass, RiskOverrides, classify, is_consequential
from backend.domain.shell import has_shell_operators

if TYPE_CHECKING:
    from backend.tools.registry import ToolRegistry


@dataclass
class PermissionEngine:
    """工具调用权限裁决引擎。

    Attributes:
        workspace_root:        写入路径边界（resolve 后必须落在其内）
        mode:                  会话级权限模式（缺省 INTERACTIVE）
        allowed_commands:      命令 allowlist（token 精确前缀匹配，免审批）
        auto_allow_tools:      CUSTOM 模式自动放行的工具白名单
        session_allow_tools:   用户在本次会话批准的工具（运行时累积；
                               EXTERNAL 风险工具除外，保持逐次审批。
                               会话内无界增长，长会话由上层负责重置）
        session_allow_commands: 用户在本次会话批准的完整命令（运行时累积）
        declared_risks:        注册表收集的工具风险声明（``registry.declared_risks()``）
        risk_overrides:        用户级风险覆盖解析器（A19，缺省 None）

    写入工具契约：WRITE_LOCAL 工具的写入路径必须通过名为 ``path`` 的
    参数传递且为绝对路径（``~`` 除外），否则引擎拒绝或无法施加路径
    边界。无 ``path`` 参数的状态修改工具（如 memory_save）仅受模式
    门禁约束 — 新增此类工具时须自行评估资源边界。
    """

    workspace_root: Path
    mode: PermissionMode = PermissionMode.INTERACTIVE
    allowed_commands: List[str] = field(default_factory=list)
    auto_allow_tools: Set[str] = field(default_factory=set)
    session_allow_tools: Set[str] = field(default_factory=set)
    session_allow_commands: Set[str] = field(default_factory=set)
    declared_risks: Dict[str, RiskClass] = field(default_factory=dict)
    risk_overrides: Optional[RiskOverrides] = None

    def __post_init__(self) -> None:
        self.workspace_root = Path(self.workspace_root).expanduser().resolve()
        # 归一化：允许调用方传裸字符串（如 JSON 配置里的 "auto"）
        self.mode = PermissionMode(self.mode)
        # 防御性拷贝：调用方事后修改传入容器不渗透进引擎
        self.allowed_commands = list(self.allowed_commands)
        self.auto_allow_tools = set(self.auto_allow_tools)
        self.session_allow_tools = set(self.session_allow_tools)
        self.session_allow_commands = set(self.session_allow_commands)
        self.declared_risks = dict(self.declared_risks)

    @classmethod
    def from_registry(
        cls,
        registry: ToolRegistry,
        workspace_root: Path,
        mode: PermissionMode = PermissionMode.INTERACTIVE,
        **kwargs: Any,
    ) -> PermissionEngine:
        """从 ``ToolRegistry`` 构造，自动注入注册时声明的风险表。"""
        return cls(
            workspace_root=workspace_root,
            mode=mode,
            declared_risks=registry.declared_risks(),
            **kwargs,
        )

    def evaluate(
        self, tool_name: str, arguments: Dict[str, Any], metadata: Any = None
    ) -> Decision:
        """裁决单次工具调用。

        Args:
            tool_name: 工具名称
            arguments: 工具调用参数（写入工具读 ``path``、shell 读 ``command``）
            metadata:  工具元数据（对象或 dict），参与风险启发式解析

        Returns:
            ``Decision``：``allowed`` 为 False 且 ``needs_user`` 为 True 时，
            上层应挂起调用并请求用户批准。
        """
        arguments = arguments or {}
        risk = classify(tool_name, metadata, self.risk_overrides, self.declared_risks)
        is_write = risk is RiskClass.WRITE_LOCAL
        is_shell = risk is RiskClass.EXEC
        consequential = is_consequential(risk)

        # DISCUSS / PLAN：只读，consequential 调用直接拒绝（不询问）。
        if self.mode in READ_ONLY_MODES and consequential:
            return Decision(False, f"{self.mode.value} mode is read-only")

        # 写入路径边界（所有模式）：必须落在 workspace_root 内。
        if is_write:
            violation = self._write_path_violation(arguments.get("path"))
            if violation is not None:
                return Decision(False, violation)

        # 无副作用工具始终放行。
        if not consequential:
            return Decision(True, "low risk")

        # AUTO：完全放行（路径边界已在上面检查过）。
        if self.mode is PermissionMode.AUTO:
            return Decision(True, "full access")

        # INTERACTIVE / CUSTOM：各类豁免名单精化。
        exempted = self._exemption_decision(tool_name, arguments, is_shell)
        if exempted is not None:
            return exempted

        # 其余：询问用户。
        return Decision(False, "requires approval", needs_user=True)

    def _exemption_decision(
        self, tool_name: str, arguments: Dict[str, Any], is_shell: bool
    ) -> Optional[Decision]:
        """检查调用是否命中豁免名单；命中返回放行裁决，否则返回 None。

        豁免来源（按检查顺序）：命令 allowlist、会话命令记忆、
        会话工具记忆、CUSTOM 模式配置白名单。

        护栏：EXTERNAL 风险工具**不**享受会话工具记忆豁免 — 出网调用
        一次批准不等于对任意 target（URL）放行，缺少精确 target 绑定
        前保持逐次审批（参考 OpenWorker permissions.py 的 connector
        排除；target 绑定能力随 A19 引入）。
        """
        if is_shell:
            command = str(arguments.get("command", ""))
            if self._command_allowed(command):
                return Decision(True, "command on allowlist")
            if command and command in self.session_allow_commands:
                return Decision(True, "command allowed for session")
        if tool_name in self.session_allow_tools:
            risk = classify(tool_name, None, self.risk_overrides, self.declared_risks)
            if risk is not RiskClass.EXTERNAL:
                return Decision(True, "tool allowed for session")
        if self.mode is PermissionMode.CUSTOM and tool_name in self.auto_allow_tools:
            return Decision(True, "auto-allowed by config")
        return None

    # -- 会话记忆 ---------------------------------------------------------
    def allow_tool_for_session(self, tool_name: str) -> None:
        """记录用户批准的工具，本次会话内同名调用免询问。"""
        self.session_allow_tools.add(tool_name)

    def allow_command_for_session(self, command: str) -> None:
        """记录用户批准的完整命令，本次会话内同命令免询问。"""
        if command:
            self.session_allow_commands.add(command)

    # -- 辅助 -------------------------------------------------------------
    def _write_path_violation(self, path: Any) -> Optional[str]:
        """校验写入路径边界；违规返回拒绝理由，合规/无路径参数返回 None。

        仅接受绝对路径（``~`` 展开后）：相对路径在引擎（按 workspace
        解析）与工具（按进程 CWD 解析，见 WriteFileTool）之间解析语义
        不一致 — 放行"判定在 workspace 内"的相对路径可能造成实际写到
        workspace 外的静默 bypass，故 fail-closed 直接拒绝。
        """
        if path is None:
            return None
        if not Path(str(path)).expanduser().is_absolute():
            return f"write path must be absolute: {path}"
        if not self._under_workspace(str(path)):
            return f"path is not in the workspace: {path}"
        return None

    def _candidate(self, path: str) -> Path:
        """相对路径按 workspace_root 解析；绝对路径/``~`` 原样展开。"""
        p = Path(path).expanduser()
        return p.resolve() if p.is_absolute() else (self.workspace_root / p).resolve()

    def _under_workspace(self, path: str) -> bool:
        """路径 resolve 后是否严格落在 workspace_root 内。"""
        try:
            self._candidate(path).relative_to(self.workspace_root)
            return True
        except ValueError:
            return False

    def _command_allowed(self, command: str) -> bool:
        """命令是否被 ``allowed_commands`` 覆盖（免审批自动执行）。

        allowlist 条目会绕过用户审批，因此字符串前缀匹配不安全：
        ``git status`` 会放过 ``git status && rm -rf ~``。携带 shell
        操作符的命令先整体拒绝，再按 token 精确前缀匹配 — 条目的
        token 序列必须是命令 token 序列的精确前缀（``git status``
        匹配 ``git status -s``，但不匹配 ``git statusfoo`` 或裸 ``git``）。
        """
        if has_shell_operators(command):
            return False
        try:
            argv = shlex.split(command)
        except ValueError:
            return False  # 引号不配对等 — 视为不在 allowlist
        if not argv:
            return False
        for allowed in self.allowed_commands:
            try:
                prefix = shlex.split(allowed)
            except ValueError:
                continue
            if prefix and argv[: len(prefix)] == prefix:
                return True
        return False
