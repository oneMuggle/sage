"""从 preferences KV 加载 bash 工具运行参数（PR-2 常量可配置化）。

存储位置是 ``preferences`` 表的 ``bash_config`` key（JSON 字符串），与
``network_policy`` 同一套 KV 机制（见 network_config.py 模块注释）—— 不走
``app_settings`` blob，避免碰 ``LEGAL_TOP_KEYS`` 白名单与前后端三处同步。

**fail-safe 方向**：任何读取/解析/校验失败都整体回退默认值。默认值与
``bash_tool`` / ``bash_session`` 的模块常量一致（``BASH_DEFAULT_TIMEOUT_SECONDS``
等）—— 无配置时行为与硬编码时代完全一致；一致性由
``tests/unit/test_bash_config.py`` 双向锁定。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

#: preferences 表的 key（需在 ``SettingsRepository.KEYS`` 白名单内）
SETTINGS_KEY_BASH_CONFIG = "bash_config"

#: timeout_default 的下限 —— 与 bash_tool.BASH_MIN_TIMEOUT_SECONDS 一致
BASH_MIN_TIMEOUT_SECONDS = 1.0


def _num(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):  # noqa: UP038 — py3.8 不支持 X | Y isinstance
        raise TypeError(f"{name} 必须是数字")
    return float(value)


def _int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):  # noqa: UP038 — py3.8 不支持 X | Y isinstance
        raise TypeError(f"{name} 必须是整数")
    return int(value)


@dataclass(frozen=True)
class BashConfig:
    """bash 工具运行参数（同步超时 / 输出截断 / 后台会话上限）。"""

    #: 前景执行默认超时（秒）—— bash_tool.BASH_DEFAULT_TIMEOUT_SECONDS
    timeout_default: float = 120.0
    #: 前景执行超时上限（秒）—— bash_tool.BASH_MAX_TIMEOUT_SECONDS
    timeout_max: float = 600.0
    #: stdout/stderr 各自的输出截断上限（字节）—— bash_tool.BASH_MAX_OUTPUT_BYTES
    output_cap: int = 30 * 1024
    #: 后台会话上限 —— bash_session.MAX_BACKGROUND_SESSIONS
    max_sessions: int = 32

    @classmethod
    def from_config(cls, cfg: Dict[str, Any]) -> BashConfig:
        """从已解析的 dict 构造，缺字段回退默认。

        字段类型不对抛 ``TypeError``、取值越界抛 ``ValueError``；两者都由
        ``load_bash_config`` 捕获并整体回退默认（与 network_config 的
        fail-safe 口径一致 —— 不做字段级降级，避免半配置的歧义状态）。
        """
        defaults = cls()
        timeout_default = _num(
            cfg.get("timeout_default", defaults.timeout_default), "timeout_default"
        )
        timeout_max = _num(
            cfg.get("timeout_max", defaults.timeout_max), "timeout_max"
        )
        output_cap = _int(cfg.get("output_cap", defaults.output_cap), "output_cap")
        max_sessions = _int(
            cfg.get("max_sessions", defaults.max_sessions), "max_sessions"
        )
        if timeout_default < BASH_MIN_TIMEOUT_SECONDS:
            raise ValueError("timeout_default 不能小于 1 秒")
        if timeout_max < timeout_default:
            raise ValueError("timeout_max 不能小于 timeout_default")
        if output_cap < 1:
            raise ValueError("output_cap 必须是正整数")
        if max_sessions < 1:
            raise ValueError("max_sessions 必须是正整数")
        return cls(
            timeout_default=timeout_default,
            timeout_max=timeout_max,
            output_cap=output_cap,
            max_sessions=max_sessions,
        )


def load_bash_config(repo: Optional[Any] = None) -> BashConfig:
    """读取 bash 运行参数；任何失败回退 ``BashConfig()``（硬编码时代行为）。

    Args:
        repo: 可注入的 ``SettingsRepository``（测试用）；``None`` 时新建。
    """
    try:
        if repo is None:
            # 惰性 import 避免 tools ↔ data 循环依赖（与 network_config 同手法）
            from backend.data.settings_repo import SettingsRepository

            repo = SettingsRepository()
        raw = repo.get(SETTINGS_KEY_BASH_CONFIG)
    except Exception:  # noqa: BLE001 — 配置读取失败绝不阻断工具注册
        logger.warning("bash 配置读取失败，回退默认值", exc_info=True)
        return BashConfig()

    if not raw:
        return BashConfig()

    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("bash 配置 JSON 解析失败，回退默认值")
        return BashConfig()

    if not isinstance(parsed, dict):
        logger.warning("bash 配置不是 JSON 对象，回退默认值")
        return BashConfig()

    try:
        return BashConfig.from_config(parsed)
    except (ValueError, TypeError):
        logger.warning("bash 配置字段非法，回退默认值")
        return BashConfig()


__all__ = ["BASH_MIN_TIMEOUT_SECONDS", "BashConfig", "SETTINGS_KEY_BASH_CONFIG", "load_bash_config"]
