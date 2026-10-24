"""``OrchRunMetrics`` 单元测试（P119 Config Advisor Phase 2.1）。

覆盖：
- ``_classify_failure`` 启发式归类（5 种错误样本）
- ``OrchRunMetrics.aggregate_recent()`` 在 4 种 fixture 下返回正确结构：
  空库 / 混合状态 / 无 tasks / DB 不可用
- 辅助函数 ``_percentile`` / ``_ms_to_iso`` 边界情况
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.data import orch_run_repo, orch_task_repo
from backend.data.database import Database
from backend.data.orch_run_metrics import (
    OrchRunMetrics,
    _classify_failure,
    _ms_to_iso,
    _percentile,
)


# ---- helpers ----


@pytest.fixture()
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Database:
    """Provide an isolated SQLite database bound to get_database()."""
    db_file = tmp_path / "test_orch_run_metrics.db"
    db = Database(db_path=str(db_file))
    db.init_db()
    for mod in (orch_run_repo, orch_task_repo):
        monkeypatch.setattr(mod, "get_database", lambda: db)
    # orch_run_metrics 也通过 get_database 拿连接，需要 patch
    import backend.data.orch_run_metrics as metrics_mod

    monkeypatch.setattr(metrics_mod, "get_database", lambda: db)
    return db


def _seed_run(db, run_id, status, created_at, final_summary=None, dispatched_at=None):
    """Seed one orch_run row."""
    from backend.data.orch_run_repo import OrchRun, OrchRunRepository

    repo = OrchRunRepository()
    run = OrchRun(
        run_id=run_id,
        session_id=f"sess-{run_id}",
        status="running",
        created_at=created_at,
        plan_json='{"tasks": []}',
        final_summary=final_summary,
        dispatched_at=dispatched_at,
        original_request="seed test",
    )
    repo.upsert(run)
    if status != "running":
        repo.finalize(run_id, status, final_summary)


def _seed_task(db, task_id, run_id, status="done", retry_count=0, error=None,
               used_tokens=None, duration_ms=None):
    """Seed one orch_task row."""
    from backend.data.orch_task_repo import OrchTaskRepository

    repo = OrchTaskRepository()
    repo.upsert_state(
        task_id=task_id,
        run_id=run_id,
        agent_id="coder",
        goal=f"goal for {task_id}",
        status=status,
        retry_count=retry_count,
        error=error,
        used_tokens=used_tokens,
        duration_ms=duration_ms,
    )


# ---- _classify_failure ----


def test_classify_failure_max_iterations():
    assert _classify_failure("max_iterations_exceeded: 25 steps") == "max_iterations_exceeded"
    assert _classify_failure("iteration limit reached") == "max_iterations_exceeded"
    assert _classify_failure("iteration count exceeded budget") == "max_iterations_exceeded"


def test_classify_failure_timeout():
    assert _classify_failure("request timed out after 30s") == "timeout"
    assert _classify_failure("OperationTimeout: 60s") == "timeout"


def test_classify_failure_rate_limit():
    assert _classify_failure("rate_limit exceeded for provider") == "rate_limit"
    assert _classify_failure("HTTP 429: rate limit") == "rate_limit"


def test_classify_failure_context_window():
    assert _classify_failure("context window exceeded: 128k tokens") == "context_window"
    assert _classify_failure("max context length 8192 tokens") == "context_window"


def test_classify_failure_cancelled():
    assert _classify_failure("run cancelled by user") == "cancelled"


def test_classify_failure_other():
    assert _classify_failure("connection refused") == "other"
    assert _classify_failure(None) == "other"
    assert _classify_failure("") == "other"


# ---- _percentile / _ms_to_iso helpers ----


def test_percentile_empty_and_single():
    assert _percentile([], 50) == 0
    assert _percentile([42], 95) == 42


def test_percentile_interpolation():
    # 10 个值：10, 20, ..., 100
    values = list(range(10, 110, 10))
    # p50 → rank = 0.5 * 9 = 4.5 → between values[4]=50 and values[5]=60 → 55
    assert _percentile(values, 50) == 55
    # p0 → 10, p100 → 100
    assert _percentile(values, 0) == 10
    assert _percentile(values, 100) == 100


def test_ms_to_iso_round_trip():
    # 2026-10-24T00:00:00 UTC ≈ 1792886400000 ms (exact doesn't matter)
    result = _ms_to_iso(1_700_000_000_000)
    assert result is not None
    assert "2023-11-14" in result  # sanity check year
    assert _ms_to_iso(None) is None
    # Invalid epoch → None (not crash)
    assert _ms_to_iso(-1_000_000_000_000_000_000) is None


# ---- aggregate_recent ----


def test_aggregate_recent_empty_db(isolated_db):
    metrics = OrchRunMetrics.aggregate_recent(limit=20)
    assert metrics["window"]["run_count"] == 0
    assert metrics["completion"] == {"success": 0, "failed": 0, "cancelled": 0, "other": 0}
    assert metrics["failure_kind"] == {}
    assert metrics["tokens"]["total"] == 0
    assert metrics["latency_ms"]["mean"] == 0
    assert metrics["retries"]["mean_per_task"] == 0.0


def test_aggregate_recent_full_shape(isolated_db):
    """混合 fixture: 4 runs (2 completed, 1 failed max_iterations, 1 cancelled)
    + 5 tasks 覆盖 retry/token/latency 统计。"""
    _seed_run(isolated_db, "r1", "completed", created_at=1_700_000_000_000,
              dispatched_at=1_700_000_000_000, final_summary="done ok")
    _seed_run(isolated_db, "r2", "completed", created_at=1_700_000_100_000,
              dispatched_at=1_700_000_100_000, final_summary="done")
    _seed_run(isolated_db, "r3", "failed", created_at=1_700_000_200_000,
              dispatched_at=1_700_000_200_000,
              final_summary="max_iterations_exceeded: 25 steps")
    _seed_run(isolated_db, "r4", "cancelled", created_at=1_700_000_300_000,
              dispatched_at=1_700_000_300_000)

    # 5 tasks across runs
    _seed_task(isolated_db, "t1", "r1", used_tokens=1000, duration_ms=500)
    _seed_task(isolated_db, "t2", "r1", used_tokens=2000, duration_ms=1000,
               retry_count=2)
    _seed_task(isolated_db, "t3", "r2", used_tokens=1500, duration_ms=800,
               retry_count=1)
    _seed_task(isolated_db, "t4", "r3", used_tokens=500, duration_ms=300,
               retry_count=0)
    _seed_task(isolated_db, "t5", "r4", used_tokens=0, duration_ms=0)

    metrics = OrchRunMetrics.aggregate_recent(limit=20)

    # window
    assert metrics["window"]["run_count"] == 4
    assert metrics["window"]["from"] is not None
    assert metrics["window"]["to"] is not None

    # completion
    assert metrics["completion"]["success"] == 2
    assert metrics["completion"]["failed"] == 1
    assert metrics["completion"]["cancelled"] == 1

    # failure_kind — r3 is the only failed run, final_summary → max_iterations_exceeded
    assert metrics["failure_kind"].get("max_iterations_exceeded") == 1

    # tokens (only non-zero counts)
    # t5 has used_tokens=0 (filtered by `if t["used_tokens"]`)
    assert metrics["tokens"]["total"] == 1000 + 2000 + 1500 + 500
    assert metrics["tokens"]["task_count_with_tokens"] == 4
    assert metrics["tokens"]["mean_per_task"] == (1000 + 2000 + 1500 + 500) // 4

    # latency_ms — t5 has duration_ms=0, filtered; 4 tasks with non-zero duration
    assert metrics["latency_ms"]["mean"] == (500 + 1000 + 800 + 300) // 4
    assert metrics["latency_ms"]["p50"] > 0
    assert metrics["latency_ms"]["p95"] >= metrics["latency_ms"]["p50"]

    # retries: total retry_count=3 across 5 tasks, 2 tasks with retry>0 (t2, t3)
    assert metrics["retries"]["mean_per_task"] == pytest.approx(3 / 5, rel=0.01)
    assert metrics["retries"]["tasks_with_retry_pct"] == pytest.approx(2 / 5 * 100, rel=0.1)


def test_aggregate_recent_no_tasks(isolated_db):
    """Runs 存在但无任何 tasks → tokens/latency/retries 全零。"""
    _seed_run(isolated_db, "r1", "completed", created_at=1_700_000_000_000,
              final_summary="ok")
    metrics = OrchRunMetrics.aggregate_recent(limit=10)
    assert metrics["window"]["run_count"] == 1
    assert metrics["completion"]["success"] == 1
    assert metrics["tokens"]["total"] == 0
    assert metrics["latency_ms"]["mean"] == 0
    assert metrics["retries"]["mean_per_task"] == 0.0
    assert metrics["retries"]["tasks_with_retry_pct"] == 0.0


def test_aggregate_recent_limit_clamps(isolated_db):
    """创建 5 runs，limit=2 只看最新 2 个。"""
    for i in range(5):
        _seed_run(isolated_db, f"r{i}", "completed",
                  created_at=1_700_000_000_000 + i * 1000,
                  dispatched_at=1_700_000_000_000 + i * 1000,
                  final_summary="ok")

    metrics = OrchRunMetrics.aggregate_recent(limit=2)
    assert metrics["window"]["run_count"] == 2


def test_aggregate_recent_db_unavailable_fails_safe(tmp_path, monkeypatch):
    """get_database() 抛异常时返回空指标，不抛。"""
    import backend.data.orch_run_metrics as metrics_mod

    def _boom():
        raise RuntimeError("db locked")

    monkeypatch.setattr(metrics_mod, "get_database", _boom)
    metrics = OrchRunMetrics.aggregate_recent(limit=20)
    assert metrics["window"]["run_count"] == 0
    assert metrics["completion"]["success"] == 0


def test_aggregate_recent_query_failure_fails_safe(isolated_db, monkeypatch):
    """cursor.execute 失败时返回空指标，不抛。"""
    import backend.data.orch_run_metrics as metrics_mod

    # 先 patch get_database 返回一个会抛错的 mock
    class _FakeCursor:
        def execute(self, *args, **kwargs):
            raise RuntimeError("table not found")

        def fetchall(self):
            return []

    class _FakeConn:
        def cursor(self):
            return _FakeCursor()

    class _FakeDB:
        def get_connection(self):
            return _FakeConn()

    monkeypatch.setattr(metrics_mod, "get_database", lambda: _FakeDB())
    metrics = OrchRunMetrics.aggregate_recent(limit=20)
    # fail-safe 兜底为空指标
    assert metrics["window"]["run_count"] == 0


def test_aggregate_recent_dispatched_at_fallback_to_created_at(isolated_db):
    """dispatched_at=None 时，时间窗口基于 created_at。"""
    _seed_run(isolated_db, "r1", "completed", created_at=1_700_000_000_000)
    _seed_run(isolated_db, "r2", "completed", created_at=1_700_000_500_000)
    metrics = OrchRunMetrics.aggregate_recent(limit=10)
    # 两个 run 都应被统计
    assert metrics["window"]["run_count"] == 2
    # from 应为 created_at（最早）
    assert metrics["window"]["from"] is not None
    # to 应为 created_at（最晚）
    assert metrics["window"]["to"] is not None
