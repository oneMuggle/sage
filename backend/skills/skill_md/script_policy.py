"""技能脚本执行策略（T-3 fail-closed 开关）。

本模块封装 "是否允许 SKILL.md 脚本分发" 这一能力的判定逻辑，
与权限系统（``backend/tools/permissions.py``）的两层闸口之一 ——
本开关是第一道（用户显式授权），权限执行器是第二道（模式矩阵）。

设计原则：
- 缺省关闭（fail-closed）：未显式开启 = 拒绝。
- 读取失败（DB 故障、key 缺失）视为关闭：记 warning 并返回 False，
  不因设置子系统故障静默放行外部脚本执行。
- 单测可注入 repo，不依赖全局单例。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: preference key（与 SettingsRepository.KEYS 白名单同步）
SETTINGS_KEY_ALLOW_SKILL_SCRIPTS = "allow_skill_scripts"


def is_script_execution_allowed(repo: Any = None) -> bool:
    """判定是否允许执行技能脚本。

    Args:
        repo: 可注入的 ``SettingsRepository``（测试用）；``None`` 时新建。

    Returns:
        仅当 value 显式为 ``"1"`` 时返回 ``True``；其余（``None`` / ``"0"`` /
        其他 / 读取异常）均返回 ``False``（fail-closed）。
    """
    if repo is None:
        from backend.data.settings_repo import SettingsRepository

        repo = SettingsRepository()
    try:
        value = repo.get(SETTINGS_KEY_ALLOW_SKILL_SCRIPTS)
    except Exception as exc:  # noqa: BLE001 — DB 故障必须 fail-closed
        logger.warning("读取技能脚本开关失败，拒绝执行: %s", exc)
        return False
    return value == "1"


__all__ = ["SETTINGS_KEY_ALLOW_SKILL_SCRIPTS", "is_script_execution_allowed"]
