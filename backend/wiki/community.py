"""Louvain 社区检测。

使用 networkx 实现 Louvain 算法，检测知识图谱中的社区结构，
并计算每个社区的凝聚度（intra-community edge density）。
"""
from typing import List, Tuple

import logging
from dataclasses import dataclass
from pathlib import Path

import networkx as nx

from .graph import build_graph
from .models import GraphData

logger = logging.getLogger(__name__)


@dataclass
class CommunityInfo:
    """社区信息。"""

    community_id: int
    members: List[str]  # 节点 ID 列表
    cohesion: float  # 凝聚度 (0-1)
    size: int


def detect_communities(graph_data: GraphData) -> List[CommunityInfo]:
    """检测图谱中的社区结构。

    使用 Louvain 算法进行社区检测，并计算每个社区的凝聚度。

    Args:
        graph_data: 图谱数据

    Returns:
        list[CommunityInfo]: 社区信息列表，按凝聚度降序排序
    """
    if not graph_data.nodes:
        return []

    # 构建 networkx 图
    G = nx.Graph()

    # 添加节点
    for node in graph_data.nodes:
        G.add_node(node.id)

    # 添加边（使用权重）
    for edge in graph_data.edges:
        # 避免重复边（networkx 会自动处理）
        if G.has_edge(edge.source, edge.target):
            # 如果边已存在，取最大权重
            existing_weight = G[edge.source][edge.target].get("weight", 0)
            G[edge.source][edge.target]["weight"] = max(existing_weight, edge.weight)
        else:
            G.add_edge(edge.source, edge.target, weight=edge.weight)

    # 执行 Louvain 社区检测
    try:
        communities = nx.community.louvain_communities(G, seed=42)
    except Exception as e:
        logger.error(f"Louvain 社区检测失败: {e}")
        return []

    # 计算每个社区的凝聚度
    community_infos = []
    for idx, community_nodes in enumerate(communities):
        members = list(community_nodes)
        size = len(members)

        # 计算凝聚度：社区内边数 / 可能的最大边数
        cohesion = _calculate_cohesion(G, members)

        community_infos.append(
            CommunityInfo(
                community_id=idx,
                members=members,
                cohesion=cohesion,
                size=size,
            )
        )

    # 按凝聚度降序排序
    community_infos.sort(key=lambda c: c.cohesion, reverse=True)

    logger.info(f"检测到 {len(community_infos)} 个社区")
    return community_infos


def _calculate_cohesion(graph: nx.Graph, members: List[str]) -> float:
    """计算社区的凝聚度。

    凝聚度 = 社区内实际边数 / 社区内可能的最大边数

    Args:
        graph: networkx 图
        members: 社区成员节点列表

    Returns:
        float: 凝聚度 (0-1)
    """
    if len(members) < 2:
        return 0.0

    # 计算社区内实际边数
    internal_edges = 0
    member_set = set(members)

    for node in members:
        for neighbor in graph.neighbors(node):
            if neighbor in member_set:
                internal_edges += 1

    # 每条边被计算了两次（无向图），所以除以 2
    internal_edges //= 2

    # 计算可能的最大边数：n * (n-1) / 2
    n = len(members)
    max_possible_edges = n * (n - 1) // 2

    if max_possible_edges == 0:
        return 0.0

    cohesion = internal_edges / max_possible_edges
    return round(cohesion, 4)


def get_communities_with_nodes(
    project_root: Path,
) -> Tuple[List[CommunityInfo], GraphData]:
    """获取社区信息及其对应的图谱数据。

    这是一个便捷函数，同时返回社区信息和图谱数据，
    方便前端进行可视化。

    Args:
        project_root: 项目根目录

    Returns:
        tuple[list[CommunityInfo], GraphData]: (社区信息列表, 图谱数据)
    """
    graph_data = build_graph(project_root)
    communities = detect_communities(graph_data)
    return communities, graph_data
