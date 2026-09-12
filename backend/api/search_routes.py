# backend/api/search_routes.py
"""全局搜索路由（P1-3.7 UI 优化方案 2026-09-13）。

聚合会话 / 记忆 / 知识三类搜索结果为统一接口，供前端命令面板 (cmdk) 使用。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query

router = APIRouter(prefix="/search", tags=["search"])


@router.get("/global")
def global_search(
    q: str = Query(..., min_length=1, description="搜索关键词"),
    limit: int = Query(10, ge=1, le=50, description="每类返回上限"),
    types: Optional[str] = Query(
        None,
        description="逗号分隔的类型过滤: session,memory,knowledge (默认全部)",
    ),
) -> Dict[str, Any]:
    """全局搜索: 聚合会话标题 / 记忆内容 / 知识库文档的模糊匹配结果。

    返回格式:
    ```json
    {
      "sessions": [{"id": "...", "title": "...", "updated_at": 1726185600000}],
      "memories": [{"id": "...", "content": "...", "memory_type": "..."}],
      "knowledge": [{"path": "...", "title": "...", "snippet": "..."}]
    }
    ```
    """
    wanted = set(types.split(",")) if types else {"session", "memory", "knowledge"}
    results: Dict[str, List[Any]] = {}

    # ---- 会话搜索 ----
    if "session" in wanted:
        results["sessions"] = _search_sessions(q, limit)

    # ---- 记忆搜索 ----
    if "memory" in wanted:
        results["memories"] = _search_memories(q, limit)

    # ---- 知识搜索 (wiki) ----
    if "knowledge" in wanted:
        results["knowledge"] = _search_knowledge(q, limit)

    return results


def _search_sessions(query: str, limit: int) -> List[Dict[str, Any]]:
    """会话标题 LIKE 搜索。"""
    from backend.data.session_repo import SessionRepository

    repo = SessionRepository()
    sessions = repo.search(query=query, limit=limit)
    return [
        {
            "id": s.id,
            "title": s.title,
            "updated_at": s.updated_at,
            "message_count": s.message_count,
        }
        for s in sessions
    ]


def _search_memories(query: str, limit: int) -> List[Dict[str, Any]]:
    """记忆内容搜索（复用 memory_manager.search_memories）。"""
    try:
        from backend.memory.registry import get_memory_manager

        mm = get_memory_manager()
        raw = mm.search_memories(query=query, limit=limit)
        normalized: List[Dict[str, Any]] = []
        for item in raw:
            normalized.append(
                {
                    "id": item.get("id", ""),
                    "content": item.get("content", "")[:200],
                    "memory_type": item.get("memory_type", item.get("type", "")),
                    "importance": item.get("importance", 0),
                    "tags": item.get("tags", []),
                }
            )
        return normalized
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning("memory search failed: %s", e)
        return []


def _search_knowledge(query: str, limit: int) -> List[Dict[str, Any]]:
    """知识库文档搜索（复用 wiki search_wiki）。无活跃项目时返回空。"""
    try:
        from backend.storage.recent_projects import load_recent
        from backend.wiki.search import search_wiki

        recent = load_recent()
        if not recent:
            return []
        # 取最近打开的项目作为搜索范围
        project_path = recent[0].path if recent else ""
        if not project_path:
            return []
        result = search_wiki(project_root=project_path, query=query, limit=limit)
        # search_wiki 返回 SearchResponse: {results: [{path, title, snippet, ...}]}
        docs = result.results if hasattr(result, "results") else []
        return [
            {
                "path": getattr(d, "path", "") or d.get("path", ""),
                "title": getattr(d, "title", "") or d.get("title", d.get("path", "")),
                "snippet": (getattr(d, "snippet", "") or d.get("snippet", ""))[:200],
            }
            for d in docs
        ]
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning("knowledge search failed: %s", e)
        return []
