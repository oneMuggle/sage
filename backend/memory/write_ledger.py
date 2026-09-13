# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""MemoryWriteLedger — 记忆写入台账（对标 ChatGPT "Memory updated" 提示）。

问题
----
记忆提取是**异步、静默**的（``async_extractor`` 单 worker 后台消费），用户在
对话里完全感知不到"Sage 刚刚记住了什么"，也没有一步撤销的入口。这与
PHILOSOPHY "透明可控" 相悖，也是与主流 AI 应用最直观的体验差距。

方案
----
在 ``extract_and_store_memory`` 的写入落点记录一条 ``WriteRecord``（进程内
环形缓冲，按 session 分桶），前端在流结束后轮询 ``/memory/recent-writes``
拿到本轮新增条目，在气泡下方显示"🧠 记住了：…"并提供撤销。撤销走
``/memory/undo-write`` → 按 ``kind`` 路由到 ``MemoryManager.delete_memory``
或 ``UserProfileStore.delete``。

设计约束
--------
- **best-effort**：台账只是 UX 增强，任何失败不得影响写入主流程。
- **有界**：每 session 最多保留 ``PER_SESSION_LIMIT`` 条、全局最多
  ``SESSION_LIMIT`` 个 session（LRU 淘汰），避免长期运行内存增长。
- **游标语义**：``list_since(session_id, after_seq)`` 用单调递增 ``seq``
  做游标，前端记住上次看到的 seq 即可只取增量，不需要时间戳比较。
- 不落库：重启后台账清空是可接受的——它描述的是"刚刚"发生的写入。
"""

from __future__ import annotations

import itertools
import threading
import time
from collections import OrderedDict, deque
from dataclasses import asdict, dataclass
from typing import Any, Deque, Dict, List, Optional

#: 每个 session 保留的最近写入条数
PER_SESSION_LIMIT = 50
#: 全局最多跟踪的 session 数（LRU）
SESSION_LIMIT = 200

#: ``WriteRecord.kind`` 取值：通用三层记忆 / 用户画像
KIND_MEMORY = "memory"
KIND_PROFILE = "profile"
VALID_KINDS = (KIND_MEMORY, KIND_PROFILE)


@dataclass(frozen=True)
class WriteRecord:
    """一次记忆写入的台账记录。"""

    seq: int
    id: str
    kind: str  # memory | profile
    content: str
    category: str  # fact/event/preference/goal/... （extractor 产出）
    memory_type: str  # episodic/semantic/working（profile 时为 "profile"）
    session_id: str
    created_at: int  # ms epoch

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class MemoryWriteLedger:
    """进程内记忆写入台账（线程安全，按 session 分桶，LRU 有界）。"""

    def __init__(
        self,
        per_session_limit: int = PER_SESSION_LIMIT,
        session_limit: int = SESSION_LIMIT,
    ) -> None:
        self._per_session_limit = max(1, int(per_session_limit))
        self._session_limit = max(1, int(session_limit))
        self._buckets: OrderedDict[str, Deque[WriteRecord]] = OrderedDict()
        self._seq = itertools.count(1)
        self._lock = threading.Lock()

    # ---- 写入 -------------------------------------------------------------

    def record(
        self,
        *,
        memory_id: str,
        kind: str,
        content: str,
        session_id: Optional[str],
        category: str = "fact",
        memory_type: str = "",
    ) -> Optional[WriteRecord]:
        """登记一次写入；无效参数（空 id / 空 session / 未知 kind）静默忽略。"""
        if not memory_id or not session_id or kind not in VALID_KINDS:
            return None
        rec = WriteRecord(
            seq=next(self._seq),
            id=str(memory_id),
            kind=kind,
            content=str(content or "")[:200],
            category=str(category or "fact"),
            memory_type=str(memory_type or ("profile" if kind == KIND_PROFILE else "episodic")),
            session_id=str(session_id),
            created_at=int(time.time() * 1000),
        )
        with self._lock:
            bucket = self._buckets.get(rec.session_id)
            if bucket is None:
                bucket = deque(maxlen=self._per_session_limit)
                self._buckets[rec.session_id] = bucket
            else:
                self._buckets.move_to_end(rec.session_id)
            bucket.append(rec)
            while len(self._buckets) > self._session_limit:
                self._buckets.popitem(last=False)
        return rec

    # ---- 读取 -------------------------------------------------------------

    def list_since(self, session_id: str, after_seq: int = 0, limit: int = 20) -> List[WriteRecord]:
        """返回 ``seq > after_seq`` 的记录（升序），最多 ``limit`` 条。"""
        if not session_id:
            return []
        with self._lock:
            bucket = self._buckets.get(session_id)
            if not bucket:
                return []
            items = [r for r in bucket if r.seq > int(after_seq or 0)]
        return items[: max(1, int(limit or 20))]

    def latest_seq(self, session_id: str) -> int:
        """该 session 当前最大 seq（无记录返回 0）。"""
        with self._lock:
            bucket = self._buckets.get(session_id)
            return bucket[-1].seq if bucket else 0

    def find(self, session_id: str, memory_id: str) -> Optional[WriteRecord]:
        with self._lock:
            bucket = self._buckets.get(session_id)
            if not bucket:
                return None
            for r in reversed(bucket):
                if r.id == memory_id:
                    return r
        return None

    # ---- 撤销 -------------------------------------------------------------

    def forget(self, session_id: str, memory_id: str) -> bool:
        """把某条记录从台账移除（撤销成功后调用）。返回是否存在。"""
        with self._lock:
            bucket = self._buckets.get(session_id)
            if not bucket:
                return False
            kept = [r for r in bucket if r.id != memory_id]
            removed = len(kept) != len(bucket)
            if removed:
                bucket.clear()
                bucket.extend(kept)
            return removed

    def clear(self, session_id: Optional[str] = None) -> None:
        with self._lock:
            if session_id is None:
                self._buckets.clear()
            else:
                self._buckets.pop(session_id, None)


# 全局单例（与 get_memory_manager / get_user_profile 同模式）
_ledger: Optional[MemoryWriteLedger] = None
_ledger_lock = threading.Lock()


def get_write_ledger() -> MemoryWriteLedger:
    global _ledger
    if _ledger is None:
        with _ledger_lock:
            if _ledger is None:
                _ledger = MemoryWriteLedger()
    return _ledger


def reset_write_ledger() -> None:
    """重置单例（仅测试用）。"""
    global _ledger
    with _ledger_lock:
        _ledger = None
