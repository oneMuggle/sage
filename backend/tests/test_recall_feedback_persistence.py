"""P0-3：召回反馈信号与指标落库。

覆盖：
* ``recall_log_store`` 写入 / 回填 / 聚合（含按 A/B 变体分组）
* ``query_hash`` 与 ``adapter.py`` 的变体选路**同口径**（否则实验无法复现）
* ``RecallEvaluator`` 绑库后 ``log_retrieval`` 落库并返回 log_id
* ``GET /memory/recall/metrics`` + ``POST /memory/recall/feedback``
"""

from __future__ import annotations

import hashlib
import tempfile

import pytest
from pydantic import ValidationError

from backend.api import legacy_memory_routes as legacy_routes
from backend.data.database import Database
from backend.memory import recall_log_store
from backend.memory.recall_eval import RecallEvaluator


@pytest.fixture()
def tmp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = Database(f.name)
        db.init_db()
        yield db
        db.close()


class _BrokenDb:
    """get_connection 直接炸 —— 用于验证 best-effort 语义。"""

    def get_connection(self):
        raise RuntimeError("db down")


# ---------- recall_log_store 基础 ----------


def test_query_hash_matches_adapter_variant_selection():
    """query_hash 前 8 位必须与 adapter 选变体时取的完全一致。

    adapter.py 的选路是 ``int(md5(query).hexdigest()[:8], 16) % 2``，
    口径一旦漂移，hash 与 variant 就对不上，A/B 实验无法复现。
    """
    for query in ["", "hello", "记忆召回怎么调优", "a" * 200]:
        digest = hashlib.md5(query.encode("utf-8")).hexdigest()
        assert recall_log_store.query_hash(query) == digest
        assert recall_log_store.query_hash(query)[:8] == digest[:8]


def test_record_recall_writes_row(tmp_db):
    log_id = recall_log_store.record_recall(
        tmp_db,
        query="记忆召回怎么调优",
        variant="A",
        weights=[0.2, 0.8],
        result_count=12,
        session_id="sess-1",
    )

    assert log_id
    row = tmp_db.get_connection().execute(
        "SELECT * FROM memory_recall_log WHERE id=?", (log_id,)
    ).fetchone()
    assert row["variant"] == "A"
    assert row["weights_json"] == "[0.2, 0.8]"
    assert row["result_count"] == 12
    assert row["session_id"] == "sess-1"
    assert row["user_feedback"] is None
    assert row["query_hash"] == recall_log_store.query_hash("记忆召回怎么调优")
    # 原文不落库 —— 只存 hash
    assert "调优" not in row["query_hash"]


def test_record_recall_is_best_effort():
    """写库失败返回 None，不抛异常（召回是热路径）。"""
    assert recall_log_store.record_recall(None, query="q") is None
    assert recall_log_store.record_recall(_BrokenDb(), query="q") is None


def test_set_feedback_updates_row(tmp_db):
    log_id = recall_log_store.record_recall(tmp_db, query="q", variant="B")

    assert recall_log_store.set_feedback(tmp_db, log_id, "up") is True

    row = tmp_db.get_connection().execute(
        "SELECT user_feedback FROM memory_recall_log WHERE id=?", (log_id,)
    ).fetchone()
    assert row["user_feedback"] == "up"


def test_set_feedback_rejects_invalid_value(tmp_db):
    log_id = recall_log_store.record_recall(tmp_db, query="q")

    assert recall_log_store.set_feedback(tmp_db, log_id, "maybe") is False
    assert recall_log_store.set_feedback(tmp_db, log_id, "") is False


def test_set_feedback_returns_false_for_unknown_id(tmp_db):
    assert recall_log_store.set_feedback(tmp_db, "no-such-id", "up") is False


# ---------- 指标聚合 ----------


def test_aggregate_metrics_splits_by_variant(tmp_db):
    """by_variant 让 A/B 变体第一次可比较。"""
    a1 = recall_log_store.record_recall(
        tmp_db, query="q1", variant="A", weights=[0.2, 0.8], result_count=10
    )
    a2 = recall_log_store.record_recall(
        tmp_db, query="q2", variant="A", weights=[0.2, 0.8], result_count=20
    )
    recall_log_store.record_recall(
        tmp_db, query="q3", variant="B", weights=[0.5, 0.5], result_count=4
    )
    recall_log_store.set_feedback(tmp_db, a1, "up")
    recall_log_store.set_feedback(tmp_db, a2, "down")

    agg = recall_log_store.aggregate_metrics(tmp_db)

    assert agg["total_recalls"] == 3
    assert agg["feedback_count"] == 2
    assert agg["positive_count"] == 1
    assert agg["negative_count"] == 1
    assert agg["by_variant"]["A"]["total"] == 2
    assert agg["by_variant"]["A"]["positive_count"] == 1
    assert agg["by_variant"]["A"]["negative_count"] == 1
    assert agg["by_variant"]["A"]["avg_result_count"] == 15.0
    assert agg["by_variant"]["B"]["total"] == 1
    assert agg["by_variant"]["B"]["feedback_count"] == 0


def test_aggregate_metrics_empty_db(tmp_db):
    agg = recall_log_store.aggregate_metrics(tmp_db)

    assert agg["total_recalls"] == 0
    assert agg["positive_count"] == 0
    assert agg["by_variant"] == {}


def test_aggregate_metrics_without_db():
    agg = recall_log_store.aggregate_metrics(None)

    assert agg["total_recalls"] == 0
    assert agg["by_variant"] == {}


def test_list_recent_returns_newest_first(tmp_db):
    recall_log_store.record_recall(tmp_db, query="old", variant="A", result_count=1)
    recall_log_store.record_recall(tmp_db, query="new", variant="B", result_count=2)

    items = recall_log_store.list_recent(tmp_db, limit=10)

    assert len(items) == 2
    assert items[0]["variant"] == "B"
    assert items[0]["result_count"] == 2


# ---------- RecallEvaluator 持久化路径 ----------


def test_log_retrieval_persists_and_returns_log_id(tmp_db):
    ev = RecallEvaluator(db=tmp_db)

    log_id = ev.log_retrieval(
        "记忆召回怎么调优",
        [{"id": "m1"}, {"id": "m2"}],
        session_id="sess-9",
        variant="A",
        weights=[0.2, 0.8],
    )

    assert log_id
    row = tmp_db.get_connection().execute(
        "SELECT * FROM memory_recall_log WHERE id=?", (log_id,)
    ).fetchone()
    assert row["variant"] == "A"
    assert row["weights_json"] == "[0.2, 0.8]"
    assert row["result_count"] == 2
    assert row["session_id"] == "sess-9"


def test_log_retrieval_without_db_does_not_raise():
    """没绑库时只留内存日志，返回 None（老行为不破）。"""
    ev = RecallEvaluator()

    assert ev.log_retrieval("q", [{"id": "m1"}]) is None
    assert len(ev.retrieval_logs) == 1


def test_log_retrieval_normalizes_legacy_feedback(tmp_db):
    """历史反馈取值（clicked/helpful）归一化成库里的 up/down。"""
    ev = RecallEvaluator(db=tmp_db)

    up_id = ev.log_retrieval("q", [{"id": "m1"}], user_feedback="clicked")
    down_id = ev.log_retrieval("q", [{"id": "m2"}], user_feedback="not_helpful")

    rows = {
        r["id"]: r["user_feedback"]
        for r in tmp_db.get_connection()
        .execute("SELECT id, user_feedback FROM memory_recall_log")
        .fetchall()
    }
    assert rows[up_id] == "up"
    assert rows[down_id] == "down"


def test_get_online_metrics_aggregates_from_db(tmp_db):
    ev = RecallEvaluator(db=tmp_db)
    a_id = ev.log_retrieval(
        "q1", [{"id": "m1"}], variant="A", weights=[0.2, 0.8]
    )
    ev.log_retrieval("q2", [{"id": "m2"}], variant="B", weights=[0.5, 0.5])
    recall_log_store.set_feedback(tmp_db, a_id, "up")

    metrics = ev.get_online_metrics()

    assert metrics["total_queries"] == 2
    assert metrics["positive_feedback"] == 1
    assert metrics["negative_feedback"] == 0
    assert metrics["feedback_count"] == 1
    assert set(metrics["by_variant"]) == {"A", "B"}


def test_get_online_metrics_without_db_keeps_legacy_semantics():
    """无库时口径不变：satisfaction_rate = 正反馈 / 全部召回。"""
    ev = RecallEvaluator()
    for feedback in ["clicked", "ignored", "helpful", "ignored"]:
        ev.log_retrieval("q", [{"id": "a"}], user_feedback=feedback)

    assert ev.get_online_metrics()["satisfaction_rate"] == 0.5


# ---------- 路由 ----------


def test_recall_metrics_route(tmp_db, monkeypatch):
    monkeypatch.setattr(legacy_routes, "get_database", lambda: tmp_db)
    log_id = recall_log_store.record_recall(
        tmp_db, query="q", variant="A", weights=[0.2, 0.8], result_count=5
    )
    recall_log_store.set_feedback(tmp_db, log_id, "up")

    result = legacy_routes.get_recall_metrics(limit=10)

    assert result["metrics"]["total_recalls"] == 1
    assert result["metrics"]["positive_count"] == 1
    assert result["metrics"]["by_variant"]["A"]["total"] == 1
    assert len(result["recent"]) == 1
    assert result["recent"][0]["id"] == log_id


def test_recall_feedback_route_updates_row(tmp_db, monkeypatch):
    monkeypatch.setattr(legacy_routes, "get_database", lambda: tmp_db)
    log_id = recall_log_store.record_recall(tmp_db, query="q", variant="A")

    result = legacy_routes.submit_recall_feedback(
        legacy_routes.RecallFeedbackRequest(log_id=log_id, feedback="up")
    )

    assert result["status"] == "ok"
    row = tmp_db.get_connection().execute(
        "SELECT user_feedback FROM memory_recall_log WHERE id=?", (log_id,)
    ).fetchone()
    assert row["user_feedback"] == "up"


def test_recall_feedback_route_404_for_unknown_id(tmp_db, monkeypatch):
    monkeypatch.setattr(legacy_routes, "get_database", lambda: tmp_db)

    with pytest.raises(legacy_routes.HTTPException) as exc:
        legacy_routes.submit_recall_feedback(
            legacy_routes.RecallFeedbackRequest(log_id="nope", feedback="down")
        )

    assert exc.value.status_code == 404


def test_recall_feedback_route_rejects_bad_value(tmp_db, monkeypatch):
    """feedback 只能是 up / down —— 非法值在 pydantic 层就被拒。"""
    monkeypatch.setattr(legacy_routes, "get_database", lambda: tmp_db)

    with pytest.raises(ValidationError):
        legacy_routes.RecallFeedbackRequest(log_id="x", feedback="sideways")
