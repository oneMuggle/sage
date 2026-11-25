"""Wiki source 级联删除：向量清理必须按库内记录的自适应维度打开。"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.wiki.lifecycle import cascade_delete_source
from backend.wiki.vectorstore import VectorStore

pytestmark = pytest.mark.unit


def _write_page(project_root: Path, title: str, sources: list[str]) -> Path:
    page = project_root / "wiki" / "notes" / f"{title}.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(
        "---\n"
        f"title: {title}\n"
        "type: note\n"
        f"sources: [{', '.join(sources)}]\n"
        "---\n\nbody\n",
        encoding="utf-8",
    )
    return page


def test_cascade_delete_uses_stored_vector_dim(tmp_path: Path) -> None:
    """1024 维库不再被硬编码 1536 打开失败，向量随页面一起清理。"""
    page = _write_page(tmp_path, "a", ["raw/sources/a.pdf"])
    page_rel = "wiki/notes/a.md"

    store = VectorStore.open(tmp_path, 1024)
    store.upsert_chunks(page_rel, [(0, "hello", [0.1] * 1024)])

    stats = cascade_delete_source(tmp_path, "raw/sources/a.pdf")

    assert stats["deleted_wiki_pages"] == [page_rel]
    assert stats["deleted_vectors"] == 1
    assert not page.exists()
    assert VectorStore.open(tmp_path, 1024).records == []


def test_cascade_delete_without_vector_store_still_deletes_pages(tmp_path: Path) -> None:
    """没有向量库时不创建空库，页面删除照常进行。"""
    page = _write_page(tmp_path, "b", ["raw/sources/b.pdf"])

    stats = cascade_delete_source(tmp_path, "raw/sources/b.pdf")

    assert stats["deleted_wiki_pages"] == ["wiki/notes/b.md"]
    assert stats["deleted_vectors"] == 0
    assert not page.exists()
    assert not (tmp_path / ".llm-wiki" / "vectors.json").exists()
