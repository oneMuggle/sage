"""记忆召回质量评估模块

提供离线评估和在线评估框架，用于度量检索质量。

评估指标：
- Precision@K: 前 K 个结果中相关结果的比例
- Recall@K: 前 K 个结果覆盖了多少相关结果
- MRR (Mean Reciprocal Rank): 第一个相关结果的位置倒数
- NDCG (Normalized Discounted Cumulative Gain): 考虑位置加权的增益

使用方式：
    evaluator = RecallEvaluator()

    # 离线评估（需要标注数据）
    metrics = evaluator.evaluate_offline(
        queries=labeled_queries,
        retrieve_fn=adapter.retrieve,
        k_values=[1, 3, 5, 10]
    )

    # 在线评估（基于检索日志）
    evaluator.log_retrieval(
        query="用户问题",
        results=retrieved_memories,
        user_feedback="clicked"  # 或 "ignored"
    )
    online_metrics = evaluator.get_online_metrics()
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

#: 记忆库里的反馈取值 → ``memory_recall_log.user_feedback`` 的归一化映射。
#: 内存路径历史上用 "clicked" / "helpful" / "ignored" / "not_helpful"，
#: 库里统一存 "up" / "down"（前端两个按钮的语义）。
_FEEDBACK_ALIASES = {
    "clicked": "up",
    "helpful": "up",
    "up": "up",
    "ignored": "down",
    "not_helpful": "down",
    "down": "down",
}


def _normalize_feedback(user_feedback: Optional[str]) -> Optional[str]:
    """把历史反馈取值归一化成 ``up`` / ``down``；无法识别时返回 None。"""
    if not user_feedback:
        return None
    return _FEEDBACK_ALIASES.get(str(user_feedback).strip().lower())


def _looks_like_database(db: Any) -> bool:
    """鸭子类型判定：只接受真实的 Database 实例。

    ``Database.db_path`` 恒为 str（``database.py:360``），而测试里的
    ``Mock()`` 的 ``db_path`` 是 Mock 对象 —— 用它把假 db 挡在全局单例
    之外，避免测试污染进程内的 evaluator 状态。
    """
    if db is None or not hasattr(db, "get_connection"):
        return False
    return isinstance(getattr(db, "db_path", None), str)


class RecallEvaluator:
    """记忆召回质量评估器

    Attributes:
        offline_metrics: 离线评估指标缓存
        online_metrics: 在线评估指标缓存
        retrieval_logs: 检索日志（用于在线评估）
    """

    def __init__(self, db: Any = None) -> None:
        """初始化评估器

        Args:
            db: 可选的 Database 实例。给了之后 ``log_retrieval`` 会把每次召回
                持久化到 ``memory_recall_log``（P0-3），``get_online_metrics``
                改为从库聚合而非只读内存。
        """
        self.offline_metrics: Dict[str, float] = {}
        self.online_metrics: Dict[str, float] = {}
        self.retrieval_logs: List[Dict[str, Any]] = []
        self._online_positive_count = 0
        self._online_total_count = 0
        self._db = db if _looks_like_database(db) else None

    @property
    def db(self) -> Any:
        """当前绑定的 Database（未绑定时为 None）。"""
        return self._db

    def attach_db(self, db: Any) -> None:
        """绑定 Database（已绑定时忽略 —— 保持单例的库归属稳定）。"""
        if self._db is None and _looks_like_database(db):
            self._db = db

    def evaluate_offline(
        self,
        queries: List[Dict[str, Any]],
        retrieve_fn: Callable,
        k_values: Optional[List[int]] = None,
    ) -> Dict[str, float]:
        """离线评估（需要标注数据）

        Args:
            queries: 标注数据列表，每项包含：
                - query: 查询文本
                - relevant_ids: 相关记忆的 ID 集合
                - session_id: 会话 ID（可选）
            retrieve_fn: 检索函数，签名：(query, session_id, limit) -> MemoryContext
                支持同步或异步函数（async def）
            k_values: 评估的 K 值列表，默认 [1, 3, 5, 10]

        Returns:
            评估指标字典，包含：
                - precision@K: 各 K 值的精确率
                - recall@K: 各 K 值的召回率
                - mrr: 平均倒数排名
                - ndcg@K: 各 K 值的 NDCG
        """
        import asyncio
        import inspect

        k_values = k_values or [1, 3, 5, 10]
        metrics: Dict[str, List[float]] = defaultdict(list)

        for query_item in queries:
            query = query_item["query"]
            relevant_ids: Set[str] = set(query_item["relevant_ids"])
            session_id = query_item.get("session_id", "")

            if not relevant_ids:
                continue

            # 执行检索（支持同步/异步 retrieve_fn）
            result = retrieve_fn(query, session_id=session_id, limit=max(k_values))
            if inspect.isawaitable(result):
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                context = loop.run_until_complete(result)
            else:
                context = result

            # 提取检索结果的 ID 列表（按顺序）
            retrieved_ids = self._extract_retrieved_ids(context)

            if not retrieved_ids:
                # 无结果，所有指标为 0
                for k in k_values:
                    metrics[f"precision@{k}"].append(0.0)
                    metrics[f"recall@{k}"].append(0.0)
                    metrics[f"ndcg@{k}"].append(0.0)
                metrics["mrr"].append(0.0)
                continue

            # 计算各 K 值的指标
            for k in k_values:
                top_k_ids = retrieved_ids[:k]
                precision = self._precision_at_k(top_k_ids, relevant_ids)
                recall = self._recall_at_k(top_k_ids, relevant_ids)
                ndcg = self._ndcg_at_k(top_k_ids, relevant_ids)

                metrics[f"precision@{k}"].append(precision)
                metrics[f"recall@{k}"].append(recall)
                metrics[f"ndcg@{k}"].append(ndcg)

            # 计算 MRR
            mrr = self._mrr(retrieved_ids, relevant_ids)
            metrics["mrr"].append(mrr)

        # 计算平均值
        avg_metrics = {
            metric_name: sum(values) / len(values) if values else 0.0
            for metric_name, values in metrics.items()
        }

        self.offline_metrics = avg_metrics
        logger.info(f"[recall_eval] 离线评估完成: {len(queries)} 个查询, 指标={avg_metrics}")
        return avg_metrics

    def _extract_retrieved_ids(self, context: Any) -> List[str]:
        """从 MemoryContext 中提取检索结果的 ID 列表

        Args:
            context: MemoryContext 对象

        Returns:
            记忆 ID 列表（按检索顺序）
        """
        ids = []
        # 按优先级提取：core > semantic > episodic
        for attr in ["core", "semantic", "episodic"]:
            items = getattr(context, attr, []) or []
            for item in items:
                mem_id = item.get("id") if isinstance(item, dict) else getattr(item, "id", None)
                if mem_id and mem_id not in ids:
                    ids.append(mem_id)
        return ids

    def _precision_at_k(self, retrieved_ids: List[str], relevant_ids: Set[str]) -> float:
        """计算 Precision@K

        Precision@K = |检索到的相关结果| / K
        """
        if not retrieved_ids:
            return 0.0
        k = len(retrieved_ids)
        relevant_retrieved = len(set(retrieved_ids) & relevant_ids)
        return relevant_retrieved / k

    def _recall_at_k(self, retrieved_ids: List[str], relevant_ids: Set[str]) -> float:
        """计算 Recall@K

        Recall@K = |检索到的相关结果| / |所有相关结果|
        """
        if not relevant_ids:
            return 0.0
        relevant_retrieved = len(set(retrieved_ids) & relevant_ids)
        return relevant_retrieved / len(relevant_ids)

    def _mrr(self, retrieved_ids: List[str], relevant_ids: Set[str]) -> float:
        """计算 MRR (Mean Reciprocal Rank)

        MRR = 1 / 第一个相关结果的位置
        """
        for i, mem_id in enumerate(retrieved_ids, start=1):
            if mem_id in relevant_ids:
                return 1.0 / i
        return 0.0

    def _ndcg_at_k(self, retrieved_ids: List[str], relevant_ids: Set[str]) -> float:
        """计算 NDCG@K (Normalized Discounted Cumulative Gain)

        NDCG@K = DCG@K / IDCG@K
        DCG@K = sum(rel_i / log2(i+1))
        IDCG@K = 理想排序的 DCG
        """
        if not retrieved_ids:
            return 0.0

        k = len(retrieved_ids)

        # 计算 DCG
        dcg = 0.0
        for i, mem_id in enumerate(retrieved_ids, start=1):
            rel = 1.0 if mem_id in relevant_ids else 0.0
            dcg += rel / math.log2(i + 1)

        # 计算 IDCG（理想排序）
        ideal_relevant = min(len(relevant_ids), k)
        idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_relevant + 1))

        return dcg / idcg if idcg > 0 else 0.0

    def log_retrieval(
        self,
        query: str,
        results: List[Dict[str, Any]],
        user_feedback: Optional[str] = None,
        session_id: Optional[str] = None,
        variant: Optional[str] = None,
        weights: Optional[List[float]] = None,
        db: Any = None,
    ) -> Optional[str]:
        """记录检索日志（用于在线评估）

        Args:
            query: 查询文本
            results: 检索结果列表
            user_feedback: 用户反馈（"clicked", "ignored", "helpful", "not_helpful"）
            session_id: 会话 ID
            variant: 本次召回使用的融合权重变体（A / B / "skip-vector"）
            weights: 本次实际使用的融合权重
            db: 本次调用用的 Database（缺省用实例上绑定的那个）

        Returns:
            持久化成功时返回 ``memory_recall_log.id``（供事后回填反馈），
            未绑定 db 或写入失败时返回 None。
        """
        log_entry = {
            "timestamp": time.time(),
            "query": query,
            "result_count": len(results),
            "result_ids": [r.get("id") for r in results if r.get("id")],
            "user_feedback": user_feedback,
            "session_id": session_id,
            "variant": variant,
        }
        self.retrieval_logs.append(log_entry)

        # 更新在线指标
        self._online_total_count += 1
        if user_feedback in ("clicked", "helpful"):
            self._online_positive_count += 1

        # P0-3：持久化到 memory_recall_log（best-effort，失败不阻塞召回）
        log_id = self._persist(
            query=query,
            result_count=len(results),
            session_id=session_id,
            variant=variant,
            weights=weights,
            user_feedback=user_feedback,
            db=db,
        )

        # 定期计算在线指标
        if self._online_total_count % 10 == 0:
            self._update_online_metrics()

        return log_id

    def _persist(
        self,
        *,
        query: str,
        result_count: int,
        session_id: Optional[str],
        variant: Optional[str],
        weights: Optional[List[float]],
        user_feedback: Optional[str],
        db: Any = None,
    ) -> Optional[str]:
        """把一次召回落到 ``memory_recall_log``。写库失败只记日志。"""
        target = db if db is not None else self._db
        if not _looks_like_database(target):
            return None
        try:
            from backend.memory.recall_log_store import (
                record_recall,
                set_feedback,
            )

            log_id = record_recall(
                target,
                query=query,
                variant=variant,
                weights=weights,
                result_count=result_count,
                session_id=session_id,
            )
            if log_id and user_feedback:
                normalized = _normalize_feedback(user_feedback)
                if normalized:
                    set_feedback(target, log_id, normalized)
            return log_id
        except Exception as exc:  # noqa: BLE001 — 召回是热路径，写库失败不阻塞
            logger.debug("[recall_eval] 召回事件落库失败: %s", exc)
            return None

    def _update_online_metrics(self) -> None:
        """更新在线评估指标"""
        if self._online_total_count == 0:
            return

        # 计算满意度
        satisfaction_rate = self._online_positive_count / self._online_total_count

        # 计算平均结果数
        avg_result_count = (
            sum(log["result_count"] for log in self.retrieval_logs) / len(self.retrieval_logs)
            if self.retrieval_logs
            else 0.0
        )

        self.online_metrics = {
            "satisfaction_rate": satisfaction_rate,
            "avg_result_count": avg_result_count,
            "total_queries": self._online_total_count,
            "positive_feedback": self._online_positive_count,
        }

        logger.info(f"[recall_eval] 在线指标更新: {self.online_metrics}")

    def get_online_metrics(self) -> Dict[str, Any]:
        """获取在线评估指标

        绑定了 Database 时从 ``memory_recall_log`` 聚合（跨进程/跨重启可见），
        否则退回内存累计值。两条路径的 key 名保持一致。

        Returns:
            在线指标字典
        """
        if self._db is not None:
            metrics = self._metrics_from_db()
            if metrics is not None:
                return metrics
        if not self.online_metrics:
            self._update_online_metrics()
        return self.online_metrics

    def _metrics_from_db(self) -> Optional[Dict[str, Any]]:
        """从 ``memory_recall_log`` 聚合在线指标。库不可用时返回 None。"""
        try:
            from backend.memory.recall_log_store import aggregate_metrics

            agg = aggregate_metrics(self._db)
        except Exception as exc:  # noqa: BLE001 — best-effort
            logger.debug("[recall_eval] 在线指标聚合失败: %s", exc)
            return None
        if not agg.get("total_recalls"):
            return None
        return {
            "satisfaction_rate": agg["satisfaction_rate"],
            "feedback_satisfaction_rate": agg["feedback_satisfaction_rate"],
            "avg_result_count": agg["avg_result_count"],
            "total_queries": agg["total_recalls"],
            "positive_feedback": agg["positive_count"],
            "negative_feedback": agg["negative_count"],
            "feedback_count": agg["feedback_count"],
            "by_variant": agg["by_variant"],
        }

    def export_report(self, filepath: str) -> None:
        """导出评估报告到 JSON 文件

        Args:
            filepath: 输出文件路径
        """
        report = {
            "timestamp": time.time(),
            "offline_metrics": self.offline_metrics,
            "online_metrics": self.online_metrics,
            "retrieval_log_count": len(self.retrieval_logs),
            "recent_logs": self.retrieval_logs[-100:],  # 最近 100 条日志
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        logger.info(f"[recall_eval] 评估报告已导出: {filepath}")


def generate_synthetic_queries(
    episodic_memory: Any,
    semantic_memory: Any,
    sample_size: int = 50,
) -> List[Dict[str, Any]]:
    """生成合成查询数据（用于测试评估框架）

    从现有记忆中抽取样本，使用摘要作为查询，原始记忆 ID 作为相关结果。

    Args:
        episodic_memory: EpisodicMemory 实例
        semantic_memory: SemanticMemory 实例
        sample_size: 样本数量

    Returns:
        合成查询列表
    """
    queries = []

    # 从 episodic 记忆抽样
    episodic_recent = episodic_memory.get_recent(limit=sample_size)
    for mem in episodic_recent:
        summary = mem.get("summary") or mem.get("content", "")
        if summary:
            queries.append({
                "query": summary[:50],  # 用摘要前 50 字符作为查询
                "relevant_ids": [mem["id"]],
                "session_id": mem.get("session_id"),
            })

    # 从 semantic 记忆抽样
    semantic_recent = semantic_memory.get_recent(limit=sample_size)
    for mem in semantic_recent:
        summary = mem.get("summary") or mem.get("content", "")
        if summary:
            queries.append({
                "query": summary[:50],
                "relevant_ids": [mem["id"]],
                "session_id": None,  # semantic 记忆无 session
            })

    logger.info(f"[recall_eval] 生成合成查询: {len(queries)} 条")
    return queries


# ============================================================================
# 模块级单例（Phase 2 接入生产链路）
# ============================================================================

_evaluator: Optional[RecallEvaluator] = None
_evaluator_lock = threading.Lock()


def get_recall_evaluator(db: Any = None) -> RecallEvaluator:
    """懒加载单例。双检锁确保只初始化一次。

    与 ``get_tag_graph()`` 同模式：首次调用创建空评估器，
    后续调用复用同一实例。所有 ``log_retrieval()`` 调用共享
    同一份 ``retrieval_logs`` / ``online_metrics``。

    Args:
        db: 可选的 Database 实例。给了之后单例会把召回事件持久化到
            ``memory_recall_log``（P0-3）。
    """
    global _evaluator
    if _evaluator is None:
        with _evaluator_lock:
            if _evaluator is None:
                _evaluator = RecallEvaluator(db=db)
    elif db is not None:
        _evaluator.attach_db(db)
    return _evaluator
