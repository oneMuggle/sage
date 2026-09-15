"""A4 复核透出 — _stamp_review_verdict unit tests.

run_review 的 verdict 写回各子 lane + review lane 自身 metadata，
交付抽屉经 listLanes 直接展示（review.submitted 事件只落 review lane）。
"""

from __future__ import annotations

import asyncio
import sys

from backend.orchestration.chat_dispatcher import ChatDispatcher, ChatTaskState
from backend.orchestration.models import Lane


def _init_tmp_db(tmp_path, monkeypatch):
    from backend.data import database as db_mod

    monkeypatch.setenv("SAGE_DB_PATH", str(tmp_path / "rv.db"))
    monkeypatch.setattr(db_mod, "_db", None)
    db_mod.get_database().init_db()


def _dispatcher(run_id="orch-rv"):
    if sys.version_info < (3, 10):  # noqa: UP036 — win7 运行时是 py3.8
        # py3.8/3.9: asyncio.Queue() 构造期绑定 get_event_loop()；pytest-asyncio
        # 结束上一个用例后 set_event_loop(None)，同步用例里需先备好 loop。
        asyncio.set_event_loop(asyncio.new_event_loop())
    return ChatDispatcher(
        stream_id="s1", entry_queue=asyncio.Queue(), run_id=run_id
    )


def _seed_lane(d, lane_id):
    task = d.task_registry.create_task(
        name=lane_id, description="d", task_type="general"
    )
    d.lane_registry.create_lane(Lane(lane_id=lane_id, task_id=task.task_id))


def _states(*task_ids):
    return [
        ChatTaskState(task_id=t, agent_id="coder", goal="g") for t in task_ids
    ]


class TestStampReviewVerdict:
    def test_stamps_subtask_lanes_and_review_lane(self, tmp_path, monkeypatch):
        _init_tmp_db(tmp_path, monkeypatch)
        d = _dispatcher()
        for lid in ("lane-t1", "lane-t2", "lane-review-orch-rv"):
            _seed_lane(d, lid)

        d._stamp_review_verdict(_states("t1", "t2"), "pass", 3)

        for lid in ("lane-t1", "lane-t2", "lane-review-orch-rv"):
            lane = d.lane_registry.get_lane(lid)
            assert lane.metadata["review_verdict"] == "pass"
            assert lane.metadata["review_assertion_count"] == 3

    def test_missing_lane_skipped_silently(self, tmp_path, monkeypatch):
        _init_tmp_db(tmp_path, monkeypatch)
        d = _dispatcher()
        _seed_lane(d, "lane-t1")

        d._stamp_review_verdict(_states("t1", "t9"), "fail", 1)

        lane = d.lane_registry.get_lane("lane-t1")
        assert lane.metadata["review_verdict"] == "fail"
        assert lane.metadata["review_assertion_count"] == 1
        assert d.lane_registry.get_lane("lane-t9") is None

    def test_registry_failure_isolated(self, tmp_path, monkeypatch):
        _init_tmp_db(tmp_path, monkeypatch)
        d = _dispatcher()
        _seed_lane(d, "lane-t1")

        def boom(lane_id):
            raise RuntimeError("db down")

        monkeypatch.setattr(d.lane_registry, "get_lane", boom)
        d._stamp_review_verdict(_states("t1"), "pass", 2)  # 不抛错
