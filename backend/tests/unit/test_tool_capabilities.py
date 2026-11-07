"""自管理对等 M0：权限能力表完整性 + 自修改审批闸。

背景（2026-11-05 分析）：``TOOL_CAPABILITIES`` 此前只登记了 24 个内置工具，
其余工具回退 ``DEFAULT_TOOL_CAPABILITY=WRITE``，在默认 WORKSPACE_WRITE 模式下
静默放行（不再走审批）—— ``update_sage_config`` / ``schedule_task`` /
``git_commit`` / ``apply_patch`` / 大部分 office 写工具全部漏网。本测试把
「表必须覆盖全部内置工具名」固化为守卫，并验证自管理工具在默认模式下
必须逐次审批。
"""

from __future__ import annotations

import io
import json
from types import SimpleNamespace
from typing import List, Optional

import pytest

from backend.domain.tool_names import ALL_BUILTIN_TOOL_NAMES
from backend.tools.execute_code_tool import ExecuteCodeTool
from backend.tools.permissions import (
    DEFAULT_TOOL_CAPABILITY,
    SELF_MODIFY_TOOLS,
    TOOL_CAPABILITIES,
    PermissionEnforcer,
    PermissionMode,
    ToolCapability,
    classify_tool,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# M0.1：覆盖守卫 —— 每个内置工具必须显式登记能力
# ---------------------------------------------------------------------------


def test_capability_table_covers_every_builtin_tool():
    missing = set(ALL_BUILTIN_TOOL_NAMES) - set(TOOL_CAPABILITIES)
    assert not missing, (
        f"TOOL_CAPABILITIES 缺登记: {sorted(missing)}；"
        "新增内置工具必须在本表显式登记，否则在默认 WORKSPACE_WRITE 模式下静默放行"
    )


def test_capability_table_has_no_unknown_names():
    extra = set(TOOL_CAPABILITIES) - set(ALL_BUILTIN_TOOL_NAMES)
    assert not extra, f"TOOL_CAPABILITIES 包含未注册的工具名: {sorted(extra)}"


def test_default_capability_is_write_fail_safe():
    """未知工具的默认能力保持 WRITE，不改 EXECUTE —— 否则 MCP/编排工具每次
    都要审批。M0.1 的策略是「内置全登记 + MCP 前缀归 EXECUTE」，不动默认值。"""
    assert DEFAULT_TOOL_CAPABILITY is ToolCapability.WRITE
    # 验证未登记但非 plugin__ 前缀的名字回退 WRITE
    assert classify_tool("not_registered_tool_xyz") is ToolCapability.WRITE


# ---------------------------------------------------------------------------
# M0.3：office_delete 归 EXECUTE（不可逆删除必须逐次审批）
# ---------------------------------------------------------------------------


def test_office_delete_classified_as_execute():
    assert classify_tool("office_delete") is ToolCapability.EXECUTE


def test_office_update_still_write():
    assert classify_tool("office_update") is ToolCapability.WRITE


def test_office_delete_always_asks_in_workspace_write():
    """office_delete 归 EXECUTE：在 WORKSPACE_WRITE 下无论工作区内外都需要
    用户逐次确认（不再区分边界）—— 不可逆删除一律审批。"""
    enforcer = PermissionEnforcer(mode=PermissionMode.WORKSPACE_WRITE, rules=[])
    for path in (None, "/some/workspace/a.xlsx", "/elsewhere/b.xlsx"):
        args = {"file_path": path} if path is not None else {}
        decision = enforcer.check("office_delete", args)
        assert decision.allowed is False
        assert decision.needs_approval is True


# ---------------------------------------------------------------------------
# M0.5：自管理工具在三种模式下的矩阵
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool_name", sorted(SELF_MODIFY_TOOLS))
def test_self_modify_tools_gated_in_workspace_write(tool_name: str):
    enforcer = PermissionEnforcer(mode=PermissionMode.WORKSPACE_WRITE, rules=[])
    decision = enforcer.check(tool_name)
    assert decision.allowed is False
    assert decision.needs_approval is True
    assert "自管理操作" in decision.reason or "修改 Sage 自身" in decision.reason


@pytest.mark.parametrize("tool_name", sorted(SELF_MODIFY_TOOLS))
def test_self_modify_tools_denied_in_read_only(tool_name: str):
    enforcer = PermissionEnforcer(mode=PermissionMode.READ_ONLY, rules=[])
    decision = enforcer.check(tool_name)
    assert decision.allowed is False
    assert decision.needs_approval is False
    assert "read_only" in decision.reason


@pytest.mark.parametrize("tool_name", sorted(SELF_MODIFY_TOOLS))
def test_self_modify_tools_asks_in_prompt(tool_name: str):
    enforcer = PermissionEnforcer(mode=PermissionMode.PROMPT, rules=[])
    decision = enforcer.check(tool_name)
    assert decision.allowed is False
    assert decision.needs_approval is True


@pytest.mark.parametrize("tool_name", sorted(SELF_MODIFY_TOOLS))
def test_self_modify_tools_allowed_in_full_access(tool_name: str):
    enforcer = PermissionEnforcer(mode=PermissionMode.FULL_ACCESS, rules=[])
    decision = enforcer.check(tool_name)
    assert decision.allowed is True
    assert decision.needs_approval is False


def test_self_modify_tool_explicit_allow_rule_wins():
    """显式 allow 规则可以放行自管理工具 —— 用户的持久授权视为知情同意。"""
    from backend.tools.permissions import parse_rules

    rules = parse_rules([{"tool_pattern": "update_sage_config", "decision": "allow"}])
    enforcer = PermissionEnforcer(mode=PermissionMode.WORKSPACE_WRITE, rules=rules)
    decision = enforcer.check("update_sage_config")
    assert decision.allowed is True
    assert decision.needs_approval is False


def test_self_modify_tool_explicit_deny_rule_also_wins():
    """deny 永远胜出：即使 FULL_ACCESS 也能挡。"""
    from backend.tools.permissions import parse_rules

    rules = parse_rules([{"tool_pattern": "update_sage_config", "decision": "deny"}])
    enforcer = PermissionEnforcer(mode=PermissionMode.FULL_ACCESS, rules=rules)
    decision = enforcer.check("update_sage_config")
    assert decision.allowed is False
    assert decision.needs_approval is False


# ---------------------------------------------------------------------------
# M0.6：配置三工具显式登记
# ---------------------------------------------------------------------------


def test_config_tools_classified():
    assert classify_tool("read_sage_config") is ToolCapability.READ
    assert classify_tool("diagnose_sage_config") is ToolCapability.READ
    assert classify_tool("update_sage_config") is ToolCapability.WRITE


def test_read_only_allows_config_reads():
    enforcer = PermissionEnforcer(mode=PermissionMode.READ_ONLY, rules=[])
    for name in ("read_sage_config", "diagnose_sage_config"):
        decision = enforcer.check(name)
        assert decision.allowed is True, f"READ_ONLY 模式应放行只读工具 {name}"


def test_read_only_denies_config_writes():
    enforcer = PermissionEnforcer(mode=PermissionMode.READ_ONLY, rules=[])
    decision = enforcer.check("update_sage_config")
    assert decision.allowed is False


# ---------------------------------------------------------------------------
# M0.2：execute_code RPC 静态拒绝面
# ---------------------------------------------------------------------------


class _RecordingRegistry:
    """返回固定结果但不记录实际调用，便于验证拒绝策略是否触达 registry。"""

    def __init__(self) -> None:
        self.calls: List[str] = []

    def get(self, name: str):
        self.calls.append(name)
        return SimpleNamespace(
            execute=lambda **kw: SimpleNamespace(
                success=True,
                content={"ok": True, "echo": kw},
                output={"ok": True, "echo": kw},
            )
        )


class _MissingRegistry:
    """始终返回 None，模拟 registry 没有该工具。"""

    def __init__(self) -> None:
        self.calls: List[str] = []

    def get(self, name: str):
        self.calls.append(name)


def _call_rpc(
    tool: ExecuteCodeTool,
    registry,
    name: str,
    arguments: Optional[dict] = None,
) -> dict:
    fake_process = SimpleNamespace(stdin=io.StringIO())
    tool._serve_rpc(
        registry,
        fake_process,
        {"id": 1, "name": name, "arguments": arguments or {}},
    )
    fake_process.stdin.seek(0)
    return json.loads(fake_process.stdin.read())


def test_rpc_denies_self_modify_tools():
    registry = _RecordingRegistry()
    tool = ExecuteCodeTool(registry=registry)
    resp = _call_rpc(tool, registry, "update_sage_config", {"key": "foo", "value": 1})
    assert resp["ok"] is False
    assert "自管理工具" in resp["error"]
    assert registry.calls == []


def test_rpc_denies_schedule_cancel():
    registry = _RecordingRegistry()
    tool = ExecuteCodeTool(registry=registry)
    for name in ("schedule_task", "cancel_scheduled_task"):
        resp = _call_rpc(tool, registry, name)
        assert resp["ok"] is False
        assert "自管理工具" in resp["error"]
    assert registry.calls == []


@pytest.mark.parametrize(
    "name",
    [
        "bash",
        "bash_output",
        "kill_shell",
        "repl",
        "execute_code",
        "skill",
        "agent",
        "runtime_exec",
        "browser_launch",
        "browser_login",
        "browser_navigate",
        "office_delete",
    ],
)
def test_rpc_denies_execute_capability_tools(name: str):
    registry = _RecordingRegistry()
    tool = ExecuteCodeTool(registry=registry)
    resp = _call_rpc(tool, registry, name)
    assert resp["ok"] is False
    assert "执行面工具" in resp["error"]
    assert registry.calls == []


def test_rpc_denies_ask_user_question():
    registry = _RecordingRegistry()
    tool = ExecuteCodeTool(registry=registry)
    resp = _call_rpc(tool, registry, "ask_user_question")
    assert resp["ok"] is False
    assert "主循环交互通道" in resp["error"]
    assert registry.calls == []


def test_rpc_allows_read_tools():
    """只读工具可在 RPC 内调用（list_dir / read_file 等）。"""
    registry = _RecordingRegistry()
    tool = ExecuteCodeTool(registry=registry)
    resp = _call_rpc(tool, registry, "read_file", {"path": "/tmp/x"})
    assert resp["ok"] is True
    assert registry.calls == ["read_file"]


def test_rpc_allows_write_tools():
    """写入工具（如 office_update）可在 RPC 内调用。"""
    registry = _RecordingRegistry()
    tool = ExecuteCodeTool(registry=registry)
    resp = _call_rpc(tool, registry, "office_update")
    assert resp["ok"] is True
    assert registry.calls == ["office_update"]


def test_rpc_unknown_tool_still_returns_not_found():
    """未知工具名仍走 registry.get 路径 → '工具不存在' 错误（保留旧行为）。"""
    registry = _MissingRegistry()
    tool = ExecuteCodeTool(registry=registry)
    resp = _call_rpc(tool, registry, "not_a_real_tool")
    assert resp["ok"] is False
    assert "工具不存在" in resp["error"]


def test_rpc_invalid_name_type_rejected():
    registry = _RecordingRegistry()
    tool = ExecuteCodeTool(registry=registry)
    resp = _call_rpc(tool, registry, "", {})
    assert resp["ok"] is False
    assert "非空字符串" in resp["error"]
    assert registry.calls == []
