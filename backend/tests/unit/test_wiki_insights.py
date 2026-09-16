# ruff: noqa: UP006, UP007, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""wiki 图谱洞察（insights）行为测试（Round 17）。

覆盖：三类惊人联系启发式（跨社区 / 类型不匹配 / 边缘-中心）、
三类知识缺口（孤立节点 / 稀疏社区 / 桥节点）、排序契约，
以及 tmp 真实 markdown 项目 → analyze_graph 的端到端链路。
"""

from __future__ import annotations

from typing import List, Optional

import pytest

from backend.wiki.community import CommunityInfo
from backend.wiki.insights import (
    KnowledgeGap,
    _find_knowledge_gaps,
    _find_surprising_connections,
    analyze_graph,
)
from backend.wiki.models import GraphData, GraphEdge, GraphNode, GraphSignal

pytestmark = pytest.mark.unit


def _node(node_id: str, label: str, page_type: Optional[str] = None) -> GraphNode:
    return GraphNode(id=node_id, label=label, page_type=page_type)


def _edge(source: str, target: str) -> GraphEdge:
    return GraphEdge(source=source, target=target, signal=GraphSignal.DirectLink, weight=1.0)


def _community(community_id: int, members: List[str], cohesion: float = 0.8) -> CommunityInfo:
    return CommunityInfo(
        community_id=community_id, members=list(members), cohesion=cohesion, size=len(members)
    )


# --------------------------------------------------------------------------- #
# 惊人联系
# --------------------------------------------------------------------------- #


class TestFindSurprisingConnections:
    def _graph(self):
        """A 社区（a1,a2）+ B 社区（b1,b2）；跨社区边 a1-b1。"""
        graph = GraphData(
            nodes=[
                _node("wiki/a1.md", "A1", "concept"),
                _node("wiki/a2.md", "A2", "concept"),
                _node("wiki/b1.md", "B1", "source"),
                _node("wiki/b2.md", "B2", "source"),
            ],
            edges=[_edge("wiki/a1.md", "wiki/a2.md"), _edge("wiki/b1.md", "wiki/b2.md")],
        )
        # a1-b1 跨社区边
        graph.edges.append(_edge("wiki/a1.md", "wiki/b1.md"))
        communities = [
            _community(0, ["wiki/a1.md", "wiki/a2.md"]),
            _community(1, ["wiki/b1.md", "wiki/b2.md"]),
        ]
        return graph, communities

    def test_cross_community_edge_flagged(self):
        graph, communities = self._graph()
        found = _find_surprising_connections(graph, communities)
        cross = [
            s
            for s in found
            if {s.source_id, s.target_id} == {"wiki/a1.md", "wiki/b1.md"} and "跨社区" in s.reason
        ]
        assert len(cross) == 1
        assert cross[0].strength == 0.8

    def test_same_community_edge_not_cross_flagged(self):
        graph, communities = self._graph()
        found = _find_surprising_connections(graph, communities)
        for s in found:
            if {s.source_id, s.target_id} == {"wiki/a1.md", "wiki/a2.md"}:
                assert "跨社区" not in s.reason

    def test_type_mismatch_flagged(self):
        graph, communities = self._graph()
        found = _find_surprising_connections(graph, communities)
        mismatch = [s for s in found if "类型不匹配" in s.reason]
        # a1(concept)-b1(source) 跨类型
        assert any({s.source_id, s.target_id} == {"wiki/a1.md", "wiki/b1.md"} for s in mismatch)
        assert all(s.strength == 0.6 for s in mismatch)

    def test_same_type_not_flagged(self):
        graph, communities = self._graph()
        found = _find_surprising_connections(graph, communities)
        for s in found:
            if {s.source_id, s.target_id} == {"wiki/a1.md", "wiki/a2.md"}:
                assert "类型不匹配" not in s.reason  # 同为 concept

    def test_hub_leaf_connection_flagged(self):
        graph = GraphData(
            nodes=[_node(f"wiki/h{i}.md", f"H{i}", "concept") for i in range(6)],
            edges=[],
        )
        # h0 连 h1..h5（度数 5 ↔ 1）
        for i in range(1, 6):
            graph.edges.append(_edge("wiki/h0.md", f"wiki/h{i}.md"))
        found = _find_surprising_connections(graph, [])
        hub_leaf = [s for s in found if "边缘到中心" in s.reason]
        assert len(hub_leaf) == 5
        assert all(s.strength == 0.7 for s in hub_leaf)

    def test_mid_degree_not_flagged(self):
        graph = GraphData(nodes=[_node("wiki/x.md", "X"), _node("wiki/y.md", "Y")], edges=[])
        graph.edges.append(_edge("wiki/x.md", "wiki/y.md"))
        assert _find_surprising_connections(graph, []) == []

    def test_sorted_by_strength_desc(self):
        graph, communities = self._graph()
        found = _find_surprising_connections(graph, communities)
        strengths = [s.strength for s in found]
        assert strengths == sorted(strengths, reverse=True)

    def test_missing_endpoint_skipped(self):
        graph = GraphData(
            nodes=[_node("wiki/a1.md", "A1")],
            edges=[_edge("wiki/a1.md", "wiki/ghost.md")],
        )
        assert _find_surprising_connections(graph, []) == []


# --------------------------------------------------------------------------- #
# 知识缺口
# --------------------------------------------------------------------------- #


class TestFindKnowledgeGaps:
    def test_isolated_node_flagged_medium(self):
        graph = GraphData(
            nodes=[_node("wiki/alone.md", "孤立页"), _node("wiki/pair.md", "P")],
            edges=[],
        )
        gaps = _find_knowledge_gaps(graph, [])
        iso = [g for g in gaps if g.gap_type == "isolated_node"]
        assert {g.node_id for g in iso} == {"wiki/alone.md", "wiki/pair.md"}
        assert all(g.severity == "medium" for g in iso)

    def test_sparse_community_low(self):
        graph = GraphData(nodes=[_node(f"wiki/s{i}.md", f"S{i}") for i in range(3)], edges=[])
        gaps = _find_knowledge_gaps(
            graph, [_community(7, [f"wiki/s{i}.md" for i in range(3)], cohesion=0.1)]
        )
        sparse = [g for g in gaps if g.gap_type == "sparse_community"]
        assert len(sparse) == 1
        assert sparse[0].severity == "low"
        assert sparse[0].node_id == "community_7"

    def test_cohesive_community_not_flagged(self):
        graph = GraphData(nodes=[_node(f"wiki/s{i}.md", f"S{i}") for i in range(3)], edges=[])
        gaps = _find_knowledge_gaps(
            graph, [_community(7, [f"wiki/s{i}.md" for i in range(3)], cohesion=0.5)]
        )
        assert all(g.gap_type != "sparse_community" for g in gaps)

    def test_small_low_cohesion_community_not_flagged(self):
        graph = GraphData(nodes=[_node("wiki/s0.md", "S0"), _node("wiki/s1.md", "S1")], edges=[])
        gaps = _find_knowledge_gaps(
            graph, [_community(7, ["wiki/s0.md", "wiki/s1.md"], cohesion=0.1)]
        )
        assert all(g.gap_type != "sparse_community" for g in gaps)

    def test_bridge_node_spanning_two_foreign_communities_high(self):
        # X ∈ A，连到 B 社区 1 个节点 + C 社区 1 个节点 → 桥节点
        graph = GraphData(
            nodes=[_node("wiki/x.md", "X"), _node("wiki/b.md", "B"), _node("wiki/c.md", "C")],
            edges=[_edge("wiki/x.md", "wiki/b.md"), _edge("wiki/x.md", "wiki/c.md")],
        )
        communities = [
            _community(0, ["wiki/x.md"]),
            _community(1, ["wiki/b.md"]),
            _community(2, ["wiki/c.md"]),
        ]
        gaps = _find_knowledge_gaps(graph, communities)
        bridges = [g for g in gaps if g.gap_type == "bridge_node"]
        assert len(bridges) == 1
        assert bridges[0].node_id == "wiki/x.md"
        assert bridges[0].severity == "high"

    def test_single_foreign_community_not_bridge(self):
        graph = GraphData(
            nodes=[_node("wiki/x.md", "X"), _node("wiki/b.md", "B")],
            edges=[_edge("wiki/x.md", "wiki/b.md")],
        )
        communities = [_community(0, ["wiki/x.md"]), _community(1, ["wiki/b.md"])]
        gaps = _find_knowledge_gaps(graph, communities)
        assert all(g.gap_type != "bridge_node" for g in gaps)

    def test_sorted_high_medium_low(self):
        graph = GraphData(
            nodes=[
                _node("wiki/x.md", "X"),
                _node("wiki/b.md", "B"),
                _node("wiki/c.md", "C"),
                _node("wiki/alone.md", "孤立页"),
            ],
            edges=[_edge("wiki/x.md", "wiki/b.md"), _edge("wiki/x.md", "wiki/c.md")],
        )
        communities = [
            _community(0, ["wiki/x.md"]),
            _community(1, ["wiki/b.md"]),
            _community(2, ["wiki/c.md"]),
        ]
        gaps = _find_knowledge_gaps(graph, communities)
        severities = [g.severity for g in gaps]
        assert severities == sorted(severities, key=lambda s: {"high": 0, "medium": 1, "low": 2}[s])


# --------------------------------------------------------------------------- #
# 端到端（tmp 真实项目）
# --------------------------------------------------------------------------- #


def _write_page(root, name: str, title: str, page_type: str, links: List[str]) -> None:
    body = "\n".join(f"参见 [[{t}]] 的相关内容。" for t in links)
    (root / "wiki").mkdir(exist_ok=True)
    (root / "wiki" / name).write_text(
        f"---\ntitle: {title}\npage_type: {page_type}\n---\n# {title}\n{body}\n",
        encoding="utf-8",
        newline="",
    )


class TestAnalyzeGraphEndToEnd:
    def test_clusters_cross_link_and_orphan(self, tmp_path):
        _write_page(tmp_path, "a1.md", "主题甲一", "concept", ["主题甲二", "主题乙一"])
        _write_page(tmp_path, "a2.md", "主题甲二", "concept", ["主题甲一"])
        _write_page(tmp_path, "b1.md", "主题乙一", "source", ["主题乙二"])
        _write_page(tmp_path, "b2.md", "主题乙二", "source", ["主题乙一"])
        _write_page(tmp_path, "orphan.md", "孤岛页", "concept", [])

        insights = analyze_graph(tmp_path)

        assert insights.stats["total_nodes"] == 5
        assert insights.stats["total_edges"] > 0
        # 跨簇链接 a1→b1 + concept↔source 类型不匹配 → 至少一条惊人联系
        assert insights.stats["surprising_connections"] > 0
        assert insights.stats["knowledge_gaps"] > 0

        # 孤立页必入 isolated_node
        iso_ids = {g.node_id for g in insights.knowledge_gaps if isinstance(g, KnowledgeGap)}
        assert "wiki/orphan.md" in iso_ids

        # label 取 frontmatter title
        labels = {s.target_label for s in insights.surprising_connections}
        assert any("\u4e3b\u9898" in lbl for lbl in labels if lbl)

        # 无 index/log/schema 页 → 节点总数即页面数
        assert insights.stats["total_nodes"] == 5

    def test_empty_project_returns_empty_insights(self, tmp_path):
        insights = analyze_graph(tmp_path)
        assert insights.stats["total_nodes"] == 0
        assert insights.surprising_connections == []
        assert insights.knowledge_gaps == []
