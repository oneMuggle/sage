"""sage_docs.indexer 单元测试：分块、增量、删除、强制重建。"""

from pathlib import Path

import pytest

from backend.services.sage_docs import indexer

pytestmark = pytest.mark.unit


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _docs_root(tmp_path: Path) -> Path:
    root = tmp_path / "docs"
    _write(
        root,
        "user-manual/07-chat.md",
        "# 对话\n\n默认重试次数是 3。\n\n## 重试\n\n可在设置中调整重试次数。\n",
    )
    _write(root, "technical/README.md", "# 技术手册\n\n后端端口默认 8765。\n")
    return root


def test_chunk_markdown_builds_heading_chain():
    chunks = indexer.chunk_markdown("# A\n\nintro\n\n## B\n\nbody\n")

    assert [chunk.heading for chunk in chunks] == ["A", "A › B"]
    assert chunks[0].start_line == 1
    assert chunks[1].start_line == 5


def test_chunk_markdown_splits_oversized_section():
    long_body = "\n\n".join("段落" * 200 for _ in range(10))

    chunks = indexer.chunk_markdown(f"# 长\n\n{long_body}\n")

    assert len(chunks) > 1
    assert all(chunk.content for chunk in chunks)


def test_chunk_markdown_ignores_empty_text():
    assert indexer.chunk_markdown("") == []


def test_ensure_index_first_build(tmp_path):
    root = _docs_root(tmp_path)
    index_dir = tmp_path / "index"

    stats = indexer.ensure_index(root, index_dir)

    assert stats == {"files": 2, "reindexed": 2, "chunks": stats["chunks"]}
    assert stats["chunks"] >= 2
    assert indexer.count_chunks(index_dir) == stats["chunks"]


def test_ensure_index_skips_unchanged_documents(tmp_path):
    root = _docs_root(tmp_path)
    index_dir = tmp_path / "index"
    first = indexer.ensure_index(root, index_dir)

    second = indexer.ensure_index(root, index_dir)

    assert second["reindexed"] == 0
    assert second["files"] == first["files"]
    assert indexer.count_chunks(index_dir) == first["chunks"]


def test_ensure_index_reindexes_only_changed_document(tmp_path):
    root = _docs_root(tmp_path)
    index_dir = tmp_path / "index"
    indexer.ensure_index(root, index_dir)
    _write(root, "user-manual/07-chat.md", "# 对话\n\n重试次数改为 5 次。\n")

    stats = indexer.ensure_index(root, index_dir)

    assert stats["reindexed"] == 1
    assert stats["files"] == 2


def test_ensure_index_drops_deleted_document(tmp_path):
    root = _docs_root(tmp_path)
    index_dir = tmp_path / "index"
    indexer.ensure_index(root, index_dir)
    (root / "user-manual" / "07-chat.md").unlink()

    stats = indexer.ensure_index(root, index_dir)

    assert stats["files"] == 1
    conn = indexer.connect_index(index_dir)
    try:
        rel_paths = {row[0] for row in conn.execute("SELECT rel_path FROM docs_meta")}
    finally:
        conn.close()
    assert rel_paths == {"technical/README.md"}


def test_ensure_index_force_reindexes_everything(tmp_path):
    root = _docs_root(tmp_path)
    index_dir = tmp_path / "index"
    indexer.ensure_index(root, index_dir)

    stats = indexer.ensure_index(root, index_dir, force=True)

    assert stats["reindexed"] == 2


def test_ensure_index_with_no_documents_creates_empty_index(tmp_path):
    root = tmp_path / "docs"
    root.mkdir()
    index_dir = tmp_path / "index"

    stats = indexer.ensure_index(root, index_dir)

    assert stats == {"files": 0, "reindexed": 0, "chunks": 0}
    assert indexer.count_chunks(index_dir) == 0


def test_count_chunks_returns_zero_without_index(tmp_path):
    assert indexer.count_chunks(tmp_path / "missing-index") == 0
