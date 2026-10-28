"""技能变更通知中枢 (缺口 #6a)。

设计要点
--------
- 单一广播源: rescan / import / delete 成功后 publish 一次事件
- 同步 + 线程安全: threading.Condition 守护 _events + _seq
- 有界 buffer: 慢消费者最多收到 max_size 个最新事件, 旧事件被丢弃
- NDJSON 流: iter_ndjson 把事件序列化为单行 JSON (带换行符),
  供 FastAPI StreamingResponse 直接迭代
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Generator, List, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SkillNotificationEvent:
    """已分派序号的事件。"""

    seq: int
    event: Dict[str, Any]
    ts: float  # monotonic, 仅用于日志/诊断


class SkillNotificationHub:
    """技能变更通知中枢。

    Args:
        max_size: buffer 最大事件数。慢消费者最多收到最新 max_size 个事件。
    """

    def __init__(self, max_size: int = 256) -> None:
        self._max_size = max_size
        self._events: List[SkillNotificationEvent] = []
        self._seq: int = 0
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)

    def publish(self, event: Dict[str, Any]) -> None:
        """发布一个事件。线程安全。"""
        with self._cv:
            self._seq += 1
            entry = SkillNotificationEvent(
                seq=self._seq, event=dict(event), ts=time.monotonic()
            )
            self._events.append(entry)
            # 有界 buffer: 超过 max_size 时丢弃最旧
            overflow = len(self._events) - self._max_size
            if overflow > 0:
                del self._events[:overflow]
            self._cv.notify_all()

    def wait_for(
        self, after: int, timeout: float = 5.0
    ) -> List[SkillNotificationEvent]:
        """等待 after 之后的新事件, 最多 timeout 秒。

        返回按 seq 升序排列的事件列表。timeout 后无新事件返回空列表。
        """
        deadline = time.monotonic() + timeout
        with self._cv:
            while True:
                new = [e for e in self._events if e.seq > after]
                if new:
                    return new
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return []
                self._cv.wait(timeout=remaining)


# ===== 模块级单例 =====
_HUB: Optional[SkillNotificationHub] = None
_HUB_LOCK = threading.Lock()


def get_notification_hub() -> SkillNotificationHub:
    """获取模块级单例 hub (lazy init, 进程内共享)。"""
    global _HUB
    if _HUB is None:
        with _HUB_LOCK:
            if _HUB is None:
                _HUB = SkillNotificationHub()
    return _HUB


def reset_notification_hub_for_testing() -> None:
    """测试用: 重置单例。"""
    global _HUB
    with _HUB_LOCK:
        _HUB = None


def iter_ndjson(
    hub: SkillNotificationHub,
    after: int = 0,
    poll_interval: float = 0.5,
    max_iterations: Optional[int] = None,
    keep_alive: float = 15.0,
) -> Generator[str, None, None]:
    """把 hub 的事件流转换为 NDJSON 行迭代器 (FastAPI StreamingResponse 消费)。

    每条 line 是单行 JSON (trailing newline), 字段: {seq, event, ts}。
    客户端断连时, 生成器被 FastAPI 销毁, 线程退出。

    Args:
        hub: 通知中枢
        after: 初始游标 (0 = 取 buffer 里全部)
        poll_interval: 等待轮询间隔
        max_iterations: 测试用, 限制最大迭代次数
        keep_alive: 每 keep_alive 秒发送一次 {} 心跳 (防止中间件超时)
    """
    cursor = after
    iterations = 0
    last_emit = time.monotonic()
    while max_iterations is None or iterations < max_iterations:
        events = hub.wait_for(after=cursor, timeout=min(poll_interval, keep_alive))
        for e in events:
            payload = {"seq": e.seq, "event": e.event, "ts": e.ts}
            yield json.dumps(payload, ensure_ascii=False, default=str) + "\n"
            cursor = max(cursor, e.seq)
            last_emit = time.monotonic()
        # 心跳 (避免反向代理 idle timeout 切断连接)
        if not events and time.monotonic() - last_emit >= keep_alive:
            yield "{}\n"
            last_emit = time.monotonic()
        iterations += 1
