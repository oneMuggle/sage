"""
Startup profiler — 启动时间诊断与并行化协调器

参考 ZCode 的内存诊断系统，为 Sage 后端实现：
1. 启动时间埋点（增强现有 _startup_mark）
2. 并行初始化协调器
3. 结构化诊断数据输出
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class StartupPhase:
    """单个启动阶段的计时数据"""
    name: str
    start_time: float
    end_time: float
    group: str  # "A", "B", "C"
    dependencies: List[str] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def duration_ms(self) -> float:
        return (self.end_time - self.start_time) * 1000


@dataclass
class StartupDiagnostics:
    """启动诊断数据"""
    phases: List[StartupPhase] = field(default_factory=list)
    group_timings: Dict[str, float] = field(default_factory=dict)
    total_startup_time: float = 0.0

    def add_phase(self, phase: StartupPhase) -> None:
        self.phases.append(phase)

    def set_group_timing(self, group: str, duration: float) -> None:
        self.group_timings[group] = duration

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典（用于 JSON 响应）"""
        return {
            "total_startup_time_ms": round(self.total_startup_time * 1000, 2),
            "parallel_groups": {
                group: round(duration * 1000, 2)
                for group, duration in sorted(self.group_timings.items())
            },
            "phases": [
                {
                    "name": phase.name,
                    "duration_ms": round(phase.duration_ms, 2),
                    "group": phase.group,
                    "dependencies": phase.dependencies,
                    "error": phase.error,
                }
                for phase in self.phases
            ],
        }


class StartupProfiler:
    """启动性能分析器

    用法:
        profiler = StartupProfiler()

        # Group A: 无依赖
        async with profiler.group("A"):
            await asyncio.gather(
                profiler.phase("auth_token", initialize_local_auth_token),
                profiler.phase("stream_registry", init_stream_registry),
                ...
            )

        # Group B: 依赖 DB
        async with profiler.group("B"):
            await asyncio.gather(
                profiler.phase("seed_catalog", seed_if_empty, deps=["db_init"]),
                ...
            )
    """

    def __init__(self) -> None:
        self.diagnostics = StartupDiagnostics()
        self._t0 = time.monotonic()
        self._current_group: Optional[str] = None
        self._group_start: Optional[float] = None

    def group(self, name: str) -> "_GroupContext":
        """上下文管理器：标记并行组开始"""
        return _GroupContext(self, name)

    async def phase(
        self,
        name: str,
        fn: Callable,
        deps: Optional[List[str]] = None,
        **kwargs,
    ) -> Any:
        """执行一个启动阶段并记录时间

        Args:
            name: 阶段名称
            fn: 要执行的函数（同步或异步）
            deps: 依赖的其他阶段名称
            **kwargs: 传递给 fn 的参数
        """
        phase = StartupPhase(
            name=name,
            start_time=time.monotonic(),
            end_time=0.0,
            group=self._current_group or "?",
            dependencies=deps or [],
        )

        try:
            if asyncio.iscoroutinefunction(fn):
                result = await fn(**kwargs)
            else:
                result = fn(**kwargs)
            phase.end_time = time.monotonic()
        except Exception as exc:
            phase.end_time = time.monotonic()
            phase.error = f"{type(exc).__name__}: {exc}"
            logger.exception("Startup phase %s failed", name)
            result = None

        self.diagnostics.add_phase(phase)
        return result

    def _begin_group(self, name: str) -> None:
        self._current_group = name
        self._group_start = time.monotonic()

    def _end_group(self, name: str) -> None:
        if self._group_start is not None:
            duration = time.monotonic() - self._group_start
            self.diagnostics.set_group_timing(name, duration)
        self._current_group = None
        self._group_start = None

    def finish(self) -> StartupDiagnostics:
        """完成启动分析，返回诊断数据"""
        self.diagnostics.total_startup_time = time.monotonic() - self._t0
        return self.diagnostics


class _GroupContext:
    """并行组上下文管理器"""

    def __init__(self, profiler: StartupProfiler, name: str) -> None:
        self.profiler = profiler
        self.name = name

    def __enter__(self) -> None:
        self.profiler._begin_group(self.name)

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.profiler._end_group(self.name)


# 全局单例（在 main.py 中初始化）
_profiler: Optional[StartupProfiler] = None


def get_profiler() -> StartupProfiler:
    """获取全局 profiler 实例"""
    global _profiler
    if _profiler is None:
        _profiler = StartupProfiler()
    return _profiler


def get_diagnostics() -> Optional[Dict[str, Any]]:
    """获取启动诊断数据（用于 /health/diagnostic 端点）"""
    if _profiler is None:
        return None
    return _profiler.diagnostics.to_dict()
