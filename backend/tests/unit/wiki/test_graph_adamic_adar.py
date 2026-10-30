"""Adamic-Adar 第 4 信号测试。"""

from __future__ import annotations

import math

import pytest

from backend.wiki.graph import build_graph
from backend.wiki.models import GraphSignal

pytestmark = pytest.mark.unit


def _write_page(root, name: str, title: str, body: str) -> None:
    wiki = root / "wiki"
    wiki.mkdir(exist_ok=True)
    (wiki / name).write_text(f"---\ntitle: {title}\n---\n{body}", encoding="utf-8")


def test_adamic_adar_edges_use_common_neighbor_degrees(tmp_path):
    # a↔b↔c triangle (c has no outgoing links, but receives from a/b).
    _write_page(tmp_path, "a.md", "A", "[[B]] [[C]]")
    _write_page(tmp_path, "b.md", "B", "[[A]] [[C]]")
    _write_page(tmp_path, "c.md", "C", "no links")

    graph = build_graph(tmp_path)
    aa = {
        (edge.source, edge.target): edge.weight
        for edge in graph.edges
        if edge.signal is GraphSignal.AdamicAdar
    }

    expected = 1.5 / math.log(2)
    assert aa[("wiki/a.md", "wiki/b.md")] == pytest.approx(expected)
    assert aa[("wiki/b.md", "wiki/a.md")] == pytest.approx(expected)


def test_no_adamic_adar_without_common_neighbors(tmp_path):
    _write_page(tmp_path, "a.md", "A", "[[B]]")
    _write_page(tmp_path, "b.md", "B", "no links")
    _write_page(tmp_path, "c.md", "C", "no links")

    graph = build_graph(tmp_path)

    assert all(edge.signal is not GraphSignal.AdamicAdar for edge in graph.edges)
