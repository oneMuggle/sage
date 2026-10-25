"""R105 会话级权限规则：存储语义 + enforcer 合并裁决单测。"""

from __future__ import annotations

import contextlib
from typing import Iterator, List

import pytest

from backend.tools.context import (
    ToolExecutionContext,
    reset_tool_context,
    set_tool_context,
)
from backend.tools.permissions import (
    PermissionEnforcer,
    PermissionMode,
    PermissionRule,
    clear_session_rules,
    remember_session_rule,
    session_rules_for,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean_session_rules() -> Iterator[None]:
    clear_session_rules()
    yield
    clear_session_rules()


@contextlib.contextmanager
def _session(session_id: str) -> Iterator[None]:
    token = set_tool_context(
        ToolExecutionContext(
            session_id=session_id,
            stream_id="test-stream",
            binding_generation=0,
            office_doc_scope=frozenset(),
        )
    )
    try:
        yield
    finally:
        reset_tool_context(token)


def _enforcer(rules: List[PermissionRule]) -> PermissionEnforcer:
    return PermissionEnforcer(mode=PermissionMode.PROMPT, rules=rules)


# --- 存储语义 ---------------------------------------------------------------


def test_store_dedupes_identical_rule() -> None:
    rule = PermissionRule("bash", "allow")
    assert remember_session_rule("s1", rule) is True
    assert remember_session_rule("s1", rule) is False
    assert remember_session_rule("s1", PermissionRule("bash", "deny")) is True
    assert session_rules_for("s1") == (rule, PermissionRule("bash", "deny"))


def test_store_isolates_sessions_and_ignores_empty_id() -> None:
    assert remember_session_rule("", PermissionRule("bash", "allow")) is False
    assert session_rules_for("") == ()
    assert session_rules_for(None) == ()
    remember_session_rule("s1", PermissionRule("bash", "allow"))
    assert session_rules_for("s2") == ()


def test_clear_session_rules_scoped_and_global() -> None:
    remember_session_rule("s1", PermissionRule("bash", "allow"))
    remember_session_rule("s2", PermissionRule("bash", "deny"))
    clear_session_rules("s1")
    assert session_rules_for("s1") == ()
    assert session_rules_for("s2") == (PermissionRule("bash", "deny"),)
    clear_session_rules()
    assert session_rules_for("s2") == ()


def test_store_caps_sessions_and_rules() -> None:
    for i in range(65):
        remember_session_rule(f"s{i}", PermissionRule("bash", "allow"))
    assert session_rules_for("s0") == ()  # 最久未用的会话被淘汰
    assert session_rules_for("s64") == (PermissionRule("bash", "allow"),)
    for i in range(201):
        remember_session_rule("big", PermissionRule(f"tool_{i}", "allow"))
    rules = session_rules_for("big")
    assert len(rules) == 200
    assert rules[0] == PermissionRule("tool_1", "allow")


# --- enforcer 合并裁决 ------------------------------------------------------


def test_session_allow_applies_only_with_matching_context() -> None:
    remember_session_rule("s1", PermissionRule("bash", "allow"))
    enforcer = _enforcer([])
    decision = enforcer.check("bash")
    assert decision.needs_approval is True  # 无上下文：与从前一致
    with _session("s2"):
        decision = enforcer.check("bash")
    assert decision.needs_approval is True  # 异会话不生效
    with _session("s1"):
        decision = enforcer.check("bash")
    assert decision.allowed is True
    assert decision.needs_approval is False


def test_session_deny_beats_persistent_allow() -> None:
    remember_session_rule("s1", PermissionRule("bash", "deny"))
    enforcer = _enforcer([PermissionRule("bash", "allow")])
    with _session("s1"):
        decision = enforcer.check("bash")
    assert decision.allowed is False
    assert decision.needs_approval is False


def test_persistent_deny_beats_session_allow() -> None:
    remember_session_rule("s1", PermissionRule("bash", "allow"))
    enforcer = _enforcer([PermissionRule("bash", "deny")])
    with _session("s1"):
        decision = enforcer.check("bash")
    assert decision.allowed is False
    assert decision.needs_approval is False


def test_session_allow_beats_persistent_ask() -> None:
    remember_session_rule("s1", PermissionRule("bash", "allow"))
    enforcer = _enforcer([PermissionRule("bash", "ask")])
    with _session("s1"):
        decision = enforcer.check("bash")
    assert decision.allowed is True
    assert decision.needs_approval is False


def test_session_plugin_wildcard_requires_authoritative_identity() -> None:
    remember_session_rule("s1", PermissionRule("plugin__demo__*", "deny"))
    enforcer = _enforcer([])
    with _session("s1"):
        denied = enforcer.check("plugin__demo__hello", plugin_name="demo")
        anonymous = enforcer.check("plugin__demo__hello")
        other = enforcer.check("plugin__demo__hello", plugin_name="other")
    assert (denied.allowed, denied.needs_approval) == (False, False)
    assert (anonymous.allowed, anonymous.needs_approval) != (False, False)
    assert (other.allowed, other.needs_approval) != (False, False)
