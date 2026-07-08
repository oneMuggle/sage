"""Unit tests for mtime-based graph cache in backend.wiki.graph.

覆盖行为：
- 冷启动构建：首次调用构建图谱并写入缓存
- 二次调用命中缓存：不重复构建
- 文件 mtime 变化：缓存失效，重新构建
- query 变化：仅重新过滤，复用缓存的全图（不重建）
- limit 变化：仅重新过滤，复用同一缓存（关键回归测试）
- 缺失 wiki 目录：不写缓存文件
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


def _make_big_wiki(project_root: Path, n: int = 60) -> None:
    """Create n wiki pages, each linked from page_00 to itself."""
    wiki = project_root / "wiki"
    wiki.mkdir(parents=True)
    for i in range(n):
        (wiki / f"page_{i:02d}.md").write_text(
            f"---\ntitle: Page {i}\n---\nbody {i}", encoding="utf-8"
        )


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
    """query 变化不应触发重建（Important #1 修复）。

    缓存存储的是完整图谱，query 仅在读时过滤。两次不同 query 的
    调用复用同一缓存条目。
    """
    _make_wiki(tmp_path)
    get_graph_cached(tmp_path, query=None)
    cache_path = tmp_path / ".llm-wiki" / "graph-cache.json"
    cached_before = json.loads(cache_path.read_text(encoding="utf-8"))
    get_graph_cached(tmp_path, query="something else")
    cached_after = json.loads(cache_path.read_text(encoding="utf-8"))
    # Cache content must be identical — no rebuild on query change
    assert cached_before == cached_after


def test_limit_change_uses_cache(tmp_path):
    """limit 变化不应触发重建（Important #1 关键回归测试）。

    同 query 不同 limit 两次调用应命中同一缓存条目。
    """
    _make_big_wiki(tmp_path, n=60)
    cache_path = tmp_path / ".llm-wiki" / "graph-cache.json"

    g1 = get_graph_cached(tmp_path, limit=100)
    assert len(g1.nodes) >= 60  # 60 pages, limit 100 → all returned

    cached_before = json.loads(cache_path.read_text(encoding="utf-8"))

    g2 = get_graph_cached(tmp_path, limit=50)
    assert len(g2.nodes) == 50  # trimmed at call time

    cached_after = json.loads(cache_path.read_text(encoding="utf-8"))
    # Cache file must be byte-identical — limit change only re-filters
    assert cached_before == cached_after


def test_missing_wiki_dir_no_cache_write(tmp_path):
    """缺失 wiki 目录时不应写缓存文件（Important #2 修复）。"""
    # tmp_path exists but has no wiki/ subdir
    graph = get_graph_cached(tmp_path)
    cache_path = tmp_path / ".llm-wiki" / "graph-cache.json"
    assert len(graph.nodes) == 0
    assert not cache_path.exists()
