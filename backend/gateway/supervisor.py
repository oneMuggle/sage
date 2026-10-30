"""网关生命周期管理：懒启动 + 配置变更即时启停。

设计目标：
- 未配置 / 未启用时零开销（不创建网关、不启动轮询线程）；
- `PUT /gateway/{platform}/config` 保存后立即生效，无需重启后端；
- 停机时统一停止所有轮询线程。

平台 getter / resetter 的约定与 `backend.gateway.{telegram,discord,slack}` 一致：
getter 在未配置时返回 None，reset 清空模块级单例。
"""

from __future__ import annotations

import importlib
import logging
import threading
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# platform -> (module_name, getter_name, resetter_name)
_PLATFORMS: Dict[str, Tuple[str, str, str]] = {
    "telegram": (
        "backend.gateway.telegram",
        "get_telegram_gateway",
        "reset_telegram_gateway",
    ),
    "discord": (
        "backend.gateway.discord",
        "get_discord_gateway",
        "reset_discord_gateway",
    ),
    "slack": (
        "backend.gateway.slack",
        "get_slack_gateway",
        "reset_slack_gateway",
    ),
}


class GatewaySupervisor:
    """按配置启停各平台网关，持有当前运行中的实例。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._running: Dict[str, Any] = {}

    def apply(self, platform: str) -> Optional[Any]:
        """按当前配置重新计算某个平台的运行状态。

        已运行实例先停止并重置单例，再按最新 settings / env 重新创建；
        未配置或 enabled=False 时保持停止。返回运行中的网关或 None。
        """
        if platform not in _PLATFORMS:
            raise KeyError(f"unknown gateway platform: {platform}")
        with self._lock:
            old = self._running.pop(platform, None)
            if old is not None:
                self._stop(old, platform)

            module_name, getter_name, reset_name = _PLATFORMS[platform]
            module = importlib.import_module(module_name)
            getattr(module, reset_name)()
            gateway = getattr(module, getter_name)()
            if gateway is None:
                logger.info("%s 网关未启用/未配置，保持停止", platform)
                return None
            gateway.start_polling()
            self._running[platform] = gateway
            logger.info("%s 网关已启动（懒启动 / 动态生效）", platform)
            return gateway

    def start_enabled(self) -> Dict[str, bool]:
        """启动所有已配置的平台；单个平台失败不影响其他平台。"""
        report: Dict[str, bool] = {}
        for platform in _PLATFORMS:
            try:
                report[platform] = self.apply(platform) is not None
            except Exception as exc:  # noqa: BLE001 — 网关失败不阻塞后端启动
                logger.warning("%s 网关启动失败（忽略）: %s", platform, exc)
                report[platform] = False
        return report

    def stop_all(self) -> None:
        with self._lock:
            for platform, gateway in list(self._running.items()):
                self._stop(gateway, platform)
            self._running.clear()

    def is_running(self, platform: str) -> bool:
        with self._lock:
            return platform in self._running

    @staticmethod
    def _stop(gateway: Any, platform: str) -> None:
        try:
            gateway.stop_polling()
            logger.info("%s 网关已停止", platform)
        except Exception as exc:  # noqa: BLE001 — 停机清理不得抛出
            logger.debug("%s 网关停止失败（忽略）: %s", platform, exc)


_supervisor: Optional[GatewaySupervisor] = None


def get_gateway_supervisor() -> GatewaySupervisor:
    """进程级单例（由 main.py lifespan 持有并挂到 app.state）。"""
    global _supervisor
    if _supervisor is None:
        _supervisor = GatewaySupervisor()
    return _supervisor
