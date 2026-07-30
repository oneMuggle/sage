"""RiskClass 风险分级测试 (A1 from OpenWorker)

测试工具风险数据化：枚举定义、按名兜底表、classify 优先级解析、
注册表风险收集。
"""

import pytest

from backend.domain.risk import (
    EXTERNAL_TOOLS,
    SHELL_TOOLS,
    WRITE_TOOLS,
    RiskClass,
    classify,
    is_consequential,
)
from backend.tools import register_all_tools
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


class TestRiskClass:
    """RiskClass 枚举测试套件"""

    def test_enum_members(self):
        """四个风险级别齐全"""
        assert {r.name for r in RiskClass} == {"READ", "WRITE_LOCAL", "EXEC", "EXTERNAL"}

    def test_str_values(self):
        """字符串值可序列化（供 API / 日志）"""
        assert RiskClass.READ.value == "read"
        assert RiskClass.WRITE_LOCAL.value == "write_local"
        assert RiskClass.EXEC.value == "exec"
        assert RiskClass.EXTERNAL.value == "external"

    def test_is_str_subclass(self):
        """str 枚举 — 可直接比较字符串"""
        assert RiskClass.READ == "read"

    def test_is_consequential(self):
        """除 READ 外都是 consequential"""
        assert is_consequential(RiskClass.READ) is False
        assert is_consequential(RiskClass.WRITE_LOCAL) is True
        assert is_consequential(RiskClass.EXEC) is True
        assert is_consequential(RiskClass.EXTERNAL) is True


class TestClassifyBaseTable:
    """classify 按名兜底表测试套件"""

    @pytest.mark.parametrize("name", sorted(WRITE_TOOLS))
    def test_builtin_write_tools(self, name):
        """内置写工具 → WRITE_LOCAL"""
        assert classify(name) is RiskClass.WRITE_LOCAL

    @pytest.mark.parametrize("name", sorted(SHELL_TOOLS))
    def test_builtin_shell_tools(self, name):
        """内置 shell 工具 → EXEC"""
        assert classify(name) is RiskClass.EXEC

    @pytest.mark.parametrize("name", sorted(EXTERNAL_TOOLS))
    def test_builtin_external_tools(self, name):
        """内置网络工具 → EXTERNAL"""
        assert classify(name) is RiskClass.EXTERNAL

    def test_unknown_tool_defaults_to_read(self):
        """未知工具兜底 READ"""
        assert classify("some_mystery_tool") is RiskClass.READ


class TestClassifyMetadata:
    """classify 元数据启发式测试套件"""

    def test_metadata_requires_approval_attr(self):
        """对象元数据 requires_approval=True → EXTERNAL"""

        class Meta:
            requires_approval = True

        assert classify("custom_tool", metadata=Meta()) is RiskClass.EXTERNAL

    def test_metadata_requires_approval_dict(self):
        """dict 元数据 requires_approval=True → EXTERNAL"""
        meta = {"requires_approval": True}
        assert classify("custom_tool", metadata=meta) is RiskClass.EXTERNAL

    def test_metadata_without_flag_is_read(self):
        """元数据无 requires_approval → READ"""
        assert classify("custom_tool", metadata={"requires_approval": False}) is RiskClass.READ
        assert classify("custom_tool", metadata=object()) is RiskClass.READ
        assert classify("custom_tool", metadata=None) is RiskClass.READ

    def test_base_table_wins_over_metadata(self):
        """按名表优先于元数据启发式"""
        meta = {"requires_approval": True}
        assert classify("write_file", metadata=meta) is RiskClass.WRITE_LOCAL


class TestClassifyPrecedence:
    """classify 优先级链测试套件"""

    def test_declared_wins_over_base(self):
        """注册声明优先于按名兜底表"""
        declared = {"write_file": RiskClass.READ}
        assert classify("write_file", declared=declared) is RiskClass.READ

    def test_declared_covers_unknown_tool(self):
        """注册声明覆盖未知工具（如动态注册的 MCP 工具）"""
        declared = {"mcp_deploy": RiskClass.EXTERNAL}
        assert classify("mcp_deploy", declared=declared) is RiskClass.EXTERNAL

    def test_overrides_win_over_declared(self):
        """用户覆盖优先于注册声明"""
        declared = {"write_file": RiskClass.READ}
        overrides = lambda name: RiskClass.EXEC if name == "write_file" else None  # noqa: E731
        assert classify("write_file", declared=declared, overrides=overrides) is RiskClass.EXEC

    def test_overrides_win_over_base(self):
        """用户覆盖优先于按名兜底表"""
        overrides = lambda name: RiskClass.READ if name == "terminal" else None  # noqa: E731
        assert classify("terminal", overrides=overrides) is RiskClass.READ

    def test_override_returning_none_defers(self):
        """覆盖解析器返回 None → 交给后续优先级"""
        overrides = lambda _name: None  # noqa: E731
        assert classify("terminal", overrides=overrides) is RiskClass.EXEC

    def test_full_precedence_chain(self):
        """完整优先级:overrides > declared > base > metadata > READ"""
        declared = {"t1": RiskClass.READ, "t2": RiskClass.WRITE_LOCAL}
        overrides = lambda name: RiskClass.EXEC if name == "t1" else None  # noqa: E731
        meta = {"requires_approval": True}

        # t1: overrides 命中
        assert classify("t1", meta, overrides, declared) is RiskClass.EXEC
        # t2: overrides 未命中 → declared 命中
        assert classify("t2", meta, overrides, declared) is RiskClass.WRITE_LOCAL
        # write_file: declared 未命中 → base 命中（优先于 metadata）
        assert classify("write_file", meta, overrides, declared) is RiskClass.WRITE_LOCAL
        # t3: 前三级均未命中 → metadata 启发式
        assert classify("t3", meta, overrides, declared) is RiskClass.EXTERNAL
        # t4: 全部未命中 → READ
        assert classify("t4", None, overrides, declared) is RiskClass.READ


class TestRegistryRiskCollection:
    """ToolRegistry 风险收集测试套件"""

    def test_register_records_declared_risk(self):
        """注册时收集工具声明的 risk"""
        registry = ToolRegistry()
        registry.register(_DummyTool("deploy", RiskClass.EXTERNAL))

        assert registry.risk_of("deploy") is RiskClass.EXTERNAL

    def test_risk_of_unknown_tool_is_read(self):
        """未注册工具 risk_of → READ"""
        registry = ToolRegistry()
        assert registry.risk_of("ghost") is RiskClass.READ

    def test_declared_risks_returns_snapshot_copy(self):
        """declared_risks 返回副本,修改不影响注册表"""
        registry = ToolRegistry()
        registry.register(_DummyTool("deploy", RiskClass.EXTERNAL))

        snapshot = registry.declared_risks()
        snapshot["deploy"] = RiskClass.READ
        snapshot["injected"] = RiskClass.EXEC

        assert registry.risk_of("deploy") is RiskClass.EXTERNAL
        assert registry.risk_of("injected") is RiskClass.READ

    def test_unregister_clears_risk(self):
        """取消注册同步清理风险记录"""
        registry = ToolRegistry()
        registry.register(_DummyTool("deploy", RiskClass.EXTERNAL))
        registry.unregister("deploy")

        assert registry.risk_of("deploy") is RiskClass.READ
        assert registry.declared_risks() == {}

    def test_clear_removes_all_risks(self):
        """clear 清空所有风险记录"""
        registry = ToolRegistry()
        registry.register(_DummyTool("a", RiskClass.EXEC))
        registry.register(_DummyTool("b", RiskClass.WRITE_LOCAL))
        registry.clear()

        assert registry.declared_risks() == {}

    def test_registry_classify_uses_declared(self):
        """registry.classify 以注册声明为 declared 来源"""
        registry = ToolRegistry()
        registry.register(_DummyTool("write_file", RiskClass.READ))

        # 声明 READ 覆盖按名表的 WRITE_LOCAL
        assert registry.classify("write_file") is RiskClass.READ
        # 未注册工具回落按名表
        assert registry.classify("terminal") is RiskClass.EXEC


class TestBuiltinToolDeclarations:
    """内置工具风险声明验收测试"""

    def test_builtin_tools_declare_expected_risk(self):
        """所有内置工具经 register_all_tools 注册后风险符合预期"""
        registry = ToolRegistry()
        register_all_tools(registry)

        expected = {
            "read_file": RiskClass.READ,
            "write_file": RiskClass.WRITE_LOCAL,
            "list_dir": RiskClass.READ,
            "terminal": RiskClass.EXEC,
            "web_search": RiskClass.EXTERNAL,
            "web_fetch": RiskClass.EXTERNAL,
            "calculator": RiskClass.READ,
            "memory_search": RiskClass.READ,
            "memory_save": RiskClass.WRITE_LOCAL,
            "office_list": RiskClass.READ,
            "office_read": RiskClass.READ,
        }
        for name, risk in expected.items():
            assert registry.risk_of(name) is risk, f"{name} risk mismatch"

    def test_base_tool_default_risk_is_read(self):
        """BaseTool 默认 risk 为 READ（新工具未声明时的安全缺省）"""
        tool = _DummyTool("plain")
        assert tool.risk is RiskClass.READ


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
