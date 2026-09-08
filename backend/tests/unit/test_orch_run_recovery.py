"""OrchRunRepository.fail_stale_running_runs（O6）单测。

- 滞留 running 的 orch-% 行 → failed + 默认 final_summary
- 非 running 行、非 orch- 前缀行、已有 final_summary 的行不动
"""

from __future__ import annotations

import pytest

from backend.data import database as db_mod
from backend.data.orch_run_repo import OrchRun, OrchRunRepository


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """tmp DB + SAGE_DB_PATH env + 重置全局 _db 单例。"""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("SAGE_DB_PATH", str(db_path))
    monkeypatch.setattr(db_mod, "_db", None)
    db = db_mod.get_database()
    db.init_db()
    return OrchRunRepository()


def _seed(run_id: str, status: str, final_summary=None):
    repo = OrchRunRepository()
    repo.upsert(OrchRun(
        run_id=run_id,
        session_id="s-1",
        status=status,
        created_at=1700000000000,
        plan_json="{}",
        final_summary=final_summary,
    ))


def test_stale_running_orch_runs_fail_closed(repo):
    _seed("orch-aaa", "running")
    _seed("orch-bbb", "running")
    count = repo.fail_stale_running_runs()
    assert count == 2
    for run_id in ("orch-aaa", "orch-bbb"):
        run = repo.get(run_id)
        assert run.status == "failed"
        assert run.final_summary == "应用重启，编排运行中断"


def test_terminal_and_non_orch_rows_untouched(repo):
    _seed("orch-done", "completed", final_summary="ok")
    _seed("orch-cancelled", "cancelled")
    _seed("agent-synth", "running")  # 单委派合成前缀，不收口
    count = repo.fail_stale_running_runs()
    assert count == 0
    assert repo.get("orch-done").status == "completed"
    assert repo.get("orch-done").final_summary == "ok"
    assert repo.get("orch-cancelled").status == "cancelled"
    assert repo.get("agent-synth").status == "running"


def test_existing_final_summary_preserved(repo):
    _seed("orch-keep", "running", final_summary="自定义摘要")
    count = repo.fail_stale_running_runs()
    assert count == 1
    run = repo.get("orch-keep")
    assert run.status == "failed"
    assert run.final_summary == "自定义摘要"


def test_empty_db_returns_zero(repo):
    assert repo.fail_stale_running_runs() == 0
