"""Wiki MCP Server - 暴露 Wiki 功能给外部 Agent。

实现 7 个 MCP 工具，让 Claude 等外部 Agent 能查询 Sage Wiki。
"""

import json
import logging
from pathlib import Path
from typing import Any

from backend.wiki import (
    build_graph,
    get_graph_cached,
    search_wiki,
)
from backend.wiki.community import detect_communities
from backend.wiki.insights import analyze_graph
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

logger = logging.getLogger(__name__)

# 创建 MCP Server 实例
server = Server("sage-wiki")


# ============================================================================
# MCP 工具定义
# ============================================================================


@server.list_tools()
async def list_tools() -> list[Tool]:
    """列出所有可用的 Wiki 工具。"""
    return [
        Tool(
            name="wiki_status",
            description="获取 Wiki 状态信息（项目数、文件数、图谱节点数等）",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {
                        "type": "string",
                        "description": "Wiki 项目根目录路径",
                    }
                },
                "required": ["project_path"],
            },
        ),
        Tool(
            name="wiki_files",
            description="列出 Wiki 项目中的文件",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {
                        "type": "string",
                        "description": "Wiki 项目根目录路径",
                    },
                    "path": {
                        "type": "string",
                        "description": "相对路径（默认为空，列出根目录）",
                        "default": "",
                    },
                },
                "required": ["project_path"],
            },
        ),
        Tool(
            name="wiki_search",
            description="搜索 Wiki 内容",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {
                        "type": "string",
                        "description": "Wiki 项目根目录路径",
                    },
                    "query": {
                        "type": "string",
                        "description": "搜索查询",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回数量上限（默认 20）",
                        "default": 20,
                    },
                },
                "required": ["project_path", "query"],
            },
        ),
        Tool(
            name="wiki_read",
            description="读取指定的 Wiki 页面",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {
                        "type": "string",
                        "description": "Wiki 项目根目录路径",
                    },
                    "path": {
                        "type": "string",
                        "description": "页面相对路径（如 'wiki/sources/test.md'）",
                    },
                },
                "required": ["project_path", "path"],
            },
        ),
        Tool(
            name="wiki_graph",
            description="获取知识图谱数据",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {
                        "type": "string",
                        "description": "Wiki 项目根目录路径",
                    },
                    "query": {
                        "type": "string",
                        "description": "可选查询（过滤节点）",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "节点数量上限（默认 100）",
                        "default": 100,
                    },
                },
                "required": ["project_path"],
            },
        ),
        Tool(
            name="wiki_communities",
            description="获取社区检测结果（Louvain 算法）",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {
                        "type": "string",
                        "description": "Wiki 项目根目录路径",
                    }
                },
                "required": ["project_path"],
            },
        ),
        Tool(
            name="wiki_insights",
            description="获取图谱洞察（惊人联系 + 知识缺口）",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {
                        "type": "string",
                        "description": "Wiki 项目根目录路径",
                    }
                },
                "required": ["project_path"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:  # noqa: PLR0911
    """调用指定的 Wiki 工具。"""
    try:
        if name == "wiki_status":
            return await _wiki_status(arguments)
        elif name == "wiki_files":
            return await _wiki_files(arguments)
        elif name == "wiki_search":
            return await _wiki_search(arguments)
        elif name == "wiki_read":
            return await _wiki_read(arguments)
        elif name == "wiki_graph":
            return await _wiki_graph(arguments)
        elif name == "wiki_communities":
            return await _wiki_communities(arguments)
        elif name == "wiki_insights":
            return await _wiki_insights(arguments)
        else:
            return [TextContent(type="text", text=f"未知工具: {name}")]
    except Exception as e:
        logger.error(f"Wiki MCP 工具 '{name}' 执行失败: {e}")
        return [TextContent(type="text", text=f"错误: {str(e)}")]


# ============================================================================
# 工具实现
# ============================================================================


async def _wiki_status(args: dict[str, Any]) -> list[TextContent]:
    """获取 Wiki 状态信息。"""
    project_path = Path(args["project_path"])

    if not project_path.exists():
        return [TextContent(type="text", text=f"项目路径不存在: {project_path}")]

    # 统计文件数
    wiki_dir = project_path / "wiki"
    wiki_files = list(wiki_dir.rglob("*.md")) if wiki_dir.exists() else []

    raw_dir = project_path / "raw" / "sources"
    source_files = list(raw_dir.rglob("*")) if raw_dir.exists() else []

    # 构建图谱统计
    graph_data = build_graph(project_path)

    status = {
        "project_path": str(project_path),
        "wiki_pages": len(wiki_files),
        "source_files": len(source_files),
        "graph_nodes": len(graph_data.nodes),
        "graph_edges": len(graph_data.edges),
    }

    return [TextContent(type="text", text=json.dumps(status, indent=2, ensure_ascii=False))]


async def _wiki_files(args: dict[str, Any]) -> list[TextContent]:
    """列出 Wiki 项目中的文件。"""
    project_path = Path(args["project_path"])
    relative_path = args.get("path", "")

    target_dir = project_path / relative_path if relative_path else project_path

    if not target_dir.exists():
        return [TextContent(type="text", text=f"路径不存在: {target_dir}")]

    if not target_dir.is_dir():
        return [TextContent(type="text", text=f"不是目录: {target_dir}")]

    files = []
    for item in sorted(target_dir.iterdir()):
        if item.name.startswith("."):
            continue

        files.append(
            {
                "name": item.name,
                "path": str(item.relative_to(project_path)).replace("\\", "/"),
                "is_dir": item.is_dir(),
            }
        )

    return [TextContent(type="text", text=json.dumps(files, indent=2, ensure_ascii=False))]


async def _wiki_search(args: dict[str, Any]) -> list[TextContent]:
    """搜索 Wiki 内容。"""
    project_path = Path(args["project_path"])
    query = args["query"]
    limit = args.get("limit", 20)

    results = search_wiki(project_path, query, limit)

    return [
        TextContent(
            type="text",
            text=json.dumps(
                {
                    "query": query,
                    "total": results.total,
                    "results": [
                        {
                            "path": r.path,
                            "title": r.title,
                            "snippet": r.snippet,
                            "score": r.score,
                        }
                        for r in results.results
                    ],
                },
                indent=2,
                ensure_ascii=False,
            ),
        )
    ]


async def _wiki_read(args: dict[str, Any]) -> list[TextContent]:
    """读取指定的 Wiki 页面。"""
    project_path = Path(args["project_path"])
    relative_path = args["path"]

    file_path = project_path / relative_path

    if not file_path.exists():
        return [TextContent(type="text", text=f"文件不存在: {file_path}")]

    content = file_path.read_text(encoding="utf-8")

    return [
        TextContent(
            type="text",
            text=json.dumps(
                {
                    "path": relative_path,
                    "content": content,
                },
                indent=2,
                ensure_ascii=False,
            ),
        )
    ]


async def _wiki_graph(args: dict[str, Any]) -> list[TextContent]:
    """获取知识图谱数据。"""
    project_path = Path(args["project_path"])
    query = args.get("query")
    limit = args.get("limit", 100)

    graph_data = get_graph_cached(project_path, query, limit)

    return [
        TextContent(
            type="text",
            text=json.dumps(
                {
                    "nodes": [
                        {
                            "id": n.id,
                            "label": n.label,
                            "page_type": n.page_type,
                            "sources": n.sources,
                            "wikilinks": n.wikilinks,
                        }
                        for n in graph_data.nodes
                    ],
                    "edges": [
                        {
                            "source": e.source,
                            "target": e.target,
                            "signal": e.signal.value,
                            "weight": e.weight,
                        }
                        for e in graph_data.edges
                    ],
                },
                indent=2,
                ensure_ascii=False,
            ),
        )
    ]


async def _wiki_communities(args: dict[str, Any]) -> list[TextContent]:
    """获取社区检测结果。"""
    project_path = Path(args["project_path"])

    graph_data = build_graph(project_path)
    communities = detect_communities(graph_data)

    return [
        TextContent(
            type="text",
            text=json.dumps(
                {
                    "total_communities": len(communities),
                    "communities": [
                        {
                            "community_id": c.community_id,
                            "size": c.size,
                            "cohesion": c.cohesion,
                            "members": c.members,
                        }
                        for c in communities
                    ],
                },
                indent=2,
                ensure_ascii=False,
            ),
        )
    ]


async def _wiki_insights(args: dict[str, Any]) -> list[TextContent]:
    """获取图谱洞察。"""
    project_path = Path(args["project_path"])

    insights = analyze_graph(project_path)

    return [
        TextContent(
            type="text",
            text=json.dumps(
                {
                    "stats": insights.stats,
                    "surprising_connections": [
                        {
                            "source_id": s.source_id,
                            "source_label": s.source_label,
                            "target_id": s.target_id,
                            "target_label": s.target_label,
                            "reason": s.reason,
                            "strength": s.strength,
                        }
                        for s in insights.surprising_connections
                    ],
                    "knowledge_gaps": [
                        {
                            "gap_type": g.gap_type,
                            "node_id": g.node_id,
                            "node_label": g.node_label,
                            "description": g.description,
                            "severity": g.severity,
                            "suggestion": g.suggestion,
                        }
                        for g in insights.knowledge_gaps
                    ],
                },
                indent=2,
                ensure_ascii=False,
            ),
        )
    ]


# ============================================================================
# 启动函数
# ============================================================================


async def run_wiki_mcp_server() -> None:
    """运行 Wiki MCP Server。"""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    import asyncio

    asyncio.run(run_wiki_mcp_server())
