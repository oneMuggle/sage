"""向量库后端选择测试。"""

from __future__ import annotations

import pytest

from backend.wiki.vectorstore import VectorStore
from backend.wiki.vectorstore_factory import ENV_KEY, backend_name, open_vector_store

pytestmark = pytest.mark.unit


def test_default_backend_is_json(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_KEY, raising=False)

    store = open_vector_store(tmp_path, 2)

    assert isinstance(store, VectorStore)
    assert backend_name() == "json"


def test_invalid_backend_falls_back_to_json(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_KEY, "not-a-backend")

    store = open_vector_store(tmp_path, 2)

    assert isinstance(store, VectorStore)
    assert backend_name() == "json"


def test_hnsw_backend_when_available(tmp_path, monkeypatch):
    pytest.importorskip("hnswlib")
    from backend.wiki.vectorstore_hnsw import HNSWVectorStore

    monkeypatch.setenv(ENV_KEY, "hnsw")

    store = open_vector_store(tmp_path, 2)

    assert isinstance(store, HNSWVectorStore)
