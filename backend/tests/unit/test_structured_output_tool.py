"""M2 structured_output 工具单元测试。

载荷存储/回显、可选 schema 校验（jsonschema 在则用之，否则最小校验器
兜底——两套路径都直接覆盖）、会话隔离提取。
"""

from __future__ import annotations

import pytest

import backend.tools.structured_output_tool as so_module
from backend.tools.context import (
    ToolExecutionContext,
    reset_tool_context,
    set_tool_context,
)
from backend.tools.structured_output_tool import (
    StructuredOutputTool,
    get_last_structured_output,
    minimal_schema_errors,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean_store():
    """复位会话存储，防跨测试泄漏。"""
    so_module._structured_output_store.clear()
    yield
    so_module._structured_output_store.clear()


# ---------------------------------------------------------------------------
# 存储与回显
# ---------------------------------------------------------------------------


def test_structured_output_stores_payload_and_echoes_it():
    """成功路径：存储载荷并在 content 回显。"""
    # Arrange
    tool = StructuredOutputTool()
    data = {"answer": 42, "tags": ["a", "b"]}

    # Act
    result = tool.execute(data=data)

    # Assert
    assert result.success is True
    assert result.content["stored"] is True
    assert result.content["data"] == data
    assert get_last_structured_output() == data


def test_structured_output_replaces_previous_payload():
    """后一次调用覆盖前一次（最后一次语义）。"""
    # Arrange
    tool = StructuredOutputTool()
    tool.execute(data={"v": 1})

    # Act
    tool.execute(data={"v": 2})

    # Assert
    assert get_last_structured_output() == {"v": 2}


def test_structured_output_requires_dict_data():
    """data 必须是 JSON 对象。"""
    # Arrange
    tool = StructuredOutputTool()

    # Act / Assert
    for bad in ([1, 2], "text", 42, None):
        result = tool.execute(data=bad)
        assert result.success is False
        assert "data 必须是 JSON 对象" in result.error


def test_structured_output_requires_dict_schema_when_given():
    """schema 提供时必须是对象。"""
    # Act
    result = StructuredOutputTool().execute(data={"a": 1}, schema="not-a-schema")

    # Assert
    assert result.success is False
    assert "schema 必须是 JSON 对象" in result.error


# ---------------------------------------------------------------------------
# schema 校验（经 validate_against_schema 的统一入口）
# ---------------------------------------------------------------------------


def test_structured_output_valid_schema_passes():
    """data 满足 schema → 成功存储。"""
    # Arrange
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
        "required": ["name"],
    }

    # Act
    result = StructuredOutputTool().execute(data={"name": "sage", "age": 3}, schema=schema)

    # Assert
    assert result.success is True


def test_structured_output_invalid_data_reports_schema_errors():
    """data 违反 schema → success=False 且错误含校验消息。"""
    # Arrange
    schema = {"type": "object", "required": ["name"], "properties": {"age": {"type": "integer"}}}

    # Act
    result = StructuredOutputTool().execute(data={"age": "three"}, schema=schema)

    # Assert
    assert result.success is False
    assert "schema 校验失败" in result.error
    assert "name" in result.error


def test_structured_output_invalid_schema_object_reports_clean_error():
    """schema 本身非法 → 干净错误，不抛异常（jsonschema check_schema 路径）。"""
    # Arrange: type 关键字取值非法
    bad_schema = {"type": "objekt"}

    # Act
    result = StructuredOutputTool().execute(data={"a": 1}, schema=bad_schema)

    # Assert（jsonschema 在 → SchemaError 转错误消息；不在 → 最小校验器宽容放行）
    if so_module._HAS_JSONSCHEMA:
        assert result.success is False
        assert "schema" in result.error
    else:  # pragma: no cover — 取决于环境
        assert result.success is True


def test_structured_output_absent_schema_skips_validation():
    """不提供 schema → 不校验，直接存储。"""
    # Act
    result = StructuredOutputTool().execute(data={"anything": [1, None, {"x": True}]})

    # Assert
    assert result.success is True


# ---------------------------------------------------------------------------
# 最小校验器（jsonschema 缺失时的兜底路径，直接单测）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "type_name", "expect_ok"),
    [
        ({}, "object", True),
        ([], "object", False),
        ([], "array", True),
        ("s", "string", True),
        (1, "integer", True),
        (True, "integer", False),  # bool 是 int 子类，必须显式排除
        (1.5, "number", True),
        (True, "number", False),
        (True, "boolean", True),
        (None, "null", True),
        ("x", "unknown-type", True),  # 未知 type 名宽容放行
    ],
)
def test_minimal_validator_type_checks(value, type_name, expect_ok):
    """最小校验器 type 判定矩阵（含 bool/int 边界）。"""
    # Act
    errors = minimal_schema_errors(value, {"type": type_name})

    # Assert
    assert (not errors) is expect_ok


def test_minimal_validator_required_and_properties_and_items():
    """最小校验器覆盖 required / properties 递归 / items 递归。"""
    # Arrange
    schema = {
        "type": "object",
        "required": ["id"],
        "properties": {
            "id": {"type": "integer"},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
    }

    # Act / Assert —— 合法实例
    assert minimal_schema_errors({"id": 1, "tags": ["a"]}, schema) == []

    # 缺 required 字段
    missing = minimal_schema_errors({"tags": []}, schema)
    assert "$: 缺少必填字段 'id'" in missing

    # id 类型错 + items 类型错
    errors = minimal_schema_errors({"id": "one", "tags": ["a", 2]}, schema)
    joined = "\n".join(errors)
    assert "$.id: 期望类型 integer" in joined
    assert "$.tags[1]: 期望类型 string" in joined


def test_minimal_validator_type_mismatch_stops_descent():
    """类型不符 → 只报一条错，不下钻产生级联噪音。"""
    # Arrange
    schema = {"type": "object", "required": ["a", "b", "c"]}

    # Act
    errors = minimal_schema_errors([1, 2], schema)

    # Assert
    assert len(errors) == 1
    assert "期望类型 object" in errors[0]


# ---------------------------------------------------------------------------
# 会话隔离提取
# ---------------------------------------------------------------------------


def test_structured_output_retrievable_per_session():
    """按 session_id 隔离存储与提取。"""
    # Arrange
    tool = StructuredOutputTool()
    ctx_a = ToolExecutionContext(
        session_id="so-a", stream_id="s", binding_generation=1, office_doc_scope=frozenset()
    )
    token = set_tool_context(ctx_a)
    try:
        tool.execute(data={"who": "a"})
    finally:
        reset_tool_context(token)

    # Act
    tool.execute(data={"who": "anon"})

    # Assert
    assert get_last_structured_output("so-a") == {"who": "a"}
    assert get_last_structured_output() == {"who": "anon"}


def test_structured_output_missing_session_returns_none():
    """未存储过的会话 → None。"""
    # Act / Assert
    assert get_last_structured_output("never-stored") is None


# ---------------------------------------------------------------------------
# FIX-2: 未知参数拒绝
# ---------------------------------------------------------------------------


def test_structured_output_rejects_unknown_kwargs():
    """FIX-2 回归：拼错的参数名 → 干净错误，不被 **kwargs 静默吞掉。"""
    # Act —— 模拟 LLM 多传一个 payload
    result = StructuredOutputTool().execute(data={"a": 1}, payload={"b": 2})

    # Assert
    assert result.success is False
    assert "未知参数" in result.error
    assert "payload" in result.error
    # 载荷未被存储
    assert get_last_structured_output() is None
