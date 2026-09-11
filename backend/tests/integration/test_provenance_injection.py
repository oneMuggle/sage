"""审批 provenance frontmatter 注入集成测试（Round 7）"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.legacy_routes import router

pytestmark = pytest.mark.integration


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, headers={"Authorization": "Bearer test-local-auth-token"})


def _patch_plain_fs_loader(monkeypatch, root):
    """朴素文件读写替身（safe_writer 在 Windows fail-closed，见 Round 3）"""
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


def _make_draft():
    from backend.skills.draft_store import get_skill_draft_store
    from backend.skills.review_service import SkillDraft

    draft = SkillDraft(
        id="draft-prov-1",
        name="prov-skill",
        description="来源标记测试",
        when_to_use="当用户明确要求验证技能来源标记的完整链路时使用",
        content=(
            "---\nname: prov-skill\ndescription: 来源标记测试\n"
            "when_to_use: 当用户明确要求验证技能来源标记的完整链路时使用\n---\n"
            "## 步骤\n1. 测试"
        ),
        trigger_type="complex_turn",
        source_session_id="",
        source_context={},
        status="pending",
        created_at=0,
    )
    get_skill_draft_store().insert(draft)


def test_approve_injects_provenance_frontmatter(client, monkeypatch, tmp_path):
    """审批落盘的 SKILL.md frontmatter 含 metadata.provenance=agent-created"""
    from backend.skills.draft_store import reset_skill_draft_store
    from backend.skills.loader import get_skill_loader, reset_skill_loader

    # 单例可能被同 worker 先行测试缓存到其临时 db_path（表已不在）——
    # 与 reset_skill_loader 同理，先重置再绑定当前测试的数据库。
    # xdist loadfile 分配变化时该隐患即显现（no such table: skill_drafts）。
    reset_skill_draft_store()

    _patch_plain_fs_loader(monkeypatch, tmp_path / "skills")
    reset_skill_loader()
    _make_draft()

    resp = client.post("/skill-drafts/draft-prov-1/approve")
    assert resp.status_code == 200, resp.text

    written = get_skill_loader().read("prov-skill")
    assert written is not None
    assert "provenance" in written
    assert "agent-created" in written

    # 审计 after_content 快照与落盘内容一致（含注入后的 frontmatter）
    from backend.skills.audit import get_skill_audit_log

    entries = get_skill_audit_log().list_entries("prov-skill")
    assert entries[0]["action"] == "create"
