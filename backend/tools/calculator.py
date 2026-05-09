"""
计算器工具 - 安全数学计算
"""
import ast
import math
from typing import Any

from .base import BaseTool, ToolSchema, ToolResult


class CalculatorTool(BaseTool):
    """
    计算器工具
    
    使用 Python eval 执行数学表达式，但做了严格的安全限制:
    - 不允许 import
    - 不允许危险函数 (__xxx__ 等)
    - 只允许数学运算和常见数学函数
    """

    # 允许的数学函数
    ALLOWED_FUNCTIONS = {
        'abs': abs,
        'round': round,
        'min': min,
        'max': max,
        'sum': sum,
        'pow': pow,
        'sqrt': math.sqrt,
        'sin': math.sin,
        'cos': math.cos,
        'tan': math.tan,
        'log': math.log,
        'log10': math.log10,
        'log2': math.log2,
        'exp': math.exp,
        'pi': math.pi,
        'e': math.e,
        'floor': math.floor,
        'ceil': math.ceil,
    }

    # 禁止的关键词
    FORBIDDEN_KEYWORDS = [
        'import', 'from', 'exec', 'eval', 'compile',
        'open', 'file', 'input', 'print', '__',
        'class', 'def', 'lambda', 'breakpoint',
        'globals', 'locals', 'vars', 'dir',
        'getattr', 'setattr', 'delattr', 'hasattr',
    ]

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="calculator",
            description="进行数学计算。支持加减乘除、指数、对数、三角函数等。",
            parameters={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "数学表达式，如: 2 + 2, sqrt(16), sin(pi/2)"
                    }
                },
                "required": ["expression"]
            }
        )

    def _is_safe_expression(self, expression: str) -> tuple:
        """
        检查表达式是否安全
        
        Args:
            expression: 数学表达式
            
        Returns:
            (is_safe, error_message)
        """
        # 检查禁止关键词
        expr_lower = expression.lower()
        for keyword in self.FORBIDDEN_KEYWORDS:
            if keyword in expr_lower:
                return False, f"表达式包含禁止关键词: {keyword}"
        
        # 检查是否有危险模式
        dangerous_patterns = ['__', 'lambda', 'def ', 'class ']
        for pattern in dangerous_patterns:
            if pattern in expression:
                return False, f"表达式包含危险模式: {pattern}"
        
        return True, None

    def _safe_eval(self, expression: str) -> Any:
        """
        安全地计算表达式
        
        Args:
            expression: 数学表达式
            
        Returns:
            计算结果
        """
        # 解析表达式为 AST
        tree = ast.parse(expression, mode='eval')
        
        # 遍历 AST 节点，只允许常量和调用允许的函数
        allowed_names = set(self.ALLOWED_FUNCTIONS.keys())
        allowed_calls = set(self.ALLOWED_FUNCTIONS.keys())
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                if node.id not in allowed_names:
                    raise ValueError(f"不允许的标识符: {node.id}")
            elif isinstance(node, ast.Attribute):
                # 不允许属性访问，如 math.sqrt
                raise ValueError("不允许的属性访问")
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id not in allowed_calls:
                        raise ValueError(f"不允许的函数调用: {node.func.id}")
                else:
                    raise ValueError("不支持的函数调用形式")
        
        # 执行表达式
        return eval(expression, {"__builtins__": {}}, self.ALLOWED_FUNCTIONS)

    def execute(self, expression: str, **kwargs) -> ToolResult:
        """
        执行计算
        
        Args:
            expression: 数学表达式
        """
        # 安全检查
        is_safe, error_msg = self._is_safe_expression(expression)
        if not is_safe:
            return ToolResult(success=False, error=error_msg)
        
        try:
            result = self._safe_eval(expression)
            
            return ToolResult(
                success=True,
                content={
                    "expression": expression,
                    "result": result,
                    "type": type(result).__name__
                }
            )
            
        except SyntaxError as e:
            return ToolResult(success=False, error=f"语法错误: {str(e)}")
        except ValueError as e:
            return ToolResult(success=False, error=f"安全错误: {str(e)}")
        except Exception as e:
            return ToolResult(success=False, error=f"计算错误: {str(e)}")
