"""
ToolValidator 测试 (A14 from LLM_Simple)

测试 AST 白名单验证用户创建的工具代码。
"""

import pytest

from backend.tools.validator import ToolValidator, validate_tool_code


class TestToolValidator:
    """ToolValidator 测试套件"""

    def test_valid_tool_passes(self):
        """合法工具代码应通过验证"""
        code = '''
import json
import requests

TOOL_DEFINITION = {
    "name": "test_tool",
    "description": "A test tool"
}

def execute(param1: str) -> str:
    """执行工具"""
    return f"Result: {param1}"
'''
        validator = ToolValidator()
        result = validator.validate(code)
        assert result.valid, f"验证失败: {result.reason}"

    def test_forbidden_import_os(self):
        """禁止导入 os 模块"""
        code = """
import os

TOOL_DEFINITION = {"name": "bad"}

def execute():
    return os.system("ls")
"""
        result = validate_tool_code(code)
        assert not result.valid
        assert "禁止导入模块" in result.reason

    def test_forbidden_import_subprocess(self):
        """禁止导入 subprocess 模块"""
        code = """
import subprocess

TOOL_DEFINITION = {"name": "bad"}

def execute():
    return subprocess.run(["ls"])
"""
        result = validate_tool_code(code)
        assert not result.valid
        assert "禁止导入模块" in result.reason

    def test_forbidden_call_eval(self):
        """禁止调用 eval"""
        code = """
TOOL_DEFINITION = {"name": "bad"}

def execute(code: str):
    return eval(code)
"""
        result = validate_tool_code(code)
        assert not result.valid
        assert "禁止调用函数" in result.reason

    def test_forbidden_call_exec(self):
        """禁止调用 exec"""
        code = """
TOOL_DEFINITION = {"name": "bad"}

def execute(code: str):
    exec(code)
"""
        result = validate_tool_code(code)
        assert not result.valid
        assert "禁止调用函数" in result.reason

    def test_forbidden_attribute_access(self):
        """禁止访问 __class__ 等属性"""
        code = """
TOOL_DEFINITION = {"name": "bad"}

def execute():
    return "".__class__.__bases__
"""
        result = validate_tool_code(code)
        assert not result.valid
        assert "禁止访问属性" in result.reason

    def test_missing_tool_definition(self):
        """缺少 TOOL_DEFINITION 应失败"""
        code = """
def execute():
    return "hello"
"""
        result = validate_tool_code(code)
        assert not result.valid
        assert "必须导出 TOOL_DEFINITION" in result.reason

    def test_missing_execute_function(self):
        """缺少 execute 函数应失败"""
        code = """
TOOL_DEFINITION = {"name": "test"}
"""
        result = validate_tool_code(code)
        assert not result.valid
        assert "必须导出 TOOL_DEFINITION" in result.reason

    def test_allowed_imports(self):
        """允许的导入应通过"""
        code = """
import json
import math
import re
from pathlib import Path
from typing import List

TOOL_DEFINITION = {"name": "test"}

def execute():
    return json.dumps({"result": "ok"})
"""
        result = validate_tool_code(code)
        assert result.valid

    def test_syntax_error(self):
        """语法错误应返回失败"""
        code = """
TOOL_DEFINITION = {"name": "test"

def execute():
    return "hello"
"""
        result = validate_tool_code(code)
        assert not result.valid
        assert "语法错误" in result.reason


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
