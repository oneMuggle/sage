"""工具执行内核共享件（hex-legacy 双栈收敛切片 A 起步）。

两栈（hex InprocToolAdapter 与 legacy run_loop 并行只读批次）共用的
超时语义、required 参数校验、output 截断文案单源；后续统一执行内核
在此扩展。

alpha.36 (Bug #1): `validate_required_args` —— 把 SageAgent
`_validate_required_params` 的校验下沉到 ToolRegistry 公共层，
让 InprocToolAdapter 与并行只读批次在分发前先拦截缺 required 参数
的调用，把 TypeError 转成 ToolResult(success=False, error=...)，
不再让 LLM 看到 `TypeError: execute() missing 1 required positional
argument: 'doc_id'`。
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Dict, List, Optional, Tuple

from backend.tools.base import BaseTool

# Python 3.10: asyncio.TimeoutError ≠ builtin TimeoutError；3.11+ 为同一类，
# 兼容两个名称（hex adapter 原内联写法收敛至此）。
TIMEOUT_EXCEPTIONS: tuple = (asyncio.TimeoutError, TimeoutError)  # noqa: UP041


def tool_timeout_message(timeout_seconds) -> str:
    """工具超时错误文案（两栈统一，供 LLM 观察结果解析）。"""
    return f"tool_timeout: exceeded {timeout_seconds}s"


def truncate_output(output: str, max_output_bytes: int) -> Tuple[str, dict]:
    """按 utf-8 字节截断工具输出（两栈统一，切片 A 收口）。

    Returns:
        (截断后字符串, metadata dict)。未截断时 metadata 为空 dict，
        截断时为 {"truncated": True, "original_bytes": N, "max_output_bytes": M}。
    """
    raw_bytes = output.encode("utf-8")
    if len(raw_bytes) <= max_output_bytes:
        return output, {}
    truncated = raw_bytes[:max_output_bytes].decode("utf-8", errors="replace")
    return truncated, {
        "truncated": True,
        "original_bytes": len(raw_bytes),
        "max_output_bytes": max_output_bytes,
    }


def required_args_error(tool: BaseTool, missing: List[str]) -> str:
    """required 参数缺失的统一错误文案（中文 + JSON-schema 风格）。"""
    name = getattr(tool, "name", type(tool).__name__)
    if len(missing) == 1:
        return f"missing_required_argument: {missing[0]} (tool={name})"
    return f"missing_required_arguments: {','.join(missing)} (tool={name})"


def validate_required_args(
    tool: BaseTool, args: Dict[str, Any]
) -> Optional[str]:
    """校验 args 是否满足 tool 的 required 参数契约。

    Args:
        tool: 待执行的工具实例（须是 `BaseTool` 子类，且有
            `schema.parameters` 的 JSON-schema `required` 列表）。
        args: LLM 给的调用参数字典。

    Returns:
        None —— 通过校验；或 str 错误文案（与
        `required_args_error` 同模板），调用方应直接返回
        `ToolResult(success=False, error=<错误文案>)`，**不要**让
        `tool.execute(**args)` 真的被调用（缺 required 时会抛
        TypeError，把内部错误文本泄漏给 LLM）。

    设计原则：
    - 校验基于 JSON-schema `required` 列表（tool 自己声明的唯一来源）；
      不读 `inspect.signature(tool.execute)` —— execute 签名可能有默认值，
      JSON-schema `required` 才是给 LLM 的契约。
    - 类型校验不在此处做（schema 参数类型校验由 ToolRegistry.get_schemas_for_llm
      与各自工具的 type: object 描述把守，TypeError 仍是工具内部实现 bug）。
    - 'None' 视为缺失（LLM 偶尔会发 {"doc_id": null}，JSON-schema required
      语义上等同于缺失）。

    alpha.36 (Bug #1)：原校验只挂在 SageAgent._await_tool_execution
    与 execute_tool（agent.py:689 / :1782），hex InprocToolAdapter
    (inproc_adapter.py:132) 与并行只读批次（agent.py:1175 _run_one）
    完全跳过 → 用户看到 Python TypeError 文本。下沉到此公共 helper。
    """
    schema = getattr(tool, "schema", None)
    if schema is None:
        return None  # 没 schema 的工具没法校验，让它自己抛
    params = getattr(schema, "parameters", None)
    if not isinstance(params, dict):
        return None
    required = params.get("required")
    if not isinstance(required, (list, tuple)) or not required:
        return None
    missing: List[str] = []
    for key in required:
        if key not in args or args[key] is None:
            missing.append(key)
    if not missing:
        return None
    return required_args_error(tool, list(missing))


def _format_typeerror_message(tool: BaseTool, exc: TypeError) -> str:
    """fallback：schema 没声明 required 但 execute() 仍因缺参数抛 TypeError。

    主要兜底旧工具（缺 BaseTool.schema 或 schema.parameters 缺失 required 段），
    不让 Python 原生 TypeError 文本泄漏到 LLM。
    """
    sig = inspect.signature(tool.execute)  # type: ignore[arg-type]
    name = getattr(tool, "name", type(tool).__name__)
    return (
        f"missing_required_argument (tool={name}); "
        f"signature={list(sig.parameters)}; original={exc}"
    )
