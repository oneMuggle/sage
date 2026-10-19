"""标签共现图谱 (TagCooccurrenceGraph) 与召回评估器 (RecallEvaluator) 测试。

覆盖 PR feat/memory-recall-optimization 的 Phase 3 Task 7 / Task 8。
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from backend.memory.recall_eval import RecallEvaluator, generate_synthetic_queries
from backend.memory.tag_graph import TagCooccurrenceGraph

pytestmark = pytest.mark.unit


def _fake_memory_store(episodic_rows, semantic_rows=None):
    """构造只提供 get_recent() 的假记忆存储。"""
    episodic = MagicMock()
    episodic.get_recent.return_value = episodic_rows
    semantic = MagicMock()
    semantic.get_recent.return_value = semantic_rows or []
    return episodic, semantic


def _mem(mem_id, tags):
    return {"id": mem_id, "tags": tags}


class TestTagCooccurrenceGraph:
    def test_build_indexes_cooccurring_tags(self):
        graph = TagCooccurrenceGraph()
        episodic, semantic = _fake_memory_store(
            [_mem("m1", ["python", "fastapi"]), _mem("m2", ["python", "fastapi"])]
        )
        graph.build_from_memories(episodic, semantic)

        assert graph.tag_cooccurrence["python"]["fastapi"] == 2
        assert graph.tag_cooccurrence["fastapi"]["python"] == 2

    def test_build_accepts_json_encoded_tags(self):
        graph = TagCooccurrenceGraph()
        episodic, semantic = _fake_memory_store(
            [_mem("m1", json.dumps(["a", "b"], ensure_ascii=False))]
        )
        graph.build_from_memories(episodic, semantic)

        assert graph.tag_cooccurrence["a"]["b"] == 1

    def test_build_skips_rows_without_tags(self):
        graph = TagCooccurrenceGraph()
        episodic, semantic = _fake_memory_store([_mem("m1", [])])
        graph.build_from_memories(episodic, semantic)

        assert graph.total_memories == 0
        assert graph.export_stats()["total_tags"] == 0

    def test_build_skips_malformed_json_tags(self):
        graph = TagCooccurrenceGraph()
        episodic, semantic = _fake_memory_store([_mem("m1", "{not json")])
        graph.build_from_memories(episodic, semantic)

        assert graph.total_memories == 0

    def test_query_returns_direct_match(self):
        graph = TagCooccurrenceGraph()
        episodic, semantic = _fake_memory_store([_mem("m1", ["python"])])
        graph.build_from_memories(episodic, semantic)

        results = graph.query(["python"])
        assert [r["memory_id"] for r in results] == ["m1"]
        assert results[0]["matched_tags"] == ["python"]

    def test_query_empty_tags_returns_empty(self):
        assert TagCooccurrenceGraph().query([]) == []

    def test_query_expands_through_cooccurrence(self):
        """查询 python 应召回只打了 fastapi 标签但与之共现的记忆。"""
        graph = TagCooccurrenceGraph()
        episodic, semantic = _fake_memory_store(
            [
                _mem("m1", ["python", "fastapi"]),
                _mem("m2", ["python", "fastapi"]),
                _mem("m3", ["python", "fastapi"]),
                _mem("m4", ["fastapi"]),
            ]
        )
        graph.build_from_memories(episodic, semantic)

        assert "m4" in {r["memory_id"] for r in graph.query(["python"])}

    def test_query_respects_min_cooccurrence(self):
        """共现次数低于阈值的弱关联不应被扩展进来。

        m1 同时打 python/fastapi, m2 只打 fastapi —— 两者共现 1 次,
        低于 min_cooccurrence=2, 故 m2 不应因 python 而被召回。
        """
        graph = TagCooccurrenceGraph()
        episodic, semantic = _fake_memory_store(
            [_mem("m1", ["python", "fastapi"]), _mem("m2", ["fastapi"])]
        )
        graph.build_from_memories(episodic, semantic)

        assert graph.query(["python"], min_cooccurrence=2) == [
            {"memory_id": "m1", "score": 1.0, "matched_tags": ["python"]}
        ]

    def test_low_cooccurrence_is_admitted_when_threshold_allows(self):
        """同一图谱下 min_cooccurrence=1 时 m2 才会被扩展召回。"""
        graph = TagCooccurrenceGraph()
        episodic, semantic = _fake_memory_store(
            [_mem("m1", ["python", "fastapi"]), _mem("m2", ["fastapi"])]
        )
        graph.build_from_memories(episodic, semantic)

        assert "m2" in {r["memory_id"] for r in graph.query(["python"], min_cooccurrence=1)}

    def test_query_respects_top_k(self):
        graph = TagCooccurrenceGraph()
        episodic, semantic = _fake_memory_store(
            [_mem(f"m{i}", ["python"]) for i in range(10)]
        )
        graph.build_from_memories(episodic, semantic)

        assert len(graph.query(["python"], top_k=3)) == 3

    def test_get_related_tags_sorted_desc(self):
        graph = TagCooccurrenceGraph()
        episodic, semantic = _fake_memory_store(
            [
                _mem("m1", ["python", "fastapi", "asyncio"]),
                _mem("m2", ["python", "fastapi"]),
                _mem("m3", ["python", "fastapi"]),
                _mem("m4", ["python", "asyncio"]),
            ]
        )
        graph.build_from_memories(episodic, semantic)

        related = graph.get_related_tags("python")
        assert related[0]["tag"] == "fastapi"
        assert related[0]["cooccurrence"] > related[1]["cooccurrence"]

    def test_get_related_tags_unknown_tag_returns_empty(self):
        assert TagCooccurrenceGraph().get_related_tags("nope") == []

    def test_export_stats_counts(self):
        graph = TagCooccurrenceGraph()
        episodic, semantic = _fake_memory_store(
            [_mem("m1", ["a", "b"]), _mem("m2", ["a", "b"])]
        )
        graph.build_from_memories(episodic, semantic)

        stats = graph.export_stats()
        assert stats["total_memories"] == 2
        assert stats["total_tags"] == 2
        assert stats["total_edges"] == 1  # a<->b 计 1 条无向边
        assert sorted(stats["top_tags"]) == ["a", "b"]

    def test_export_stats_on_empty_graph(self):
        assert TagCooccurrenceGraph().export_stats() == {
            "total_memories": 0,
            "total_tags": 0,
            "total_edges": 0,
            "avg_edges_per_tag": 0,
            "top_tags": [],
        }


# ==================== RecallEvaluator ====================


def _context(ids):
    return MagicMock(core=[], episodic=[{"id": i} for i in ids], semantic=[])


class TestRecallEvaluatorOffline:
    def test_perfect_ranking_scores_one(self):
        ev = RecallEvaluator()
        metrics = ev.evaluate_offline(
            queries=[{"query": "q", "relevant_ids": ["a", "b"]}],
            retrieve_fn=lambda q, session_id, limit: _context(["a", "b"]),
        )
        assert metrics["precision@10"] == 1.0
        assert metrics["recall@10"] == 1.0
        assert metrics["mrr"] == 1.0
        assert metrics["ndcg@10"] == 1.0

    def test_missing_relevant_lowers_recall(self):
        ev = RecallEvaluator()
        metrics = ev.evaluate_offline(
            queries=[{"query": "q", "relevant_ids": ["a", "b"]}],
            retrieve_fn=lambda q, session_id, limit: _context(["a", "x", "y"]),
        )
        assert metrics["recall@10"] == 0.5
        assert metrics["precision@1"] == 1.0

    def test_mrr_reflects_rank_of_first_hit(self):
        ev = RecallEvaluator()
        metrics = ev.evaluate_offline(
            queries=[{"query": "q", "relevant_ids": ["z"]}],
            retrieve_fn=lambda q, session_id, limit: _context(["x", "y", "z"]),
        )
        assert metrics["mrr"] == pytest.approx(1 / 3)

    def test_no_relevant_at_query_is_skipped(self):
        ev = RecallEvaluator()
        metrics = ev.evaluate_offline(
            queries=[{"query": "q", "relevant_ids": []}],
            retrieve_fn=lambda q, session_id, limit: _context(["a"]),
        )
        assert metrics == {}

    def test_empty_retrieval_scores_zero(self):
        ev = RecallEvaluator()
        metrics = ev.evaluate_offline(
            queries=[{"query": "q", "relevant_ids": ["a"]}],
            retrieve_fn=lambda q, session_id, limit: _context([]),
        )
        assert metrics["precision@1"] == 0.0
        assert metrics["mrr"] == 0.0

    def test_async_retrieve_fn_supported(self):
        async def retrieve(q, session_id, limit):
            return _context(["a"])

        ev = RecallEvaluator()
        metrics = ev.evaluate_offline(
            queries=[{"query": "q", "relevant_ids": ["a"]}], retrieve_fn=retrieve
        )
        assert metrics["mrr"] == 1.0

    def test_core_ids_ranked_before_episodic(self):
        ev = RecallEvaluator()
        context = MagicMock(core=[{"id": "a"}], episodic=[{"id": "b"}], semantic=[])
        metrics = ev.evaluate_offline(
            queries=[{"query": "q", "relevant_ids": ["b"]}],
            retrieve_fn=lambda *a, **k: context,
        )
        assert metrics["mrr"] == 0.5  # b 排在第二位

    def test_duplicate_ids_are_deduplicated(self):
        """同一记忆在 core/episodic 重复出现时只计一次, 不虚增分母。"""
        ev = RecallEvaluator()
        metrics = ev.evaluate_offline(
            queries=[{"query": "q", "relevant_ids": ["a"]}],
            retrieve_fn=lambda q, session_id, limit: _context(["a", "a"]),
        )
        assert metrics["precision@10"] == 1.0

    def test_custom_k_values(self):
        ev = RecallEvaluator()
        metrics = ev.evaluate_offline(
            queries=[{"query": "q", "relevant_ids": ["a"]}],
            retrieve_fn=lambda q, session_id, limit: _context(["a"]),
            k_values=[1, 3],
        )
        assert "precision@3" in metrics
        assert "precision@10" not in metrics


class TestRecallEvaluatorOnline:
    def test_satisfaction_rate_counts_positive_feedback(self):
        ev = RecallEvaluator()
        for feedback in ["clicked", "ignored", "helpful", "ignored"]:
            ev.log_retrieval("q", [{"id": "a"}], user_feedback=feedback)
        assert ev.get_online_metrics()["satisfaction_rate"] == 0.5

    def test_online_metrics_track_counts(self):
        ev = RecallEvaluator()
        ev.log_retrieval("q", [{"id": "a"}, {"id": "b"}])
        metrics = ev.get_online_metrics()
        assert metrics["total_queries"] == 1
        assert metrics["avg_result_count"] == 2.0

    def test_online_metrics_update_every_ten_calls(self):
        ev = RecallEvaluator()
        for _ in range(10):
            ev.log_retrieval("q", [{"id": "a"}], user_feedback="clicked")
        assert ev.online_metrics["total_queries"] == 10

    def test_export_report_writes_json(self, tmp_path):
        ev = RecallEvaluator()
        ev.log_retrieval("q", [{"id": "a"}], user_feedback="clicked", session_id="s1")
        target = tmp_path / "report.json"
        ev.export_report(str(target))

        report = json.loads(target.read_text(encoding="utf-8"))
        assert report["retrieval_log_count"] == 1
        assert report["recent_logs"][0]["session_id"] == "s1"

    def test_export_report_keeps_only_recent_hundred(self, tmp_path):
        ev = RecallEvaluator()
        for _ in range(120):
            ev.log_retrieval("q", [{"id": "a"}])
        target = tmp_path / "report.json"
        ev.export_report(str(target))

        report = json.loads(target.read_text(encoding="utf-8"))
        assert report["retrieval_log_count"] == 120
        assert len(report["recent_logs"]) == 100


class TestGenerateSyntheticQueries:
    def test_builds_queries_from_both_stores(self):
        episodic, semantic = _fake_memory_store(
            [{"id": "e1", "summary": "episodic 摘要", "session_id": "s1"}],
            [{"id": "s1", "summary": "semantic 摘要"}],
        )
        queries = generate_synthetic_queries(episodic, semantic)

        assert {q["query"] for q in queries} == {"episodic 摘要", "semantic 摘要"}
        assert {q["relevant_ids"][0] for q in queries} == {"e1", "s1"}

    def test_semantic_queries_have_no_session(self):
        episodic, semantic = _fake_memory_store(
            [], [{"id": "s1", "summary": "semantic 摘要"}]
        )
        assert generate_synthetic_queries(episodic, semantic)[0]["session_id"] is None

    def test_rows_without_summary_are_skipped(self):
        episodic, semantic = _fake_memory_store([{"id": "e1", "content": ""}])
        assert generate_synthetic_queries(episodic, semantic) == []
