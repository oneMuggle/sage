"""从 preferences KV 加载 ``NetworkPolicy``。

存储位置是 ``preferences`` 表的 ``network_policy`` key（JSON 字符串），与
``permission_mode`` 同一套 KV 机制 —— 不走 ``app_settings`` blob，避免碰
``LEGAL_TOP_KEYS`` 白名单与前后端三处同步。

**fail-safe 方向**：任何读取/解析/校验失败都回退 ``OFFLINE``。
不可信配置不得扩大网络权限；本地工具仍可使用。企业部署环境提供更严格的上限。
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from backend.domain.network_policy import NetworkMode, NetworkPolicy

logger = logging.getLogger(__name__)

#: preferences 表的 key（需在 ``SettingsRepository.KEYS`` 白名单内）
SETTINGS_KEY_NETWORK_POLICY = "network_policy"


def load_network_policy(repo: Optional[Any] = None) -> NetworkPolicy:
    """读取网络策略；任何失败回退 OFFLINE，管理员部署模式优先。

    Args:
        repo: 可注入的 ``SettingsRepository``（测试用）；``None`` 时新建。
    """
    deployment = os.environ.get("SAGE_DEPLOYMENT_MODE", "").strip().lower()
    if deployment and deployment != "online":
        if deployment == "intranet":
            try:
                hosts = tuple(h.strip() for h in os.environ.get("SAGE_NETWORK_ALLOWED_HOSTS", "").split(",") if h.strip())
                return NetworkPolicy(mode=NetworkMode.INTRANET, allowed_hosts=hosts)
            except (ValueError, TypeError):
                logger.warning("管理员内网白名单非法，已禁止外联（offline）")
        return NetworkPolicy(mode=NetworkMode.OFFLINE)
    try:
        if repo is None:
            from backend.data.settings_repo import SettingsRepository

            repo = SettingsRepository()
        raw = repo.get(SETTINGS_KEY_NETWORK_POLICY)
        if not raw:
            return NetworkPolicy(mode=NetworkMode.OFFLINE)
        parsed = json.loads(raw)
        if not isinstance(parsed, dict) or "mode" not in parsed:
            raise ValueError("network_policy must be an object with an explicit mode")
        return NetworkPolicy.from_config(parsed)
    except Exception:  # noqa: BLE001 — invalid/unreadable policy must never expand network access
        logger.warning("网络策略读取或校验失败，已禁止外联（offline）", exc_info=True)
        return NetworkPolicy(mode=NetworkMode.OFFLINE)
