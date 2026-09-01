"""Tests for Wiki vector stores, including Python 3.8-compatible paths."""

import ast
from pathlib import Path

import pytest

from backend.wiki.vectorstore import _cosine_similarity


@pytest.mark.unit()
def test_cosine_similarity_preserves_zip_truncation_for_unequal_vectors():
    # The former strict=False call intentionally used the shorter length.
    assert _cosine_similarity([1.0, 0.0, 99.0], [1.0, 0.0]) == pytest.approx(0.010100494835363)


def test_vector_store_zip_calls_do_not_use_strict_keyword():
    backend_root = Path(__file__).parents[2]
    source_files = (
        backend_root / "wiki" / "vectorstore.py",
        backend_root / "wiki" / "vectorstore_hnsw.py",
        backend_root / "wiki" / "ingest.py",
    )
    for source_file in source_files:
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "zip":
                assert not any(keyword.arg == "strict" for keyword in node.keywords), source_file


def test_hnsw_search_supports_equal_length_labels_and_distances(monkeypatch):
    np = pytest.importorskip("numpy")
    hnsw_module = pytest.importorskip("backend.wiki.vectorstore_hnsw")

    class FakeIndex:
        def knn_query(self, query_array, k):
            assert query_array.shape == (1, 2)
            assert k == 1
            return np.array([[0]]), np.array([[0.25]])

    store = hnsw_module.HNSWVectorStore.__new__(hnsw_module.HNSWVectorStore)
    store.dim = 2
    store.records = {
        "page::0": hnsw_module.ChunkRecord(
            id="page::0", page_path="page", chunk_index=0, content="content"
        )
    }
    store.label_to_id = {0: "page::0"}
    store.index = FakeIndex()

    hits = store.search([1.0, 0.0], limit=1)

    assert len(hits) == 1
    assert hits[0].content == "content"
def test_hnsw_rejects_preexisting_index_symlink_before_native_load(monkeypatch, tmp_path):
    hnsw_module = pytest.importorskip("backend.wiki.vectorstore_hnsw")

    project_root = tmp_path
    wiki_dir = project_root / ".llm-wiki"
    wiki_dir.mkdir()
    outside = tmp_path / "outside.hnsw"
    outside.write_bytes(b"not an index")
    (wiki_dir / "vectors.hnsw").symlink_to(outside)
    (wiki_dir / "vectors.json").write_text(
        '{"records": {}, "label_to_id": {}, "next_label": 0}', encoding="utf-8"
    )

    native_index_called = False

    def forbidden_native_index(*args, **kwargs):
        nonlocal native_index_called
        native_index_called = True
        raise AssertionError("native hnswlib must not be called for a symlink")

    monkeypatch.setattr(hnsw_module.hnswlib, "Index", forbidden_native_index)

    with pytest.raises(
        OSError,
        match="拒绝读取非 regular Wiki 文件|符号链接|Wiki 文件操作|Too many levels",
    ):
        hnsw_module.HNSWVectorStore.open(project_root, dim=2)
    assert native_index_called is False


def test_hnsw_fails_closed_when_safe_filesystem_primitives_are_unavailable(
    monkeypatch, tmp_path
):
    hnsw_module = pytest.importorskip("backend.wiki.vectorstore_hnsw")
    monkeypatch.setattr(hnsw_module, "_require_posix_safety", lambda: (_ for _ in ()).throw(OSError("no-follow")))
    with pytest.raises(OSError, match="no-follow"):
        hnsw_module.HNSWVectorStore.open(tmp_path, dim=2)
