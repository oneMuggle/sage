"""模块级惰性导入辅助（Phase 3 启动性能）。

模块级 ``__getattr__`` 不参与函数体内的 LOAD_GLOBAL，故在调用点用它：
先查调用方模块的 ``globals()``（保持 ``patch("a.b.SageAgent")`` 语义），
未命中再从目标模块导入并缓存回调用方 globals。第二次起只是一次字典查找。
"""

from importlib import import_module
from typing import Any, Dict, Optional

_MISSING = object()


def load_attr(
    module_name: str,
    attr: str,
    scope_globals: Dict[str, Any],
    alias: Optional[str] = None,
) -> Any:
    """惰性取目标模块的具名属性，缓存回调用方 ``globals()``。

    ``alias`` 用于"取的是 A.B 但在本模块里叫 C"的场景（如
    ``from docx import Document as _Docx``）：缓存键取 ``alias``，
    否则 ``patch("本模块._Docx")`` 会因为模块 ``__dict__`` 里没有该键
    而落到 ``__getattr__``，patch 语义不完整。
    """
    cache_key = alias or attr
    value = scope_globals.get(cache_key, _MISSING)
    if value is not _MISSING:
        return value
    value = getattr(import_module(module_name), attr)
    scope_globals[cache_key] = value
    return value


def load_module(module_name: str, alias: str, scope_globals: Dict[str, Any]) -> Any:
    """惰性导入整个模块并缓存回调用方 ``globals()``。

    用于 ``import pandas as pd`` 这类"模块本身即导出值"的场景——
    ``load_attr`` 只能取模块内的具名属性，取不到模块对象本身。

    先查 ``scope_globals[alias]``（保持 ``patch("a.b.pd")`` 语义），
    未命中再 ``import_module`` 并写回。第二次起只是一次字典查找。
    """
    value = scope_globals.get(alias, _MISSING)
    if value is not _MISSING:
        return value
    value = import_module(module_name)
    scope_globals[alias] = value
    return value


def module_getattr(
    name: str,
    exports: Dict[str, str],
    scope_globals: Dict[str, Any],
    module_name: str,
) -> Any:
    """PEP 562 ``__getattr__`` 的共用实现：按名字映射惰性导入并缓存。

    调用方模块只需::

        _LAZY_EXPORTS = {"SageAgent": "backend.core.legacy.agent"}

        def __getattr__(name: str) -> Any:
            return module_getattr(name, _LAZY_EXPORTS, globals(), __name__)

    这样 ``patch("pkg.mod.SageAgent")`` 依旧可用：首次解析把真实对象写回
    模块 ``globals()``，patch 的读取/覆盖/还原都落在正常属性槽上。
    """
    module_path = exports.get(name)
    if module_path is None:
        raise AttributeError(f"module {module_name!r} has no attribute {name!r}")
    value = getattr(import_module(module_path), name)
    scope_globals[name] = value
    return value
