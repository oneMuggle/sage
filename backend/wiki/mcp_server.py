"""Wiki MCP Server - 暴露 Wiki 功能给外部 Agent。

实现 7 个 MCP 工具，让 Claude 等外部 Agent 能查询 Sage Wiki。
"""

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from fastapi import HTTPException

from backend.api.wiki_routes import _canonical_project_root, _resolve_project_file
from backend.storage.recent_projects import load_recent
from backend.wiki import (
    build_graph,
    get_graph_cached,
    search_wiki,
)
from backend.wiki.community import detect_communities
from backend.wiki.files import (
    _require_posix_safety,
    is_reparse_point,
    iter_wiki_markdown,
    secure_read_text,
)
from backend.wiki.insights import analyze_graph

logger = logging.getLogger(__name__)

# MCP is an optional runtime feature.  Importing its server package can fail
# when an installed MCP release is incompatible with the backend's Pydantic
# pin, so keep the wiki helpers importable for the regular backend and tests.
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import TextContent, Tool
except Exception as exc:  # noqa: BLE001 — optional integration must not break backend
    Server = None  # type: ignore[assignment,misc]
    stdio_server = None  # type: ignore[assignment]
    _MCP_IMPORT_ERROR = exc

    class TextContent:  # type: ignore[no-redef]
        """Small fallback used by wiki helpers when MCP is unavailable."""

        def __init__(self, *, type: str, text: str):
            self.type = type
            self.text = text

    @dataclass
    class Tool:  # type: ignore[no-redef]
        """Fallback tool descriptor for helper tests without MCP."""

        name: str
        description: str
        inputSchema: Dict[str, Any]  # noqa: N815 — MCP protocol field name
else:
    _MCP_IMPORT_ERROR = None

try:
    server = Server("sage-wiki") if _MCP_IMPORT_ERROR is None else None
except Exception as exc:  # noqa: BLE001 — optional integration must not break backend
    server = None
    _MCP_IMPORT_ERROR = exc


def _handler_decorator(method_name: str):
    """Return an MCP decorator, or an identity decorator without MCP."""
    if server is None:
        return lambda function: function
    return getattr(server, method_name)()


def _require_mcp_runtime() -> None:
    """Raise an actionable error when the optional MCP runtime is unavailable."""
    if _MCP_IMPORT_ERROR is not None:
        raise RuntimeError(
            "Wiki MCP server requires a compatible 'mcp' installation; "
            f"import failed with {type(_MCP_IMPORT_ERROR).__name__}: {_MCP_IMPORT_ERROR}"
        ) from _MCP_IMPORT_ERROR


_MCP_PROJECT_ROOTS_ENV = "SAGE_MCP_WIKI_PROJECT_ROOTS"


def _recheck_project_tree(root: Path) -> None:
    """Recheck symlinks immediately before recursive reads.

    This is defense-in-depth, not an atomic TOCTOU guarantee: without
    platform-specific directory-handle APIs, the tree can still change after
    this check and before a later filesystem operation.
    """
    try:
        if is_reparse_point(root):
            raise HTTPException(status_code=400, detail="项目目录包含不安全的重解析点")
        for current, directories, files in os.walk(root, followlinks=False):
            if any(
                Path(current, name).is_symlink() for name in directories + files
            ):
                raise HTTPException(status_code=400, detail="项目目录不能包含符号链接")
            if any(
                is_reparse_point(Path(current, name))
                for name in directories + files
            ):
                raise HTTPException(status_code=400, detail="项目目录包含不安全的重解析点")
    except OSError as exc:
        raise HTTPException(status_code=400, detail="项目路径无效") from exc


def _authorized_project_root(project_path: str) -> Path:
    """Canonicalize and authorize a project root for every MCP operation.

    MCP runs as an external process, so accepting an arbitrary path would turn
    the read-only Wiki tools into a general filesystem browser (and make any
    future write tool unsafe).  Authorization is explicit: roots listed in
    ``SAGE_MCP_WIKI_PROJECT_ROOTS`` or roots already recorded by the Wiki
    project picker are accepted.  With neither source configured, access is
    denied (fail closed).
    """
    root = _canonical_project_root(project_path)
    configured: set[str] = set()
    for item in os.environ.get(_MCP_PROJECT_ROOTS_ENV, "").split(os.pathsep):
        if not item.strip():
            continue
        try:
            configured.add(_canonical_project_root(item).as_posix())
        except HTTPException:
            continue

    registered: set[str] = set()
    for item in load_recent():
        if not item.path:
            continue
        try:
            registered.add(_canonical_project_root(item.path).as_posix())
        except HTTPException:
            continue
    if root.as_posix() not in configured | registered:
        raise HTTPException(status_code=403, detail="项目根未获 MCP 授权")

    # Do not allow a symlink anywhere in the project tree to be followed by
    # graph/search implementations which recursively enumerate files.
    _recheck_project_tree(root)
    return root


# ============================================================================
# MCP 工具定义
# ============================================================================


@_handler_decorator("list_tools")
async def list_tools() -> List[Tool]:
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


@_handler_decorator("call_tool")
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:  # noqa: PLR0911
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
        logger.error("Wiki MCP 工具执行失败: name=%s error_type=%s", name, type(e).__name__)
        return [TextContent(type="text", text="错误: Wiki 工具执行失败")]


# ============================================================================
# 工具实现
# ============================================================================


def _count_regular_files_without_following_links(root: Path) -> int:
    """Count source files without traversing symlink/reparse entries."""
    count = 0
    try:
        entries = list(os.scandir(root))
    except OSError:
        return 0

    for entry in entries:
        try:
            entry_path = Path(entry.path)
            if entry.is_symlink() or is_reparse_point(entry_path):
                continue
            if entry.is_dir(follow_symlinks=False):
                count += _count_regular_files_without_following_links(entry_path)
            elif entry.is_file(follow_symlinks=False):
                count += 1
        except OSError:
            # Skip entries that disappear or become unsafe during the scan.
            continue
    return count


async def _wiki_status(args: Dict[str, Any]) -> List[TextContent]:
    """获取 Wiki 状态信息。"""
    try:
        _require_posix_safety()
    except OSError as exc:
        raise HTTPException(status_code=400, detail="Wiki 状态检查在当前平台不可用") from exc
    project_path = _authorized_project_root(args["project_path"])
    _recheck_project_tree(project_path)
    if not project_path.exists():
        return [TextContent(type="text", text="项目路径不存在")]

    # 统计文件数
    wiki_dir = project_path / "wiki"
    wiki_files = list(iter_wiki_markdown(project_path)) if wiki_dir.exists() else []

    raw_dir = project_path / "raw" / "sources"
    source_files = (
        _count_regular_files_without_following_links(raw_dir) if raw_dir.exists() else 0
    )

    # 构建图谱统计
    graph_data = build_graph(project_path)

    status = {
        "project_path": str(project_path),
        "wiki_pages": len(wiki_files),
        "source_files": source_files,
        "graph_nodes": len(graph_data.nodes),
        "graph_edges": len(graph_data.edges),
    }

    return [TextContent(type="text", text=json.dumps(status, indent=2, ensure_ascii=False))]


async def _wiki_files(args: Dict[str, Any]) -> List[TextContent]:
    """列出 Wiki 项目中的文件。"""
    project_path = _authorized_project_root(args["project_path"])
    _recheck_project_tree(project_path)
    relative_path = args.get("path", "")
    if relative_path:
        _, target_dir = _resolve_project_file(str(project_path), relative_path)
    else:
        target_dir = project_path

    if not target_dir.exists():
        return [TextContent(type="text", text="路径不存在")]

    if not target_dir.is_dir():
        return [TextContent(type="text", text="不是目录")]

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


async def _wiki_search(args: Dict[str, Any]) -> List[TextContent]:
    """搜索 Wiki 内容。"""
    project_path = _authorized_project_root(args["project_path"])
    _recheck_project_tree(project_path)
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


async def _wiki_read(args: Dict[str, Any]) -> List[TextContent]:
    """读取指定的 Wiki 页面。"""
    project_path = _authorized_project_root(args["project_path"])
    _recheck_project_tree(project_path)
    relative_path = args["path"]
    _, file_path = _resolve_project_file(str(project_path), relative_path)

    try:
        content = secure_read_text(project_path, file_path)
    except FileNotFoundError:
        return [TextContent(type="text", text="文件不存在")]
    except (OSError, UnicodeError):
        return [TextContent(type="text", text="文件读取失败")]

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


async def _wiki_graph(args: Dict[str, Any]) -> List[TextContent]:
    """获取知识图谱数据。"""
    project_path = _authorized_project_root(args["project_path"])
    _recheck_project_tree(project_path)
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


async def _wiki_communities(args: Dict[str, Any]) -> List[TextContent]:
    """获取社区检测结果。"""
    project_path = _authorized_project_root(args["project_path"])
    _recheck_project_tree(project_path)
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


async def _wiki_insights(args: Dict[str, Any]) -> List[TextContent]:
    """获取图谱洞察。"""
    project_path = _authorized_project_root(args["project_path"])
    _recheck_project_tree(project_path)
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
    _require_mcp_runtime()
    assert server is not None
    assert stdio_server is not None
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    import asyncio

    asyncio.run(run_wiki_mcp_server())
