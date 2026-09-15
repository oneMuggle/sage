"""SkillAuditLog 单元测试（Round 3）"""

from __future__ import annotations

import tempfile

import pytest

from backend.data.database import Database
from backend.skills.audit import SkillAuditLog, get_skill_audit_log, reset_skill_audit_log

pytestmark = pytest.mark.unit


@pytest.fixture()
def tmp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = Database(f.name)
        db.init_db()
        yield db
        db.close()


@pytest.fixture()
def audit(tmp_db):
    return SkillAuditLog(db=tmp_db)


class TestRecord:
    def test_create_and_list(self, audit):
        assert audit.record("deploy", "create", actor="user", after_content="v1") is True
        entries = audit.list_entries("deploy")
        assert len(entries) == 1
        assert entries[0]["action"] == "create"
        assert entries[0]["actor"] == "user"

    def test_unknown_action_rejected(self, audit):
        assert audit.record("deploy", "delete") is False
        assert audit.list_entries() == []

    def test_append_only_ordering(self, audit):
        audit.record("deploy", "create")
        audit.record("deploy", "update", before_content="v1", after_content="v2")
        audit.record("deploy", "archive")
        entries = audit.list_entries("deploy")
        assert [e["action"] for e in entries] == ["archive", "update", "create"]

    def test_global_list_no_filter(self, audit):
        audit.record("a", "create")
        audit.record("b", "create")
        assert len(audit.list_entries()) == 2


class TestRollbackSnapshot:
    def test_latest_before_snapshot(self, audit):
        audit.record("deploy", "create", after_content="v1")
        audit.record("deploy", "update", before_content="v1", after_content="v2")
        audit.record("deploy", "update", before_content="v2", after_content="v3")
        assert audit.latest_before_snapshot("deploy") == "v2"

    def test_no_snapshot_returns_none(self, audit):
        audit.record("deploy", "create")
        assert audit.latest_before_snapshot("deploy") is None
        assert audit.latest_before_snapshot("missing") is None


class TestSingleton:
    def test_reset(self, tmp_db):
        reset_skill_audit_log()
        log1 = get_skill_audit_log()
        reset_skill_audit_log()
        log2 = get_skill_audit_log()
        assert log1 is not log2
