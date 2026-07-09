"""Graph Insights - 图谱洞察。

实现惊人联系发现和知识缺口分析，帮助用户发现知识库中的有趣模式和潜在问题。
"""

import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import List

from .community import CommunityInfo, detect_communities
from .graph import build_graph
from .models import GraphData

logger = logging.getLogger(__name__)


@dataclass
class SurprisingConnection:
    """惊人联系。"""

    source_id: str
    source_label: str
    target_id: str
    target_label: str
    reason: str  # 为什么这个连接是惊人的
    strength: float  # 0-1，表示这个连接有多惊人


@dataclass
class KnowledgeGap:
    """知识缺口。"""

    gap_type: str  # "isolated_node" | "sparse_community" | "bridge_node"
    node_id: str
    node_label: str
    description: str
    severity: str  # "low" | "medium" | "high"
    suggestion: str  # 建议如何填补这个缺口


@dataclass
class GraphInsights:
    """图谱洞察结果。"""

    surprising_connections: List[SurprisingConnection]
    knowledge_gaps: List[KnowledgeGap]
    stats: dict  # 统计信息


def analyze_graph(project_root: Path) -> GraphInsights:
    """分析图谱，生成洞察。

    Args:
        project_root: 项目根目录

    Returns:
        GraphInsights: 包含惊人联系和知识缺口的洞察结果
    """
    graph_data = build_graph(project_root)
    communities = detect_communities(graph_data)

    surprising = _find_surprising_connections(graph_data, communities)
    gaps = _find_knowledge_gaps(graph_data, communities)

    stats = {
        "total_nodes": len(graph_data.nodes),
        "total_edges": len(graph_data.edges),
        "total_communities": len(communities),
        "surprising_connections": len(surprising),
        "knowledge_gaps": len(gaps),
    }

    return GraphInsights(
        surprising_connections=surprising,
        knowledge_gaps=gaps,
        stats=stats,
    )


def _find_surprising_connections(
    graph_data: GraphData, communities: List[CommunityInfo]
) -> List[SurprisingConnection]:
    """发现惊人联系。

    惊人联系包括：
    1. 跨社区边（不同社区的节点相连）
    2. 类型不匹配（不同类型节点相连）
    3. 边缘到中心连接（低度节点连接到高度节点）

    Args:
        graph_data: 图谱数据
        communities: 社区信息列表

    Returns:
        list[SurprisingConnection]: 惊人联系列表
    """
    surprising = []

    # 构建节点到社区的映射
    node_to_community = {}
    for community in communities:
        for member_id in community.members:
            node_to_community[member_id] = community.community_id

    # 构建节点映射
    node_map = {node.id: node for node in graph_data.nodes}

    # 计算节点度数
    degree = defaultdict(int)
    for edge in graph_data.edges:
        degree[edge.source] += 1
        degree[edge.target] += 1

    # 分析每条边
    for edge in graph_data.edges:
        source_node = node_map.get(edge.source)
        target_node = node_map.get(edge.target)

        if not source_node or not target_node:
            continue

        # 1. 跨社区边
        source_community = node_to_community.get(edge.source)
        target_community = node_to_community.get(edge.target)

        if (
            source_community is not None
            and target_community is not None
            and source_community != target_community
        ):
            surprising.append(
                SurprisingConnection(
                    source_id=edge.source,
                    source_label=source_node.label,
                    target_id=edge.target,
                    target_label=target_node.label,
                    reason=f"跨社区连接（社区 {source_community} ↔ 社区 {target_community}）",
                    strength=0.8,
                )
            )

        # 2. 类型不匹配
        if (
            source_node.page_type
            and target_node.page_type
            and source_node.page_type != target_node.page_type
        ):
            surprising.append(
                SurprisingConnection(
                    source_id=edge.source,
                    source_label=source_node.label,
                    target_id=edge.target,
                    target_label=target_node.label,
                    reason=f"类型不匹配（{source_node.page_type} ↔ {target_node.page_type}）",
                    strength=0.6,
                )
            )

        # 3. 边缘到中心连接（度数差异大）
        source_degree = degree[edge.source]
        target_degree = degree[edge.target]
        max_degree = max(source_degree, target_degree)
        min_degree = min(source_degree, target_degree)

        if max_degree >= 5 and min_degree <= 1:
            surprising.append(
                SurprisingConnection(
                    source_id=edge.source,
                    source_label=source_node.label,
                    target_id=edge.target,
                    target_label=target_node.label,
                    reason=f"边缘到中心连接（度数 {min_degree} ↔ {max_degree}）",
                    strength=0.7,
                )
            )

    # 按强度降序排序
    surprising.sort(key=lambda s: s.strength, reverse=True)

    return surprising


def _find_knowledge_gaps(
    graph_data: GraphData, communities: List[CommunityInfo]
) -> List[KnowledgeGap]:
    """发现知识缺口。

    知识缺口包括：
    1. 孤立节点（无边）
    2. 稀疏社区（低凝聚度）
    3. 桥节点（连接多个社区的关键节点）

    Args:
        graph_data: 图谱数据
        communities: 社区信息列表

    Returns:
        list[KnowledgeGap]: 知识缺口列表
    """
    gaps = []

    # 构建节点映射
    node_map = {node.id: node for node in graph_data.nodes}

    # 计算节点度数
    degree = defaultdict(int)
    for edge in graph_data.edges:
        degree[edge.source] += 1
        degree[edge.target] += 1

    # 1. 孤立节点
    for node in graph_data.nodes:
        if degree[node.id] == 0:
            gaps.append(
                KnowledgeGap(
                    gap_type="isolated_node",
                    node_id=node.id,
                    node_label=node.label,
                    description=f"节点 '{node.label}' 没有任何连接",
                    severity="medium",
                    suggestion=f"考虑添加与 '{node.label}' 相关的页面，或检查是否应该删除此页面",
                )
            )

    # 2. 稀疏社区
    for community in communities:
        if community.size >= 3 and community.cohesion < 0.3:
            gaps.append(
                KnowledgeGap(
                    gap_type="sparse_community",
                    node_id=f"community_{community.community_id}",
                    node_label=f"社区 {community.community_id}",
                    description=f"社区 {community.community_id} 凝聚度较低（{community.cohesion:.2f}），包含 {community.size} 个节点",
                    severity="low",
                    suggestion="考虑在这些节点之间添加更多关联，或者重新组织这些页面",
                )
            )

    # 3. 桥节点（连接多个社区）
    node_to_community = {}
    for community in communities:
        for member_id in community.members:
            node_to_community[member_id] = community.community_id

    # 找出连接不同社区的节点
    bridge_nodes = defaultdict(set)
    for edge in graph_data.edges:
        source_community = node_to_community.get(edge.source)
        target_community = node_to_community.get(edge.target)

        if (
            source_community is not None
            and target_community is not None
            and source_community != target_community
        ):
            bridge_nodes[edge.source].add(target_community)
            bridge_nodes[edge.target].add(source_community)

    for node_id, connected_communities in bridge_nodes.items():
        if len(connected_communities) >= 2:
            node = node_map.get(node_id)
            if node:
                gaps.append(
                    KnowledgeGap(
                        gap_type="bridge_node",
                        node_id=node_id,
                        node_label=node.label,
                        description=f"节点 '{node.label}' 连接了 {len(connected_communities)} 个社区",
                        severity="high",
                        suggestion=f"'{node.label}' 是关键桥节点，确保其内容准确且完整",
                    )
                )

    # 按严重性排序（high > medium > low）
    severity_order = {"high": 0, "medium": 1, "low": 2}
    gaps.sort(key=lambda g: severity_order.get(g.severity, 3))

    return gaps
