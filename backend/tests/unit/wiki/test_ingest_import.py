"""外部文件导入 ``raw/sources/`` 的安全边界测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.wiki.ingest import import_source_into_raw

pytestmark = pytest.mark.unit


@pytest.mark.asyncio()
async def test_imports_regular_file_into_raw_sources(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    src = outside / "paper.md"
    src.write_text("# hi", encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir()

    dest = await import_source_into_raw(project, src)

    assert dest == project / "raw" / "sources" / "paper.md"
    assert dest.read_text(encoding="utf-8") == "# hi"


@pytest.mark.asyncio()
async def test_rejects_symlink(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    real = outside / "real.md"
    real.write_text("x", encoding="utf-8")
    link = outside / "link.md"
    link.symlink_to(real)
    project = tmp_path / "project"
    project.mkdir()

    with pytest.raises(ValueError, match="仅支持普通文件"):
        await import_source_into_raw(project, link)


@pytest.mark.asyncio()
async def test_rejects_relative_path(tmp_path):
    project = tmp_path / "project"
    project.mkdir()

    with pytest.raises(ValueError, match="绝对路径"):
        await import_source_into_raw(project, Path("relative.md"))


@pytest.mark.asyncio()
async def test_rejects_oversized_file(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    big = outside / "big.md"
    big.write_bytes(b"x" * 32)
    project = tmp_path / "project"
    project.mkdir()

    with pytest.raises(ValueError, match="file exceeds configured read limit"):
        await import_source_into_raw(project, big, max_bytes=16)


@pytest.mark.asyncio()
async def test_rejects_unsupported_suffix(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "id_rsa"
    secret.write_text("PRIVATE KEY", encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir()

    with pytest.raises(ValueError, match="不支持的文件类型"):
        await import_source_into_raw(project, secret)
