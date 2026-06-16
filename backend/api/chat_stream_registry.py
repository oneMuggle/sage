"""
Chat 流注册表 (I2: 拆分 create/attach,避免 LLM 被调两次)

为什么需要这个模块:
  原 /chat/stream POST 一次响应里同时创建流 + 触发 LLM + 流式输出。
  Electron 端在 invokeBackend 阶段读首行拿 streamId 就关 body,在 relay 阶段
  又 POST 同样的 args 重放 → LLM 被调两次、token 翻倍。

  改为 create + attach:
    POST /chat/stream  → 创建流,立即返回 {streamId},后台跑 agent.run_loop
                          (LLM 调一次,事件入 asyncio.Queue)
    GET  /chat/stream/{id} → attach 已有流,从 queue 拉事件 → NDJSON

本模块:
  - StreamEntry: 状态/队列/task 的不可变视图
  - StreamRegistry: 持有 streamId → StreamEntry 的 dict,负责生命周期
  - SENTINEL: queue 中的"流结束"标记(避免 done 事件与 sentinel 语义混淆)
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

# 当 Queue.get() 收到此 sentinel,attach 端点就关闭 NDJSON 流。
# 必须是单例(用 `is` 比较),不能是 None 或 dict(None) 等可能的合法事件值。
SENTINEL: Any = object()

ProducerFn = Callable[["StreamEntry"], Awaitable[None]]


@dataclass
class StreamEntry:
    """一个 chat stream 的运行时状态。

    Fields:
        queue:   跨生产(producer task)/消费(HTTP attach)的事件队列,有界 (maxsize=1000)
                 backpressure 而非 OOM
        task:    跑 producer 协程的 asyncio.Task。客户端断开时**不**取消 —
                 已消耗的 LLM token 不能浪费,让 task 跑完供后续 attach 复用
        status:  pending → running → done | failed
        created_at: 单调时间戳(秒),用于 TTL 回收
    """

    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=1000))
    task: asyncio.Task | None = None
    status: str = "pending"
    created_at: float = field(default_factory=time.time)


class StreamRegistry:
    """streamId → StreamEntry 的内存注册表。

    单进程使用(桌面 Electron 后端单实例,不存在多 worker)。
    生命周期:
      create() 注册并启动 producer task
      get() 查找
      pop() / pop_if_done() 删除
      sweep_expired() 周期清理孤儿
    """

    def __init__(self) -> None:
        self._entries: dict[str, StreamEntry] = {}

    async def create(
        self,
        stream_id: str,
        queue_maxsize: int = 1000,
        producer: ProducerFn | None = None,
    ) -> StreamEntry:
        """注册新 stream,可选启动 producer task。

        Args:
            stream_id: 全局唯一 ID(uuid4 128bit,bearer-token 安全)
            queue_maxsize: asyncio.Queue 容量上限,backpressure 防止 OOM
            producer: 可选协程 `(entry) -> None`,被包装为 task 启动。
                      协程正常返回 → entry.status = 'done'(由调用方设置)
                      协程抛异常 → 框架捕获并设 entry.status = 'failed'
        """
        if stream_id in self._entries:
            raise ValueError(f"streamId already exists: {stream_id}")
        entry = StreamEntry(
            queue=asyncio.Queue(maxsize=queue_maxsize),
            status="pending",
            created_at=time.time(),
        )
        self._entries[stream_id] = entry
        if producer is not None:
            entry.task = asyncio.create_task(
                self._run_producer(entry, producer),
                name=f"chat-stream-{stream_id}",
            )
        return entry

    async def _run_producer(self, entry: StreamEntry, producer: ProducerFn) -> None:
        """包装 producer:捕获异常、设置 status、最后入队 SENTINEL。

        异常情况下也入队一个 failed 事件 + SENTINEL,让 attach 端点能
        拿到错误信息并正常关闭。
        """
        entry.status = "running"
        try:
            await producer(entry)
            if entry.status == "running":
                entry.status = "done"
        except Exception as exc:  # noqa: BLE001 — producer 是不可信 LLM 调用
            entry.status = "failed"
            # 把错误作为事件入队,attach 端点会发给客户端
            await entry.queue.put(
                {"error": {"type": "unknown", "message": str(exc)}, "state": "failed"}
            )
        finally:
            # 无论成功失败,attach 端点都要收到关闭信号
            with contextlib.suppress(asyncio.CancelledError):
                await entry.queue.put(SENTINEL)

    def get(self, stream_id: str) -> StreamEntry | None:
        return self._entries.get(stream_id)

    def pop(self, stream_id: str) -> bool:
        """立即移除(用于显式 cancel 或 shutdown)。"""
        if stream_id in self._entries:
            entry = self._entries.pop(stream_id)
            # 取消后台 task(若有)防止泄漏
            if entry.task is not None and not entry.task.done():
                entry.task.cancel()
            return True
        return False

    async def pop_if_done(self, stream_id: str, grace_seconds: float = 60.0) -> None:
        """若 stream 已 done/failed,等 grace_seconds 后删除(给迟到 attach 留窗口)。

        Args:
            grace_seconds: 完成后再保留多久,默认 60 秒
        """
        entry = self._entries.get(stream_id)
        if entry is None:
            return
        if entry.status not in ("done", "failed"):
            return
        await asyncio.sleep(grace_seconds)
        # 期间可能有更新,二次确认仍是同一个 entry
        if self._entries.get(stream_id) is entry and entry.status in ("done", "failed"):
            self._entries.pop(stream_id, None)

    async def sweep_expired(self, max_age_seconds: float = 300.0) -> int:
        """清理超过 max_age_seconds 仍未完成(dangling)的 entry。

        正常情况下 done/failed 的 entry 会被 pop_if_done 主动删,
        sweep 是兜底 — 处理 producer 死循环 / 异常路径漏删的孤儿。
        """
        now = time.time()
        expired = [
            sid for sid, entry in self._entries.items() if now - entry.created_at > max_age_seconds
        ]
        for sid in expired:
            entry = self._entries.pop(sid)
            if entry.task is not None and not entry.task.done():
                entry.task.cancel()
        return len(expired)

    def size(self) -> int:
        return len(self._entries)

    def __contains__(self, stream_id: str) -> bool:
        return stream_id in self._entries
