"""R150 — 子代理自动批准包装器（AutoApproveEnforcer）单元测试。

安全不变式：deny 永远胜出；边界类升级永不自动批准；执行面危险命令
保留人工；无法评估风险的执行面工具保守转人工；非危险自动批准并打
auto 标记。base/分类器/校验器/审计 repo 全 monkeypatch。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.orchestration import subagent_approval as sa
from backend.orchestration.subagent_approval import (
    AutoApproveEnforcer,
    build_subagent_enforcer,
)
from backend.tools.bash_validation import BashRisk
from backend.tools.permissions import PermissionDecision, ToolCapability

pytestmark = pytest.mark.unit


def _decision(allowed=True, needs_approval=False, reason=""):
    return PermissionDecision(allowed=allowed, needs_approval=needs_approval, reason=reason)


class _FakeBase:
    def __init__(self, decision, mode="workspace_write"):
        self._decision = decision
        self.mode = mode
        self.rules = {"r": 1}
        self.check_calls = []

    def check(self, tool_name, args=None):
        self.check_calls.append((tool_name, args))
        return self._decision


@pytest.fixture(autouse=True)
def _no_audit(monkeypatch):
    """审计 repo 抛错必须被吞掉（全吞降级语义）。"""
    monkeypatch.setattr(
        sa, "_record_auto_approval", lambda tool_name: None
    )


def _patch_classify(monkeypatch, capability):
    monkeypatch.setattr(sa, "classify_tool", lambda name: capability)


def _patch_validate(monkeypatch, risk):
    validation = SimpleNamespace(risk=risk)
    monkeypatch.setattr(sa, "validate_bash", lambda command: validation)


# ---------------------------------------------------------------------------
# 透传语义
# ---------------------------------------------------------------------------


def test_allow_passthrough_untouched(monkeypatch):
    base = _FakeBase(_decision(allowed=True, needs_approval=False, reason="ok"))
    wrapper = AutoApproveEnforcer(base)
    out = wrapper.check("read_file", {})
    assert out is base._decision  # 原样透传，不加 auto 后缀


def test_deny_always_wins(monkeypatch):
    _patch_classify(monkeypatch, ToolCapability.WRITE)
    base = _FakeBase(_decision(allowed=False, needs_approval=False, reason="deny"))
    wrapper = AutoApproveEnforcer(base)
    out = wrapper.check("write_file", {})
    assert out is base._decision  # deny 不被改写


def test_mode_and_rules_delegate_to_base():
    base = _FakeBase(_decision(), mode="autopilot_test")
    wrapper = AutoApproveEnforcer(base)
    assert wrapper.mode == "autopilot_test"
    assert wrapper.rules == {"r": 1}


# ---------------------------------------------------------------------------
# 边界类升级：永不自动批准
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("reason", ["写入工作区外路径", "边界解析失败", "路径在边界之外"])
def test_boundary_upgrade_keeps_manual(monkeypatch, reason):
    _patch_classify(monkeypatch, ToolCapability.WRITE)
    base = _FakeBase(_decision(allowed=False, needs_approval=True, reason=reason))
    wrapper = AutoApproveEnforcer(base)
    out = wrapper.check("write_file", {})
    assert out.needs_approval is True
    assert out.allowed is False


# ---------------------------------------------------------------------------
# 自动批准
# ---------------------------------------------------------------------------


def test_write_tool_needs_approval_auto_approved(monkeypatch):
    _patch_classify(monkeypatch, ToolCapability.WRITE)
    base = _FakeBase(_decision(allowed=False, needs_approval=True, reason="write mode gate"))
    wrapper = AutoApproveEnforcer(base)
    out = wrapper.check("write_file", {})
    assert out.allowed is True
    assert out.needs_approval is False
    assert out.reason.endswith("（编排自动批准 auto）")


def test_execute_missing_command_keeps_manual(monkeypatch):
    _patch_classify(monkeypatch, ToolCapability.EXECUTE)
    base = _FakeBase(_decision(allowed=False, needs_approval=True, reason="exec gate"))
    wrapper = AutoApproveEnforcer(base)
    out = wrapper.check("skill", {})
    assert out.needs_approval is True  # 无法评估 → 保守转人工


def test_execute_blank_command_keeps_manual(monkeypatch):
    _patch_classify(monkeypatch, ToolCapability.EXECUTE)
    base = _FakeBase(_decision(allowed=False, needs_approval=True, reason="exec gate"))
    wrapper = AutoApproveEnforcer(base)
    out = wrapper.check("bash", {"command": "   "})
    assert out.needs_approval is True


@pytest.mark.parametrize("risk", [BashRisk.DESTRUCTIVE, BashRisk.SUSPICIOUS])
def test_dangerous_commands_keep_manual(monkeypatch, risk):
    _patch_classify(monkeypatch, ToolCapability.EXECUTE)
    _patch_validate(monkeypatch, risk)
    base = _FakeBase(_decision(allowed=False, needs_approval=True, reason="exec gate"))
    wrapper = AutoApproveEnforcer(base)
    out = wrapper.check("bash", {"command": "rm -rf /"})
    assert out.needs_approval is True


def test_safe_command_auto_approved(monkeypatch):
    _patch_classify(monkeypatch, ToolCapability.EXECUTE)
    _patch_validate(monkeypatch, BashRisk.SAFE)
    base = _FakeBase(_decision(allowed=False, needs_approval=True, reason="exec gate"))
    wrapper = AutoApproveEnforcer(base)
    out = wrapper.check("bash", {"command": "echo hi"})
    assert out.allowed is True
    assert out.needs_approval is False
    assert "auto" in out.reason


# ---------------------------------------------------------------------------
# 审计降级与工厂
# ---------------------------------------------------------------------------


def test_record_auto_approval_swallows_repo_errors(monkeypatch):
    import backend.data.approval_decision_repo as repo_mod
    import backend.tools.context as ctx_mod

    class _Boom:
        def append(self, **kwargs):
            raise RuntimeError("db down")

    monkeypatch.setattr(repo_mod, "ApprovalDecisionRepository", _Boom)
    monkeypatch.setattr(ctx_mod, "current_tool_context", lambda: None)
    # 不抛错即通过（审计降级不阻塞执行）
    sa._record_auto_approval("bash")


def test_build_subagent_enforcer_non_auto_returns_none():
    assert build_subagent_enforcer("manual") is None
    assert build_subagent_enforcer("") is None


def test_build_subagent_enforcer_auto_wraps_base(monkeypatch):
    base = _FakeBase(_decision())
    monkeypatch.setattr(
        "backend.tools.permissions.load_enforcer_from_settings", lambda: base
    )
    wrapper = build_subagent_enforcer("auto")
    assert isinstance(wrapper, AutoApproveEnforcer)


def test_build_subagent_enforcer_load_failure_returns_none(monkeypatch):
    def boom():
        raise RuntimeError("settings broken")

    monkeypatch.setattr(
        "backend.tools.permissions.load_enforcer_from_settings", boom
    )
    assert build_subagent_enforcer("auto") is None
