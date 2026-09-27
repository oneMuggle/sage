"""R143 — LLM 错误领域模型单元测试。

覆盖：LLMErrorType 七分类枚举值、LLMError 的 Exception 语义（str/args
携带 message）、to_dict 四键序列化、可选字段缺省。
"""

from __future__ import annotations

import pytest

from backend.domain.errors import LLMError, LLMErrorType

pytestmark = pytest.mark.unit


def test_seven_error_types():
    assert LLMErrorType.AUTH_FAILED == "auth_failed"
    assert LLMErrorType.RATE_LIMITED == "rate_limited"
    assert LLMErrorType.SERVER_ERROR == "server_error"
    assert LLMErrorType.NETWORK == "network_error"
    assert LLMErrorType.TIMEOUT == "timeout"
    assert LLMErrorType.PARSING == "parsing_error"
    assert LLMErrorType.UNKNOWN == "unknown"
    assert len(LLMErrorType) == 7


def test_llm_error_is_exception_with_message():
    err = LLMError(type=LLMErrorType.TIMEOUT, message="请求超时")
    assert isinstance(err, Exception)
    assert str(err) == "请求超时"  # __post_init__ 手动 super().__init__ 的回归
    assert err.args[0] == "请求超时"


def test_to_dict_serializes_type_to_snake_case():
    err = LLMError(type=LLMErrorType.AUTH_FAILED, message="key invalid", status_code=401)
    assert err.to_dict() == {
        "type": "auth_failed",
        "message": "key invalid",
        "status_code": 401,
        "retry_after": None,
    }


def test_optional_fields_default_none():
    err = LLMError(type=LLMErrorType.UNKNOWN, message="mystery")
    assert err.status_code is None
    assert err.retry_after is None


def test_rate_limited_shape_with_retry_after():
    err = LLMError(
        type=LLMErrorType.RATE_LIMITED,
        message="slow down",
        status_code=429,
        retry_after=30,
    )
    d = err.to_dict()
    assert d["type"] == "rate_limited"
    assert d["status_code"] == 429
    assert d["retry_after"] == 30


def test_raise_and_catch_roundtrip():
    with pytest.raises(LLMError) as excinfo:
        raise LLMError(type=LLMErrorType.NETWORK, message="dns down")
    assert excinfo.value.type == LLMErrorType.NETWORK
    assert excinfo.value.message == "dns down"
