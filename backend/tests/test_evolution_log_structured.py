"""P0-1：结构化进化日志的可观测性保障。

覆盖：
* ``elapsed_ms`` 的单调时钟语义（非负整数）
* ``_serialize_metrics`` 的健壮性（None / 空 / 超长 / 不可序列化）
* ``record_evolution_log`` 的写入成功路径（duration_ms + metrics_json 落库）
* best-effort 语义（写失败只返回 None，不抛异常）
* ``get_evolution_logs`` 路由返回新字段（pydantic 不会静默丢列）
"""

from __future__ import annotations

import json
import time

import pytest

from backend.data.database import Database
from backend.scheduler import get_evolution_logs
from backend.scheduler.evolution_log import (
    _MAX_METRICS_CHARS,
    _serialize_metrics,
    elapsed_ms,
    record_evolution_log,
)


@pytest.fixture()
def db(tmp_path):
    database = Database(str(tmp_path / "evo.db"))
    database.init_db()
    yield database
    database.close()


# ---------- elapsed_ms ----------


def test_elapsed_ms_returns_non_negative_integer():
    started = time.monotonic()
    time.sleep(0.005)
    result = elapsed_ms(started)

    assert isinstance(result, int)
    assert result >= 0


def test_elapsed_ms_reflects_elapsed_time_within_tolerance():
    started = time.monotonic()
    time.sleep(0.05)
    result = elapsed_ms(started)

    # 50ms sleep → 期望 40..200ms（容忍 CI 抖动）
    assert 40 <= result <= 200


# ---------- _serialize_metrics ----------


def test_serialize_metrics_none_returns_none():
    assert _serialize_metrics(None) is None


def test_serialize_metrics_empty_dict_returns_none():
    assert _serialize_metrics({}) is None


def test_serialize_metrics_non_dict_returns_none():
    # 非 dict 一律视为无效，不抛异常
    assert _serialize_metrics([1, 2, 3]) is None  # type: ignore[arg-type]
    assert _serialize_metrics("not a dict") is None  # type: ignore[arg-type]


def test_serialize_metrics_roundtrip():
    metrics = {"scanned": 42, "merged": 3, "label": "每日摘要"}
    text = _serialize_metrics(metrics)

    assert text is not None
    parsed = json.loads(text)
    assert parsed == metrics


def test_serialize_metrics_truncates_oversized():
    # 生成一个超 _MAX_METRICS_CHARS 的 dict（每个 key 必须唯一，否则 dict 会折叠）
    big = {f"key_{i:04d}": "v" * 100 for i in range(200)}
    text = _serialize_metrics(big)

    assert text is not None
    assert len(text) <= _MAX_METRICS_CHARS + 100  # 截断标记约 14 字符
    assert "truncated" in text


def test_serialize_metrics_handles_unserializable():
    # default=str 兜底；至少不应抛异常
    class Weird:
        def __str__(self):
            return "<weird>"

    result = _serialize_metrics({"weird": Weird()})
    assert result is None or isinstance(result, str)


# ---------- record_evolution_log ----------


def test_record_evolution_log_writes_duration_and_metrics(db):
    log_id = record_evolution_log(
        db,
        evolution_type="daily_summary",
        description="测试日志",
        status="success",
        duration_ms=1234,
        metrics={"sessions": 5, "summarized": 3},
    )

    assert log_id is not None

    conn = db.get_connection()
    row = conn.execute(
        "SELECT evolution_type, description, status, duration_ms, metrics_json "
        "FROM evolution_log WHERE id=?",
        (log_id,),
    ).fetchone()

    assert row["evolution_type"] == "daily_summary"
    assert row["description"] == "测试日志"
    assert row["status"] == "success"
    assert row["duration_ms"] == 1234
    assert row["metrics_json"] is not None
    parsed = json.loads(row["metrics_json"])
    assert parsed == {"sessions": 5, "summarized": 3}


def test_record_evolution_log_supports_all_status_values(db):
    for status in ("success", "failed", "skipped"):
        log_id = record_evolution_log(
            db,
            evolution_type="test_status",
            description=f"status={status}",
            status=status,
            duration_ms=10,
        )
        assert log_id is not None

    conn = db.get_connection()
    rows = conn.execute(
        "SELECT status FROM evolution_log WHERE evolution_type='test_status' "
        "ORDER BY created_at"
    ).fetchall()
    assert [r["status"] for r in rows] == ["success", "failed", "skipped"]


def test_record_evolution_log_success_sets_completed_at(db):
    log_id = record_evolution_log(
        db,
        evolution_type="test",
        description="ok",
        status="success",
        duration_ms=5,
    )

    row = db.get_connection().execute(
        "SELECT completed_at FROM evolution_log WHERE id=?", (log_id,)
    ).fetchone()
    assert row["completed_at"] is not None


def test_record_evolution_log_failed_leaves_completed_at_null(db):
    log_id = record_evolution_log(
        db,
        evolution_type="test",
        description="boom",
        status="failed",
        error_message="some error",
        duration_ms=5,
    )

    row = db.get_connection().execute(
        "SELECT completed_at, error_message FROM evolution_log WHERE id=?",
        (log_id,),
    ).fetchone()
    assert row["completed_at"] is None
    assert row["error_message"] == "some error"


def test_record_evolution_log_omits_metrics_when_none(db):
    log_id = record_evolution_log(
        db,
        evolution_type="test",
        description="no metrics",
        duration_ms=7,
    )

    row = db.get_connection().execute(
        "SELECT metrics_json, duration_ms FROM evolution_log WHERE id=?", (log_id,)
    ).fetchone()
    assert row["metrics_json"] is None
    assert row["duration_ms"] == 7


def test_record_evolution_log_is_best_effort():
    """写入失败只返回 None，不抛异常 —— 日志失败不能拖垮进化任务。"""

    class BrokenDB:
        def get_connection(self):
            raise RuntimeError("db exploded")

    result = record_evolution_log(
        BrokenDB(),  # type: ignore[arg-type]
        evolution_type="test",
        description="will fail",
        duration_ms=1,
    )
    assert result is None


# ---------- get_evolution_logs 路由返回新字段 ----------


def test_get_evolution_logs_returns_duration_and_metrics(db):
    record_evolution_log(
        db,
        evolution_type="memory_pruning",
        description="pruned 5",
        status="success",
        duration_ms=42,
        metrics={"pruned": 5, "kept": 100},
    )

    logs = get_evolution_logs(db, limit=10, offset=0)

    assert len(logs) >= 1
    target = next(log for log in logs if log["evolution_type"] == "memory_pruning")
    assert target["duration_ms"] == 42
    assert target["metrics_json"] is not None
    parsed = json.loads(target["metrics_json"])
    assert parsed == {"pruned": 5, "kept": 100}


def test_get_evolution_logs_legacy_fields_still_present(db):
    """新字段是 additive 的；旧字段必须仍然返回（不能破坏现有前端）。"""
    record_evolution_log(
        db,
        evolution_type="daily_summary",
        description="legacy check",
        status="success",
        duration_ms=1,
    )

    logs = get_evolution_logs(db, limit=10, offset=0)

    assert len(logs) >= 1
    row = logs[0]
    for key in (
        "id",
        "evolution_type",
        "description",
        "status",
        "trigger_type",
        "created_at",
    ):
        assert key in row, f"legacy field {key!r} missing from evolution_log row"
