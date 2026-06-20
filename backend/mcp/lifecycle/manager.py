"""MCP 生命周期管理器。

管理 MCP 服务的完整生命周期，包括：
- 初始化
- 启动/暂停/恢复
- 健康检查
- 优雅关闭
- 资源清理
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from sage_core import Message

from .state_machine import MCPState, MCPStateMachine, StateTransitionError

logger = logging.getLogger(__name__)


class MCPServiceError(Exception):
    """MCP 服务错误基类。"""


class MCPNotReadyError(MCPServiceError):
    """MCP 服务未就绪错误。"""


class MCPHealthCheckError(MCPServiceError):
    """MCP 健康检查失败错误。"""


class MCPLifecycleManager:
    """MCP 生命周期管理器。"""

    def __init__(self, max_retries: int = 3, health_check_interval: float = 30.0):
        """初始化生命周期管理器。

        Args:
            max_retries: 最大重试次数
            health_check_interval: 健康检查间隔（秒）
        """
        self._state_machine = MCPStateMachine()
        self._max_retries = max_retries
        self._health_check_interval = health_check_interval
        self._health_check_task: Optional[asyncio.Task] = None
        self._resources: list[object] = []  # 需要清理的资源
        self._shutdown_event = asyncio.Event()

    @property
    def state(self) -> MCPState:
        """当前状态。"""
        return self._state_machine.state

    @property
    def is_healthy(self) -> bool:
        """服务是否健康。"""
        return self._state_machine.state in {
            MCPState.READY,
            MCPState.RUNNING,
            MCPState.PAUSED,
        }

    async def initialize(self) -> None:
        """初始化 MCP 服务。

        执行初始化逻辑，转换到 READY 状态。
        """
        logger.info("初始化 MCP 服务...")

        # 状态转换: CREATED → INITIALIZING
        self._state_machine.transition_to(MCPState.INITIALIZING)

        try:
            # 初始化资源
            await self._initialize_resources()

            # 状态转换: INITIALIZING → READY
            self._state_machine.transition_to(MCPState.READY)
            logger.info("MCP 服务初始化完成")

        except Exception as e:
            logger.error(f"MCP 服务初始化失败: {e}")
            await self.shutdown()
            raise

    async def start(self) -> None:
        """启动 MCP 服务。

        启动健康检查任务，转换到 RUNNING 状态。
        """
        if self._state_machine.state != MCPState.READY:
            raise MCPNotReadyError(
                f"MCP 服务未就绪，当前状态: {self._state_machine.state.value}"
            )

        logger.info("启动 MCP 服务...")

        # 状态转换: READY → RUNNING
        self._state_machine.transition_to(MCPState.RUNNING)

        # 启动健康检查
        self._start_health_check()

        logger.info("MCP 服务已启动")

    async def pause(self) -> None:
        """暂停 MCP 服务。

        转换到 PAUSED 状态。
        """
        if self._state_machine.state != MCPState.RUNNING:
            raise MCPServiceError(
                f"MCP 服务未运行，当前状态: {self._state_machine.state.value}"
            )

        logger.info("暂停 MCP 服务...")

        # 状态转换: RUNNING → PAUSED
        self._state_machine.transition_to(MCPState.PAUSED)

        # 停止健康检查
        self._stop_health_check()

        logger.info("MCP 服务已暂停")

    async def resume(self) -> None:
        """恢复 MCP 服务。

        转换到 RUNNING 状态。
        """
        if self._state_machine.state != MCPState.PAUSED:
            raise MCPServiceError(
                f"MCP 服务未暂停，当前状态: {self._state_machine.state.value}"
            )

        logger.info("恢复 MCP 服务...")

        # 状态转换: PAUSED → RUNNING
        self._state_machine.transition_to(MCPState.RUNNING)

        # 启动健康检查
        self._start_health_check()

        logger.info("MCP 服务已恢复")

    async def shutdown(self) -> None:
        """关闭 MCP 服务。

        执行优雅关闭，清理资源，转换到 SHUTDOWN 状态。
        """
        if self._state_machine.state == MCPState.SHUTDOWN:
            logger.warning("MCP 服务已关闭")
            return

        logger.info("关闭 MCP 服务...")

        # 停止健康检查
        self._stop_health_check()

        try:
            # 状态转换: * → SHUTDOWN
            self._state_machine.transition_to(MCPState.SHUTDOWN)

            # 清理资源
            await self._cleanup_resources()

            logger.info("MCP 服务已关闭")

        except Exception as e:
            logger.error(f"MCP 服务关闭失败: {e}")
            raise

    async def _initialize_resources(self) -> None:
        """初始化资源。

        子类可以重写此方法以初始化特定资源。
        """
        logger.debug("初始化资源...")
        # 示例：初始化数据库连接、缓存等

    async def _cleanup_resources(self) -> None:
        """清理资源。

        子类可以重写此方法以清理特定资源。
        """
        logger.debug("清理资源...")

        for resource in reversed(self._resources):
            try:
                if hasattr(resource, "close"):
                    await resource.close()
                elif hasattr(resource, "aclose"):
                    await resource.aclose()
            except Exception as e:
                logger.warning(f"清理资源失败: {e}")

        self._resources.clear()

    def _start_health_check(self) -> None:
        """启动健康检查任务。"""
        if self._health_check_task is not None:
            return

        self._health_check_task = asyncio.create_task(
            self._health_check_loop(),
            name="mcp-health-check"
        )
        logger.debug("健康检查任务已启动")

    def _stop_health_check(self) -> None:
        """停止健康检查任务。"""
        if self._health_check_task is not None:
            self._health_check_task.cancel()
            self._health_check_task = None
            logger.debug("健康检查任务已停止")

    async def _health_check_loop(self) -> None:
        """健康检查循环。"""
        try:
            while self._state_machine.state == MCPState.RUNNING:
                await self._perform_health_check()
                await asyncio.sleep(self._health_check_interval)
        except asyncio.CancelledError:
            logger.debug("健康检查任务已取消")

    async def _perform_health_check(self) -> None:
        """执行健康检查。

        子类可以重写此方法以实现特定的健康检查逻辑。
        """
        logger.debug("执行健康检查...")
        # 示例：检查数据库连接、缓存可用性等

    def register_resource(self, resource: object) -> None:
        """注册需要清理的资源。

        Args:
            resource: 需要清理的资源对象（必须有 close 或 aclose 方法）
        """
        self._resources.append(resource)
        logger.debug(f"注册资源: {resource}")

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator["MCPLifecycleManager"]:
        """生命周期上下文管理器。

        使用示例：
            async with lifecycle_manager.lifespan() as manager:
                await manager.start()
                # 服务运行中
        """
        try:
            await self.initialize()
            yield self
        finally:
            await self.shutdown()
