# ruff: noqa: UP006, UP007, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Python 3.8 兼容垫片（win7 LTS 支持用）。

- ``to_thread``：asyncio.to_thread 是 3.9+ 才有的标准库 API；
  3.8 退化为 ``loop.run_in_executor``（默认线程池，语义等价——都不能取消已入池任务）。
"""
from __future__ import annotations

import ast
import asyncio
import contextvars
import functools
import sys
from typing import Any, Callable

_has_native_to_thread = sys.version_info >= (3, 9)


async def to_thread(func: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
    """``asyncio.to_thread`` 的 py38 等价实现。"""
    call = functools.partial(func, *args, **kwargs)
    if _has_native_to_thread:
        return await asyncio.to_thread(func, *args, **kwargs)
    ctx = contextvars.copy_context()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, ctx.run, call)


# wait_for / wait 超时异常族：py38 中 asyncio.TimeoutError 与 builtin
# TimeoutError 是两个类（3.11 起合流），except 必须同时覆盖。
# 以常量形式提供，避免各 except 行被 UP041 autofix 改回单型。
TIMEOUT_ERRORS = (TimeoutError, getattr(asyncio, "TimeoutError", TimeoutError))


def ast_unparse(node: ast.AST) -> str:
    """``ast.unparse`` 的 py38 兼容实现（3.9+ 才有）。

    降级策略：Name/Attribute/Constant 精确还原，其余（Subscript 等
    复合标注）返回空串——调用方（文档生成）对空串有容错。
    """
    if hasattr(ast, "unparse"):
        return ast.unparse(node)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parts = []
        cur: ast.expr = node
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
            return ".".join(reversed(parts))
        return ""
    if isinstance(node, ast.Constant):
        return repr(node.value)
    return ""
