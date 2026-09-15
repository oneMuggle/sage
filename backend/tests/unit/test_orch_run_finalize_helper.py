"""P0-4 — legacy_routes._finalize_orch_run helper：闭环 + 降级。"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    from backend.data import database as db_mod

    monkeypatch.setenv("SAGE_DB_PATH", str(tmp_path / "fin.db"))
    monkeypatch.setattr(db_mod, "_db", None)
    db = db_mod.get_database()
    db.init_db()
    return db


def test_finalize_helper_writes_completed(tmp_db):
    from backend.api import legacy_routes as lr
    from backend.data.orch_run_repo import OrchRun, OrchRunRepository

    repo = OrchRunRepository()
    repo.upsert(OrchRun(
        run_id="orch-h", session_id="s", status="running",
        created_at=1, plan_json="{}",
    ))
    lr._finalize_orch_run("orch-h", "completed", "all done")
    fetched = repo.get("orch-h")
    assert fetched.status == "completed"
    assert fetched.final_summary == "all done"


def test_finalize_helper_skips_none_run_id(tmp_db):
    """single 模式 run_id=None → 直接跳过，不碰 DB。"""
    from backend.api import legacy_routes as lr

    lr._finalize_orch_run(None, "completed", "x")  # 无异常即通过


def test_finalize_helper_degrades_on_db_error(tmp_db, monkeypatch):
    """DB 异常只 warning，不向 producer finally 冒泡。"""
    import backend.data.orch_run_repo as repo_mod
    from backend.api import legacy_routes as lr

    def _boom(*args, **kwargs):
        raise RuntimeError("db gone")

    monkeypatch.setattr(repo_mod.OrchRunRepository, "finalize", _boom)
    lr._finalize_orch_run("orch-x", "failed", None)  # 不抛异常
