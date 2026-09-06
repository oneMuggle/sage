"""LLM 用量追踪与成本估算 (M6 生态扩展)。

设计改编自 claw-code ``rust/crates/runtime/src/usage.rs``
(TokenUsage / UsageTracker / pricing_for_model / estimate_cost_usd)。

有意只做内存态 (YAGNI: 不新增 DB 表):
- 最近 ``RECORD_CAP`` 条 UsageRecord 的 ring buffer;
- 按日 (本地 YYYY-MM-DD) 聚合字典;
- 按模型聚合字典。

模块级单例 ``usage_tracker`` 供 LLMClient 与 /api/v1/usage 共享。
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

RECORD_CAP = 1000

# 每百万 token 的美元定价: (input, output)。键按最长前缀优先匹配
# (lowercased 模型名), 未知模型 → 成本 None。
# 数据来源: 各厂商公开定价 (2026-07), 仅用于估算。
PRICING_PER_MILLION_TOKENS: Dict[str, Tuple[float, float]] = {
    # OpenAI
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    "o3-mini": (1.10, 4.40),
    "o3": (2.00, 8.00),
    # Anthropic 家族前缀
    "claude-opus": (15.00, 75.00),
    "claude-sonnet": (3.00, 15.00),
    "claude-haiku": (0.80, 4.00),
    # DeepSeek
    "deepseek-reasoner": (0.55, 2.19),
    "deepseek-chat": (0.27, 1.10),
    # Gemini
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.0-flash": (0.10, 0.40),
}


def pricing_for_model(model: str) -> Optional[Tuple[float, float]]:
    """返回模型的 (input, output) USD/1M 定价; 未知模型 → None。

    先精确匹配, 再最长前缀匹配 (让 ``gpt-4o-mini`` 优先于 ``gpt-4o``,
    ``claude-sonnet-4-20250514`` 命中 ``claude-sonnet``)。
    """
    if not model:
        return None
    normalized = model.strip().lower()
    if normalized in PRICING_PER_MILLION_TOKENS:
        return PRICING_PER_MILLION_TOKENS[normalized]
    best: Optional[str] = None
    for key in PRICING_PER_MILLION_TOKENS:
        if normalized.startswith(key) and (best is None or len(key) > len(best)):
            best = key
    if best is None:
        return None
    return PRICING_PER_MILLION_TOKENS[best]


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> Optional[float]:
    """估算单次请求的美元成本; 未知模型 → None。"""
    pricing = pricing_for_model(model)
    if pricing is None:
        return None
    input_cost = prompt_tokens / 1_000_000.0 * pricing[0]
    output_cost = completion_tokens / 1_000_000.0 * pricing[1]
    return round(input_cost + output_cost, 8)


@dataclass
class UsageRecord:
    """一次 LLM 请求的用量记录。"""

    model: str
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: Optional[float]
    at: str  # ISO-8601 (UTC)


def _empty_bucket() -> Dict[str, Any]:
    return {
        "requests": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "estimated_cost_usd": None,
    }


def _accumulate(bucket: Dict[str, Any], prompt_tokens: int, completion_tokens: int, cost: Optional[float]) -> None:
    bucket["requests"] += 1
    bucket["prompt_tokens"] += prompt_tokens
    bucket["completion_tokens"] += completion_tokens
    if cost is not None:
        base = bucket["estimated_cost_usd"] or 0.0
        bucket["estimated_cost_usd"] = round(base + cost, 8)


class UsageTracker:
    """内存态用量追踪器 (线程安全)。"""

    def __init__(self, cap: int = RECORD_CAP) -> None:
        self._records: Deque[UsageRecord] = deque(maxlen=cap)
        self._by_model: Dict[str, Dict[str, Any]] = {}
        self._daily: Dict[str, Dict[str, Any]] = {}
        self._totals: Dict[str, Any] = _empty_bucket()
        self._lock = threading.Lock()

    def record(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        session_id: Optional[str] = None,
    ) -> UsageRecord:
        """记录一次 LLM 调用; 返回生成的 UsageRecord。

        L8 (批次 C): 同步 best-effort 落库 (usage_events 表, 带会话维度),
        失败只 debug 日志——内存聚合与调用方永不受 DB 故障影响。
        """
        cost = estimate_cost_usd(model, prompt_tokens, completion_tokens)
        entry = UsageRecord(
            model=model,
            prompt_tokens=int(prompt_tokens),
            completion_tokens=int(completion_tokens),
            estimated_cost_usd=cost,
            # noqa UP017: datetime.UTC 需 py3.11+, timezone.utc 是 py3.8 兼容写法
            at=datetime.now(timezone.utc).isoformat(),  # noqa: UP017
        )
        day = datetime.now().strftime("%Y-%m-%d")
        with self._lock:
            self._records.append(entry)
            _accumulate(self._totals, entry.prompt_tokens, entry.completion_tokens, cost)
            model_bucket = self._by_model.setdefault(model, _empty_bucket())
            _accumulate(model_bucket, entry.prompt_tokens, entry.completion_tokens, cost)
            day_bucket = self._daily.setdefault(day, _empty_bucket())
            _accumulate(day_bucket, entry.prompt_tokens, entry.completion_tokens, cost)
        self._persist(entry, session_id)
        return entry

    @staticmethod
    def _persist(entry: UsageRecord, session_id: Optional[str]) -> None:
        """单行落库 (L8)。任何失败静默——用量是增强信息, 不是关键路径。"""
        try:
            import uuid

            from backend.data.database import _SQLITE_LOCK, get_database

            row = (
                str(uuid.uuid4()),
                session_id,
                entry.model,
                entry.prompt_tokens,
                entry.completion_tokens,
                entry.prompt_tokens + entry.completion_tokens,
                entry.estimated_cost_usd,
                int(time.time() * 1000),
            )
            with _SQLITE_LOCK:
                get_database().get_connection().execute(
                    "INSERT INTO usage_events (id, session_id, model, prompt_tokens,"
                    " completion_tokens, total_tokens, estimated_cost_usd, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    row,
                )
                get_database().get_connection().commit()
        except Exception as exc:  # noqa: BLE001 — fail-open 铁律
            logger.debug("usage_events 落库跳过: %s", exc)

    def session_summary(self, session_id: str) -> Dict[str, Any]:
        """U14: 某会话的持久化用量聚合 (DB 直查, 重启不丢)。"""
        try:
            from backend.data.database import _SQLITE_LOCK, get_database

            with _SQLITE_LOCK:
                conn = get_database().get_connection()
                row = conn.execute(
                    "SELECT COUNT(*) AS requests,"
                    " COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,"
                    " COALESCE(SUM(completion_tokens), 0) AS completion_tokens,"
                    " COALESCE(SUM(total_tokens), 0) AS total_tokens,"
                    " COALESCE(SUM(estimated_cost_usd), 0) AS estimated_cost_usd"
                    " FROM usage_events WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
            return {
                "session_id": session_id,
                "requests": int(row["requests"]) if row else 0,
                "prompt_tokens": int(row["prompt_tokens"]) if row else 0,
                "completion_tokens": int(row["completion_tokens"]) if row else 0,
                "total_tokens": int(row["total_tokens"]) if row else 0,
                "estimated_cost_usd": float(row["estimated_cost_usd"]) if row else 0.0,
            }
        except Exception as exc:  # noqa: BLE001
            logger.debug("session_summary 读取失败: %s", exc)
            return {
                "session_id": session_id,
                "requests": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "estimated_cost_usd": 0.0,
            }

    def today_cost_usd(self) -> float:
        """F5: 今日已花费的持久化估算 (本地日界)。DB 不可用 → 0 (限额失效)。"""
        try:
            from backend.data.database import _SQLITE_LOCK, get_database

            day_start = datetime.strptime(datetime.now().strftime("%Y-%m-%d"), "%Y-%m-%d")  # noqa: DTZ007 — 本地日界, 非时区敏感
            start_ms = int(day_start.timestamp() * 1000)
            with _SQLITE_LOCK:
                row = get_database().get_connection().execute(
                    "SELECT COALESCE(SUM(estimated_cost_usd), 0) AS total"
                    " FROM usage_events WHERE created_at >= ?",
                    (start_ms,),
                ).fetchone()
            return float(row["total"]) if row else 0.0
        except Exception as exc:  # noqa: BLE001
            logger.debug("today_cost_usd 读取失败: %s", exc)
            return 0.0

    def summary(self) -> Dict[str, Any]:
        """返回 {totals, by_model: [...], today: {...}} 快照。"""
        day = datetime.now().strftime("%Y-%m-%d")
        with self._lock:
            by_model = [
                {"model": model, **bucket}
                for model, bucket in sorted(
                    self._by_model.items(),
                    key=lambda kv: kv[1]["requests"],
                    reverse=True,
                )
            ]
            return {
                "totals": dict(self._totals),
                "by_model": by_model,
                "today": dict(self._daily.get(day, _empty_bucket())),
            }

    def recent(self, limit: int = 50) -> List[UsageRecord]:
        """返回最近 ``limit`` 条记录 (新 → 旧)。"""
        with self._lock:
            items = list(self._records)
        items.reverse()
        return items[:limit]

    def reset(self) -> None:
        """清空全部状态 (测试用)。"""
        with self._lock:
            self._records.clear()
            self._by_model.clear()
            self._daily.clear()
            self._totals = _empty_bucket()


# 模块级单例: LLMClient 写入, /api/v1/usage 读取。
usage_tracker = UsageTracker()
