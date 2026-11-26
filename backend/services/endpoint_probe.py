"""2026-11-26: 失败端点的轻量后台健康探测。

仅探测 ``degraded`` / ``failed`` 端点（健康端点零开销），请求
``GET {baseUrl}/models``（Ollama 用 ``/api/tags``），5 秒超时，不消耗 token。

判定：

- 2xx → 记录成功（恢复 healthy）；
- 401 / 5xx / 超时 / 连接失败 → 记录失败；
- 403 / 404 / 405 → 端点可达（模型列表权限/路径不支持，不代表聊天不可用），
  不改状态。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any, Dict, List, Optional

import httpx

from backend.services.endpoint_health import (
    DEGRADED,
    FAILED,
    get_health_registry,
    load_failover_config,
)

logger = logging.getLogger(__name__)

PROBE_TIMEOUT_S = 5.0
#: 探测循环休眠按 ≤30s 分片，便于及时响应 shutdown。
_SLEEP_CHUNK_S = 30.0
#: 视为「端点可达但模型列表不可用」的状态码。
_REACHABLE_STATUSES = frozenset({403, 404, 405})


def _probe_url(endpoint: Dict[str, Any]) -> Optional[str]:
    base_url = endpoint.get("baseUrl")
    if not isinstance(base_url, str) or not base_url.strip():
        return None
    base = base_url.rstrip("/")
    if (endpoint.get("protocol") or "openai-compatible") == "ollama":
        return f"{base}/api/tags"
    return f"{base}/models"


async def probe_endpoint(
    endpoint: Dict[str, Any],
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> str:
    """探测单个端点；返回 ``success`` / ``failure`` / ``reachable``。"""
    endpoint_id = endpoint.get("id")
    url = _probe_url(endpoint)
    if not url:
        return "failure"
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=httpx.Timeout(PROBE_TIMEOUT_S))
    headers: Dict[str, str] = {}
    api_key = endpoint.get("apiKey")
    if isinstance(api_key, str) and api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    registry = get_health_registry()
    try:
        response = await client.get(url, headers=headers)
        status = response.status_code
        if status < 400:
            registry.record_success(endpoint_id)
            return "success"
        if status in _REACHABLE_STATUSES:
            logger.debug(
                "probe: endpoint %s reachable but model list not supported (%s)",
                endpoint_id,
                status,
            )
            return "reachable"
        registry.record_failure(endpoint_id, "probe")
        return "failure"
    except Exception as exc:  # noqa: BLE001 — 探测失败是数据，不是程序错误
        logger.debug("probe: endpoint %s failed: %s", endpoint_id, exc)
        registry.record_failure(endpoint_id, "probe")
        return "failure"
    finally:
        if owns_client:
            await client.aclose()


def _load_probe_candidates() -> List[Dict[str, Any]]:
    try:
        from backend.data.settings_canonicalizer import to_camel
        from backend.data.settings_repo import SettingsRepository

        raw = SettingsRepository().get_json("app_settings")
        settings = to_camel(raw) if isinstance(raw, dict) else {}
        endpoints = settings.get("endpoints") or []
        return [ep for ep in endpoints if isinstance(ep, dict)]
    except Exception as exc:  # noqa: BLE001 — 设置不可用则本轮不探测
        logger.debug("probe: settings unavailable: %s", exc)
        return []


async def run_endpoint_probe_loop(stop_event: Optional[asyncio.Event] = None) -> None:
    """按 ``failover.probeIntervalMs`` 周期探测 degraded/failed 端点。"""
    stop_event = stop_event or asyncio.Event()
    while not stop_event.is_set():
        config = load_failover_config()
        registry = get_health_registry()
        registry.configure(
            threshold=config.consecutive_fail_threshold,
            cooldown_s=config.cooldown_ms / 1000.0,
        )
        if config.enabled:
            for endpoint in _load_probe_candidates():
                if stop_event.is_set():
                    break
                endpoint_id = endpoint.get("id")
                if not isinstance(endpoint_id, str):
                    continue
                state = registry.get(endpoint_id)
                if state.status not in (DEGRADED, FAILED):
                    continue
                await probe_endpoint(endpoint)
        remaining = config.probe_interval_ms / 1000.0
        while remaining > 0 and not stop_event.is_set():
            chunk = min(_SLEEP_CHUNK_S, remaining)
            # py38: asyncio.TimeoutError 与内置 TimeoutError 尚非同一类型。
            with contextlib.suppress(asyncio.TimeoutError):  # noqa: UP041
                await asyncio.wait_for(stop_event.wait(), timeout=chunk)
            remaining -= chunk


def _log_probe_task_exit(task: asyncio.Task) -> None:
    """探测任务意外退出时留下可见日志（取消属正常路径，静默）。"""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("endpoint-probe task exited unexpectedly: %s", exc, exc_info=exc)


def start_endpoint_probe_task() -> asyncio.Task:
    """lifespan 启动钩子：返回后台探测任务（调用方负责 cancel）。"""
    task = asyncio.create_task(run_endpoint_probe_loop(), name="endpoint-probe")
    task.add_done_callback(_log_probe_task_exit)
    return task
