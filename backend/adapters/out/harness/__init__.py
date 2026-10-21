"""Harness 出站适配器。

- ``SqliteHarnessAdapter`` : 将 ``harness_components`` 表桥接为
  ``HarnessPort``,提供 harness 组件的注册、发现、配置更新与 usage 记账。
"""

from .sqlite_adapter import HARNESS_COMPONENT_TYPES, SqliteHarnessAdapter

__all__ = ["HARNESS_COMPONENT_TYPES", "SqliteHarnessAdapter"]
