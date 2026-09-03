"""从 preferences KV 加载 ``NetworkPolicy``。

存储位置是 ``preferences`` 表的 ``network_policy`` key（JSON 字符串），与
``permission_mode`` 同一套 KV 机制 —— 不走 ``app_settings`` blob，避免碰
``LEGAL_TOP_KEYS`` 白名单与前后端三处同步。

**fail-safe 方向**：任何读取/解析/校验失败都回退 ``ONLINE``（现状行为）。
配置读不出来时不应该把用户的既有能力锁死。这与
``load_tool_policy_from_config`` 的降级口径一致。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from backend.domain.network_policy import NetworkPolicy

logger = logging.getLogger(__name__)

#: preferences 表的 key（需在 ``SettingsRepository.KEYS`` 白名单内）
SETTINGS_KEY_NETWORK_POLICY = "network_policy"


def load_network_policy(repo: Optional[Any] = None) -> NetworkPolicy:
    """读取网络策略；任何失败回退 ``NetworkPolicy()``（ONLINE）。

    Args:
        repo: 可注入的 ``SettingsRepository``（测试用）；``None`` 时新建。
    """
    try:
        if repo is None:
            # 惰性 import 避免 tools ↔ data 循环依赖（与 permissions.py 同手法）
            from backend.data.settings_repo import SettingsRepository

            repo = SettingsRepository()
        raw = repo.get(SETTINGS_KEY_NETWORK_POLICY)
    except Exception:  # noqa: BLE001 — 配置读取失败绝不阻断工具注册
        logger.warning("网络策略读取失败，回退 online 模式", exc_info=True)
        return NetworkPolicy()

    if not raw:
        return NetworkPolicy()

    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("网络策略 JSON 解析失败，回退 online 模式")
        return NetworkPolicy()

    if not isinstance(parsed, dict):
        logger.warning("网络策略不是 JSON 对象，回退 online 模式")
        return NetworkPolicy()

    try:
        return NetworkPolicy.from_config(parsed)
    except (ValueError, TypeError):
        logger.warning("网络策略字段非法，回退 online 模式")
        return NetworkPolicy()
