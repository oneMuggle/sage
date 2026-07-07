"""CLI 确认适配器（v2）。

生产环境使用的 ``ConfirmationPort`` 实现，通过可注入的 callback 获取用户确认。

设计要点
--------

- callback 可以是 sync 或 async，统一通过 ``asyncio.iscoroutine`` 判断
- callback 抛异常时返回 False（默认拒绝，更安全）
- 无 callback 时默认返回 True（向后兼容，假设测试/开发环境）
- 可配置超时（默认 60s）
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)


class CliConfirmationAdapter:
    """CLI 确认适配器（生产用）。

    通过可注入的 callback 函数获取用户确认。callback 可以是:
      - 普通函数（返回 bool）
      - async 函数（返回 coroutine）

    Args:
        timeout_s: 确认超时（秒），默认 60s
        callback: 用户定义的确认回调函数。签名: ``(skill_name, script_path, args) -> bool | Awaitable[bool]``
                 如果为 None，**默认拒绝**（M3 fail-closed：更安全）。
                 调用方需显式注入自动确认 callback 才能无回调通过。

    M3 变更：callback=None 旧默认 True → 新默认 False（fail-closed）。
    """

    def __init__(
        self,
        *,
        timeout_s: float = 60.0,
        callback: Optional[Callable[..., Any]] = None,
    ) -> None:
        self._timeout_s = timeout_s
        self._callback = callback

    async def confirm(
        self,
        skill_name: str,
        script_path: Path,
        args: Tuple[str, ...],
    ) -> bool:
        """调用 callback 获取用户确认。

        Args:
            skill_name: 技能名
            script_path: 脚本路径
            args: 脚本参数

        Returns:
            callback 返回值，异常时返回 False，无 callback 时**默认拒绝**（M3）
        """
        if self._callback is None:
            logger.debug(
                "CliConfirmationAdapter has no callback, fail-closed reject %s",
                skill_name,
            )
            return False

        try:
            result = self._callback(
                skill_name=skill_name,
                script_path=script_path,
                args=args,
            )

            # 如果 callback 返回的是 coroutine，等待它
            if inspect.iscoroutine(result):
                result = await asyncio.wait_for(result, timeout=self._timeout_s)

            return bool(result)

        except TimeoutError:
            logger.warning(
                "CliConfirmationAdapter timeout after %.1fs for skill %s",
                self._timeout_s,
                skill_name,
            )
            return False
        except Exception as exc:
            logger.warning(
                "CliConfirmationAdapter callback failed for skill %s: %s",
                skill_name,
                exc,
            )
            return False
