"""Phase 6 Hook 执行历史仓储测试。"""

from __future__ import annotations

import pytest

from backend.data.database import Database
from backend.hooks.history import (
    HookHistoryRepository,
    make_record,
)

pytestmark = pytest.mark.unit


@pytest.fixture()
def db(tmp_path):
    db_path = tmp_path / "test.db"
    database = Database(str(db_path))
    database.init_db()
    yield database
    database.close()


@pytest.fixture()
def repo(db):
    return HookHistoryRepository(db)


def test_make_record_defaults():
    record = make_record(
        hook_type="python",
        event="pre_tool_use",
        tool_name="bash",
        builtin_id="security_guard",
        decision="deny",
        duration_ms=2.5,
        reason="blocked dangerous command",
    )
    assert record.hook_id == "security_guard"
    assert record.hook_type == "python"
    assert record.event == "pre_tool_use"
    assert record.tool_name == "bash"
    assert record.decision == "deny"
    assert record.duration_ms == 2.5
    assert record.reason == "blocked dangerous command"
    assert record.occurred_at  # ISO timestamp set
    assert record.id  # UUID set


def test_make_record_hook_id_priority():
    """builtin_id > url > handler > command 截断。"""
    rec = make_record(
        hook_type="python",
        event="pre_tool_use",
        tool_name="bash",
        builtin_id="sec",
        handler="some.handler",
        command="echo hi",
        decision="allow",
        duration_ms=0,
    )
    assert rec.hook_id == "sec"

    rec = make_record(
        hook_type="http",
        event="pre_tool_use",
        tool_name="bash",
        url="https://x.test/hook",
        command="ignored",
        decision="allow",
        duration_ms=0,
    )
    assert rec.hook_id == "https://x.test/hook"

    rec = make_record(
        hook_type="shell",
        event="pre_tool_use",
        tool_name="bash",
        command="ruff check .",
        decision="allow",
        duration_ms=0,
    )
    assert rec.hook_id == "ruff check ."


def test_save_and_list(repo):
    rec = make_record(
        hook_type="python",
        event="pre_tool_use",
        tool_name="bash",
        builtin_id="security_guard",
        decision="deny",
        duration_ms=1.2,
        reason="blocked",
    )
    repo.save(rec)

    records = repo.list_records(limit=10)
    assert len(records) == 1
    assert records[0].id == rec.id
    assert records[0].decision == "deny"
    assert records[0].duration_ms == 1.2


def test_list_filter_by_hook_id(repo):
    repo.save(make_record(
        hook_type="python", event="pre_tool_use", tool_name="bash",
        builtin_id="sec", decision="deny", duration_ms=0,
    ))
    repo.save(make_record(
        hook_type="python", event="post_tool_use", tool_name="bash",
        builtin_id="audit", decision="allow", duration_ms=0,
    ))

    filtered = repo.list_records(hook_id="sec")
    assert len(filtered) == 1
    assert filtered[0].hook_id == "sec"


def test_list_filter_by_event(repo):
    repo.save(make_record(
        hook_type="python", event="pre_tool_use", tool_name="bash",
        builtin_id="sec", decision="deny", duration_ms=0,
    ))
    repo.save(make_record(
        hook_type="python", event="post_tool_use", tool_name="bash",
        builtin_id="sec", decision="allow", duration_ms=0,
    ))

    filtered = repo.list_records(event="pre_tool_use")
    assert len(filtered) == 1
    assert filtered[0].event == "pre_tool_use"


def test_list_limit(repo):
    for i in range(5):
        repo.save(make_record(
            hook_type="python", event="pre_tool_use", tool_name="bash",
            builtin_id=f"h{i}", decision="allow", duration_ms=0,
        ))

    records = repo.list_records(limit=3)
    assert len(records) == 3


def test_list_since(repo):
    rec1 = make_record(
        hook_type="python", event="pre_tool_use", tool_name="bash",
        builtin_id="old", decision="allow", duration_ms=0,
    )
    rec1.occurred_at = "2020-01-01T00:00:00+00:00"
    repo.save(rec1)

    rec2 = make_record(
        hook_type="python", event="pre_tool_use", tool_name="bash",
        builtin_id="new", decision="allow", duration_ms=0,
    )
    repo.save(rec2)

    filtered = repo.list_records(since="2024-01-01T00:00:00+00:00")
    assert len(filtered) == 1
    assert filtered[0].hook_id == "new"


def test_clear(repo):
    repo.save(make_record(
        hook_type="python", event="pre_tool_use", tool_name="bash",
        builtin_id="sec", decision="deny", duration_ms=0,
    ))
    repo.save(make_record(
        hook_type="python", event="post_tool_use", tool_name="bash",
        builtin_id="audit", decision="allow", duration_ms=0,
    ))

    deleted = repo.clear()
    assert deleted == 2
    assert len(repo.list_records()) == 0


def test_prune_by_age(repo):
    """超过 7 天的记录被清理。"""
    old = make_record(
        hook_type="python", event="pre_tool_use", tool_name="bash",
        builtin_id="old", decision="allow", duration_ms=0,
    )
    old.occurred_at = "2020-01-01T00:00:00+00:00"
    repo.save(old)

    new = make_record(
        hook_type="python", event="pre_tool_use", tool_name="bash",
        builtin_id="new", decision="allow", duration_ms=0,
    )
    repo.save(new)

    repo._prune()
    records = repo.list_records()
    assert len(records) == 1
    assert records[0].hook_id == "new"


def test_prune_by_count(repo):
    """超过 1000 条时清理旧记录。"""
    for i in range(1050):
        repo.save(make_record(
            hook_type="python", event="pre_tool_use", tool_name="bash",
            builtin_id=f"h{i}", decision="allow", duration_ms=0,
        ))

    repo._prune()
    records = repo.list_records(limit=2000)
    assert len(records) <= 1000


def test_schema_idempotent(db):
    """多次构造仓储不报错 (CREATE TABLE IF NOT EXISTS)。"""
    repo1 = HookHistoryRepository(db)
    repo2 = HookHistoryRepository(db)
    rec = make_record(
        hook_type="python", event="pre_tool_use", tool_name="bash",
        builtin_id="sec", decision="deny", duration_ms=0,
    )
    repo1.save(rec)
    assert len(repo2.list_records()) == 1


def test_record_reason_truncation():
    """reason 超长截断到 512 字符。"""
    long_reason = "x" * 1000
    rec = make_record(
        hook_type="python", event="pre_tool_use", tool_name="bash",
        builtin_id="sec", decision="deny", duration_ms=0,
        reason=long_reason,
    )
    assert len(rec.reason) == 512


def test_record_stdout_snippet_truncation():
    """stdout/stderr snippet 超长截断到 1KB。"""
    long_output = "y" * 5000
    rec = make_record(
        hook_type="shell", event="pre_tool_use", tool_name="bash",
        command="echo hi", decision="allow", duration_ms=0,
        stdout_snippet=long_output,
    )
    assert len(rec.stdout_snippet) == 1024
