"""
文件修改队列串行化 (A26 from pi)

确保所有文件修改操作（write_file, edit_file）串行化执行，避免并发冲突。

问题：
- 多个工具同时修改同一文件 → 数据竞争
- 并发写入导致文件损坏

解决方案：
- 所有文件修改操作提交到队列
- 队列处理器串行执行操作
- 使用 asyncio.Lock 保证原子性

使用示例：
    file_queue = FileMutationQueue()
    await file_queue.start()

    # 所有文件修改通过队列串行化
    async def write_file(path: str, content: str):
        return await file_queue.submit(lambda: _write_file_impl(path, content))

    await file_queue.stop()

From pi's packages/coding-agent/src/core/tools/file-mutation-queue.ts pattern.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any, Callable, Coroutine, Optional

# 操作类型：返回 Any 的异步函数
FileOperation = Callable[[], Coroutine[Any, Any, Any]]


class FileMutationQueue:
    """
    文件修改队列

    确保文件修改操作串行化执行，避免并发冲突。

    特性：
    - 异步队列（asyncio.Queue）
    - 串行执行（asyncio.Lock）
    - 优雅关闭（等待所有操作完成）
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[tuple[FileOperation, asyncio.Future]] = asyncio.Queue()
        self._running = False
        self._lock = asyncio.Lock()
        self._processor_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """启动队列处理器"""
        if self._running:
            return

        self._running = True
        self._processor_task = asyncio.create_task(self._process_loop())

    async def stop(self) -> None:
        """停止队列处理器（等待所有操作完成）"""
        if not self._running:
            return

        self._running = False

        # 等待队列清空
        await self._queue.join()

        # 取消处理器任务
        if self._processor_task:
            self._processor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._processor_task
            self._processor_task = None

    async def submit(self, operation: FileOperation) -> Any:
        """
        提交文件修改操作

        Args:
            operation: 异步操作函数

        Returns:
            操作结果

        Raises:
            Exception: 操作执行时的异常
        """
        # 创建 Future 用于等待结果
        future = asyncio.get_event_loop().create_future()

        # 将操作和 Future 加入队列
        await self._queue.put((operation, future))

        # 等待操作完成
        return await future

    async def _process_loop(self) -> None:
        """处理队列（串行执行操作）"""
        while self._running:
            try:
                # 等待下一个操作（超时 1 秒检查 _running）
                operation, future = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=1.0,
                )

                # 使用锁保证串行执行
                async with self._lock:
                    try:
                        result = await operation()
                        future.set_result(result)
                    except Exception as e:
                        future.set_exception(e)

                # 标记任务完成
                self._queue.task_done()

            except TimeoutError:
                # 超时检查 _running，继续循环
                continue
            except asyncio.CancelledError:
                # 任务被取消，退出循环
                break


# 全局队列实例（可选）
_global_queue: Optional[FileMutationQueue] = None


async def get_file_mutation_queue() -> FileMutationQueue:
    """获取全局文件修改队列"""
    global _global_queue
    if _global_queue is None:
        _global_queue = FileMutationQueue()
        await _global_queue.start()
    return _global_queue


async def shutdown_file_mutation_queue() -> None:
    """关闭全局文件修改队列"""
    global _global_queue
    if _global_queue:
        await _global_queue.stop()
        _global_queue = None
