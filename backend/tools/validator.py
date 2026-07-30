"""
工具安全验证器 (A14 from LLM_Simple)

使用 AST 白名单验证用户创建的工具代码，防止恶意代码执行。

验证内容：
1. 禁止导入危险模块（os, subprocess, sys 等）
2. 禁止调用危险函数（eval, exec, __import__ 等）
3. 必须导出 TOOL_DEFINITION (dict) 和 execute (callable)

示例：
    validator = ToolValidator()
    result = validator.validate(user_tool_code)
    if not result.valid:
        raise ToolValidationError(result.reason)
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Optional


@dataclass
class ValidationResult:
    """验证结果"""
    valid: bool
    reason: Optional[str] = None


class ToolValidator:
    """AST 白名单验证用户创建的工具"""

    # 允许导入的模块白名单
    ALLOWED_IMPORTS = {
        'csv', 'json', 're', 'math', 'pathlib', 'requests', 'datetime',
        'typing', 'dataclasses', 'collections', 'itertools', 'functools',
        'string', 'textwrap', 'uuid', 'hashlib', 'base64', 'urllib.parse',
    }

    # 禁止调用的函数/方法
    FORBIDDEN_CALLS = {
        'eval', 'exec', 'compile', '__import__', 'globals', 'locals',
        'getattr', 'setattr', 'delattr', 'open', 'input', 'breakpoint',
    }

    # 禁止访问的属性
    FORBIDDEN_ATTRIBUTES = {
        '__class__', '__bases__', '__subclasses__', '__mro__',
        '__globals__', '__code__', '__closure__', '__func__',
    }

    def validate(self, code: str) -> ValidationResult:
        """
        验证工具代码是否安全

        Args:
            code: Python 源代码字符串

        Returns:
            ValidationResult(valid=True) 或 ValidationResult(valid=False, reason=...)
        """
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return ValidationResult(False, f"语法错误: {e}")

        # 检查 import 语句
        for node in ast.walk(tree):
            # 检查 import
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module_name = alias.name.split('.')[0]
                    if module_name not in self.ALLOWED_IMPORTS:
                        return ValidationResult(
                            False,
                            f"禁止导入模块: {alias.name} (允许: {', '.join(sorted(self.ALLOWED_IMPORTS))})"
                        )

            # 检查 from ... import
            if isinstance(node, ast.ImportFrom):
                if node.module:
                    module_name = node.module.split('.')[0]
                    if module_name not in self.ALLOWED_IMPORTS:
                        return ValidationResult(
                            False,
                            f"禁止从模块导入: {node.module} (允许: {', '.join(sorted(self.ALLOWED_IMPORTS))})"
                        )

            # 检查函数调用
            if isinstance(node, ast.Call):
                func_name = self._get_call_name(node)
                if func_name in self.FORBIDDEN_CALLS:
                    return ValidationResult(
                        False,
                        f"禁止调用函数: {func_name}"
                    )

            # 检查属性访问
            if isinstance(node, ast.Attribute):
                if node.attr in self.FORBIDDEN_ATTRIBUTES:
                    return ValidationResult(
                        False,
                        f"禁止访问属性: {node.attr}"
                    )

        # 检查必须导出的内容
        if not self._has_required_exports(tree):
            return ValidationResult(
                False,
                "工具必须导出 TOOL_DEFINITION (dict) 和 execute (callable)"
            )

        return ValidationResult(True)

    def _get_call_name(self, node: ast.Call) -> Optional[str]:
        """获取函数调用的名称"""
        if isinstance(node.func, ast.Name):
            return node.func.id
        elif isinstance(node.func, ast.Attribute):
            # 处理 obj.method() 形式
            if isinstance(node.func.value, ast.Name):
                return node.func.attr
        return None

    def _has_required_exports(self, tree: ast.Module) -> bool:
        """检查是否导出了必需的内容"""
        has_definition = False
        has_execute = False

        for node in ast.walk(tree):
            # 检查 TOOL_DEFINITION = ...
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == 'TOOL_DEFINITION':
                        has_definition = True

            # 检查 def execute(...)
            if isinstance(node, ast.FunctionDef) and node.name == 'execute':
                has_execute = True

        return has_definition and has_execute


# 便捷函数
def validate_tool_code(code: str) -> ValidationResult:
    """验证工具代码（便捷函数）"""
    validator = ToolValidator()
    return validator.validate(code)
