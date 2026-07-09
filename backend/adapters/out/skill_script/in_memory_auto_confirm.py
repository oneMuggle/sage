"""In-Memory 自动确认适配器（v2）。

测试和开发环境使用的 ``ConfirmationPort`` 实现，总是返回固定值（默认 True）。
支持 ``auto_approve()`` / ``auto_deny()`` 工厂方法。

设计要点
--------

- 简单、确定性，便于测试
- 通过 ``response`` 参数配置返回值
- 工厂方法提供语义化构造（auto_approve / auto_deny）
"""

from __future__ import annotations
from typing import Tuple

from pathlib import Path
from typing import Tuple


class InMemoryAutoConfirmAdapter:
    """自动确认适配器（测试用）。

    Args:
        response: confirm() 的固定返回值（默认 True = 自动批准）
    """

    def __init__(self, response: bool = True) -> None:
        self._response = response

    async def confirm(
        self,
        skill_name: str,
        script_path: Path,
        args: Tuple[str, ...],
    ) -> bool:
        """返回 ``self._response``（忽略所有参数）。

        Args:
            skill_name: 技能名（忽略）
            script_path: 脚本路径（忽略）
            args: 脚本参数（忽略）

        Returns:
            ``self._response`` 的值
        """
        return self._response

    @classmethod
    def auto_approve(cls) -> InMemoryAutoConfirmAdapter:
        """工厂方法: 构造一个自动批准的适配器。"""
        return cls(response=True)

    @classmethod
    def auto_deny(cls) -> InMemoryAutoConfirmAdapter:
        """工厂方法: 构造一个自动拒绝的适配器。"""
        return cls(response=False)
