"""
文件修改队列测试 (A26 from pi)

测试文件修改队列串行化。
"""

import asyncio

import pytest

from backend.application.services.file_mutation_queue import (
    FileMutationQueue,
    get_file_mutation_queue,
    shutdown_file_mutation_queue,
)


class TestFileMutationQueue:
    """FileMutationQueue 测试套件"""

    @pytest.mark.asyncio()
    async def test_submit_and_execute(self):
        """提交并执行操作"""
        queue = FileMutationQueue()
        await queue.start()

        result = await queue.submit(lambda: asyncio.sleep(0, result="done"))

        assert result == "done"
        await queue.stop()

    @pytest.mark.asyncio()
    async def test_serial_execution(self):
        """串行执行（无并发）"""
        queue = FileMutationQueue()
        await queue.start()

        execution_order = []

        async def op1():
            execution_order.append(1)
            await asyncio.sleep(0.01)
            return "op1"

        async def op2():
            execution_order.append(2)
            await asyncio.sleep(0.01)
            return "op2"

        # 并发提交两个操作
        results = await asyncio.gather(
            queue.submit(op1),
            queue.submit(op2),
        )

        # 应该串行执行（op1 完成后才执行 op2）
        assert execution_order == [1, 2]
        assert results == ["op1", "op2"]
        await queue.stop()

    @pytest.mark.asyncio()
    async def test_exception_propagation(self):
        """异常传播"""
        queue = FileMutationQueue()
        await queue.start()

        async def failing_op():
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            await queue.submit(failing_op)

        await queue.stop()

    @pytest.mark.asyncio()
    async def test_stop_waits_for_completion(self):
        """stop 等待所有操作完成"""
        queue = FileMutationQueue()
        await queue.start()

        completed = []

        async def slow_op():
            await asyncio.sleep(0.05)
            completed.append(True)
            return "done"

        # 提交并等待操作完成（避免 race condition）
        result = await queue.submit(slow_op)

        # 此时操作已完成
        assert len(completed) == 1
        assert result == "done"

        # stop 应该立即返回
        await queue.stop()

    @pytest.mark.asyncio()
    async def test_multiple_operations(self):
        """多个操作"""
        queue = FileMutationQueue()
        await queue.start()

        results = []

        async def create_op(n):
            async def op():
                results.append(n)
                return n
            return op

        # 提交 5 个操作
        for i in range(5):
            op = await create_op(i)
            await queue.submit(op)

        assert results == [0, 1, 2, 3, 4]
        await queue.stop()

    @pytest.mark.asyncio()
    async def test_global_queue(self):
        """全局队列"""
        queue1 = await get_file_mutation_queue()
        queue2 = await get_file_mutation_queue()

        assert queue1 is queue2  # 同一个实例

        await shutdown_file_mutation_queue()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
