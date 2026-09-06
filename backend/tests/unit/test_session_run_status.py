# backend/tests/unit/test_session_run_status.py
# S1 (2026-09-06): 会话运行态落库 —— update_run_status / recover_stale_run_states
# 与 Session 序列化的单元测试。
import time

import pytest

from backend.data.session_repo import SessionRepository


@pytest.fixture()
def repo(setup_test_db):
    return SessionRepository()


def _create_session(repo, title="s"):
    return repo.create(title=title)


def test_new_session_defaults_to_idle(repo):
    sess = _create_session(repo)
    assert sess.run_status == "idle"
    assert sess.last_error is None
    assert sess.last_run_at is None
    d = repo.get(sess.id).to_dict()
    assert d["run_status"] == "idle"
    assert d["last_error"] is None
    assert d["last_run_at"] is None


def test_update_run_status_running_then_completed(repo):
    sess = _create_session(repo)
    assert repo.update_run_status(sess.id, "running") is True
    row = repo.get(sess.id)
    assert row.run_status == "running"
    assert row.last_error is None
    assert row.last_run_at is not None

    assert repo.update_run_status(sess.id, "completed") is True
    row = repo.get(sess.id)
    assert row.run_status == "completed"
    assert row.last_error is None


def test_update_run_status_failed_sets_error_and_truncates(repo):
    sess = _create_session(repo)
    long_error = "x" * 2000
    repo.update_run_status(sess.id, "failed", error=long_error)
    row = repo.get(sess.id)
    assert row.run_status == "failed"
    assert row.last_error is not None
    assert len(row.last_error) == 500


def test_update_run_status_does_not_bump_updated_at(repo):
    # 运行态变化不应重排侧栏（list 按 updated_at DESC）—— update_run_status
    # 必须绕开通用 update() 的 updated_at 刷新。
    sess = _create_session(repo)
    before = repo.get(sess.id).updated_at
    time.sleep(0.01)
    repo.update_run_status(sess.id, "running")
    after = repo.get(sess.id).updated_at
    assert before == after


def test_update_run_status_missing_session_returns_false(repo):
    # /btw 伪会话 __btw__ 在 sessions 表无行 —— 静默 False,不抛异常
    assert repo.update_run_status("__btw__", "running") is False


def test_recover_stale_run_states_only_touches_running(repo):
    ids = {s: _create_session(repo).id for s in ("running", "done", "susp", "idle")}
    repo.update_run_status(ids["running"], "running")
    repo.update_run_status(ids["done"], "completed")
    repo.update_run_status(ids["susp"], "suspended")

    recovered = repo.recover_stale_run_states()
    assert recovered == 1
    assert repo.get(ids["running"]).run_status == "failed"
    assert "重启" in repo.get(ids["running"]).last_error
    # 终态/挂起不受影响
    assert repo.get(ids["done"]).run_status == "completed"
    assert repo.get(ids["susp"]).run_status == "suspended"
    assert repo.get(ids["idle"]).run_status == "idle"


def test_recover_stale_run_states_noop_when_clean(repo):
    _create_session(repo)
    assert repo.recover_stale_run_states() == 0
