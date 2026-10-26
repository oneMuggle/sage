"""技能目录读取策略（T-4a）。

从 preferences 表读取 ``skills_dir``，做基础校验（非空、绝对路径、无 ``..`` 段），
非法或缺失返回 ``None`` 让调用方回退到下一级优先级（env var / 缺省）。

设计原则（镜像 ``script_policy.py``）：
- 不抛异常：设置损坏不应升级成启动失败。
- 读取失败（DB 故障、key 缺失）→ 记 warning 返回 None。
- 单测可注入 repo，不依赖全局单例。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: preference key（与 SettingsRepository.KEYS 白名单同步）
SETTINGS_KEY_SKILLS_DIR = "skills_dir"


def read_skills_dir_preference(repo: Any = None) -> Optional[Path]:
    """读取 skills_dir preference，做基础校验。

    Args:
        repo: 可注入的 ``SettingsRepository``（测试用）；``None`` 时新建。

    Returns:
        校验通过返回 ``Path``（已 expanduser、未 mkdir）；
        缺值 / 非法 / 读取异常均返回 ``None``。
    """
    if repo is None:
        from backend.data.settings_repo import SettingsRepository

        try:
            repo = SettingsRepository()
        except Exception as exc:  # noqa: BLE001 — DB 不可用时回退，不能把设置损坏升级成启动失败
            logger.warning("skills_dir preference 无法访问数据库，回退下一级: %s", exc)
            return None
    try:
        value = repo.get(SETTINGS_KEY_SKILLS_DIR)
    except Exception as exc:  # noqa: BLE001 — DB 故障必须回退，不能把设置损坏升级成启动失败
        logger.warning("读取 skills_dir preference 失败，回退下一级: %s", exc)
        return None
    if not value:
        return None

    try:
        candidate = Path(value).expanduser()
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        logger.warning("skills_dir preference 路径无法解析 '%s': %s", value, exc)
        return None

    if (
        not candidate.is_absolute()
        or ".." in candidate.parts
    ):
        logger.warning("skills_dir preference 非法 '%s'，回退下一级", value)
        return None

    return candidate


__all__ = ["SETTINGS_KEY_SKILLS_DIR", "read_skills_dir_preference"]
