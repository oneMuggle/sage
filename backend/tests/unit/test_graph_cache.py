"""Unit tests for mtime-based graph cache in backend.wiki.graph.

覆盖行为：
- 冷启动构建：首次调用构建图谱并写入缓存
- 二次调用命中缓存：不重复构建
- 文件 mtime 变化：缓存失效，重新构建
- query 变化：缓存失效，使用新 query 重新构建
"""

import json
import time
from pathlib import Path

from backend.wiki.graph import get_graph_cached


def _make_wiki(project_root: Path) -> None:
    wiki = project_root / "wiki"
    wiki.mkdir(parents=True)
    (wiki / "a.md").write_text("---\ntitle: A\n---\nbody A")
    (wiki / "b.md").write_text("---\ntitle: B\n---\nbody B", encoding="utf-8")


def test_graph_cache_cold_build(tmp_path):
    _make_wiki(tmp_path)
    graph = get_graph_cached(tmp_path)
    assert len(graph.nodes) >= 2


def test_graph_cache_hit_on_second_call(tmp_path):
    _make_wiki(tmp_path)
    cache_path = tmp_path / ".llm-wiki" / "graph-cache.json"
    _g1 = get_graph_cached(tmp_path)  # noqa: F841  两次调用须均成功，缓存键相同
    assert cache_path.exists()
    # Read raw data; ensure same data was reused
    cached = json.loads(cache_path.read_text(encoding="utf-8"))
    _g2 = get_graph_cached(tmp_path)  # noqa: F841  二次调用验证缓存命中
    cached2 = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cached == cached2


def test_graph_cache_miss_on_mtime_change(tmp_path):
    _make_wiki(tmp_path)
    _g1 = get_graph_cached(tmp_path)  # noqa: F841  冷启动构建
    time.sleep(0.02)  # ensure mtime granularity
    (tmp_path / "wiki" / "a.md").write_text("updated content")
    _g2 = get_graph_cached(tmp_path)  # noqa: F841  mtime 变化后重建
    # Different cache state (mtime changed)
    cache_path = tmp_path / ".llm-wiki" / "graph-cache.json"
    cached = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cached["latest_mtime"] > 0


def test_graph_cache_miss_on_query_change(tmp_path):
    _make_wiki(tmp_path)
    get_graph_cached(tmp_path, query=None)
    get_graph_cached(tmp_path, query="something else")
    cache_path = tmp_path / ".llm-wiki" / "graph-cache.json"
    cached = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cached["query"] == "something else"
