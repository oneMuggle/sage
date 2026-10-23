"""R138 — Sage 异常体系单元测试。

覆盖：基类缺省 code/details、to_dict、__str__ 有/无 details、各子类
固定 code 与 details 合并语义（ToolCallError/MaxIterationsError/
SageMemoryError）、统一捕获契约。
"""

from __future__ import annotations

import pytest

from backend.domain.exceptions import (
    AgentError,
    MaxIterationsError,
    SageBaseError,
    SageMemoryError,
    SecurityError,
    SessionNotFoundError,
    ToolCallError,
    ValidationError,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# 基类
# ---------------------------------------------------------------------------


def test_base_defaults():
    err = SageBaseError("boom")
    assert err.message == "boom"
    assert err.code == "SAGE_ERROR"
    assert err.details == {}


def test_base_explicit_fields():
    err = SageBaseError("boom", code="CUSTOM", details={"k": 1})
    assert err.code == "CUSTOM"
    assert err.details == {"k": 1}


def test_to_dict_three_keys():
    err = SageBaseError("bad", code="X", details={"a": 1})
    assert err.to_dict() == {"error": "X", "message": "bad", "details": {"a": 1}}


def test_str_without_details():
    assert str(SageBaseError("boom")) == "[SAGE_ERROR] boom"


def test_str_with_details():
    err = SageBaseError("boom", code="X", details={"a": 1})
    assert str(err) == "[X] boom - {'a': 1}"


# ---------------------------------------------------------------------------
# 子类
# ---------------------------------------------------------------------------


def test_agent_error_fixed_code():
    err = AgentError("engine stuck", details={"step": 3})
    assert err.code == "AGENT_ERROR"
    assert err.details == {"step": 3}


def test_tool_call_error_merges_tool_name():
    err = ToolCallError("terminal", "exit 1", details={"cwd": "/tmp"})
    assert err.code == "TOOL_CALL_ERROR"
    assert "工具 'terminal' 执行失败: exit 1" in err.message
    assert err.details["tool_name"] == "terminal"
    assert err.details["cwd"] == "/tmp"  # 调用方 details 不丢


def test_max_iterations_error_merges_limit():
    err = MaxIterationsError(25)
    assert err.code == "MAX_ITERATIONS_ERROR"
    assert "(25)" in err.message
    assert err.details["max_iterations"] == 25


def test_memory_error_merges_operation():
    err = SageMemoryError("search", "table missing")
    assert err.code == "MEMORY_ERROR"
    assert "记忆操作 'search' 失败" in err.message
    assert err.details["operation"] == "search"


def test_session_not_found_error():
    err = SessionNotFoundError("s-42")
    assert err.code == "SESSION_NOT_FOUND"
    assert "会话未找到: s-42" in err.message
    assert err.details["session_id"] == "s-42"


def test_validation_error():
    err = ValidationError("email", "格式非法")
    assert err.code == "VALIDATION_ERROR"
    assert err.details["field"] == "email"
    assert "验证失败 [email]" in err.message


def test_security_error():
    err = SecurityError("sql_injection", "检测到注入模式")
    assert err.code == "SECURITY_ERROR"
    assert err.details["threat_type"] == "sql_injection"
    assert "安全威胁 [sql_injection]" in err.message


def test_unified_catch_via_base():
    with pytest.raises(SageBaseError):
        raise MaxIterationsError(10)
