from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.api import wiki_routes
from backend.api.wiki_routes import (
    _cleanup_temp_paths,
    _resolve_project_file,
    delete_file,
    list_directory_impl,
    read_file,
    rename_file,
    write_file,
)
from backend.wiki.files import secure_open_file, secure_read_file, secure_write_file


def _make_hardlink_or_skip(source: Path, target: Path) -> None:
    try:
        target.hardlink_to(source)
    except (OSError, NotImplementedError):
        pytest.skip("hardlinks are not supported")


def test_secure_reads_reject_hardlink_to_outside(tmp_path: Path) -> None:
    root = tmp_path / "project"
    wiki = root / "wiki"
    wiki.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("outside-secret", encoding="utf-8")
    linked = wiki / "linked.md"
    _make_hardlink_or_skip(outside, linked)

    with pytest.raises(OSError, match="多链接"):
        secure_open_file(root, linked)
    with pytest.raises(OSError, match="多链接"):
        secure_read_file(root, linked)


def test_secure_write_rejects_hardlink_without_modifying_outside(tmp_path: Path) -> None:
    root = tmp_path / "project"
    wiki = root / "wiki"
    wiki.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("outside-secret", encoding="utf-8")
    linked = wiki / "linked.md"
    _make_hardlink_or_skip(outside, linked)

    with pytest.raises(OSError, match="多链接"):
        secure_write_file(root, linked, "replacement")
    assert outside.read_text(encoding="utf-8") == "outside-secret"


def test_cleanup_temp_paths_attempts_every_path_after_unlink_error(tmp_path, monkeypatch):
    first = tmp_path / "first.tmp"
    second = tmp_path / "second.tmp"
    attempted = []

    def unlink(self, *, missing_ok=False):
        attempted.append(self)
        if self == first:
            raise OSError("synthetic cleanup failure")

    monkeypatch.setattr(Path, "unlink", unlink)

    _cleanup_temp_paths(first, second)

    assert attempted == [first, second]

def test_resolve_accepts_legal_relative_path(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    resolved_root, target = _resolve_project_file(str(root), "wiki/page.md")
    assert resolved_root == root.resolve()
    assert target == root.resolve() / "wiki/page.md"


def test_declared_project_symlink_is_rejected(tmp_path):
    root = tmp_path / "project"
    target = tmp_path / "real-project"
    target.mkdir()
    root.symlink_to(target, target_is_directory=True)
    with pytest.raises(HTTPException) as exc:
        _resolve_project_file(str(root), "wiki/page.md")
    assert exc.value.status_code == 400


def test_nested_symlink_is_rejected_even_when_target_stays_under_root(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    real = root / "real"
    real.mkdir()
    (root / "alias").symlink_to(real, target_is_directory=True)
    with pytest.raises(HTTPException) as exc:
        _resolve_project_file(str(root), "alias/file.md")
    assert exc.value.status_code == 400
def test_list_directory_accepts_empty_path_as_project_root(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "wiki").mkdir()

    listing = list_directory_impl("", str(root))

    assert listing[0]["path"] == "."
    assert listing[0]["is_dir"] is True


@pytest.mark.asyncio()
async def test_file_handlers_keep_legal_relative_functionality(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setattr(wiki_routes, "authorize_registered_project", lambda _: root)
    assert await write_file("wiki/page.md", "hello", str(root)) == {"success": True}
    assert await read_file("wiki/page.md", str(root)) == "hello"
    assert list_directory_impl("wiki", str(root))[0]["name"] == "wiki"
    assert await rename_file("wiki/page.md", "wiki/renamed.md", str(root)) == {"success": True}
    assert await delete_file("wiki/renamed.md", str(root)) == {"success": True}


@pytest.mark.asyncio()
async def test_file_handlers_reject_symlinked_destination_without_touching_outside(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setattr(wiki_routes, "authorize_registered_project", lambda _: root)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "wiki").symlink_to(outside, target_is_directory=True)

    with pytest.raises(HTTPException) as exc:
        await write_file("wiki/evil.md", "secret", str(root))
    assert exc.value.status_code == 400
    assert not (outside / "evil.md").exists()


@pytest.mark.asyncio()
async def test_file_handlers_reject_symlink_delete_and_rename_without_touching_outside(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setattr(wiki_routes, "authorize_registered_project", lambda _: root)
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "keep.md"
    outside_file.write_text("keep", encoding="utf-8")
    (root / "wiki").mkdir()
    (root / "wiki" / "link.md").symlink_to(outside_file)

    with pytest.raises(HTTPException) as delete_exc:
        await delete_file("wiki/link.md", str(root))
    with pytest.raises(HTTPException) as rename_exc:
        await rename_file("wiki/link.md", "wiki/new.md", str(root))

    assert delete_exc.value.status_code == 400
    assert rename_exc.value.status_code == 400
    assert outside_file.read_text(encoding="utf-8") == "keep"
    assert outside_file.exists()


@pytest.mark.asyncio()
async def test_clip_rejects_raw_sources_symlink_without_creating_outside_file(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setattr(wiki_routes, "authorize_registered_project", lambda _: root)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "raw").mkdir()
    (root / "raw" / "sources").symlink_to(outside, target_is_directory=True)

    request = wiki_routes.ClipRequest(
        title="unsafe", url="https://example.test", content="payload",
        project_path=str(root), auto_ingest=False,
    )
    with pytest.raises(HTTPException) as exc:
        await wiki_routes.clip_webpage(request)

    assert exc.value.status_code == 400
    assert list(outside.iterdir()) == []


@pytest.mark.asyncio()
async def test_file_handlers_reject_escape_without_mutating_outside(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setattr(wiki_routes, "authorize_registered_project", lambda _: root)
    outside = tmp_path / "outside.txt"
    outside.write_text("safe")
    for handler, args in (
        (read_file, ("../outside.txt", str(root))),
        (write_file, ("../outside.txt", "bad", str(root))),
        (delete_file, ("../outside.txt", str(root))),
    ):
        with pytest.raises(HTTPException) as exc:
            await handler(*args)
        assert exc.value.status_code == 400
    assert outside.read_text() == "safe"
