"""2026-11-26: 端点健康注册表（LLM 故障转移用）。

进程内内存状态机，不持久化：

- ``record_failure`` 累计连续失败，达到阈值 → ``failed``，否则 ``degraded``；
- ``record_success`` 立即恢复 ``healthy``；
- ``is_available`` 对 ``failed`` 端点只在其冷却期已满时返回 True（被动 failback），
  冷却期内由构链逻辑排到末尾、由后台探测恢复。

配置来源 ``app_settings.failover``（``load_failover_config`` 防御式读取，
任何失败回退默认值）。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

HEALTHY = "healthy"
DEGRADED = "degraded"
FAILED = "failed"

DEFAULT_THRESHOLD = 2
DEFAULT_COOLDOWN_S = 60.0
DEFAULT_PROBE_INTERVAL_MS = 300_000
DEFAULT_COOLDOWN_MS = 60_000
FAILOVER_INT_RANGES = {
    "probeIntervalMs": (30_000, 86_400_000),
    "cooldownMs": (5_000, 3_600_000),
    "consecutiveFailThreshold": (1, 10),
}


@dataclass
class FailoverConfig:
    """``app_settings.failover`` 的解析结果。"""

    enabled: bool = False
    probe_interval_ms: int = DEFAULT_PROBE_INTERVAL_MS
    cooldown_ms: int = DEFAULT_COOLDOWN_MS
    consecutive_fail_threshold: int = DEFAULT_THRESHOLD


def _coerce_int(value: Any, default: int, key: str) -> int:
    """取值合法（非 bool 的 int 且在范围内）→ 原值，否则默认值。"""
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    lo, hi = FAILOVER_INT_RANGES[key]
    if not lo <= value <= hi:
        return default
    return value


def load_failover_config() -> FailoverConfig:
    """读取 ``app_settings.failover``；任何失败回退默认（永不抛错）。"""
    raw: Dict[str, Any] = {}
    try:
        from backend.data.settings_canonicalizer import to_camel
        from backend.data.settings_repo import SettingsRepository

        data = SettingsRepository().get_json("app_settings")
        if isinstance(data, dict):
            raw = to_camel(data).get("failover") or {}
    except Exception as exc:  # noqa: BLE001 — 配置读取不得打断聊天
        logger.debug("failover config unavailable: %s", exc)
        return FailoverConfig()
    if not isinstance(raw, dict):
        return FailoverConfig()
    return FailoverConfig(
        enabled=raw.get("enabled") is True,
        probe_interval_ms=_coerce_int(
            raw.get("probeIntervalMs"), DEFAULT_PROBE_INTERVAL_MS, "probeIntervalMs"
        ),
        cooldown_ms=_coerce_int(raw.get("cooldownMs"), DEFAULT_COOLDOWN_MS, "cooldownMs"),
        consecutive_fail_threshold=_coerce_int(
            raw.get("consecutiveFailThreshold"),
            DEFAULT_THRESHOLD,
            "consecutiveFailThreshold",
        ),
    )


@dataclass
class EndpointHealthState:
    """单个端点的健康状态。"""

    endpoint_id: str
    status: str = HEALTHY
    consecutive_failures: int = 0
    last_failure_at: Optional[float] = None
    last_success_at: Optional[float] = None
    last_failure_reason: Optional[str] = None
    failover_count: int = 0


class EndpointHealthRegistry:
    """线程/协程安全的轻量注册表（仅受 GIL 保护的字段赋值）。"""

    def __init__(
        self,
        threshold: int = DEFAULT_THRESHOLD,
        cooldown_s: float = DEFAULT_COOLDOWN_S,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self._threshold = max(1, int(threshold))
        self._cooldown_s = max(0.0, float(cooldown_s))
        self._clock = clock or time.time
        self._states: Dict[str, EndpointHealthState] = {}

    def configure(
        self, *, threshold: Optional[int] = None, cooldown_s: Optional[float] = None
    ) -> None:
        if threshold is not None:
            self._threshold = max(1, int(threshold))
        if cooldown_s is not None:
            self._cooldown_s = max(0.0, float(cooldown_s))

    def get(self, endpoint_id: str) -> EndpointHealthState:
        state = self._states.get(endpoint_id)
        if state is None:
            state = EndpointHealthState(endpoint_id=endpoint_id)
            self._states[endpoint_id] = state
        return state

    def record_success(self, endpoint_id: Optional[str]) -> None:
        if not endpoint_id:
            return
        state = self.get(endpoint_id)
        state.status = HEALTHY
        state.consecutive_failures = 0
        state.last_success_at = self._clock()
        state.last_failure_reason = None

    def record_failure(self, endpoint_id: Optional[str], reason: str) -> None:
        if not endpoint_id:
            return
        state = self.get(endpoint_id)
        state.consecutive_failures += 1
        state.last_failure_at = self._clock()
        state.last_failure_reason = reason
        state.status = FAILED if state.consecutive_failures >= self._threshold else DEGRADED

    def record_failover(self, endpoint_id: Optional[str]) -> None:
        if not endpoint_id:
            return
        self.get(endpoint_id).failover_count += 1

    def is_available(self, endpoint_id: Optional[str]) -> bool:
        if not endpoint_id:
            return True
        state = self._states.get(endpoint_id)
        if state is None or state.status != FAILED:
            return True
        if state.last_failure_at is None:
            return True
        return (self._clock() - state.last_failure_at) >= self._cooldown_s

    def snapshot(self, endpoint_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        ids = list(endpoint_ids or [])
        for endpoint_id in self._states:
            if endpoint_id not in ids:
                ids.append(endpoint_id)
        rows: List[Dict[str, Any]] = []
        for endpoint_id in ids:
            state = self.get(endpoint_id)
            rows.append(
                {
                    "endpointId": endpoint_id,
                    "status": state.status,
                    "consecutiveFailures": state.consecutive_failures,
                    "lastFailureAt": state.last_failure_at,
                    "lastSuccessAt": state.last_success_at,
                    "lastFailureReason": state.last_failure_reason,
                    "failoverCount": state.failover_count,
                }
            )
        return rows

    def reset(self) -> None:
        self._states.clear()


_registry: Optional[EndpointHealthRegistry] = None


def get_health_registry() -> EndpointHealthRegistry:
    """进程级单例。"""
    global _registry
    if _registry is None:
        _registry = EndpointHealthRegistry()
    return _registry


def reset_health_registry() -> None:
    """测试用：丢弃单例（下次访问重建默认配置）。"""
    global _registry
    _registry = None
