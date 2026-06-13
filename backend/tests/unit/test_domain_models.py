"""验证 domain/ 模型独立可用（零外部依赖）。

仅依赖 Python 标准库与 pytest；不允许 import fastapi / httpx / pydantic
或 backend.core / backend.application 等任何非 domain 模块。
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import re

import pytest

from backend.domain import (
    AgentDecision,
    AgentError,
    AgentState,
    LLMError,
    LLMErrorType,
    MaxIterationsError,
    Message,
    Role,
    SageBaseError,
    SecurityError,
    SessionNotFoundError,
    SkillResult,
    SkillSpec,
    ToolCall,
    ToolCallError,
    ToolResult,
    ToolSpec,
    ValidationError,
    exceptions as domain_exceptions,
)

pytestmark = pytest.mark.unit


# ---------- AgentState 状态机 ----------


class TestAgentState:
    def test_initial_is_idle(self) -> None:
        assert AgentState.initial() == AgentState.IDLE

    def test_string_value_is_lowercase(self) -> None:
        assert AgentState.THINKING.value == "thinking"
        # 兼容 str 比较（继承 str）
        assert AgentState.THINKING == "thinking"

    def test_legal_transition_idle_to_thinking(self) -> None:
        assert AgentState.IDLE.can_transition_to(AgentState.THINKING)

    def test_illegal_transition_idle_to_acting(self) -> None:
        assert not AgentState.IDLE.can_transition_to(AgentState.ACTING)

    def test_thinking_can_go_to_acting_done_or_failed(self) -> None:
        assert AgentState.THINKING.can_transition_to(AgentState.ACTING)
        assert AgentState.THINKING.can_transition_to(AgentState.DONE)
        assert AgentState.THINKING.can_transition_to(AgentState.FAILED)

    def test_acting_can_go_to_observing_or_failed(self) -> None:
        assert AgentState.ACTING.can_transition_to(AgentState.OBSERVING)
        assert AgentState.ACTING.can_transition_to(AgentState.FAILED)
        # 不能直接 ACTING → DONE，必须先 OBSERVING
        assert not AgentState.ACTING.can_transition_to(AgentState.DONE)

    def test_observing_can_go_back_to_thinking(self) -> None:
        assert AgentState.OBSERVING.can_transition_to(AgentState.THINKING)
        assert AgentState.OBSERVING.can_transition_to(AgentState.DONE)

    def test_terminal_done_has_no_transitions(self) -> None:
        for state in AgentState:
            assert not AgentState.DONE.can_transition_to(state)

    def test_terminal_failed_has_no_transitions(self) -> None:
        for state in AgentState:
            assert not AgentState.FAILED.can_transition_to(state)


# ---------- AgentDecision 值对象 ----------


class TestAgentDecision:
    def test_decision_is_frozen(self) -> None:
        decision = AgentDecision(state=AgentState.DONE, final_message="hi")
        with pytest.raises(dataclasses.FrozenInstanceError):
            decision.state = AgentState.IDLE  # type: ignore[misc]

    def test_decision_default_optional_fields(self) -> None:
        decision = AgentDecision(state=AgentState.THINKING)
        assert decision.final_message is None
        assert decision.action_name is None
        assert decision.action_args is None

    def test_decision_acting_payload(self) -> None:
        decision = AgentDecision(
            state=AgentState.ACTING,
            action_name="calculator",
            action_args={"expr": "1+1"},
        )
        assert decision.action_name == "calculator"
        assert decision.action_args == {"expr": "1+1"}


# ---------- Message / Role / ToolCall ----------


class TestMessage:
    def test_message_minimal(self) -> None:
        msg = Message(role=Role.USER, content="hi")
        assert msg.content == "hi"
        assert msg.tool_calls == []
        assert msg.tool_call_id is None

    def test_message_with_tool_call(self) -> None:
        msg = Message(
            role=Role.ASSISTANT,
            content="",
            tool_calls=[ToolCall(name="calc", args={"x": 1}, id="tc_1")],
        )
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0].name == "calc"
        assert msg.tool_calls[0].id == "tc_1"

    def test_tool_message(self) -> None:
        msg = Message(role=Role.TOOL, content="42", tool_call_id="tc_1")
        assert msg.tool_call_id == "tc_1"
        assert msg.role == Role.TOOL

    def test_role_values(self) -> None:
        assert Role.SYSTEM.value == "system"
        assert Role.USER.value == "user"
        assert Role.ASSISTANT.value == "assistant"
        assert Role.TOOL.value == "tool"


# ---------- ToolSpec / ToolResult ----------


class TestTool:
    def test_tool_spec_defaults(self) -> None:
        spec = ToolSpec(name="calc", description="计算器")
        assert spec.parameters == {}

    def test_tool_result_success(self) -> None:
        res = ToolResult(success=True, output="42")
        assert res.success
        assert res.output == "42"
        assert res.error is None

    def test_tool_result_failure(self) -> None:
        res = ToolResult(success=False, error="boom")
        assert not res.success
        assert res.error == "boom"


# ---------- SkillSpec / SkillResult ----------


class TestSkill:
    def test_skill_spec_defaults(self) -> None:
        spec = SkillSpec(name="search", description="搜索")
        assert spec.triggers == []
        assert spec.parameters == {}
        assert spec.examples == []

    def test_skill_result_metadata_default(self) -> None:
        res = SkillResult(success=True, content="ok")
        assert res.metadata == {}


# ---------- LLMError / LLMErrorType ----------


class TestLLMError:
    def test_error_types_have_snake_case_values(self) -> None:
        assert LLMErrorType.AUTH_FAILED.value == "auth_failed"
        assert LLMErrorType.RATE_LIMITED.value == "rate_limited"
        assert LLMErrorType.NETWORK.value == "network_error"

    def test_llm_error_is_exception(self) -> None:
        err = LLMError(LLMErrorType.TIMEOUT, "请求超时")
        assert isinstance(err, Exception)
        # __post_init__ 应已把 message 传给 Exception
        assert str(err) == "请求超时"

    def test_llm_error_to_dict_round_trips_json(self) -> None:
        err = LLMError(
            LLMErrorType.RATE_LIMITED,
            "太频繁了",
            status_code=429,
            retry_after=30,
        )
        payload = err.to_dict()
        # 必须可 JSON 序列化（domain 模型对 API 友好）
        round_tripped = json.loads(json.dumps(payload))
        assert round_tripped["type"] == "rate_limited"
        assert round_tripped["retry_after"] == 30
        assert round_tripped["status_code"] == 429

    def test_can_raise_and_catch(self) -> None:
        with pytest.raises(LLMError) as exc_info:
            raise LLMError(LLMErrorType.AUTH_FAILED, "no key")
        assert exc_info.value.type == LLMErrorType.AUTH_FAILED


# ---------- SageBaseError 异常体系 ----------


class TestExceptions:
    def test_base_error_default_code(self) -> None:
        err = SageBaseError("出错了")
        assert err.code == "SAGE_ERROR"
        assert err.details == {}
        assert "出错了" in str(err)

    def test_base_error_with_details(self) -> None:
        err = SageBaseError("x", code="X", details={"k": "v"})
        d = err.to_dict()
        assert d == {"error": "X", "message": "x", "details": {"k": "v"}}

    def test_agent_error_is_subclass(self) -> None:
        err = AgentError("boom")
        assert isinstance(err, SageBaseError)
        assert err.code == "AGENT_ERROR"

    def test_tool_call_error_includes_tool_name(self) -> None:
        err = ToolCallError("calc", "div by zero")
        assert err.details["tool_name"] == "calc"
        assert err.code == "TOOL_CALL_ERROR"
        assert "calc" in err.message

    def test_max_iterations_error_includes_limit(self) -> None:
        err = MaxIterationsError(5)
        assert err.details["max_iterations"] == 5

    def test_session_not_found_error_includes_id(self) -> None:
        err = SessionNotFoundError("sess_xyz")
        assert err.details["session_id"] == "sess_xyz"

    def test_validation_error_includes_field(self) -> None:
        err = ValidationError("email", "格式错误")
        assert err.details["field"] == "email"

    def test_security_error_includes_threat_type(self) -> None:
        err = SecurityError("xss", "脚本注入")
        assert err.details["threat_type"] == "xss"

    def test_sage_memory_error_distinct_from_builtin(self) -> None:
        # 故意命名 SageMemoryError 避免与 Python 内置 MemoryError 冲突
        err = domain_exceptions.SageMemoryError("save", "disk full")
        assert err.code == "MEMORY_ERROR"
        assert err.details["operation"] == "save"
        # 不应该是内置 MemoryError 的实例
        assert not isinstance(err, MemoryError)


# ---------- 零外部依赖契约 ----------


class TestDomainPurity:
    """确保 domain/ 模块只 import 标准库 + 自身。"""

    def test_no_external_imports_in_domain(self) -> None:
        domain_dir = pathlib.Path(__file__).resolve().parents[2] / "domain"
        assert domain_dir.is_dir(), f"domain/ 不存在: {domain_dir}"

        allowed_stdlib = {
            "dataclasses",
            "enum",
            "typing",
            "abc",
            "collections",
            "__future__",
        }
        # 允许 domain 内部互相 import
        allowed_internal = "backend.domain"

        import_re = re.compile(r"^\s*(?:from|import)\s+([\w\.]+)")
        offenders: list[str] = []

        for py_file in sorted(domain_dir.rglob("*.py")):
            for line in py_file.read_text(encoding="utf-8").splitlines():
                match = import_re.match(line)
                if not match:
                    continue
                mod = match.group(1)
                root = mod.split(".")[0]
                if mod.startswith(allowed_internal):
                    continue
                if root in allowed_stdlib:
                    continue
                offenders.append(f"{py_file.name}: {line.strip()}")

        assert offenders == [], "domain/ 出现非法外部 import:\n" + "\n".join(offenders)
