# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""分发前门控链测试（DSH 对标 R5，GT1）。

覆盖 `_pre_dispatch_gate`：白名单拒绝（含 enforcer 仍被调用的顺序保持）、
放行记账（S3 台账）、needs_approval 不记账、enforcer 拒绝不记账、
无白名单配置直通。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.core.legacy.agent import SageAgent

pytestmark = pytest.mark.unit


def _tc(name):
    tc = MagicMock()
    tc.name = name
    return tc


def _decision(allowed=True, needs_approval=False):
    d = MagicMock()
    d.allowed = allowed
    d.needs_approval = needs_approval
    d.reason = "test-reason"
    return d


def _agent(profile=None):
    agent = SageAgent()
    agent.profile = profile
    return agent


class TestPreDispatchGate:
    def test_whitelist_deny(self):
        agent = _agent({"tools": ["list_dir"]})
        enforcer = MagicMock()
        enforcer.check.return_value = _decision(allowed=True)
        decision, content = agent._pre_dispatch_gate(
            _tc("bash"), {"cmd": "x"}, enforcer, "sess-1"
        )
        assert decision.allowed is False
        assert decision.needs_approval is False
        assert "未对当前 Agent 开放" in content
        assert "bash" in content
        # 顺序保持：白名单拒绝时 enforcer.check 仍被调用（既有副作用顺序）
        enforcer.check.assert_called_once()


class TestBuildApprovalRequestPluginName:
    def test_published_plugin_tool_carries_authoritative_plugin_name(self):
        agent = _agent(None)
        bridge = MagicMock()
        bridge.published_tool.return_value = SimpleNamespace(plugin_name="demo")

        with patch(
            "backend.plugins.tool_bridge.get_plugin_tool_bridge",
            return_value=bridge,
        ):
            req = agent._build_approval_request(
                "plugin__demo__hello",
                {},
                _decision(allowed=False, needs_approval=True),
            )

        bridge.published_tool.assert_called_once_with("plugin__demo__hello")
        assert req.plugin_name == "demo"
        assert req.to_dict()["plugin_name"] == "demo"

    def test_unpublished_plugin_tool_has_no_plugin_scope_metadata(self):
        agent = _agent(None)
        bridge = MagicMock()
        bridge.published_tool.return_value = None

        with patch(
            "backend.plugins.tool_bridge.get_plugin_tool_bridge",
            return_value=bridge,
        ):
            req = agent._build_approval_request(
                "plugin__demo__hello",
                {},
                _decision(allowed=False, needs_approval=True),
            )

        assert req.plugin_name is None
        assert "plugin_name" not in req.to_dict()

    def test_non_plugin_tool_does_not_query_bridge(self):
        agent = _agent(None)

        with patch(
            "backend.plugins.tool_bridge.get_plugin_tool_bridge"
        ) as getter:
            req = agent._build_approval_request(
                "bash",
                {"command": "ls"},
                _decision(allowed=False, needs_approval=True),
            )

        getter.assert_not_called()
        assert req.plugin_name is None

    def test_pre_dispatch_passes_authoritative_plugin_name_to_enforcer(self):
        agent = _agent(None)
        bridge = MagicMock()
        bridge.published_tool.return_value = SimpleNamespace(plugin_name="demo")
        enforcer = MagicMock()
        enforcer.check.return_value = _decision(
            allowed=False, needs_approval=True
        )

        with patch(
            "backend.plugins.tool_bridge.get_plugin_tool_bridge",
            return_value=bridge,
        ):
            agent._pre_dispatch_gate(
                _tc("plugin__demo__hello"), {}, enforcer, "sess-1"
            )

        bridge.published_tool.assert_called_once_with("plugin__demo__hello")
        enforcer.check.assert_called_once_with(
            "plugin__demo__hello", {}, plugin_name="demo"
        )

    def test_pre_dispatch_unpublished_plugin_keeps_legacy_check_call(self):
        agent = _agent(None)
        bridge = MagicMock()
        bridge.published_tool.return_value = None
        enforcer = MagicMock()
        enforcer.check.return_value = _decision(
            allowed=False, needs_approval=True
        )

        with patch(
            "backend.plugins.tool_bridge.get_plugin_tool_bridge",
            return_value=bridge,
        ):
            agent._pre_dispatch_gate(
                _tc("plugin__demo__hello"), {}, enforcer, "sess-1"
            )

        enforcer.check.assert_called_once_with("plugin__demo__hello", {})

    def test_plugin_wildcard_passes_profile_gate_r92(self):
        # 通配内工具不被 profile 白名单拒绝；用 needs_approval 决策同时
        # 证明通配不绕过后续审批（拒绝时会覆盖为 allowed=False）。
        for pattern in ("plugin__demo__*", "plugin__*"):
            agent = _agent({"tools": [pattern]})
            enforcer = MagicMock()
            enforcer.check.return_value = _decision(
                allowed=True, needs_approval=True
            )
            decision, content = agent._pre_dispatch_gate(
                _tc("plugin__demo__hello"), {}, enforcer, "sess-1"
            )
            assert decision.needs_approval is True
            assert content == ""
            enforcer.check.assert_called_once()

    def test_plugin_wildcard_other_plugin_still_denied_r92(self):
        agent = _agent({"tools": ["plugin__demo__*"]})
        enforcer = MagicMock()
        enforcer.check.return_value = _decision(allowed=True)
        decision, content = agent._pre_dispatch_gate(
            _tc("plugin__other__hello"), {}, enforcer, "sess-1"
        )
        assert decision.allowed is False
        assert decision.needs_approval is False
        assert "plugin__other__hello" in content
        enforcer.check.assert_called_once()

    def test_whitelist_pass_records_auto_approval(self):
        agent = _agent({"tools": ["list_dir"]})
        enforcer = MagicMock()
        enforcer.check.return_value = _decision(allowed=True, needs_approval=False)
        enforcer.mode = MagicMock(value="default")
        with patch(
            "backend.services.auto_approval_ledger.get_auto_approval_ledger"
        ) as getter:
            decision, content = agent._pre_dispatch_gate(
                _tc("list_dir"), {"path": "x"}, enforcer, "sess-1"
            )
            getter.return_value.record.assert_called_once()
            record_kwargs = getter.return_value.record.call_args.kwargs
            assert record_kwargs["session_id"] == "sess-1"
            assert record_kwargs["tool_name"] == "list_dir"
        assert decision.allowed is True
        assert content == ""

    def test_needs_approval_skips_ledger(self):
        agent = _agent(None)
        enforcer = MagicMock()
        enforcer.check.return_value = _decision(allowed=True, needs_approval=True)
        enforcer.mode = MagicMock(value="default")
        with patch(
            "backend.services.auto_approval_ledger.get_auto_approval_ledger"
        ) as getter:
            decision, content = agent._pre_dispatch_gate(
                _tc("bash"), {"cmd": "x"}, enforcer, "sess-1"
            )
            getter.return_value.record.assert_not_called()
        assert decision.needs_approval is True
        assert content == ""

    def test_enforcer_deny_skips_ledger(self):
        agent = _agent(None)
        enforcer = MagicMock()
        enforcer.check.return_value = _decision(allowed=False, needs_approval=False)
        enforcer.mode = MagicMock(value="default")
        with patch(
            "backend.services.auto_approval_ledger.get_auto_approval_ledger"
        ) as getter:
            decision, content = agent._pre_dispatch_gate(
                _tc("bash"), {"cmd": "x"}, enforcer, "sess-1"
            )
            getter.return_value.record.assert_not_called()
        assert decision.allowed is False
        assert content == ""  # 拒绝文案由 run_loop 按 decision.reason 组装

    def test_no_whitelist_config_passes_through(self):
        agent = _agent(None)
        enforcer = MagicMock()
        enforcer.check.return_value = _decision(allowed=True, needs_approval=False)
        enforcer.mode = MagicMock(value="default")
        with patch(
            "backend.services.auto_approval_ledger.get_auto_approval_ledger"
        ) as getter:
            decision, content = agent._pre_dispatch_gate(
                _tc("any"), {}, enforcer, "sess-1"
            )
            getter.return_value.record.assert_called_once()
        assert decision.allowed is True
        assert content == ""

    def test_ledger_failure_never_breaks_gate(self):
        """S3 台账故障 fail-safe：不影响门控判定。"""
        agent = _agent(None)
        enforcer = MagicMock()
        enforcer.check.return_value = _decision(allowed=True, needs_approval=False)
        enforcer.mode = MagicMock(value="default")
        with patch(
            "backend.services.auto_approval_ledger.get_auto_approval_ledger",
            side_effect=RuntimeError("ledger down"),
        ):
            decision, content = agent._pre_dispatch_gate(
                _tc("any"), {}, enforcer, "sess-1"
            )
        assert decision.allowed is True
        assert content == ""
