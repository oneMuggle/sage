"""Harness effectiveness 埋点 (阶段 1)。

把工具 / 技能的每次调用写进 harness 组件注册表，累积
``usage_count`` / ``success_count`` / ``total_latency_ms``，
供 ``GET /api/v1/harness/components`` 消费。

设计要点
--------

- **埋点绝不阻塞调用方**：``record_tool_usage`` 把协程提交到模块级单 worker
  线程池，由线程内的 ``asyncio.run`` 跑完。同步 / 异步 caller 皆安全，
  SkillTool 的临时事件循环也不会丢记录（fire-and-forget，无 running-loop 假设）。
- **埋点绝不打断主路径**：协程内任何异常只记 warning 日志。
- **懒注册组件**：``tool:<name>`` / ``skill:<name>`` 首次埋点时才写入
  注册表（进程内 ``_known`` 缓存避免重复注册）。
- **组件 id 规范**：``<prefix>:<name>``（``tool:`` / ``skill:``），
  ``type`` 字段取 8 类白名单之一，供前端按类型分组。
- **可替换**：``install_recorder`` 让测试与 composition root 注入
  自带实现；未安装时所有埋点是 no-op。
"""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import suppress
from threading import Lock
from typing import Any, Dict, Optional, Set

from backend.application.services.harness_service import HarnessService

logger = logging.getLogger(__name__)

# 组件 id 前缀 → 组件类型
COMPONENT_TYPE_BY_PREFIX = {
    "tool": "tool_guidance",
    "skill": "skills",
}

# --- 后台线程池（单 worker 串行写 SQLite，避免并发写竞争）---
_executor: Optional[ThreadPoolExecutor] = None
_executor_lock = Lock()
_pending: Set[Future[None]] = set()


def _get_executor() -> ThreadPoolExecutor:
    """惰性构造单 worker 线程池（首次埋点时才起线程）。"""
    global _executor
    with _executor_lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="harness-telemetry"
            )
    return _executor


def _run(coro: Any) -> None:
    """后台线程中跑协程。异常只记 warning，绝不冒泡。"""
    try:
        asyncio.run(coro)
    except Exception as exc:  # noqa: BLE001 — 埋点失败只记 warning
        logger.warning("harness 埋点执行失败: %s", exc)


def _submit(coro: Any) -> None:
    """把协程提交到后台线程池并持有强引用。"""
    try:
        fut: Future[None] = _get_executor().submit(_run, coro)
    except RuntimeError as exc:
        coro.close()
        logger.debug("harness 埋点提交失败: %s", exc)
        return
    _pending.add(fut)
    fut.add_done_callback(lambda f: _pending.discard(f))


def flush_pending(timeout: float = 2.0) -> bool:
    """等待所有已提交的埋点完成（测试用）。

    Returns:
        True 表示所有埋点都在 timeout 内写完；False 表示超时。
    """
    deadline = time.monotonic() + timeout
    snapshot = list(_pending)
    for fut in snapshot:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        with suppress(Exception):
            fut.result(timeout=remaining)
    return True


# --- recorder ---


class HarnessRecorder:
    """把组件使用写入 harness 注册表。"""

    def __init__(self, service: HarnessService) -> None:
        """初始化 recorder。

        Args:
            service: harness 用例服务（负责注册与 usage 记账）。
        """
        self._service = service
        self._known: Set[str] = set()
        self._known_lock = Lock()

    async def ensure_component(
        self,
        component_id: str,
        component_type: str,
        name: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """确保组件已在注册表中（进程内缓存，重复调用零开销）。

        Returns:
            True 表示组件已注册（或此前已注册）。
        """
        with self._known_lock:
            if component_id in self._known:
                return True
        try:
            await self._service.register_component(
                component_id, component_type, name, config or {}
            )
        except Exception as exc:  # noqa: BLE001 — 注册失败不应影响主路径
            logger.warning("harness 组件注册失败 component_id=%s: %s", component_id, exc)
            return False
        with self._known_lock:
            self._known.add(component_id)
        return True

    async def record(
        self,
        component_id: str,
        component_type: str,
        name: str,
        success: bool,
        latency_ms: float,
    ) -> None:
        """记录一次组件使用（注册 + 记账）。**永不抛出异常。**"""
        try:
            if not await self.ensure_component(component_id, component_type, name):
                return
            await self._service.record_usage(component_id, success, latency_ms)
        except Exception as exc:  # noqa: BLE001 — 埋点绝不打断主路径
            logger.warning(
                "harness usage 埋点失败 component_id=%s: %s", component_id, exc
            )

    async def record_tool(
        self,
        tool_name: str,
        success: bool,
        latency_ms: float,
    ) -> None:
        """记录一次工具调用（组件 id ``tool:<name>``）。"""
        await self.record(
            f"tool:{tool_name}",
            COMPONENT_TYPE_BY_PREFIX["tool"],
            tool_name,
            success,
            latency_ms,
        )

    async def record_skill(
        self,
        skill_name: str,
        success: bool,
        latency_ms: float,
    ) -> None:
        """记录一次技能调用（组件 id ``skill:<name>``）。"""
        await self.record(
            f"skill:{skill_name}",
            COMPONENT_TYPE_BY_PREFIX["skill"],
            skill_name,
            success,
            latency_ms,
        )


_recorder: Optional[HarnessRecorder] = None


def install_recorder(recorder: Optional[HarnessRecorder]) -> None:
    """安装全局 recorder（composition root / 测试注入）。

    Args:
        recorder: recorder 实例；传 ``None`` 表示卸载（埋点变 no-op）。
    """
    global _recorder
    _recorder = recorder


def get_recorder() -> Optional[HarnessRecorder]:
    """返回当前全局 recorder；未安装时返回 ``None``。"""
    return _recorder


def record_tool_usage(tool_name: str, success: bool, latency_ms: float) -> None:
    """fire-and-forget 记录一次工具调用（线程池 dispatch，任何调用上下文皆安全）。"""
    recorder = _recorder
    if recorder is None:
        return
    _submit(recorder.record_tool(tool_name, success, latency_ms))


def record_skill_usage(skill_name: str, success: bool, latency_ms: float) -> None:
    """fire-and-forget 记录一次技能调用（线程池 dispatch）。"""
    recorder = _recorder
    if recorder is None:
        return
    _submit(recorder.record_skill(skill_name, success, latency_ms))


class HarnessProbe:
    """测量一次组件调用的耗时与成败，退出时 fire-and-forget 埋点。

    用作上下文管理器包裹工具 / 技能执行：

    .. code-block:: python

        with HarnessProbe("tool", "bash") as probe:
            result = await run()
            probe.result = result

    ``result`` 缺省为 ``None`` 时视为失败（取消 / 无结果）。
    异常原样向上抛（``__exit__`` 返回 ``False``），只记录 ``success=False``。
    """

    def __init__(self, kind: str, name: str) -> None:
        """初始化探针。

        Args:
            kind: ``"tool"`` 或 ``"skill"``。
            name: 组件名称（工具名 / 技能名）。
        """
        self.kind = kind
        self.name = name
        self.result: Any = None
        self.success = True
        self.latency_ms = 0.0
        self._started = 0.0

    def __enter__(self) -> HarnessProbe:
        """开始计时。"""
        self._started = time.perf_counter()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        """结束计时并埋点。返回 ``False`` 表示不吞异常。"""
        self.latency_ms = (time.perf_counter() - self._started) * 1000
        if exc_type is not None or self.result is None:
            self.success = False
        else:
            self.success = bool(getattr(self.result, "success", True))
        self.emit()
        return False

    def emit(self) -> None:
        """发出 fire-and-forget 埋点。"""
        if self.kind == "skill":
            record_skill_usage(self.name, self.success, self.latency_ms)
        else:
            record_tool_usage(self.name, self.success, self.latency_ms)
