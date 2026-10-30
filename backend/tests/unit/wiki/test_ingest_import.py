"""外部文件导入 ``raw/sources/`` 的安全边界测试。"""

from __future__ import annotations

import pytest

from backend.wiki.ingest import import_source_into_raw

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_rejects_symlink(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    real = outside / "real.md"
    real.write_text("x", encoding="utf-8")
    link = outside / "link.md"
    link.symlink_to(real)
    project = tmp_path / "project"
    project.mkdir()

    with pytest.raises(ValueError):
        await import_source_into_raw(project, link)


@pytest.mark.asyncio
async def test_rejects_relative_path(tmp_path):
    project = tmp_path / "project"
    project.mkdir()

    with pytest.raises(ValueError):
        await import_source_into_raw(project, project / "relative.md")


@pytest.mark.asyncio
async def test_rejects_oversized_file(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    big = outside / "big.md"
    big.write_bytes(b"x" * 32)
    project = tmp_path / "project"
    project.mkdir()

    with pytest.raises(ValueError):
        await import_source_into_raw(project, big, max_bytes=16)
