"""模块级惰性导入辅助（Phase 3 启动性能）。

模块级 ``__getattr__`` 不参与函数体内的 LOAD_GLOBAL，故在调用点用它：
先查调用方模块的 ``globals()``（保持 ``patch("a.b.SageAgent")`` 语义），
未命中再从目标模块导入并缓存回调用方 globals。第二次起只是一次字典查找。
"""

from importlib import import_module
from typing import Any, Dict

_MISSING = object()


def load_attr(module_name: str, attr: str, scope_globals: Dict[str, Any]) -> Any:
    value = scope_globals.get(attr, _MISSING)
    if value is not _MISSING:
        return value
    value = getattr(import_module(module_name), attr)
    scope_globals[attr] = value
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
