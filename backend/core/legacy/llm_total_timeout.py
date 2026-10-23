"""整轮 agent 任务 wall-clock 上限（`llm_total_timeout_s()`）。

替代原模块级常量 `_SAGE_LLM_TOTAL_TIMEOUT_S`（`backend/api/legacy_routes.py`
旧版），把读取从 import 时求值改成**每次请求函数式读取**，以便 UI 改完
`app_settings.llmTotalTimeoutS` 立即生效、无须重启后端。

优先级（用户已确认）：

1. ``app_settings.llmTotalTimeoutS``（键存在即用；``0`` = 不限）
2. 环境变量 ``SAGE_LLM_TOTAL_TIMEOUT_S``（> 0 才生效）
3. 内置默认 ``_LLM_TOTAL_TIMEOUT_DEFAULT_S``（= 1800）

任何解析失败静默回退下一级、绝不抛错；非法值记 warning。

调用方约定：

- 返回值 ``0.0`` 表示"不限"——`asyncio.wait_for(coro, timeout=None)` 在
  py3.8 等价于 ``await coro``，因此**直接传 0.0 不行**，需调用方判 ``or None``。
  本模块显式提供 :func:`llm_total_timeout_or_none` 做这层转换。
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# 默认 1800s = 2 × orch.subagentTaskTimeoutS 默认 900s。
# 保证单个合法子代理不会比整轮预算活得久（事故 2026-10-22 成因）。
_LLM_TOTAL_TIMEOUT_DEFAULT_S: float = 1800.0


def llm_total_timeout_s() -> float:
    """整轮任务 wall-clock 上限（秒）。

    Returns:
        上限秒数；``0.0`` 表示不限。调用方使用 :func:`llm_total_timeout_or_none`
        拿到可直接传给 ``asyncio.wait_for`` 的值。
    """
    value = _LLM_TOTAL_TIMEOUT_DEFAULT_S
    resolved = False

    # 1) app_settings 优先（用户已在 UI 设置过则 env 不再介入）
    try:
        from backend.data.settings_repo import SettingsRepository

        raw = SettingsRepository().get_json("app_settings") or {}
        if isinstance(raw, dict):
            configured = raw.get("llmTotalTimeoutS")
            if isinstance(configured, bool):
                pass  # bool 是 int 子类，显式排除
            elif isinstance(configured, int) and configured >= 0:
                value = float(configured)
                resolved = True
            elif isinstance(configured, float) and configured >= 0.0:
                value = configured
                resolved = True
    except (ImportError, OSError, ValueError, TypeError):
        # 读配置失败静默回退 env/默认
        pass

    if resolved:
        return value

    # 2) 环境变量（仅当 app_settings 未提供值时）
    raw_env = os.environ.get("SAGE_LLM_TOTAL_TIMEOUT_S", "").strip()
    if raw_env:
        try:
            env_value = float(raw_env)
            if env_value >= 0.0:
                value = env_value
            else:
                logger.warning(
                    "env SAGE_LLM_TOTAL_TIMEOUT_S=%r 负值,回退", raw_env
                )
        except ValueError:
            logger.warning(
                "env SAGE_LLM_TOTAL_TIMEOUT_S=%r 非法,回退默认", raw_env
            )

    return value


def llm_total_timeout_or_none() -> float | None:
    """返回可直接传给 ``asyncio.wait_for(coro, timeout=...)`` 的值。

    0.0 → None（= 不限）；其他正值原样返回。
    """
    v = llm_total_timeout_s()
    return None if v <= 0.0 else v
