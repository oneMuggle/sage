import pytest
from backend.core.errors import LLMErrorType, LLMError


def test_llm_error_contains_type_and_message():
    err = LLMError(LLMErrorType.AUTH_FAILED, "API Key 无效", status_code=401)
    assert err.type == LLMErrorType.AUTH_FAILED
    assert err.message == "API Key 无效"
    assert err.status_code == 401
    assert err.retry_after is None


def test_llm_error_can_be_raised_and_caught():
    with pytest.raises(LLMError) as exc_info:
        raise LLMError(LLMErrorType.RATE_LIMITED, "请求过于频繁", retry_after=60)
    assert exc_info.value.type == LLMErrorType.RATE_LIMITED
    assert exc_info.value.retry_after == 60


def test_llm_error_type_values_are_strings():
    """枚举值应可作为字符串序列化（用于 JSON 响应）。"""
    assert LLMErrorType.AUTH_FAILED.value == "auth_failed"
    assert LLMErrorType.RATE_LIMITED.value == "rate_limited"
    assert LLMErrorType.SERVER_ERROR.value == "server_error"
    assert LLMErrorType.NETWORK.value == "network_error"
    assert LLMErrorType.TIMEOUT.value == "timeout"
    assert LLMErrorType.PARSING.value == "parsing_error"
    assert LLMErrorType.UNKNOWN.value == "unknown"


def test_llm_error_to_dict_for_api_response():
    err = LLMError(LLMErrorType.TIMEOUT, "请求超时")
    result = err.to_dict()
    assert result == {
        "type": "timeout",
        "message": "请求超时",
        "status_code": None,
        "retry_after": None,
    }


def test_llm_error_str_contains_message():
    err = LLMError(LLMErrorType.AUTH_FAILED, "API Key 无效", status_code=401)
    assert str(err) == "API Key 无效"
    assert err.args == ("API Key 无效",)
