"""Unit tests for backend.office.read_cache (Round D P8 读缓存层)."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from pydantic import BaseModel

from backend.office import read_cache


class FakeResult(BaseModel):
    value: str
    nested: dict = {}


@pytest.fixture(autouse=True)
def _fresh_cache():
    read_cache.clear()
    yield
    read_cache.clear()


@pytest.fixture()
def doc(tmp_path: Path) -> Path:
    f = tmp_path / "doc.docx"
    f.write_bytes(b"PK\x03\x04 v1")
    return f


def test_hit_skips_loader(doc):
    calls = []

    def loader():
        calls.append(1)
        return FakeResult(value="parsed")

    first = read_cache.get_or_read("word", doc, "opts", loader)
    second = read_cache.get_or_read("word", doc, "opts", loader)
    assert first.value == second.value == "parsed"
    assert len(calls) == 1


def test_returned_copy_is_isolated(doc):
    """路由层就地改写返回值（_persist_read_summary）不得污染缓存。"""
    read_cache.get_or_read("word", doc, "opts", lambda: FakeResult(value="clean"))
    got = read_cache.get_or_read("word", doc, "opts", lambda: FakeResult(value="X"))
    got.value = "mutated"
    again = read_cache.get_or_read("word", doc, "opts", lambda: FakeResult(value="Y"))
    assert again.value == "clean"


def test_mtime_change_invalidates(doc):
    calls = []

    def loader():
        calls.append(1)
        return FakeResult(value=f"v{len(calls)}")

    read_cache.get_or_read("word", doc, "opts", loader)
    doc.write_bytes(b"PK\x03\x04 v2 changed")
    future = time.time() + 5
    os.utime(doc, (future, future))
    result = read_cache.get_or_read("word", doc, "opts", loader)
    assert result.value == "v2"
    assert len(calls) == 2


def test_options_key_separates_entries(doc):
    calls = []

    def loader():
        calls.append(1)
        return FakeResult(value=f"v{len(calls)}")

    a = read_cache.get_or_read("excel", doc, "ws=/a|", loader)
    b = read_cache.get_or_read("excel", doc, "ws=/b|", loader)
    assert a.value != b.value
    assert len(calls) == 2


def test_loader_exception_not_cached(doc):
    calls = []

    def failing():
        calls.append(1)
        raise ValueError("parse failed")

    with pytest.raises(ValueError, match="parse failed"):
        read_cache.get_or_read("word", doc, "opts", failing)
    # 失败未被缓存 —— 下次重试 loader
    with pytest.raises(ValueError, match="parse failed"):
        read_cache.get_or_read("word", doc, "opts", failing)
    assert len(calls) == 2


def test_invalidate_drops_all_kinds(doc):
    calls = []

    def loader():
        calls.append(1)
        return FakeResult(value=f"v{len(calls)}")

    read_cache.get_or_read("word", doc, "a", loader)
    read_cache.get_or_read("word", doc, "b", loader)
    read_cache.invalidate(doc)
    read_cache.get_or_read("word", doc, "a", loader)
    assert len(calls) == 3


def test_lru_eviction(tmp_path, monkeypatch):
    monkeypatch.setattr(read_cache, "_MAX_ENTRIES", 2)
    calls = []

    def loader():
        calls.append(1)
        return FakeResult(value="x")

    files = []
    for i in range(3):
        f = tmp_path / f"doc{i}.docx"
        f.write_bytes(b"PK")
        files.append(f)
        read_cache.get_or_read("word", f, "o", loader)
    # doc0 应已被逐出 → 再读触发 loader
    read_cache.get_or_read("word", files[0], "o", loader)
    assert len(calls) == 4


def test_missing_file_falls_through(tmp_path):
    ghost = tmp_path / "ghost.docx"
    sentinel = FakeResult(value="loader ran")
    result = read_cache.get_or_read("word", ghost, "o", lambda: sentinel)
    assert result.value == "loader ran"
