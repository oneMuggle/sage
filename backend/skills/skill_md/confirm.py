"""SKILL.md 用户确认协议（v2）。

- ``ConfirmationPort``: 用户确认端口协议（六边形出站边界）

设计要点
--------

- 核心逻辑不依赖具体传输方式（HTTP / WebSocket / CLI dialog）
- 单测可注入 auto-confirm mock
- 实际实现（CLI/HTTP 回调）在 ``backend/adapters/out/skill_script/``
"""

from __future__ import annotations
from typing import Tuple

from pathlib import Path
from typing import Protocol


class ConfirmationPort(Protocol):
    """用户确认端口（六边形出站边界）。

    沙箱执行前必须先确认。返回 True 表示用户允许执行，False 表示拒绝。

    实现要点:
      - 永不抛异常: callback 失败时返回 False（默认拒绝）
      - 默认实现: 无 callback 时返回 True（向后兼容，假设测试/开发环境）
      - 异步: 实际确认可能涉及 UI 弹窗、网络回调，因此必须是 async
    """

    async def confirm(
        self,
        skill_name: str,
        script_path: Path,
        args: Tuple[str, ...],
    ) -> bool:
        """请求用户确认脚本执行。

        Args:
            skill_name: 请求执行的技能名
            script_path: 要执行的脚本路径（用于显示给用户）
            args: 脚本参数（用于显示给用户）

        Returns:
            True 表示用户允许执行，False 表示拒绝
        """
        ...
