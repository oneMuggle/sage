"""Playbook 导入与分享链路集成测试 (2026-11-03)。

覆盖 M2/M3 的两条端到端链路（HTTP 层）：
- Word 上传 → 预览 → 确认 → 绑定项目
- 生成分享链接 → 访问 → 导入项目

使用 conftest.py 的 autouse ``setup_test_db`` + async ``client`` fixtures。
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from backend.data.project_repo import ProjectRepository


@pytest.fixture()
def project(tmp_path, setup_test_db):
    """创建测试项目（目录必须在磁盘上存在）。"""
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()
    return ProjectRepository().register(str(project_dir))


def _docx_bytes(tmp_path: Path) -> bytes:
    """构造一份含阶段/产物/规则的最小 Word 文档。"""
    from docx import Document

    doc = Document()
    for line in (
        "1. 开题阶段",
        "2. 实施阶段",
        "产物",
        "- 开题报告",
        "- 中期检查表",
        "规则",
        "- 评审材料须双人复核",
    ):
        doc.add_paragraph(line)
    path = tmp_path / "科研课题规范.docx"
    doc.save(str(path))
    return path.read_bytes()


@pytest.fixture()
def word_document(tmp_path) -> bytes:
    return _docx_bytes(tmp_path)


async def _preview_document(client, word_document: bytes) -> dict:
    resp = await client.post(
        "/api/v1/playbooks/import/document",
        json={
            "filename": "科研课题规范.docx",
            "content_base64": base64.b64encode(word_document).decode("ascii"),
            "use_llm": False,
        },
    )
    assert resp.status_code == 200
    return resp.json()


class TestDocumentImportFlow:
    """Word 上传 → 预览 → 确认 → 绑定项目。"""

    async def test_upload_word_previews_playbook(self, client, word_document):
        data = await _preview_document(client, word_document)
        spec = data["playbook"]
        assert data["source"] == "deterministic"
        assert data["llm_available"] is False
        labels = [stage["label"] for stage in spec["stages"]]
        assert labels == ["开题阶段", "实施阶段"]

    async def test_import_preview_rejects_unsupported_format(self, client):
        resp = await client.post(
            "/api/v1/playbooks/import/document",
            json={
                "filename": "规范.exe",
                "content_base64": base64.b64encode(b"x").decode("ascii"),
                "use_llm": False,
            },
        )
        assert resp.status_code == 400
        assert "不支持的文件格式" in resp.json()["detail"]

    async def test_confirm_import_binds_project(self, client, project, word_document):
        spec = (await _preview_document(client, word_document))["playbook"]

        bind = await client.put(
            f"/api/v1/projects/{project.id}/playbook",
            json={"spec": spec, "source": "document-import"},
        )
        assert bind.status_code == 200
        assert bind.json()["playbook"]["id"] == spec["id"]

        current = await client.get(f"/api/v1/projects/{project.id}/playbook")
        assert current.status_code == 200
        assert current.json()["playbook"]["id"] == spec["id"]


class TestShareLinkFlow:
    """生成分享链接 → 访问 → 导入项目。"""

    @staticmethod
    def _envelope(spec: dict) -> dict:
        return {
            "format": "sage.playbook",
            "playbook": spec,
            "scaffold": {"include": False, "directories": [], "documents": []},
        }

    async def _library_item(self, client, spec: dict) -> dict:
        resp = await client.post(
            "/api/v1/playbooks/library",
            json={"envelope": self._envelope(spec), "source": "imported"},
        )
        assert resp.status_code == 200
        return resp.json()["item"]

    async def test_share_link_resolves_and_imports(self, client, project, word_document):
        spec = (await _preview_document(client, word_document))["playbook"]
        item = await self._library_item(client, spec)

        share = await client.post(
            f"/api/v1/playbooks/library/{item['id']}/share", json={"expiry_days": 7}
        )
        assert share.status_code == 200
        link = share.json()
        assert link["share_url"] == f"/share/playbook/{link['token']}"

        shared = await client.get(f"/api/v1/playbooks/shared/{link['token']}")
        assert shared.status_code == 200
        payload = shared.json()
        assert payload["playbook_id"] == item["id"]
        assert payload["spec"]["id"] == spec["id"]

        bind = await client.put(
            f"/api/v1/projects/{project.id}/playbook",
            json={"spec": payload["spec"], "source": "shared-link"},
        )
        assert bind.status_code == 200
        assert bind.json()["playbook"]["id"] == spec["id"]

    async def test_shared_token_is_invalid_when_unknown(self, client):
        resp = await client.get("/api/v1/playbooks/shared/not-a-real-token")
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "share_invalid"

    async def test_expired_share_link_returns_gone(self, client, word_document):
        spec = (await _preview_document(client, word_document))["playbook"]
        item = await self._library_item(client, spec)

        share = await client.post(
            f"/api/v1/playbooks/library/{item['id']}/share", json={"expiry_days": 0}
        )
        token = share.json()["token"]

        resp = await client.get(f"/api/v1/playbooks/shared/{token}")
        assert resp.status_code == 410
        assert resp.json()["detail"]["code"] == "share_expired"

    async def test_share_link_for_missing_playbook_returns_404(self, client):
        resp = await client.post(
            "/api/v1/playbooks/library/does-not-exist/share", json={"expiry_days": 7}
        )
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "playbook_not_found"
