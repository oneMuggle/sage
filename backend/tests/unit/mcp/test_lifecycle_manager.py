"""MCP 生命周期管理器单元测试。"""

import pytest

from backend.mcp.lifecycle import (
    MCPLifecycleManager,
    MCPNotReadyError,
    MCPState,
)


class TestMCPLifecycleManager:
    """测试 MCP 生命周期管理器。"""

    @pytest.mark.asyncio()
    async def test_initialize_transitions_to_ready(self):
        """测试初始化转换到 READY。"""
        manager = MCPLifecycleManager()
        assert manager.state == MCPState.CREATED

        await manager.initialize()

        assert manager.state == MCPState.READY

    @pytest.mark.asyncio()
    async def test_start_transitions_to_running(self):
        """测试启动转换到 RUNNING。"""
        manager = MCPLifecycleManager()
        await manager.initialize()

        await manager.start()

        assert manager.state == MCPState.RUNNING

    @pytest.mark.asyncio()
    async def test_start_without_initialize_raises_error(self):
        """测试未初始化就启动抛出错误。"""
        manager = MCPLifecycleManager()

        with pytest.raises(MCPNotReadyError):
            await manager.start()

    @pytest.mark.asyncio()
    async def test_pause_transitions_to_paused(self):
        """测试暂停转换到 PAUSED。"""
        manager = MCPLifecycleManager()
        await manager.initialize()
        await manager.start()

        await manager.pause()

        assert manager.state == MCPState.PAUSED

    @pytest.mark.asyncio()
    async def test_resume_transitions_to_running(self):
        """测试恢复转换到 RUNNING。"""
        manager = MCPLifecycleManager()
        await manager.initialize()
        await manager.start()
        await manager.pause()

        await manager.resume()

        assert manager.state == MCPState.RUNNING

    @pytest.mark.asyncio()
    async def test_shutdown_transitions_to_shutdown(self):
        """测试关闭转换到 SHUTDOWN。"""
        manager = MCPLifecycleManager()
        await manager.initialize()
        await manager.start()

        await manager.shutdown()

        assert manager.state == MCPState.SHUTDOWN

    @pytest.mark.asyncio()
    async def test_shutdown_idempotent(self):
        """测试关闭是幂等的。"""
        manager = MCPLifecycleManager()
        await manager.initialize()

        await manager.shutdown()
        await manager.shutdown()  # 第二次调用不应抛出错误

        assert manager.state == MCPState.SHUTDOWN

    @pytest.mark.asyncio()
    async def test_is_healthy_when_ready_or_running(self):
        """测试 READY 或 RUNNING 时服务健康。"""
        manager = MCPLifecycleManager()

        # CREATED 时不健康
        assert not manager.is_healthy

        # READY 时健康
        await manager.initialize()
        assert manager.is_healthy

        # RUNNING 时健康
        await manager.start()
        assert manager.is_healthy

        # PAUSED 时健康
        await manager.pause()
        assert manager.is_healthy

        # SHUTDOWN 时不健康
        await manager.shutdown()
        assert not manager.is_healthy

    @pytest.mark.asyncio()
    async def test_lifespan_context_manager(self):
        """测试生命周期上下文管理器。"""
        manager = MCPLifecycleManager()

        async with manager.lifespan() as m:
            assert m.state == MCPState.READY
            await m.start()
            assert m.state == MCPState.RUNNING

        # 退出上下文后应该已关闭
        assert manager.state == MCPState.SHUTDOWN

    @pytest.mark.asyncio()
    async def test_register_and_cleanup_resources(self):
        """测试资源注册和清理。"""
        manager = MCPLifecycleManager()

        class MockResource:
            def __init__(self):
                self.closed = False

            async def aclose(self):
                self.closed = True

        resource = MockResource()
        manager.register_resource(resource)

        await manager.initialize()
        await manager.shutdown()

        assert resource.closed
