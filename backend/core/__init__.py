"""Core 模块。

Phase 3 (startup perf): 顶层不再 eager import `backend.core.legacy.agent` /
`llm_client`。任何 `backend.core.<submodule>` 导入都会先执行本文件，原 eager
导出会把 `backend.tools`（~1.4s）拖进后端启动关键路径。改用 PEP 562 惰性
`__getattr__`：只在属性首次被访问时才导入对应子模块。
"""

from importlib import import_module
from typing import Any, List

__all__ = [
    "SageAgent",
    "LLMClient",
    "LLMConfig",
    "LLMResponse",
    "AgentError",
    "ToolCallError",
    "handle_sage_error",
    "ConventionManager",
    "Convention",
]

_LAZY_EXPORTS = {
    "SageAgent": ("backend.core.legacy.agent", "SageAgent"),
    "LLMClient": ("backend.core.legacy.llm_client", "LLMClient"),
    "LLMConfig": ("backend.core.legacy.llm_client", "LLMConfig"),
    "LLMResponse": ("backend.core.legacy.llm_client", "LLMResponse"),
    "AgentError": ("backend.core.exceptions", "AgentError"),
    "ToolCallError": ("backend.core.exceptions", "ToolCallError"),
    "handle_sage_error": ("backend.core.exceptions", "handle_sage_error"),
    "ConventionManager": ("backend.core.conventions", "ConventionManager"),
    "Convention": ("backend.core.conventions", "Convention"),
}


def __getattr__(name: str) -> Any:
    try:
        module_path, attr = _LAZY_EXPORTS[name]
    except KeyError:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from None
    value = getattr(import_module(module_path), attr)
    globals()[name] = value
    return value


def __dir__() -> List[str]:
    return sorted(set(globals()) | set(__all__))
