"""`llm_json` 单元测试（2026-10-27）。"""

from __future__ import annotations

import pytest

from backend.services.llm_json import (  # noqa: E402
    extract_json_object,
    parse_json,
    strip_code_fences,
)


def test_parse_json_direct() -> None:
    assert parse_json('{"a": 1}') == {"a": 1}


def test_parse_json_with_fences() -> None:
    raw = """some preamble
```json
{"health_score": 85, "summary": "ok"}
```
some trailing text
"""
    assert parse_json(raw) == {"health_score": 85, "summary": "ok"}


def test_parse_json_with_braces_only() -> None:
    raw = """以下是治理方案：
{"suggested_rules": [{"key": "coding"}]}
请根据需要调整。
"""
    result = parse_json(raw)
    assert result == {"suggested_rules": [{"key": "coding"}]}


def test_parse_json_empty_raises() -> None:
    with pytest.raises(ValueError, match="empty response"):
        parse_json("")
    with pytest.raises(ValueError, match="empty response"):
        parse_json("   \n  ")


def test_parse_json_unparseable_raises() -> None:
    with pytest.raises(
        ValueError, match="could not parse JSON object from LLM response"
    ):
        parse_json("just plain text, no JSON here")


def test_parse_json_nested_json() -> None:
    raw = """```json
{"rules": [{"a": {"b": 1}}]}
"""
    assert parse_json(raw) == {"rules": [{"a": {"b": 1}}]}


def test_strip_code_fences_no_fences() -> None:
    assert strip_code_fences("plain text") == "plain text"


def test_extract_json_object_no_braces() -> None:
    with pytest.raises(ValueError, match="no balanced JSON object found"):
        extract_json_object("no braces here")
