"""CalculatorTool 单元测试

覆盖 calculator.py 的全部主要分支：
- Schema 元数据
- 基本数学运算 (加减乘除)
- 高级数学函数 (sqrt, sin, log)
- 安全检查 (禁止关键词、危险模式、未授权标识符)
- 错误处理 (语法错误、除零、属性访问)
"""

import pytest

from backend.tools.calculator import CalculatorTool

pytestmark = pytest.mark.unit


# ---------- Schema ----------


def test_calculator_schema_metadata():
    """CalculatorTool 的 schema 字段正确"""
    tool = CalculatorTool()
    schema = tool.schema
    assert schema.name == "calculator"
    assert "数学" in schema.description
    assert schema.parameters["type"] == "object"
    assert "expression" in schema.parameters["properties"]
    assert schema.parameters["required"] == ["expression"]


def test_calculator_name_and_description_properties():
    """name / description 通过基类 property 暴露"""
    tool = CalculatorTool()
    assert tool.name == "calculator"
    assert isinstance(tool.description, str)


# ---------- 基本运算 ----------


def test_calculator_addition():
    """加法返回正确结果"""
    tool = CalculatorTool()
    result = tool.execute(expression="2 + 3")
    assert result.success is True
    assert result.content["result"] == 5
    assert result.content["expression"] == "2 + 3"
    assert result.content["type"] == "int"


def test_calculator_subtraction_multiplication_division():
    """减/乘/除运算"""
    tool = CalculatorTool()
    assert tool.execute(expression="10 - 4").content["result"] == 6
    assert tool.execute(expression="6 * 7").content["result"] == 42
    assert tool.execute(expression="20 / 4").content["result"] == 5.0


def test_calculator_with_parentheses_and_precedence():
    """运算符优先级正确"""
    tool = CalculatorTool()
    result = tool.execute(expression="(2 + 3) * 4")
    assert result.success is True
    assert result.content["result"] == 20


# ---------- 数学函数 ----------


def test_calculator_sqrt_function():
    """sqrt 函数可用"""
    tool = CalculatorTool()
    result = tool.execute(expression="sqrt(16)")
    assert result.success is True
    assert result.content["result"] == 4.0


def test_calculator_pi_and_trig():
    """pi 常量和 sin 函数可用"""
    tool = CalculatorTool()
    result = tool.execute(expression="sin(pi/2)")
    assert result.success is True
    assert abs(result.content["result"] - 1.0) < 1e-9


def test_calculator_abs_round_pow():
    """abs/round/pow 内置函数"""
    tool = CalculatorTool()
    assert tool.execute(expression="abs(-5)").content["result"] == 5
    assert tool.execute(expression="round(3.7)").content["result"] == 4
    assert tool.execute(expression="pow(2, 8)").content["result"] == 256


# ---------- 错误 / 安全分支 ----------


def test_calculator_division_by_zero():
    """除零应捕获为计算错误"""
    tool = CalculatorTool()
    result = tool.execute(expression="1 / 0")
    assert result.success is False
    assert result.error is not None
    assert "计算错误" in result.error or "zero" in result.error.lower()


def test_calculator_syntax_error():
    """语法错误返回失败"""
    tool = CalculatorTool()
    result = tool.execute(expression="2 +")
    assert result.success is False
    assert "语法错误" in result.error


def test_calculator_forbidden_keyword():
    """禁止关键词触发安全拦截"""
    tool = CalculatorTool()
    result = tool.execute(expression="__import__('os')")
    assert result.success is False
    assert "禁止关键词" in result.error or "危险模式" in result.error


def test_calculator_unauthorized_identifier():
    """未授权标识符（例如 os）被 AST 检查拦截"""
    tool = CalculatorTool()
    result = tool.execute(expression="os + 1")
    assert result.success is False
    # 走 _safe_eval AST 检查 → "安全错误"
    assert "安全错误" in result.error or "不允许的标识符" in result.error


def test_calculator_attribute_access_rejected():
    """属性访问（如 pi.real）被 AST 检查拦截"""
    tool = CalculatorTool()
    result = tool.execute(expression="pi.real")
    assert result.success is False
    assert "属性访问" in result.error or "安全错误" in result.error


def test_calculator_dangerous_pattern_double_underscore():
    """双下划线模式被关键词检查拦截"""
    tool = CalculatorTool()
    result = tool.execute(expression="a__b + 1")
    assert result.success is False
    assert "__" in result.error or "禁止" in result.error
