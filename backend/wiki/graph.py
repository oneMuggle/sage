"""4 信号知识图谱。

实现 4 信号图谱构建：DirectLink、SourceOverlap、TypeAffinity，以及 2-hop 相关性传播。
"""

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import frontmatter
from .models import GraphData, GraphEdge, GraphNode, GraphSignal

# 常量
DIRECT_LINK_WEIGHT = 3.0
SOURCE_OVERLAP_WEIGHT = 4.0
TYPE_AFFINITY_WEIGHT = 1.0
DECAY = 0.5
K_HOPS = 2


def build_graph(project_root: Path) -> GraphData:
    """构建知识图谱。

    Args:
        project_root: 项目根目录

    Returns:
        GraphData: 图谱数据
    """
    wiki_dir = project_root / "wiki"
    if not wiki_dir.exists():
        return GraphData(nodes=[], edges=[])

    # Step 1: 收集节点
    nodes = []
    node_map = {}  # id → GraphNode

    for md_file in wiki_dir.rglob("*.md"):
        # 跳过隐藏目录
        if any(part.startswith(".") for part in md_file.parts):
            continue

        # 跳过特殊文件
        if md_file.name in ("index.md", "log.md", "schema.md"):
            continue

        # 读取内容
        content = md_file.read_text(encoding="utf-8")
        parsed = frontmatter.parse(content)

        # 提取标题
        title = parsed.frontmatter.title or _extract_title_from_body(parsed.body)

        # 提取 wikilinks
        wikilinks = frontmatter.extract_wikilinks(content)
        wikilinks.extend(parsed.frontmatter.related)
        wikilinks = list(set(wikilinks))  # 去重

        # 创建节点
        node_id = str(md_file.relative_to(project_root)).replace("\\", "/")
        node = GraphNode(
            id=node_id,
            label=title,
            page_type=parsed.frontmatter.page_type,
            sources=parsed.frontmatter.sources,
            wikilinks=wikilinks,
        )

        nodes.append(node)
        node_map[node_id] = node

    # Step 2: 构建边
    edges = []
    edge_set = set()  # (source, target, signal) → 去重

    # Signal 1: DirectLink
    for node in nodes:
        for wikilink in node.wikilinks:
            # 解析 wikilink 到目标节点
            target = _resolve_wikilink(wikilink, node_map)
            if target and target.id != node.id:
                edge_key = (node.id, target.id, GraphSignal.DirectLink)
                if edge_key not in edge_set:
                    edges.append(
                        GraphEdge(
                            source=node.id,
                            target=target.id,
                            signal=GraphSignal.DirectLink,
                            weight=DIRECT_LINK_WEIGHT,
                        )
                    )
                    edge_set.add(edge_key)

    # Signal 2: SourceOverlap
    for i, node_a in enumerate(nodes):
        if not node_a.sources:
            continue

        for node_b in nodes[i + 1 :]:
            if not node_b.sources:
                continue

            # 计算共享 sources
            shared = len(set(node_a.sources) & set(node_b.sources))
            if shared > 0:
                weight = (
                    shared / max(len(node_a.sources), len(node_b.sources))
                ) * SOURCE_OVERLAP_WEIGHT

                # 双向边
                for source, target in [(node_a, node_b), (node_b, node_a)]:
                    edge_key = (source.id, target.id, GraphSignal.SourceOverlap)
                    if edge_key not in edge_set:
                        edges.append(
                            GraphEdge(
                                source=source.id,
                                target=target.id,
                                signal=GraphSignal.SourceOverlap,
                                weight=weight,
                            )
                        )
                        edge_set.add(edge_key)

    # Signal 3: TypeAffinity
    type_groups = defaultdict(list)
    for node in nodes:
        if node.page_type:
            type_groups[node.page_type].append(node)

    for _page_type, group in type_groups.items():
        for i, node_a in enumerate(group):
            for node_b in group[i + 1 :]:
                # 双向边
                for source, target in [(node_a, node_b), (node_b, node_a)]:
                    edge_key = (source.id, target.id, GraphSignal.TypeAffinity)
                    if edge_key not in edge_set:
                        edges.append(
                            GraphEdge(
                                source=source.id,
                                target=target.id,
                                signal=GraphSignal.TypeAffinity,
                                weight=TYPE_AFFINITY_WEIGHT,
                            )
                        )
                        edge_set.add(edge_key)

    return GraphData(nodes=nodes, edges=edges)


def relevance(query: str, graph: GraphData, k_hops: int = K_HOPS) -> List[Tuple[str, float]]:
    """计算节点相关性（2-hop 传播）。

    Args:
        query: 查询字符串
        graph: 图谱数据
        k_hops: 传播跳数

    Returns:
        list[tuple[str, float]]: (node_id, score) 列表，按 score 降序
    """
    if not query:
        return []

    query_lower = query.lower()

    # 找到种子节点
    seeds = []
    for node in graph.nodes:
        if query_lower in node.label.lower() or query_lower in node.id.lower():
            seeds.append(node.id)

    if not seeds:
        return []

    # BFS 传播
    scores: Dict[str, float] = {seed: 1.0 for seed in seeds}
    frontier = set(seeds)

    # 构建邻接表
    adjacency = defaultdict(list)
    for edge in graph.edges:
        adjacency[edge.source].append((edge.target, edge.weight))

    for _ in range(k_hops):
        next_frontier = set()

        for node_id in frontier:
            current_score = scores[node_id]

            for target, weight in adjacency[node_id]:
                new_score = current_score * weight * DECAY

                if new_score > scores.get(target, 0.0):
                    scores[target] = new_score
                    next_frontier.add(target)

        frontier = next_frontier
        if not frontier:
            break

    # 排序
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def get_graph_cached(
    project_root: Path, query: Optional[str] = None, limit: int = 100
) -> GraphData:
    """Build or load the wiki graph, with mtime-based cache.

    Cache stores the FULL unfiltered graph; query/limit filtering is
    applied on every read so changing either is free (no rebuild).

    Cache key: max mtime of wiki/**/*.md (changes to wiki files only).
    Cache file: {project_root}/.llm-wiki/graph-cache.json

    Args:
        project_root: 项目根目录
        query: 可选查询（过滤节点）
        limit: 节点数量上限

    Returns:
        GraphData: 图谱数据
    """
    cache_path = project_root / ".llm-wiki" / "graph-cache.json"
    wiki_dir = project_root / "wiki"

    # Early return when wiki dir does not exist — never write a useless
    # cache file in that case (Important #2 fix).
    if not wiki_dir.exists():
        return build_graph(project_root)

    latest_mtime = max(
        (p.stat().st_mtime for p in wiki_dir.rglob("*.md") if p.is_file()),
        default=0.0,
    )

    graph: Optional[GraphData] = None
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            # Match on mtime only — query/limit are filtered at read time
            # (Important #1 fix).
            if cache.get("latest_mtime") == latest_mtime:
                graph = _deserialize_graph_data(cache["data"])
        except (json.JSONDecodeError, KeyError, OSError):
            pass  # corrupt cache, rebuild

    if graph is None:
        graph = build_graph(project_root)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "latest_mtime": latest_mtime,
                    "data": _serialize_graph_data(graph),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    # Apply query/limit filtering at call time so the cached full graph
    # is reused for different queries/limits (Important #1 fix).
    if query:
        ranked = relevance(query, graph)
        top_ids = {node_id for node_id, _ in ranked[:limit]}
        filtered_nodes = [n for n in graph.nodes if n.id in top_ids]
        filtered_edges = [e for e in graph.edges if e.source in top_ids and e.target in top_ids]
        return GraphData(nodes=filtered_nodes, edges=filtered_edges)

    if len(graph.nodes) > limit:
        return GraphData(nodes=graph.nodes[:limit], edges=graph.edges)

    return graph


def _serialize_graph_data(graph: GraphData) -> Dict[str, Any]:
    """Serialize GraphData to a JSON-compatible dict."""
    return {
        "nodes": [
            {
                "id": n.id,
                "label": n.label,
                "page_type": n.page_type,
                "sources": list(n.sources),
                "wikilinks": list(n.wikilinks),
            }
            for n in graph.nodes
        ],
        "edges": [
            {
                "source": e.source,
                "target": e.target,
                "signal": e.signal.value,
                "weight": e.weight,
            }
            for e in graph.edges
        ],
    }


def _deserialize_graph_data(data: Dict[str, Any]) -> GraphData:
    """Deserialize a dict (from cache JSON) back into GraphData."""
    return GraphData(
        nodes=[
            GraphNode(
                id=n["id"],
                label=n["label"],
                page_type=n.get("page_type"),
                sources=list(n.get("sources", [])),
                wikilinks=list(n.get("wikilinks", [])),
            )
            for n in data.get("nodes", [])
        ],
        edges=[
            GraphEdge(
                source=e["source"],
                target=e["target"],
                signal=GraphSignal(e["signal"]),
                weight=e["weight"],
            )
            for e in data.get("edges", [])
        ],
    )


def _resolve_wikilink(wikilink: str, node_map: Dict[str, GraphNode]) -> GraphNode | None:
    """解析 wikilink 到目标节点。"""
    wikilink_lower = wikilink.lower()

    # 1. 精确 label 匹配
    for node in node_map.values():
        if node.label.lower() == wikilink_lower:
            return node

    # 2. 精确 id 匹配
    if wikilink in node_map:
        return node_map[wikilink]

    # 3. Slug 匹配
    wikilink_slug = _slugify(wikilink)
    for node in node_map.values():
        node_slug = _slugify(node.label)
        if node_slug == wikilink_slug:
            return node

    return None


def _slugify(text: str) -> str:
    """将文本转换为 slug。"""
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


def _extract_title_from_body(body: str) -> str:
    """从 body 提取标题。"""
    for raw_line in body.split("\n"):
        line = raw_line.strip()
        if line.startswith("# "):
            return line[2:].strip()
        if line.startswith("## "):
            return line[3:].strip()
        if line and not line.startswith("---"):
            return line[:80]

    return "未命名页面"
