"""CLI 确认适配器。

生产环境使用的 ``ConfirmationPort`` 实现，通过 callback 获取用户确认。
所有确认器都 fail-closed：没有 callback 时拒绝执行。
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)


class ConfiguredScriptConfirmationAdapter:
    """由显式配置白名单确认脚本执行的生产确认器。

    配置通过 ``SAGE_SKILL_SCRIPT_ALLOWLIST`` 传入，使用逗号分隔的条目：
    ``skill:<exact-name>`` 或 ``path:<absolute-directory>``。默认值为空，
    且 malformed 条目不会放宽权限。技能名匹配是精确匹配；路径匹配要求
    脚本解析后的路径位于配置目录内（不接受目录前缀伪匹配）。

    这不是用户交互审批，也不替代 ``ApprovalGate``；它只为当前没有同步
    HTTP→Electron 脚本 callback 的生产装配提供一个显式、可审计的 fail-closed
    配置入口。
    """

    ENV_ALLOWLIST = "SAGE_SKILL_SCRIPT_ALLOWLIST"

    def __init__(
        self,
        *,
        allowed_skill_names: Iterable[str] = (),
        allowed_path_roots: Iterable[Path] = (),
    ) -> None:
        self._allowed_skill_names = frozenset(
            name for name in allowed_skill_names if isinstance(name, str) and name
        )
        self._allowed_path_roots = tuple(
            path.resolve() for path in allowed_path_roots if isinstance(path, Path)
        )

    @classmethod
    def from_environment(cls) -> ConfiguredScriptConfirmationAdapter:
        """从环境变量解析白名单；未设置或包含非法项时仍保持最小授权。"""
        skill_names = []
        path_roots = []
        raw = os.environ.get(cls.ENV_ALLOWLIST, "")
        for raw_entry in raw.split(","):
            entry = raw_entry.strip()
            if not entry:
                continue
            kind, separator, value = entry.partition(":")
            value = value.strip()
            if not separator or not value:
                logger.warning("忽略格式非法的脚本白名单条目")
                continue
            if kind == "skill":
                skill_names.append(value)
            elif kind == "path":
                path = Path(value).expanduser()
                if path.is_absolute() and path.is_dir():
                    path_roots.append(path)
                else:
                    logger.warning("忽略非绝对或不存在的脚本白名单路径")
            else:
                logger.warning("忽略未知脚本白名单类型: %s", kind)
        return cls(allowed_skill_names=skill_names, allowed_path_roots=path_roots)

    def _path_is_allowed(self, script_path: Path) -> bool:
        """使用 commonpath 做目录边界匹配，避免 ``/rooted`` 命中 ``/root``。"""
        candidate = str(script_path.resolve())
        for root in self._allowed_path_roots:
            try:
                if os.path.commonpath((candidate, str(root))) == str(root):
                    return True
            except ValueError:
                # Windows 不同盘符等不可比较的路径必须拒绝。
                continue
        return False

    async def confirm(
        self,
        skill_name: str,
        script_path: Path,
        args: Tuple[str, ...],
    ) -> bool:
        """仅在技能名或受控路径显式命中时批准；args 不参与授权。"""
        del args
        return skill_name in self._allowed_skill_names or self._path_is_allowed(script_path)


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

        except (asyncio.TimeoutError, TimeoutError):  # noqa: UP041 - retain both names for Python 3.8/3.10 compatibility
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
