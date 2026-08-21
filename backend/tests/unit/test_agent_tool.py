"""
M5 — AgentTool (in-loop sub-agent) unit tests.

- mocked LLM sub-agent → answer returned + lane created SUCCEEDED
- sub-agent tool whitelist is strictly read-only (no terminal/write/agent)
- sub-agent attempting terminal → registry rejects (tool not found), loop recovers
- LLM failure → error ToolResult, caller (primary loop) continues
- output cap (20_000 chars) enforced
- no LLM configured → clean error ToolResult
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import backend.tools.agent_tool as agent_tool_module
from backend.core.legacy.llm_client import LLMResponse, LLMToolCall
from backend.orchestration.lane_registry import LaneRegistry
from backend.orchestration.models import LaneStatus
from backend.tools.agent_tool import (
    SUBAGENT_ANSWER_CAP,
    AgentTool,
    build_readonly_tool_registry,
)
from backend.tools.base import ToolResult


def _done_response(content: str) -> LLMResponse:
    return LLMResponse(content=content, finish_reason="stop", tool_calls=[])


def _tool_call_response(name: str, arguments: dict) -> LLMResponse:
    return LLMResponse(
        content="",
        finish_reason="tool_calls",
        tool_calls=[LLMToolCall(id="call_1", name=name, arguments=json.dumps(arguments))],
    )


def _mock_sub_llm(*responses: LLMResponse) -> MagicMock:
    """Mock LLM client: run_loop calls ``client.chat(...)``."""
    client = MagicMock()
    client.chat = AsyncMock(side_effect=list(responses))
    return client


class TestReadonlyWhitelist:
    def test_default_registries_use_distinct_restrictive_scratch_roots(self):
        first = build_readonly_tool_registry()
        second = build_readonly_tool_registry()

        first_root = Path(first.get("read_file")._policy.workspace_root)
        second_root = Path(second.get("read_file")._policy.workspace_root)

        assert first_root != second_root
        assert first_root.is_dir() and second_root.is_dir()
        assert first_root.stat().st_mode & 0o777 == 0o700
        assert second_root.stat().st_mode & 0o777 == 0o700

        agent_tool_module._cleanup_subagent_workspace(first_root)
        agent_tool_module._cleanup_subagent_workspace(second_root)

    def test_default_registry_does_not_reuse_preexisting_unsafe_root(self, monkeypatch, tmp_path):
        unsafe = tmp_path / "sage-subagent-scratch"
        unsafe.mkdir(mode=0o755)
        symlink = tmp_path / "sage-subagent-link"
        symlink.symlink_to(tmp_path)
        monkeypatch.setattr(agent_tool_module.tempfile, "gettempdir", lambda: str(tmp_path))

        registry = build_readonly_tool_registry()
        root = Path(registry.get("read_file")._policy.workspace_root)

        assert root not in (unsafe, symlink)
        assert root.stat().st_mode & 0o777 == 0o700
        agent_tool_module._cleanup_subagent_workspace(root)

    def test_explicit_workspace_is_not_owned_or_deleted(self, tmp_path):
        workspace = tmp_path / "caller-workspace"
        workspace.mkdir(mode=0o700)

        registry = build_readonly_tool_registry(
            policy=agent_tool_module.ToolPolicy(workspace_root=str(workspace))
        )
        agent_tool_module._cleanup_subagent_workspace(
            getattr(registry, "_owned_workspace_root", None)
        )

        assert workspace.is_dir()

    def test_whitelist_is_read_only(self):
        """Registry exposes exactly the six read-only tools — nothing else."""
        registry = build_readonly_tool_registry()

        names = set(registry.list_names())
        assert names == {
            "read_file",
            "list_dir",
            "web_search",
            "web_fetch",
            "memory_search",
            "calculator",
        }
        # Never granted to sub-agents.
        for dangerous in ("terminal", "write_file", "memory_save", "agent", "office_read"):
            assert registry.get(dangerous) is None


    def test_subagent_file_tools_reject_outside_traversal_and_symlink(self, tmp_path):
        root = tmp_path / "scratch"
        root.mkdir()
        outside = tmp_path / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        link = root / "escape.txt"
        link.symlink_to(outside)
        registry = build_readonly_tool_registry(
            policy=agent_tool_module.ToolPolicy(workspace_root=str(root))
        )

        absolute = registry.get("read_file").execute(path=str(outside))
        traversal = registry.get("read_file").execute(path=str(root / ".." / "outside.txt"))
        symlink = registry.get("read_file").execute(path=str(link))
        listed = registry.get("list_dir").execute(path=str(tmp_path))

        assert all(not result.success for result in (absolute, traversal, symlink, listed))
        assert all("path_outside_workspace" in result.error for result in (absolute, traversal, symlink, listed))

    def test_success_returns_answer_and_creates_succeeded_lane(self):
        tool = AgentTool(llm_client=_mock_sub_llm(_done_response("sub answer: 42")))

        result = tool.execute(description="Compute answer", prompt="What is 6*7?")

        assert isinstance(result, ToolResult)
        assert result.success is True
        assert result.content["answer"] == "sub answer: 42"
        assert result.content["truncated"] is False

        lane = LaneRegistry().get_lane(result.content["lane_id"])
        assert lane is not None
        assert lane.status == LaneStatus.SUCCEEDED
        assert lane.agent_id == "subagent"
        assert lane.metadata.get("source") == "subagent"

    def test_subagent_terminal_call_rejected_and_loop_recovers(self):
        """Sub LLM tries terminal → not registered → error fed back, loop DONEs."""
        sub_llm = _mock_sub_llm(
            _tool_call_response("terminal", {"command": "rm -rf /"}),
            _done_response("recovered answer"),
        )
        tool = AgentTool(llm_client=sub_llm)

        result = tool.execute(description="Naughty", prompt="do something")

        # The loop survived the rejected tool call and still produced an answer.
        assert result.success is True
        assert result.content["answer"] == "recovered answer"
        # Two LLM turns: the tool-call attempt and the recovery.
        assert sub_llm.chat.await_count == 2
        lane = LaneRegistry().get_lane(result.content["lane_id"])
        assert lane.status == LaneStatus.SUCCEEDED

    def test_llm_failure_returns_error_result_and_failed_lane(self):
        sub_llm = MagicMock()
        sub_llm.chat = AsyncMock(side_effect=RuntimeError("llm exploded"))
        tool = AgentTool(llm_client=sub_llm)

        result = tool.execute(description="Failing task", prompt="anything")

        assert result.success is False
        assert "llm exploded" in result.error
        assert "subagent_failed" in result.error
        # Lane recorded as FAILED but exists — board shows the failed run.
        lane = LaneRegistry().get_lane(result.content["lane_id"])
        assert lane.status == LaneStatus.FAILED
        assert lane.error is not None

    def test_missing_params_rejected_without_lane(self):
        tool = AgentTool(llm_client=_mock_sub_llm(_done_response("x")))

        result = tool.execute(description="", prompt="")

        assert result.success is False
        assert "non-empty" in result.error
        # No lane created for a validation failure.
        assert LaneRegistry().list_all_lanes() == []

    def test_no_llm_configured_clean_error(self, monkeypatch):
        monkeypatch.setattr(
            "backend.tools.agent_tool.build_llm_client_from_settings", lambda: None
        )
        tool = AgentTool()  # no injected client, factory yields None

        result = tool.execute(description="No LLM", prompt="task")

        assert result.success is False
        assert "no_llm_configured" in result.error
        assert LaneRegistry().list_all_lanes() == []

    def test_answer_capped_at_limit(self):
        long_answer = "x" * (SUBAGENT_ANSWER_CAP + 10_000)
        tool = AgentTool(llm_client=_mock_sub_llm(_done_response(long_answer)))

        result = tool.execute(description="Verbose", prompt="be verbose")

        assert result.success is True
        assert len(result.content["answer"]) == SUBAGENT_ANSWER_CAP
        assert result.content["truncated"] is True

    def test_subagent_built_without_default_tool_registration(self, monkeypatch):
        """MEDIUM-1: AgentTool uses the bare SageAgent path — no
        register_all_tools (avoids memory stack + cold MCP list_tools)."""
        import backend.core.legacy.agent as agent_module

        calls = []
        monkeypatch.setattr(
            agent_module, "register_all_tools", lambda registry: calls.append(registry)
        )
        tool = AgentTool(llm_client=_mock_sub_llm(_done_response("ok")))

        result = tool.execute(description="Bare build", prompt="task")

        assert result.success is True
        assert calls == []  # default registration never ran for the sub-agent

    def test_subagent_factory_injection_used(self):
        """Custom factory (test seam) receives the restricted registry."""
        captured = {}

        class _FakeSubagent:
            def __init__(self, registry):
                captured["registry"] = registry
                self.llm_client = None

            async def run_loop(self, messages, max_iterations=None):
                from backend.core.legacy.agent_state import AgentEvent, AgentState

                yield AgentEvent(state=AgentState.DONE, content="fake answer")

        tool = AgentTool(
            llm_client=_mock_sub_llm(_done_response("unused")),
            subagent_factory=lambda registry: _FakeSubagent(registry),
        )

        result = tool.execute(description="Factory", prompt="task")

        assert result.success is True
        assert result.content["answer"] == "fake answer"
        assert "terminal" not in captured["registry"].list_names()


class TestSubagentIterationBudget:
    """子代理迭代预算读 orch_settings（此前硬编码 SUBAGENT_MAX_ITERATIONS=6）。"""

    @staticmethod
    def _capturing_tool(captured: dict) -> AgentTool:
        class _FakeSubagent:
            def __init__(self, registry):
                self.llm_client = None

            async def run_loop(self, messages, max_iterations=None):
                from backend.core.legacy.agent_state import AgentEvent, AgentState

                captured["max_iterations"] = max_iterations
                yield AgentEvent(state=AgentState.DONE, content="ok")

        return AgentTool(
            llm_client=_mock_sub_llm(_done_response("unused")),
            subagent_factory=lambda registry: _FakeSubagent(registry),
        )

    def test_uses_configured_budget(self, monkeypatch):
        """orch.maxSubagentIterations=11 → run_loop 收到 11。"""
        from backend.orchestration.orch_settings import OrchSettings

        monkeypatch.setattr(
            agent_tool_module,
            "load_orch_settings",
            lambda: OrchSettings(max_subagent_iterations=11),
        )
        captured: dict = {}

        result = self._capturing_tool(captured).execute(description="d", prompt="p")

        assert result.success is True
        assert captured["max_iterations"] == 11

    def test_falls_back_to_constant_when_settings_unreadable(self, monkeypatch):
        """配置读取抛错 → 回落模块常量 6，绝不抛穿到调用方。"""

        def _boom():
            raise RuntimeError("settings backend down")

        monkeypatch.setattr(agent_tool_module, "load_orch_settings", _boom)
        captured: dict = {}

        result = self._capturing_tool(captured).execute(description="d", prompt="p")

        assert result.success is True
        assert captured["max_iterations"] == agent_tool_module.SUBAGENT_MAX_ITERATIONS == 6


class TestSubagentTimeout:
    def test_timeout_returns_error_result_and_fails_lane(self, monkeypatch):
        """Hung sub-run → bounded wait, 超时 error ToolResult, lane FAILED."""
        monkeypatch.setattr(agent_tool_module, "SUBAGENT_TIMEOUT_S", 0.2)

        async def _slow_run(llm_client, description, prompt):
            await asyncio.sleep(1.0)
            return "late answer", None

        tool = AgentTool(llm_client=_mock_sub_llm(_done_response("unused")))
        monkeypatch.setattr(tool, "_run_subagent_async", _slow_run)

        start = time.monotonic()
        result = tool.execute(description="Slow", prompt="hang")
        elapsed = time.monotonic() - start

        assert result.success is False
        assert "超时" in result.error
        assert "timeout" in result.error
        assert elapsed < 0.9  # bounded by SUBAGENT_TIMEOUT_S, not the 1s sleep
        # Lane recorded as FAILED with the timeout reason.
        lane = LaneRegistry().get_lane(result.content["lane_id"])
        assert lane is not None
        assert lane.status == LaneStatus.FAILED
        assert "timeout" in (lane.error or "")

    def test_timeout_env_override_parsed(self, monkeypatch):
        """SAGE_AGENT_TOOL_TIMEOUT overrides the default; junk falls back."""
        monkeypatch.setenv("SAGE_AGENT_TOOL_TIMEOUT", "12.5")
        assert agent_tool_module._resolve_timeout() == 12.5

        monkeypatch.setenv("SAGE_AGENT_TOOL_TIMEOUT", "garbage")
        assert agent_tool_module._resolve_timeout() == 300.0

        monkeypatch.setenv("SAGE_AGENT_TOOL_TIMEOUT", "-3")
        assert agent_tool_module._resolve_timeout() == 300.0

        monkeypatch.delenv("SAGE_AGENT_TOOL_TIMEOUT")
        assert agent_tool_module._resolve_timeout() == 300.0
