# backend/services/llm_trace/tests/test_redactor.py
import json

from backend.services.llm_trace.redactor import (
    REDACTION_MARKER,
    redact_body,
    redact_headers,
    redact_text,
    redact_url,
)

# --- redact_url ---

def test_redact_url_strips_userinfo():
    out = redact_url("http://user:pass@host.com/api")
    assert "user:pass" not in out
    assert "***:***@" in out


def test_redact_url_replaces_api_key_query():
    out = redact_url("https://x.com/v1?api_key=sk-abc123&model=foo")
    assert "sk-abc123" not in out
    assert "***REDACTED:api_key***" in out
    assert "model=foo" in out  # 其他 query 保留


def test_redact_url_passthrough_when_no_secrets():
    out = redact_url("https://internal-llm.company.com/v1/chat/completions")
    assert out == "https://internal-llm.company.com/v1/chat/completions"


# --- redact_headers ---

def test_redact_headers_replaces_bearer():
    out = redact_headers({"Authorization": "Bearer eyJabc.def.signature"})
    assert "eyJabc" not in out["Authorization"]
    assert REDACTION_MARKER.format(kind="bearer") in out["Authorization"]


def test_redact_headers_case_insensitive_keys():
    out = redact_headers({"AUTHORIZATION": "Bearer xyz", "content-type": "application/json"})
    assert "xyz" not in out["AUTHORIZATION"]
    assert out["content-type"] == "application/json"


def test_redact_headers_replaces_cookie():
    out = redact_headers({"Cookie": "session=abc; csrf=xyz"})
    assert "abc" not in out["Cookie"]
    assert "xyz" not in out["Cookie"]
    assert REDACTION_MARKER.format(kind="cookie") in out["Cookie"]


def test_redact_headers_replaces_basic():
    out = redact_headers({"Authorization": "Basic dXNlcjpwYXNz"})
    assert "dXNlcjpwYXNz" not in out["Authorization"]
    assert REDACTION_MARKER.format(kind="basic") in out["Authorization"]


# --- redact_body (JSON) ---

def test_redact_body_json_replaces_password_field():
    body = {"user": "alice", "password": "secret123"}
    out, err = redact_body(json.dumps(body).encode("utf-8"), include_prompts=True)
    assert err is None
    assert out["password"] == REDACTION_MARKER.format(kind="password")
    assert out["user"] == "alice"  # 普通字段不脱敏


def test_redact_body_json_recursive_in_nested_dict():
    body = {"data": {"nested": {"api_key": "k-123"}}}
    out, _ = redact_body(json.dumps(body).encode("utf-8"), include_prompts=True)
    assert out["data"]["nested"]["api_key"] == REDACTION_MARKER.format(kind="api_key")


def test_redact_body_json_recursive_in_list():
    body = {"items": [{"token": "t-1"}, {"token": "t-2"}, {"safe": "ok"}]}
    out, _ = redact_body(json.dumps(body).encode("utf-8"), include_prompts=True)
    assert out["items"][0]["token"] == REDACTION_MARKER.format(kind="token")
    assert out["items"][1]["token"] == REDACTION_MARKER.format(kind="token")
    assert out["items"][2]["safe"] == "ok"


def test_redact_body_json_drops_prompt_by_default():
    body = {"messages": [{"role": "user", "content": "Hello, my key is sk-abc123def456ghi789"}]}
    out, _ = redact_body(json.dumps(body).encode("utf-8"), include_prompts=False)
    assert out["messages"][0]["content"] == REDACTION_MARKER.format(kind="prompt")
    assert out["messages"][0]["role"] == "user"  # 结构保留


def test_redact_body_json_keeps_prompt_when_opted_in_but_still_redacts_secrets_in_it():
    body = {"messages": [{"role": "user", "content": "Hello, my key is sk-abc123def456ghi789"}]}
    out, _ = redact_body(json.dumps(body).encode("utf-8"), include_prompts=True)
    assert "sk-abc123" not in out["messages"][0]["content"]
    assert "Hello" in out["messages"][0]["content"]  # 大部分原文保留


def test_redact_body_invalid_json_returns_parse_error():
    out, err = redact_body(b"not valid json {", include_prompts=True)
    assert out is None
    assert err is not None
    assert "json" in err.lower()


def test_redact_body_binary_returns_none():
    out, err = redact_body(b"\x00\x01\xff\xfe", include_prompts=True)
    assert out is None
    assert err == "binary"


def test_redact_body_none_passes_through():
    out, err = redact_body(None, include_prompts=True)
    assert out is None
    assert err is None


def test_redact_body_keeps_non_string_values_intact():
    body = {"count": 42, "enabled": True, "data": None}
    out, _ = redact_body(json.dumps(body).encode("utf-8"), include_prompts=True)
    assert out == body  # 非 string value 不变


# --- redact_text ---

def test_redact_text_replaces_jwt():
    text = "token=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    out = redact_text(text)
    assert "eyJhbGciOiJIUzI1NiJ9" not in out
    assert REDACTION_MARKER.format(kind="jwt") in out


def test_redact_text_replaces_openai_style_keys():
    out = redact_text("Use key sk-proj-abc123def456ghi789jkl012mno345")
    assert "sk-proj-abc123" not in out
    assert REDACTION_MARKER.format(kind="openai_key") in out


# --- invariant (红actor 是安全关键路径,必须有这个测试) ---

def test_invariant_password_secret_does_not_leak_through_export():
    """含 password=secret123 的输入,经 redact_body 后不能再 grep 到 secret123。"""
    payload = {
        "user": "alice",
        "password": "secret123",
        "nested": {"api_key": "k-9876543210abcdef", "token": "tok-abcdef1234567890"},
    }
    out, _ = redact_body(json.dumps(payload).encode("utf-8"), include_prompts=True)
    serialized = json.dumps(out)
    assert "secret123" not in serialized
    assert "k-9876543210" not in serialized
    assert "tok-abcdef1234567890" not in serialized
