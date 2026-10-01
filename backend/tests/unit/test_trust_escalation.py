"""P2-5 渐进式授权 —— 安全不变式测试。

本模块改的是权限决策路径，**每条不变式都必须有断言**：任何一条被打破都可能
让危险操作被自动放行。

覆盖：
- 默认关闭（未经用户同意的自动放行不允许存在）
- 只认人工批准（auto/trust/timeout 不计入连续次数）
- 遇拒绝即重置、信任不跨会话
- 边界升级 / 破坏性命令 / 无法静态评估的工具永不自动放行
- 计数查询失败 → 继续人工审批（fail-safe 方向不能反）
"""

from __future__ import annotations

import pytest

from backend.data.approval_decision_repo import ApprovalDecisionRepository
from backend.services import trust_escalation as te
from backend.services.trust_escalation import (
    TrustEscalationEnforcer,
    build_trust_enforcer,
    load_trust_policy,
)
from backend.tools.bash_validation import validate_bash
from backend.tools.permissions import (
    PermissionDecision,
    PermissionEnforcer,
    PermissionMode,
    ToolCapability,
    classify_tool,
)


class _StubRepo:
    """最小 SettingsRepository 替身。"""

    def __init__(self, values=None):
        self.values = dict(values or {})
        self.written = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value, category=None):
        self.written[key] = value
        self.values[key] = value


@pytest.fixture
def stub_repo(monkeypatch):
    repo = _StubRepo()
    monkeypatch.setattr("backend.data.settings_repo.SettingsRepository", lambda: repo)
    return repo


@pytest.fixture
def base_enforcer():
    return PermissionEnforcer(
        mode=PermissionMode.WORKSPACE_WRITE,
        rules=(),
        bash_validator=validate_bash,
    )


@pytest.fixture
def trust_env(monkeypatch):
    """把信任数据源替换成可控桩：连续次数 / 会话 id / 落库记录。"""

    state = {"count": 0, "session": "s1", "recorded": []}

    monkeypatch.setattr(te, "_current_session_id", lambda: state["session"])
    monkeypatch.setattr(te, "_consecutive_approvals", lambda s, t: state["count"])
    monkeypatch.setattr(
        te, "_record_trust_release", lambda tool, n: state["recorded"].append((tool, n))
    )
    return state


def _gui(repo, tool, *, session="s1", approved=True, n=1):
    for _ in range(n):
        repo.append(
            tool_name=tool,
            approved=approved,
            answered_by="gui",
            session_id=session,
            risk="safe",
        )


# ── 计数口径 ────────────────────────────────────────────────────────────


def test_consecutive_counts_gui_approvals():
    repo = ApprovalDecisionRepository()
    _gui(repo, "edit_file", n=3)
    assert repo.consecutive_gui_approvals("s1", "edit_file") == 3


def test_denial_resets_the_streak():
    """拒绝在最前 → 连续计数归零。用户拒绝过一次就说明判断变了。"""
    repo = ApprovalDecisionRepository()
    _gui(repo, "edit_file", n=3)
    repo.append(
        tool_name="edit_file", approved=False, answered_by="gui", session_id="s1", risk="safe"
    )
    assert repo.consecutive_gui_approvals("s1", "edit_file") == 0


def test_non_gui_decisions_do_not_count():
    """auto/trust 放行不能自我强化 —— 那不是「用户表达过同意」。"""
    repo = ApprovalDecisionRepository()
    _gui(repo, "edit_file", n=1)
    repo.append(
        tool_name="edit_file", approved=True, answered_by="trust", session_id="s1", risk="safe"
    )
    assert repo.consecutive_gui_approvals("s1", "edit_file") == 0


def test_trust_is_session_scoped():
    repo = ApprovalDecisionRepository()
    _gui(repo, "edit_file", session="s1", n=5)
    assert repo.consecutive_gui_approvals("s1", "edit_file") == 5
    assert repo.consecutive_gui_approvals("s2", "edit_file") == 0


def test_empty_inputs_return_zero():
    repo = ApprovalDecisionRepository()
    assert repo.consecutive_gui_approvals("", "edit_file") == 0
    assert repo.consecutive_gui_approvals("s1", "") == 0


def test_query_failure_falls_back_to_zero(monkeypatch):
    """DB 故障时降级方向必须是「继续问人」。"""

    class _Broken:
        def __init__(self):
            self.db = self

        def get_connection(self):
            raise RuntimeError("db down")

    repo = ApprovalDecisionRepository()
    monkeypatch.setattr(repo, "db", _Broken())
    assert repo.consecutive_gui_approvals("s1", "edit_file") == 0


# ── 策略开关 ────────────────────────────────────────────────────────────


def test_policy_defaults_to_disabled(stub_repo):
    enabled, threshold = load_trust_policy()
    assert enabled is False
    assert threshold == te.DEFAULT_TRUST_THRESHOLD


def test_policy_reads_stored_values(stub_repo):
    stub_repo.values[te.SETTINGS_KEY_ENABLED] = "1"
    stub_repo.values[te.SETTINGS_KEY_THRESHOLD] = "5"
    enabled, threshold = load_trust_policy()
    assert enabled is True
    assert threshold == 5


def test_bad_threshold_falls_back_to_default(stub_repo):
    stub_repo.values[te.SETTINGS_KEY_THRESHOLD] = "abc"
    _, threshold = load_trust_policy()
    assert threshold == te.DEFAULT_TRUST_THRESHOLD


def test_build_returns_none_when_disabled(base_enforcer, stub_repo):
    """默认关闭时**不包装** —— 行为必须与本模块存在前逐位一致。"""
    assert build_trust_enforcer(base_enforcer) is None


def test_build_wraps_when_enabled(base_enforcer, stub_repo):
    stub_repo.values[te.SETTINGS_KEY_ENABLED] = "1"
    wrapped = build_trust_enforcer(base_enforcer)
    assert isinstance(wrapped, TrustEscalationEnforcer)


def test_build_clamps_threshold(stub_repo):
    stub_repo.values[te.SETTINGS_KEY_ENABLED] = "1"
    stub_repo.values[te.SETTINGS_KEY_THRESHOLD] = "0"
    _, threshold = load_trust_policy()
    assert threshold == 1


# ── enforcer 行为 ────────────────────────────────────────────────────────


def test_write_file_needs_no_approval_in_workspace_write(base_enforcer, trust_env):
    """sanity：workspace_write 下写类工具本就不需审批，包装器原样透传。

    渐进式授权只作用在 base 判定 needs_approval 的场景；给不需要审批的调用
    加后缀反而会污染审计语义。
    """
    trust_env["count"] = 99
    enforcer = TrustEscalationEnforcer(base_enforcer, threshold=3)
    decision = enforcer.check("write_file", {"path": "a.txt", "content": "x"})
    assert decision.needs_approval is False
    assert te._TRUST_REASON_SUFFIX not in (decision.reason or "")
    assert trust_env["recorded"] == []


def test_releases_after_threshold(base_enforcer, trust_env):
    # bash 在 workspace_write 下需要审批 —— 这才是渐进式授权的作用面
    trust_env["count"] = 3
    enforcer = TrustEscalationEnforcer(base_enforcer, threshold=3)
    decision = enforcer.check("bash", {"command": "ls -la"})
    assert decision.allowed is True
    assert decision.needs_approval is False
    assert te._TRUST_REASON_SUFFIX in (decision.reason or "")
    # 放行必须落审计，便于事后区分「用户点的」与「系统放行的」
    assert trust_env["recorded"] == [("bash", 3)]


def test_keeps_asking_below_threshold(base_enforcer, trust_env):
    trust_env["count"] = 2
    enforcer = TrustEscalationEnforcer(base_enforcer, threshold=3)
    decision = enforcer.check("bash", {"command": "ls -la"})
    assert decision.needs_approval is True
    assert trust_env["recorded"] == []


def test_never_upgrades_a_deny(trust_env):
    """deny 永远胜出 —— 包装器只在 needs_approval 时改写。"""
    trust_env["count"] = 99

    class _Deny(PermissionEnforcer):
        def check(self, tool_name, args=None):
            return PermissionDecision(allowed=False, needs_approval=False, reason="规则拒绝")

    denying = TrustEscalationEnforcer(_Deny(mode=PermissionMode.FULL_ACCESS, rules=()), threshold=3)
    decision = denying.check("write_file", {"path": "a.txt"})
    assert decision.allowed is False
    assert decision.needs_approval is False
    assert trust_env["recorded"] == []


def test_destructive_command_never_auto_released(base_enforcer, trust_env):
    trust_env["count"] = 99
    enforcer = TrustEscalationEnforcer(base_enforcer, threshold=3)
    decision = enforcer.check("bash", {"command": "rm -rf /"})
    assert decision.needs_approval is True
    assert trust_env["recorded"] == []


def test_safe_command_can_be_released(base_enforcer, trust_env):
    trust_env["count"] = 99
    enforcer = TrustEscalationEnforcer(base_enforcer, threshold=3)
    decision = enforcer.check("bash", {"command": "ls -la"})
    assert decision.needs_approval is False


def test_execute_without_command_stays_manual(base_enforcer, trust_env):
    """skill / repl 无法静态评估风险 → 保守转人工。"""
    trust_env["count"] = 99
    enforcer = TrustEscalationEnforcer(base_enforcer, threshold=3)
    decision = enforcer.check("repl", {})
    assert decision.needs_approval is True


def test_no_session_context_stays_manual(base_enforcer, trust_env):
    trust_env["count"] = 99
    trust_env["session"] = None
    enforcer = TrustEscalationEnforcer(base_enforcer, threshold=3)
    decision = enforcer.check("bash", {"command": "ls -la"})
    assert decision.needs_approval is True
    assert trust_env["recorded"] == []


def test_mode_and_rules_delegate_to_base(base_enforcer, trust_env):
    enforcer = TrustEscalationEnforcer(base_enforcer, threshold=3)
    assert enforcer.mode == base_enforcer.mode
    assert enforcer.rules == base_enforcer.rules


def test_tool_capability_classification_is_unchanged():
    """sanity：包装器依赖的分类入口存在且行为稳定。"""
    assert classify_tool("write_file") is ToolCapability.WRITE
