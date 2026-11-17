"""启动分层就绪注册表（Progressive Readiness）。

设计约束：

- **纯内存、零 IO**：``/health/ready`` 在冷启动期会被 Electron 以 1s 间隔
  轮询，端点开销必须与 ``/health`` 同级（后者专门用纯 ASGI 中间件保证了
  P99，见 ``backend/api/local_auth.py``）。
- **上报永不反噬启动**：``mark_module`` 内部吞掉一切异常；状态缺失/失败
  只影响就绪展示，不影响初始化流程本身。
- **层级语义**：L1 = 最小可用（数据库/记忆/会话，可浏览历史），
  L2 = 对话可用（ChatService + LLM 端点配置），L3 = 完整就绪
  （后台服务全部到达终态；degraded/failed 也算终态）。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

STATE_PENDING = "pending"
STATE_WARMING = "warming"
STATE_READY = "ready"
STATE_DEGRADED = "degraded"
STATE_FAILED = "failed"

TERMINAL_STATES = frozenset({STATE_READY, STATE_DEGRADED, STATE_FAILED})
_ALL_STATES = TERMINAL_STATES | frozenset({STATE_PENDING, STATE_WARMING})

# 模块 → 就绪层级。未列出的模块默认 L3。
MODULE_LAYERS: Dict[str, int] = {
    # L1 最小可用：能浏览历史会话
    "database": 1,
    "memory": 1,
    "sessions": 1,
    # L2 对话可用：能发消息
    "chat_service": 2,
    "llm": 2,
    # L3 后台服务
    "mcp": 3,
    "scheduler": 3,
    "todo": 3,
    "review_queue": 3,
    "wake_scheduler": 3,
    "gateways": 3,
    "design_studio": 3,
    "multi_agent": 3,
    "arena": 3,
    "storage": 3,
}


class StartupStatusRegistry:
    """Thread-safe in-memory module readiness tracker."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started = time.monotonic()
        self._modules: Dict[str, Dict[str, Any]] = {}

    def declare(self, name: str, layer: Optional[int] = None) -> None:
        """Declare a module as pending (idempotent)."""
        with self._lock:
            if name in self._modules:
                return
            self._modules[name] = {
                "state": STATE_PENDING,
                "layer": layer if layer is not None else MODULE_LAYERS.get(name, 3),
                "started_at": None,
                "finished_at": None,
                "detail": None,
            }

    def mark(
        self,
        name: str,
        state: str,
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        if state not in _ALL_STATES:
            raise ValueError(f"unknown startup state: {state!r}")
        now = time.monotonic()
        with self._lock:
            entry = self._modules.get(name)
            if entry is None:
                entry = {
                    "state": STATE_PENDING,
                    "layer": MODULE_LAYERS.get(name, 3),
                    "started_at": None,
                    "finished_at": None,
                    "detail": None,
                }
                self._modules[name] = entry
            if entry["state"] in TERMINAL_STATES and state not in TERMINAL_STATES:
                # 终态不可回退：迟到的 warming/pending 上报（例如独立后台
                # 观察协程在兜底 finalize 之后才启动）不得把已完成的模块
                # 拉回未完成，否则 phase 会从 L3 回退且 elapsed 计时被冻结。
                return
            if entry["started_at"] is None:
                entry["started_at"] = now
            entry["state"] = state
            if detail is not None:
                entry["detail"] = detail
            if state in TERMINAL_STATES and entry["finished_at"] is None:
                entry["finished_at"] = now

    def snapshot(self) -> Dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            modules: Dict[str, Dict[str, Any]] = {}
            for name, entry in self._modules.items():
                elapsed_ms = None
                if entry["started_at"] is not None:
                    end = entry["finished_at"]
                    elapsed_ms = int(((end if end is not None else now) - entry["started_at"]) * 1000)
                modules[name] = {
                    "state": entry["state"],
                    "layer": entry["layer"],
                    "elapsed_ms": elapsed_ms,
                    "detail": entry["detail"],
                }
            boot_ms = int((now - self._started) * 1000)

        all_terminal = bool(modules) and all(
            m["state"] in TERMINAL_STATES for m in modules.values()
        )
        if all_terminal:
            bad = any(m["state"] in (STATE_DEGRADED, STATE_FAILED) for m in modules.values())
            status = "degraded" if bad else "ready"
            phase = "L3"
        else:
            status = "warming"
            phase = "L0"
            for layer in (1, 2):
                layer_states = [m["state"] for m in modules.values() if m["layer"] == layer]
                if layer_states and all(s == STATE_READY for s in layer_states):
                    phase = "L%d" % layer
                else:
                    break

        done = sum(1 for m in modules.values() if m["state"] in TERMINAL_STATES)
        return {
            "status": status,
            "phase": phase,
            "boot_ms": boot_ms,
            "modules": modules,
            "warmup": {"done": done, "total": len(modules)},
        }


_registry: Optional[StartupStatusRegistry] = None
_registry_lock = threading.Lock()


def get_startup_status() -> StartupStatusRegistry:
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = StartupStatusRegistry()
    return _registry


def declare_all_modules() -> None:
    registry = get_startup_status()
    for name in MODULE_LAYERS:
        registry.declare(name)


def mark_module(
    name: str,
    state: str,
    detail: Optional[Dict[str, Any]] = None,
) -> None:
    """Best-effort readiness report — never breaks the caller (startup path)."""
    try:
        get_startup_status().mark(name, state, detail)
    except Exception:  # noqa: BLE001 — 状态上报失败不得影响初始化
        logger.debug("startup_status mark failed: %s=%s", name, state, exc_info=True)


def reset_startup_status() -> None:
    """Drop the process-wide registry (fresh singleton on next access).

    Called at the top of the FastAPI lifespan: a second lifespan in the same
    process (tests, in-process restart) must not inherit the previous run's
    terminal states / timings.
    """
    global _registry
    with _registry_lock:
        _registry = None


def reset_startup_status_for_tests() -> None:
    reset_startup_status()
