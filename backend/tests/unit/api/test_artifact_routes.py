"""R73 — artifact 产物路由单元测试。

直接调用路由函数。artifact_repo / artifact_reader / artifact_version_repo
全 monkeypatch（路由模块以模块对象引用，patch 其属性）。覆盖：清单映射、
content 读取按 kind/后缀分派（pdf/image/office/html/text）、reveal、
版本清单/读取/恢复（sha256 + 锁内建版本）、乐观并发更新
（ConflictError 409 / ValueError 400 / FileNotFoundError 404 / 成功）。
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.api import artifact_routes as ar

pytestmark = pytest.mark.unit


SID = "sess-1"
AID = "art-1"


def _artifact(**overrides):
    art = SimpleNamespace(
        artifact_id=AID,
        session_id=SID,
        path="/ws/notes.py",
        kind="text",
    )
    art.to_dict = lambda: {"id": art.artifact_id,
                           "session_id": art.session_id,
                           "path": art.path, "kind": art.kind}
    for k, v in overrides.items():
        setattr(art, k, v)
    return art


def _patch_repo(monkeypatch, artifact=None):
    monkeypatch.setattr(
        ar.artifact_repo, "get_artifact", lambda aid: artifact
    )
    return artifact


# ---------------------------------------------------------------------------
# list / content 分派
# ---------------------------------------------------------------------------


def test_list_artifacts_maps_to_dict(monkeypatch):
    monkeypatch.setattr(
        ar.artifact_repo,
        "list_artifacts",
        lambda session_id: [_artifact(), _artifact(artifact_id="art-2")],
    )
    out = ar.list_artifacts(SID)
    assert [a["id"] for a in out["artifacts"]] == [AID, "art-2"]


def test_get_content_404_when_missing(monkeypatch):
    _patch_repo(monkeypatch, None)
    with pytest.raises(HTTPException) as ei:
        ar.get_artifact_content(SID, AID)
    assert ei.value.status_code == 404


def test_get_content_404_on_session_mismatch(monkeypatch):
    _patch_repo(monkeypatch, _artifact(session_id="other"))
    with pytest.raises(HTTPException) as ei:
        ar.get_artifact_content(SID, AID)
    assert ei.value.status_code == 404


@pytest.mark.parametrize(
    ("kind", "suffix", "expect_reader", "expect_kwargs"),
    [
        ("pdf", "py", "read_pdf", None),
        ("image", "png", "read_image", None),
        ("docx", "py", "read_office", {"kind": "docx"}),
        ("text", "docx", "read_office", {"kind": "docx"}),
    ],
)
def test_get_content_dispatch(monkeypatch, kind, suffix, expect_reader, expect_kwargs):
    art = _artifact(kind=kind, path=f"/ws/file.{suffix}")
    _patch_repo(monkeypatch, art)
    seen = {}

    def fake_reader(name):
        def _read(artifact_id, **kwargs):
            seen["reader"] = name
            seen["kwargs"] = kwargs
            return {"via": name}
        return _read

    monkeypatch.setattr(ar.artifact_reader, "read_pdf", fake_reader("read_pdf"))
    monkeypatch.setattr(ar.artifact_reader, "read_image", fake_reader("read_image"))
    monkeypatch.setattr(ar.artifact_reader, "read_office", fake_reader("read_office"))
    monkeypatch.setattr(ar.artifact_reader, "read_text", fake_reader("read_text"))

    out = ar.get_artifact_content(SID, AID)
    assert seen["reader"] == expect_reader
    assert out["via"] == expect_reader
    if expect_kwargs is not None:
        assert seen["kwargs"] == expect_kwargs


def test_get_content_html_suffix_marks_kind(monkeypatch):
    _patch_repo(monkeypatch, _artifact(kind="text", path="/ws/page.html"))
    monkeypatch.setattr(
        ar.artifact_reader, "read_text", lambda aid, **kw: {"content": "<p/>"}
    )
    out = ar.get_artifact_content(SID, AID)
    assert out["kind"] == "html"


def test_get_content_default_text(monkeypatch):
    _patch_repo(monkeypatch, _artifact(kind="text", path="/ws/notes.py"))
    monkeypatch.setattr(
        ar.artifact_reader, "read_text", lambda aid, **kw: {"content": "x"}
    )
    out = ar.get_artifact_content(SID, AID)
    assert "kind" not in out


# ---------------------------------------------------------------------------
# reveal
# ---------------------------------------------------------------------------


def test_reveal_hit(monkeypatch):
    _patch_repo(monkeypatch, _artifact())
    monkeypatch.setattr(
        ar.artifact_reader, "reveal_in_file_manager", lambda aid: {"ok": True}
    )
    assert ar.reveal_artifact(SID, AID) == {"ok": True}


def test_reveal_404(monkeypatch):
    _patch_repo(monkeypatch, None)
    with pytest.raises(HTTPException) as ei:
        ar.reveal_artifact(SID, AID)
    assert ei.value.status_code == 404


# ---------------------------------------------------------------------------
# 版本清单 / 读取 / 恢复
# ---------------------------------------------------------------------------


def test_list_versions(monkeypatch):
    _patch_repo(monkeypatch, _artifact())
    monkeypatch.setattr(
        ar.artifact_version_repo, "list_versions", lambda aid: [{"v": 1}]
    )
    assert ar.list_artifact_versions(SID, AID) == {"versions": [{"v": 1}]}


def test_get_version_missing_404(monkeypatch):
    _patch_repo(monkeypatch, _artifact())
    monkeypatch.setattr(
        ar.artifact_version_repo, "get_version", lambda aid, num: None
    )
    with pytest.raises(HTTPException) as ei:
        ar.get_artifact_version(SID, AID, 9)
    assert ei.value.status_code == 404


@pytest.mark.asyncio()
async def test_restore_version_success(monkeypatch):
    _patch_repo(monkeypatch, _artifact(path="/ws/notes.py"))
    target = {"content": "restored-body"}
    monkeypatch.setattr(
        ar.artifact_version_repo, "get_version", lambda aid, num: target
    )
    created = {}

    def fake_create(artifact_id, content, content_hash, snapshot_dir, note):
        created.update(
            artifact_id=artifact_id, content=content, content_hash=content_hash,
            snapshot_dir=snapshot_dir, note=note,
        )
        return {"version": 5}

    monkeypatch.setattr(
        ar.artifact_version_repo, "create_version", fake_create
    )
    req = ar.RestoreVersionRequest(version_num=2, note="r")
    out = await ar.restore_artifact_version(SID, AID, req)
    assert out["restored_from"] == 2
    assert out["new_version"] == {"version": 5}
    assert created["content"] == "restored-body"
    assert created["content_hash"] == hashlib.sha256(b"restored-body").hexdigest()
    assert ".snapshots" in created["snapshot_dir"]


# ---------------------------------------------------------------------------
# 乐观并发更新
# ---------------------------------------------------------------------------


def _patch_apply(monkeypatch, behavior):
    async def apply_edit(**kwargs):
        if isinstance(behavior, Exception):
            raise behavior
        return behavior

    monkeypatch.setattr(ar.artifact_version_repo, "apply_edit", apply_edit)


@pytest.mark.asyncio()
async def test_update_content_success(monkeypatch):
    _patch_repo(monkeypatch, _artifact())
    _patch_apply(monkeypatch, {"version": 7})
    req = ar.UpdateArtifactRequest(base_hash="h", content="new", note="e")
    out = await ar.update_artifact_content(SID, AID, req)
    assert out == {"version": {"version": 7}}


@pytest.mark.asyncio()
async def test_update_content_404_when_missing(monkeypatch):
    _patch_repo(monkeypatch, None)
    req = ar.UpdateArtifactRequest(base_hash="h", content="new")
    with pytest.raises(HTTPException) as ei:
        await ar.update_artifact_content(SID, AID, req)
    assert ei.value.status_code == 404


@pytest.mark.asyncio()
async def test_update_content_conflict_409(monkeypatch):
    _patch_repo(monkeypatch, _artifact())
    _patch_apply(
        monkeypatch, ar.artifact_version_repo.ConflictError("hash mismatch")
    )
    req = ar.UpdateArtifactRequest(base_hash="stale", content="new")
    with pytest.raises(HTTPException) as ei:
        await ar.update_artifact_content(SID, AID, req)
    assert ei.value.status_code == 409


@pytest.mark.asyncio()
async def test_update_content_value_error_400(monkeypatch):
    _patch_repo(monkeypatch, _artifact())
    _patch_apply(monkeypatch, ValueError("too large"))
    req = ar.UpdateArtifactRequest(base_hash="h", content="new")
    with pytest.raises(HTTPException) as ei:
        await ar.update_artifact_content(SID, AID, req)
    assert ei.value.status_code == 400


@pytest.mark.asyncio()
async def test_update_content_file_gone_404(monkeypatch):
    _patch_repo(monkeypatch, _artifact())
    _patch_apply(monkeypatch, FileNotFoundError("file gone"))
    req = ar.UpdateArtifactRequest(base_hash="h", content="new")
    with pytest.raises(HTTPException) as ei:
        await ar.update_artifact_content(SID, AID, req)
    assert ei.value.status_code == 404


# ---------------------------------------------------------------------------
# restore 前置 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_restore_version_artifact_missing_404(monkeypatch):
    _patch_repo(monkeypatch, None)
    req = ar.RestoreVersionRequest(version_num=1)
    with pytest.raises(HTTPException) as ei:
        await ar.restore_artifact_version(SID, AID, req)
    assert ei.value.status_code == 404


@pytest.mark.asyncio()
async def test_restore_version_target_missing_404(monkeypatch):
    _patch_repo(monkeypatch, _artifact())
    monkeypatch.setattr(
        ar.artifact_version_repo, "get_version", lambda aid, num: None
    )
    with pytest.raises(HTTPException) as ei:
        await ar.restore_artifact_version(
            SID, AID, ar.RestoreVersionRequest(version_num=1)
        )
    assert ei.value.status_code == 404
