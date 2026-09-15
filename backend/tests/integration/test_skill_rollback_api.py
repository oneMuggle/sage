"""技能回滚 API 集成测试（Round 3: 审批 → 更新 → 回滚闭环）"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.legacy_routes import router

pytestmark = pytest.mark.integration


@pytest.fixture()
def client():
    """Bare app + legacy router（与 test_approval_api 同模式）"""
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, headers={"Authorization": "Bearer test-local-auth-token"})


def _patch_plain_fs_loader(monkeypatch, root):
    """把 SkillLoader 的读写换成朴素文件实现。

    safe_writer 在 Windows 上 fail-closed 拒写（安全设计，本地无法走
    真实写盘路径）；本替身只验证回滚 API 的流程语义，写入安全属性
    由 safe_writer 自身的测试覆盖。
    """
    from pathlib import Path

    from backend.skills import loader as loader_mod

    base = Path(root)

    def plain_write(self, name: str, content: str, *, overwrite: bool = True):
        d = base / name
        f = d / "SKILL.md"
        if f.exists() and not overwrite:
            raise FileExistsError(name)
        d.mkdir(parents=True, exist_ok=True)
        f.write_text(content, encoding="utf-8")
        return f

    def plain_read(self, name: str):
        f = base / name / "SKILL.md"
        if not f.is_file():
            return None
        return f.read_text(encoding="utf-8")

    monkeypatch.setattr(loader_mod.SkillLoader, "write", plain_write)
    monkeypatch.setattr(loader_mod.SkillLoader, "read", plain_read)


class TestSkillRollbackFlow:
    def test_approve_audit_and_rollback(self, client, monkeypatch, tmp_path):
        """更新 → 台账有 before 快照 → 回滚恢复上一版内容"""
        from backend.skills.loader import reset_skill_loader

        _patch_plain_fs_loader(monkeypatch, tmp_path / "skills")
        reset_skill_loader()

        from backend.skills.audit import get_skill_audit_log
        from backend.skills.loader import get_skill_loader

        loader = get_skill_loader()
        content_v1 = (
            "---\nname: roll-skill\ndescription: v1\n"
            "when_to_use: 当用户明确要求执行该技能的完整流程时使用该技能\n---\n# v1"
        )
        # 先手写一份 v1（模拟"已存在的旧版本"），再审批同名新版本会 409，
        # 所以直接走：v1 落盘 → 造 update 台账 → 回滚
        loader.write("roll-skill", content_v1, overwrite=True)

        audit_log = get_skill_audit_log()
        content_v2 = (
            "---\nname: roll-skill\ndescription: v2\n"
            "when_to_use: 当用户明确要求执行该技能的完整流程时使用该技能\n---\n# v2"
        )
        loader.write("roll-skill", content_v2, overwrite=True)
        audit_log.record(
            "roll-skill",
            "update",
            actor="system",
            before_content=content_v1,
            after_content=content_v2,
        )

        # 台账可查
        resp = client.get("/skills/roll-skill/audit")
        assert resp.status_code == 200
        entries = resp.json()["entries"]
        assert entries[0]["action"] == "update"

        # 回滚 → 文件内容回到 v1
        resp = client.post("/skills/roll-skill/rollback")
        assert resp.status_code == 200, resp.text
        assert loader.read("roll-skill") == content_v1

        # 回滚动作本身也进了台账
        entries = client.get("/skills/roll-skill/audit").json()["entries"]
        assert entries[0]["action"] == "rollback"

    def test_rollback_without_snapshot_conflict(self, client, monkeypatch, tmp_path):
        """无可回滚快照 → 409"""
        from backend.skills.loader import get_skill_loader, reset_skill_loader

        _patch_plain_fs_loader(monkeypatch, tmp_path / "skills2")
        reset_skill_loader()
        loader = get_skill_loader()
        loader.write(
            "plain-skill",
            "---\nname: plain-skill\ndescription: d\n"
            "when_to_use: 当用户明确要求执行该技能的完整流程时使用该技能\n---\n# v1",
            overwrite=True,
        )
        resp = client.post("/skills/plain-skill/rollback")
        assert resp.status_code == 409

    def test_rollback_missing_skill_404(self, client, monkeypatch, tmp_path):
        monkeypatch.setenv("SAGE_SKILLS_DIR", str(tmp_path / "skills3"))
        from backend.skills.loader import reset_skill_loader

        reset_skill_loader()
        resp = client.post("/skills/never-existed/rollback")
        assert resp.status_code == 404

    def test_lifecycle_archive_recorded(self, client, monkeypatch, tmp_path):
        """归档动作自动进台账（lifecycle 挂钩）"""
        monkeypatch.setenv("SAGE_SKILLS_DIR", str(tmp_path / "skills4"))
        from backend.skills.audit import get_skill_audit_log
        from backend.skills.lifecycle import get_lifecycle_store

        get_lifecycle_store().set_archived("some-skill", True)
        entries = get_skill_audit_log().list_entries("some-skill")
        assert entries[0]["action"] == "archive"
        assert entries[0]["actor"] == "system"
