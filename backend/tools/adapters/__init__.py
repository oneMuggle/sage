"""适配器初始化入口。

集中导入并注册运行时适配器，便于上层 ``runtime_probe`` /
``runtime_exec`` / ``project_diagnose`` 调用。
"""

from __future__ import annotations

from typing import Iterable

from backend.tools.runtime_adapter import RuntimeAdapter, registry

from .node_adapter import NodeAdapter
from .python_adapter import PythonAdapter


def register_default_adapters() -> None:
    """注册内置运行时适配器（幂等）。"""

    for adapter in _iter_default_adapters():
        if registry.get(adapter.language) is None:
            registry.register(adapter)


def _iter_default_adapters() -> Iterable[RuntimeAdapter]:
    return [
        PythonAdapter(),
        NodeAdapter(),
    ]


__all__ = ["register_default_adapters"]
