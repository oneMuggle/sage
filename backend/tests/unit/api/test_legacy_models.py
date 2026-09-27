"""R174 — legacy API 请求/响应模型（13 个 Pydantic DTO）单元测试。

覆盖：各模型缺省值、必填字段校验、client_message_id pattern、
AgentToggle StrictBool、AgentCreate id pattern、ChatResponse 三态。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.api.legacy_models import (
    AgentCreate,
    AgentToggle,
    AgentUpdate,
    ChatErrorInfo,
    ChatRequest,
    ChatResponse,
    EvolutionLogResponse,
    InterruptRequest,
    LearnRequest,
    MessageResponse,
    SessionCreate,
    SessionUpdate,
    SteerRequest,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# SessionCreate / SessionUpdate
# ---------------------------------------------------------------------------


def test_session_create_defaults():
    m = SessionCreate()
    assert m.title == "新对话"
    assert m.parent_id is None


def test_session_update_all_optional():
    m = SessionUpdate()
    assert m.title is None
    assert m.is_pinned is None


# ---------------------------------------------------------------------------
# ChatRequest
# ---------------------------------------------------------------------------


def test_chat_request_required_fields():
    m = ChatRequest(session_id="s1", message="hello")
    assert m.session_id == "s1"
    assert m.client_message_id is None
    assert m.agent_id is None
    assert m.auto_context is None
    assert m.office_refs == []
    assert m.attachment_media_ids == []
    assert m.images == []
    assert m.orchestration_mode == "auto"
    assert m.memory_mode == "on"
    assert m.context_reset is False
    assert m.plan_mode is False


def test_chat_request_missing_session_id_rejected():
    with pytest.raises(ValidationError):
        ChatRequest(message="hello")


def test_chat_request_client_message_id_pattern():
    # 合法 hex UUID
    ok = ChatRequest(session_id="s", message="m", client_message_id="a" * 32)
    assert ok.client_message_id == "a" * 32
    # 非法字符
    with pytest.raises(ValidationError):
        ChatRequest(session_id="s", message="m", client_message_id="zz!" * 20)
    # 过短
    with pytest.raises(ValidationError):
        ChatRequest(session_id="s", message="m", client_message_id="abc")


def test_chat_request_full_fields():
    m = ChatRequest(
        session_id="s1",
        message="hello",
        agent_id="coder",
        max_context=8192,
        auto_context=True,
        endpoint_id="ep1",
        temperature=0.7,
        provider="openai",
        reasoning_effort="high",
        thinking_budget=4096,
        plan_mode=True,
    )
    assert m.agent_id == "coder"
    assert m.max_context == 8192
    assert m.temperature == 0.7
    assert m.reasoning_effort == "high"
    assert m.thinking_budget == 4096
    assert m.plan_mode is True


# ---------------------------------------------------------------------------
# MessageResponse / ChatErrorInfo / ChatResponse
# ---------------------------------------------------------------------------


def test_message_response_roundtrip():
    m = MessageResponse(
        id="m1", session_id="s1", role="user", content="hello", created_at=1000
    )
    assert m.model is None
    assert m.tool_calls is None


def test_chat_error_info_fields():
    err = ChatErrorInfo(type="rate_limited", message="slow down", status_code=429, retry_after=30)
    assert err.type == "rate_limited"
    assert err.retry_after == 30
    err2 = ChatErrorInfo(type="timeout", message="timed out")
    assert err2.status_code is None
    assert err2.retry_after is None


def test_chat_response_success_shape():
    out = ChatResponse(
        message=MessageResponse(id="m1", session_id="s1", role="assistant", content="hi", created_at=1),
        session={"id": "s1"},
    )
    assert out.message is not None
    assert out.error is None


def test_chat_response_failure_shape():
    err = ChatErrorInfo(type="timeout", message="too slow")
    out = ChatResponse(error=err)
    assert out.message is None
    assert out.error is not None


# ---------------------------------------------------------------------------
# EvolutionLogResponse
# ---------------------------------------------------------------------------


def test_evolution_log_response_roundtrip():
    m = EvolutionLogResponse(
        id="e1",
        evolution_type="tool_usage",
        description="learned new pattern",
        trigger_type="explicit_learn",
        status="completed",
        tokens_used=500,
        created_at=1700000000,
    )
    assert m.before_state is None
    assert m.after_state is None
    assert m.error_message is None
    assert m.completed_at is None
    assert m.tokens_used == 500


# ---------------------------------------------------------------------------
# AgentToggle / AgentUpdate / AgentCreate
# ---------------------------------------------------------------------------


def test_agent_toggle_strict_bool_rejects_int():
    with pytest.raises(ValidationError):
        AgentToggle(enabled=1)
    with pytest.raises(ValidationError):
        AgentToggle(enabled="yes")


def test_agent_toggle_accepts_bool():
    assert AgentToggle(enabled=True).enabled is True
    assert AgentToggle(enabled=False).enabled is False


def test_agent_update_all_optional():
    m = AgentUpdate()
    assert m.name is None
    assert m.max_iterations is None
    assert m.enabled is None
    assert m.model_config_data is None


def test_agent_create_defaults():
    m = AgentCreate(id="my-agent", name="My Agent")
    assert m.role == "general"
    assert m.system_prompt == ""
    assert m.tools is None
    assert m.enabled is None


def test_agent_create_id_pattern_rejects_invalid():
    with pytest.raises(ValidationError):
        AgentCreate(id="has space", name="x")
    with pytest.raises(ValidationError):
        AgentCreate(id="a" * 65, name="x")
    with pytest.raises(ValidationError):
        AgentCreate(id="", name="x")


def test_agent_create_valid_id_with_hyphen_and_underscore():
    m = AgentCreate(id="my-agent_1", name="n")
    assert m.id == "my-agent_1"


# ---------------------------------------------------------------------------
# InterruptRequest / SteerRequest / LearnRequest
# ---------------------------------------------------------------------------


def test_interrupt_request_stream_id_optional():
    assert InterruptRequest().stream_id is None
    assert InterruptRequest(stream_id="s1").stream_id == "s1"


def test_steer_request_fields():
    m = SteerRequest(stream_id="s1", content="go left")
    assert m.stream_id == "s1"
    assert m.content == "go left"
    with pytest.raises(ValidationError):
        SteerRequest(content="no stream_id")


def test_learn_request_defaults():
    m = LearnRequest(session_id="s1")
    assert m.prompt == ""
    m2 = LearnRequest(session_id="s1", prompt="review this")
    assert m2.prompt == "review this"
