"""M1 工具安全加固 — PermissionEnforcer 决策矩阵测试。

覆盖: 模式 × 能力矩阵、规则优先级 (deny > allow > ask > 模式)、
fnmatch 通配、未知工具 fail-safe 默认能力、bash 破坏性命令升级安全网、
settings 加载工厂 (load_enforcer_from_settings)。
"""

from __future__ import annotations

import pytest

from backend.tools.bash_validation import validate_bash
from backend.tools.permissions import (
    DEFAULT_PERMISSION_MODE,
    DEFAULT_TOOL_CAPABILITY,
    PermissionEnforcer,
    PermissionMode,
    PermissionRule,
    ToolCapability,
    classify_tool,
    load_enforcer_from_settings,
    parse_rules,
)

pytestmark = pytest.mark.unit


def _enforcer(mode, rules=()):
    return PermissionEnforcer(mode=mode, rules=list(rules), bash_validator=validate_bash)


# ---------------------------------------------------------------------------
# 模式 × 能力矩阵
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "tool", "args", "expect_allowed", "expect_approval"),
    [
        # FULL_ACCESS 普通调用全放行
        (PermissionMode.FULL_ACCESS, "read_file", {}, True, False),
        (PermissionMode.FULL_ACCESS, "write_file", {}, True, False),
        (PermissionMode.FULL_ACCESS, "terminal", {"command": "ls"}, True, False),
        # READ_ONLY: 只读放行, 写/执行拒绝
        (PermissionMode.READ_ONLY, "read_file", {}, True, False),
        (PermissionMode.READ_ONLY, "list_dir", {}, True, False),
        (PermissionMode.READ_ONLY, "write_file", {}, False, False),
        (PermissionMode.READ_ONLY, "terminal", {"command": "ls"}, False, False),
        # WORKSPACE_WRITE: 读/写放行, 执行需审批
        (PermissionMode.WORKSPACE_WRITE, "read_file", {}, True, False),
        (PermissionMode.WORKSPACE_WRITE, "write_file", {}, True, False),
        (PermissionMode.WORKSPACE_WRITE, "terminal", {"command": "ls"}, False, True),
        # PROMPT: 只读放行, 写/执行逐次审批
        (PermissionMode.PROMPT, "read_file", {}, True, False),
        (PermissionMode.PROMPT, "write_file", {}, False, True),
        (PermissionMode.PROMPT, "terminal", {"command": "ls"}, False, True),
        # 未知工具默认 WRITE 能力 (fail-safe)
        (PermissionMode.READ_ONLY, "mystery_tool", {}, False, False),
        (PermissionMode.WORKSPACE_WRITE, "mystery_tool", {}, True, False),
        (PermissionMode.PROMPT, "mystery_tool", {}, False, True),
    ],
)
def test_enforcer_mode_capability_matrix(mode, tool, args, expect_allowed, expect_approval):
    """无规则时, 决策完全由模式 × 能力矩阵决定。"""
    # Arrange
    enforcer = _enforcer(mode)

    # Act
    decision = enforcer.check(tool, args)

    # Assert
    assert decision.allowed is expect_allowed
    assert decision.needs_approval is expect_approval
    assert decision.reason  # 每个分支都必须有可读原因


def test_enforcer_every_decision_carries_human_readable_reason():
    """每个分支的 reason 非空且提及关键上下文。"""
    # Arrange / Act
    deny = _enforcer(PermissionMode.READ_ONLY).check("write_file", {})
    ask = _enforcer(PermissionMode.PROMPT).check("write_file", {})
    allow = _enforcer(PermissionMode.FULL_ACCESS).check("read_file", {})

    # Assert
    assert "read_only" in deny.reason
    assert "prompt" in ask.reason
    assert "full_access" in allow.reason


# ---------------------------------------------------------------------------
# 规则优先级
# ---------------------------------------------------------------------------


def test_enforcer_deny_rule_beats_full_access_mode():
    """deny 规则永远胜出——即使 FULL_ACCESS 模式。"""
    # Arrange
    enforcer = _enforcer(
        PermissionMode.FULL_ACCESS, [PermissionRule("terminal", "deny")]
    )

    # Act
    decision = enforcer.check("terminal", {"command": "ls"})

    # Assert
    assert decision.allowed is False
    assert decision.needs_approval is False
    assert "deny" in decision.reason


def test_enforcer_deny_rule_beats_allow_rule_for_same_tool():
    """同一工具同时命中 deny 和 allow → deny 胜。"""
    # Arrange
    enforcer = _enforcer(
        PermissionMode.WORKSPACE_WRITE,
        [
            PermissionRule("terminal", "allow"),
            PermissionRule("terminal", "deny"),
        ],
    )

    # Act
    decision = enforcer.check("terminal", {"command": "ls"})

    # Assert
    assert decision.allowed is False
    assert "deny" in decision.reason


def test_enforcer_allow_rule_beats_restrictive_mode():
    """allow 规则可以放宽模式矩阵 (read_only 下显式放行写工具)。"""
    # Arrange
    enforcer = _enforcer(
        PermissionMode.READ_ONLY, [PermissionRule("write_file", "allow")]
    )

    # Act
    decision = enforcer.check("write_file", {})

    # Assert
    assert decision.allowed is True
    assert "allow" in decision.reason


def test_enforcer_ask_rule_forces_approval_even_under_full_access():
    """ask 规则把 FULL_ACCESS 下的工具降级为逐次审批。"""
    # Arrange
    enforcer = _enforcer(
        PermissionMode.FULL_ACCESS, [PermissionRule("write_file", "ask")]
    )

    # Act
    decision = enforcer.check("write_file", {})

    # Assert
    assert decision.allowed is False
    assert decision.needs_approval is True


def test_enforcer_wildcard_deny_rule_blocks_everything():
    """'*' deny 规则封锁所有工具。"""
    # Arrange
    enforcer = _enforcer(PermissionMode.FULL_ACCESS, [PermissionRule("*", "deny")])

    # Act / Assert
    for tool in ("read_file", "write_file", "terminal", "unknown_x"):
        decision = enforcer.check(tool, {})
        assert decision.allowed is False, tool


def test_enforcer_fnmatch_pattern_matches_tool_family():
    """fnmatch 通配: office_* 规则覆盖 office_list / office_read。"""
    # Arrange
    enforcer = _enforcer(PermissionMode.READ_ONLY, [PermissionRule("office_*", "deny")])

    # Act / Assert
    assert enforcer.check("office_list", {}).allowed is False
    assert enforcer.check("office_read", {}).allowed is False
    # 不匹配的工具不受影响 (read_file 仍是 READ → read_only 放行)
    assert enforcer.check("read_file", {}).allowed is True


# ---------------------------------------------------------------------------
# bash 破坏性命令升级 (安全网)
# ---------------------------------------------------------------------------


def test_enforcer_destructive_bash_under_full_access_escalates_to_approval():
    """FULL_ACCESS + rm -rf / → 升级 needs_approval (显式安全网)。"""
    # Arrange
    enforcer = _enforcer(PermissionMode.FULL_ACCESS)

    # Act
    decision = enforcer.check("terminal", {"command": "rm -rf /"})

    # Assert
    assert decision.allowed is False
    assert decision.needs_approval is True
    assert "破坏性" in decision.reason


def test_enforcer_destructive_bash_under_read_only_is_denied():
    """READ_ONLY + 破坏性命令 → 直接 deny (不是 ask)。"""
    # Arrange
    enforcer = _enforcer(PermissionMode.READ_ONLY)

    # Act
    decision = enforcer.check("terminal", {"command": "mkfs.ext4 /dev/sda"})

    # Assert
    assert decision.allowed is False
    assert decision.needs_approval is False
    assert "read_only" in decision.reason


def test_enforcer_destructive_bash_beats_explicit_allow_rule():
    """显式 allow 规则也不能放行破坏性命令 (安全网优先)。"""
    # Arrange
    enforcer = _enforcer(
        PermissionMode.WORKSPACE_WRITE, [PermissionRule("terminal", "allow")]
    )

    # Act
    decision = enforcer.check("terminal", {"command": "dd if=/dev/zero of=/dev/sda"})

    # Assert
    assert decision.allowed is False
    assert decision.needs_approval is True
    assert "破坏性" in decision.reason


def test_enforcer_suspicious_bash_does_not_escalate_beyond_mode():
    """SUSPICIOUS (非破坏性) 命令不额外升级: FULL_ACCESS 下仍放行,
    WORKSPACE_WRITE 下按 EXECUTE 常态 needs_approval 并在原因里注明可疑。"""
    # Arrange / Act
    full = _enforcer(PermissionMode.FULL_ACCESS).check(
        "terminal", {"command": "sudo apt install nginx"}
    )
    ws = _enforcer(PermissionMode.WORKSPACE_WRITE).check(
        "terminal", {"command": "sudo apt install nginx"}
    )

    # Assert
    assert full.allowed is True
    assert ws.needs_approval is True
    assert "可疑" in ws.reason


def test_enforcer_terminal_without_command_arg_skips_bash_validation():
    """terminal 调用缺 command 参数时不跑 bash 校验, 走纯模式矩阵。"""
    # Arrange
    enforcer = _enforcer(PermissionMode.WORKSPACE_WRITE)

    # Act
    decision = enforcer.check("terminal", {})

    # Assert
    assert decision.needs_approval is True
    assert "破坏性" not in decision.reason


# ---------------------------------------------------------------------------
# 能力分类与 fail-safe 默认
# ---------------------------------------------------------------------------


def test_classify_tool_known_tools():
    """内置分类表覆盖任务契约中的全部工具。"""
    # Arrange / Act / Assert
    for name in (
        "read_file",
        "list_dir",
        "memory_search",
        "web_search",
        "web_fetch",
        "office_list",
        "office_read",
        "calculator",
    ):
        assert classify_tool(name) is ToolCapability.READ, name
    assert classify_tool("write_file") is ToolCapability.WRITE
    assert classify_tool("terminal") is ToolCapability.EXECUTE


def test_classify_tool_unknown_defaults_to_write_fail_safe():
    """未登记工具默认 WRITE: 不静默放行执行, 也不过度拦截。"""
    # Arrange / Act / Assert
    assert classify_tool("brand_new_tool") is DEFAULT_TOOL_CAPABILITY
    assert DEFAULT_TOOL_CAPABILITY is ToolCapability.WRITE


# ---------------------------------------------------------------------------
# PermissionRule 校验与序列化
# ---------------------------------------------------------------------------


def test_permission_rule_rejects_invalid_decision():
    """非法 decision 值在构造时即报错。"""
    # Arrange / Act / Assert
    with pytest.raises(ValueError, match="decision"):
        PermissionRule("terminal", "maybe")


def test_permission_rule_roundtrip_via_dict():
    """to_dict / from_dict 往返一致。"""
    # Arrange
    rule = PermissionRule("office_*", "ask")

    # Act
    restored = PermissionRule.from_dict(rule.to_dict())

    # Assert
    assert restored == rule


def test_parse_rules_skips_bad_entries_but_keeps_good_ones():
    """parse_rules 容错: 坏条目跳过, 好条目保留, 非 list 回退空。"""
    # Arrange
    raw = [
        {"tool_pattern": "terminal", "decision": "deny"},
        {"tool_pattern": "", "decision": "allow"},  # 空 pattern → 非法
        {"decision": "allow"},  # 缺字段 → 非法
        "not-a-dict",
        {"tool_pattern": "write_file", "decision": "ask"},
    ]

    # Act
    rules = parse_rules(raw)

    # Assert
    assert rules == [
        PermissionRule("terminal", "deny"),
        PermissionRule("write_file", "ask"),
    ]
    assert parse_rules(None) == []
    assert parse_rules({"not": "a list"}) == []


# ---------------------------------------------------------------------------
# settings 工厂
# ---------------------------------------------------------------------------


def test_load_enforcer_from_settings_reads_mode_and_rules():
    """settings 中的 mode + rules 被正确装载。"""
    # Arrange
    from backend.data.settings_repo import SettingsRepository

    repo = SettingsRepository()
    repo.set("permission_mode", "prompt")
    repo.set_json("permission_rules", [{"tool_pattern": "write_file", "decision": "allow"}])

    # Act
    enforcer = load_enforcer_from_settings(repo)

    # Assert
    assert enforcer.mode is PermissionMode.PROMPT
    assert enforcer.rules == (PermissionRule("write_file", "allow"),)
    # 规则生效: prompt 下 write_file 本应 ask, allow 规则放行
    assert enforcer.check("write_file", {}).allowed is True


def test_load_enforcer_from_settings_defaults_when_unset():
    """未配置时回退默认: workspace_write + 无规则。"""
    # Arrange
    from backend.data.settings_repo import SettingsRepository

    repo = SettingsRepository()

    # Act
    enforcer = load_enforcer_from_settings(repo)

    # Assert
    assert enforcer.mode is DEFAULT_PERMISSION_MODE
    assert enforcer.rules == ()


def test_load_enforcer_from_settings_invalid_mode_falls_back():
    """非法 mode 值回退默认而不是抛异常。"""
    # Arrange
    from backend.data.settings_repo import SettingsRepository

    repo = SettingsRepository()
    repo.set("permission_mode", "yolo_mode")

    # Act
    enforcer = load_enforcer_from_settings(repo)

    # Assert
    assert enforcer.mode is DEFAULT_PERMISSION_MODE
