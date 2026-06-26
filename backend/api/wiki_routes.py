"""Wiki HTTP API 路由。

提供 Wiki 子系统的 HTTP API：文件操作、搜索、Ingest、Chat、Graph、Research、Clip。
"""

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.wiki import (
    ChatConfig,
    GraphData,
    IngestConfig,
    IngestResult,
    SearchResponse,
    chat_with_wiki,
    get_graph_cached,
    ingest_source,
    search_wiki,
)
from backend.wiki.file_parser import parse_document

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wiki", tags=["wiki"])


# ============================================================================
# Project Management
# ============================================================================


class CreateProjectRequest(BaseModel):
    """创建 Wiki 项目请求。"""

    name: str
    base_path: str  # 项目根目录的绝对路径


class OpenProjectRequest(BaseModel):
    """打开 Wiki 项目请求。"""

    path: str  # 项目根目录的绝对路径


class ProjectInfo(BaseModel):
    """项目信息。"""

    id: str
    name: str
    path: str
    created_at: str
    has_content: bool


def _create_wiki_structure(project_path: Path) -> None:
    """创建 Wiki 项目的标准目录结构。

    Args:
        project_path: 项目根目录
    """
    from datetime import datetime

    project_path.mkdir(parents=True, exist_ok=True)

    # 创建标准目录
    (project_path / "raw" / "sources").mkdir(parents=True, exist_ok=True)
    (project_path / "raw" / "assets").mkdir(parents=True, exist_ok=True)
    (project_path / "wiki" / "entities").mkdir(parents=True, exist_ok=True)
    (project_path / "wiki" / "concepts").mkdir(parents=True, exist_ok=True)
    (project_path / "wiki" / "sources").mkdir(parents=True, exist_ok=True)
    (project_path / "wiki" / "queries").mkdir(parents=True, exist_ok=True)
    (project_path / ".llm-wiki").mkdir(parents=True, exist_ok=True)

    # 创建 schema.md
    schema_file = project_path / "wiki" / "schema.md"
    if not schema_file.exists():
        schema_file.write_text(
            "# Schema\n\n"
            "本项目的 Wiki 结构定义。\n\n"
            "## 目录结构\n\n"
            "- `raw/sources/` - 原始文档（不可变）\n"
            "- `raw/assets/` - 附件资源\n"
            "- `wiki/entities/` - 实体页面\n"
            "- `wiki/concepts/` - 概念页面\n"
            "- `wiki/sources/` - 源文档摘要页面\n"
            "- `wiki/queries/` - 查询结果页面\n",
            encoding="utf-8",
        )

    # 创建 overview.md
    overview_file = project_path / "wiki" / "overview.md"
    if not overview_file.exists():
        overview_file.write_text(
            f"# {project_path.name}\n\n"
            f"创建于 {datetime.now(tz=timezone.utc).isoformat()}\n\n"
            "## 概述\n\n"
            "这是一个新的 Wiki 项目。开始添加源文档来构建知识库。\n",
            encoding="utf-8",
        )

    # 创建 index.md
    index_file = project_path / "wiki" / "index.md"
    if not index_file.exists():
        index_file.write_text(
            f"# Wiki 索引\n\n"
            f"自动生成于 {datetime.now(tz=timezone.utc).isoformat()}\n\n"
            "## 页面\n\n"
            "_暂无页面_\n",
            encoding="utf-8",
        )


@router.post("/project/create")
async def create_project(req: CreateProjectRequest) -> ProjectInfo:
    """创建新的 Wiki 项目。

    Args:
        req: 创建项目请求

    Returns:
        ProjectInfo: 项目信息
    """
    import uuid
    from datetime import datetime

    project_path = Path(req.base_path).expanduser().resolve()

    if not project_path.exists():
        try:
            _create_wiki_structure(project_path)
        except Exception as e:
            logger.error(f"创建项目失败: {e}")
            raise HTTPException(status_code=500, detail=f"创建项目失败: {e}")
    elif not (project_path / "wiki").exists():
        # 路径存在但不是 Wiki 项目，创建目录结构
        _create_wiki_structure(project_path)

    # 生成项目 ID
    project_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(project_path)))

    return ProjectInfo(
        id=project_id,
        name=req.name,
        path=str(project_path),
        created_at=datetime.now(tz=timezone.utc).isoformat(),
        has_content=False,
    )


@router.post("/project/open")
async def open_project(req: OpenProjectRequest) -> ProjectInfo:
    """打开现有的 Wiki 项目。

    Args:
        req: 打开项目请求

    Returns:
        ProjectInfo: 项目信息

    Raises:
        HTTPException: 如果项目不存在或不是有效的 Wiki 项目
    """
    import uuid
    from datetime import datetime

    project_path = Path(req.path).expanduser().resolve()

    if not project_path.exists():
        raise HTTPException(status_code=404, detail="项目路径不存在")

    if not (project_path / "wiki").exists():
        raise HTTPException(status_code=400, detail="不是一个有效的 Wiki 项目（缺少 wiki/ 目录）")

    # 生成项目 ID
    project_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(project_path)))

    # 检查是否有内容
    has_content = False
    wiki_dir = project_path / "wiki"
    for md_file in wiki_dir.rglob("*.md"):
        if md_file.name not in ("index.md", "schema.md", "overview.md"):
            has_content = True
            break

    return ProjectInfo(
        id=project_id,
        name=project_path.name,
        path=str(project_path),
        created_at=datetime.now(tz=timezone.utc).isoformat(),
        has_content=has_content,
    )


@router.get("/project/list")
async def list_projects(base_path: str = "") -> list[ProjectInfo]:
    """列出指定目录下的 Wiki 项目。

    Args:
        base_path: 父目录路径（可选）

    Returns:
        list[ProjectInfo]: 项目列表
    """
    import uuid
    from datetime import datetime

    if not base_path:
        return []

    base = Path(base_path).expanduser().resolve()
    if not base.exists():
        return []

    projects = []
    for item in base.iterdir():
        if not item.is_dir():
            continue
        if not (item / "wiki").exists():
            continue

        project_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(item)))
        has_content = any(
            md.name not in ("index.md", "schema.md", "overview.md")
            for md in (item / "wiki").rglob("*.md")
        )

        projects.append(
            ProjectInfo(
                id=project_id,
                name=item.name,
                path=str(item),
                created_at=datetime.now(tz=timezone.utc).isoformat(),
                has_content=has_content,
            )
        )

    return projects


# ============================================================================
# Request/Response Models
# ============================================================================


class IngestRequest(BaseModel):
    """Ingest 请求。"""

    source_file: str  # 源文件绝对路径
    project_path: str  # 项目根目录
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    embed_base_url: str
    embed_api_key: str
    embed_model: str


class ChatRequest(BaseModel):
    """Chat 请求。"""

    query: str
    project_path: str
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    embed_base_url: str
    embed_api_key: str
    embed_model: str
    max_tokens: int = 4096


class ChatResponse(BaseModel):
    """Chat 响应。"""

    answer: str
    citations: list[str]


# ============================================================================
# File Operations
# ============================================================================


@router.get("/list")
async def list_directory(path: str, project_path: str) -> list[dict]:
    """列出目录内容。

    Args:
        path: 相对路径（相对于 project_path）
        project_path: 项目根目录

    Returns:
        list[dict]: 文件节点列表
    """
    project_root = Path(project_path)
    target_dir = project_root / path if path else project_root

    if not target_dir.exists():
        raise HTTPException(status_code=404, detail="目录不存在")

    nodes = []
    for item in sorted(target_dir.iterdir()):
        # 跳过隐藏文件
        if item.name.startswith("."):
            continue

        node = {
            "name": item.name,
            "path": str(item.relative_to(project_root)).replace("\\", "/"),
            "is_dir": item.is_dir(),
        }

        if item.is_dir():
            # 递归列出子目录（简化版）
            node["children"] = []

        nodes.append(node)

    return nodes


@router.get("/read")
async def read_file(path: str, project_path: str) -> str:
    """读取文件内容。

    Args:
        path: 相对路径
        project_path: 项目根目录

    Returns:
        str: 文件内容
    """
    file_path = Path(project_path) / path

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    return file_path.read_text(encoding="utf-8")


@router.post("/write")
async def write_file(path: str, content: str, project_path: str) -> dict:
    """写入文件。

    Args:
        path: 相对路径
        content: 文件内容
        project_path: 项目根目录

    Returns:
        dict: 成功消息
    """
    file_path = Path(project_path) / path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")

    return {"success": True}


@router.delete("/delete")
async def delete_file(path: str, project_path: str) -> dict:
    """删除文件。

    Args:
        path: 相对路径
        project_path: 项目根目录

    Returns:
        dict: 成功消息
    """
    file_path = Path(project_path) / path

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    if file_path.is_dir():
        import shutil

        shutil.rmtree(file_path)
    else:
        file_path.unlink()

    return {"success": True}


@router.delete("/source/{source_path:path}")
async def delete_source(source_path: str, project_path: str) -> dict:
    """级联删除 Source 及其关联资源。

    删除流程：
    1. 删除原始 source 文件
    2. 查找并删除所有引用此 source 的 wiki 页面
    3. 删除这些页面的嵌入向量
    4. 清理其他页面中的死链
    5. 更新 index.md

    Args:
        source_path: source 相对路径（如 "raw/sources/test.pdf"）
        project_path: 项目根目录

    Returns:
        dict: 删除统计信息
    """
    from backend.wiki.lifecycle import cascade_delete_source

    project_root = Path(project_path)
    source_file = project_root / source_path

    if not source_file.exists():
        raise HTTPException(status_code=404, detail="Source 文件不存在")

    # 先删除原始 source 文件
    try:
        source_file.unlink()
    except Exception as e:
        logger.error(f"删除 source 文件失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除 source 文件失败: {e}")

    # 执行级联删除
    try:
        stats = cascade_delete_source(project_root, source_path)
        return {
            "success": True,
            "source_deleted": source_path,
            **stats,
        }
    except Exception as e:
        logger.error(f"级联删除失败: {e}")
        raise HTTPException(status_code=500, detail=f"级联删除失败: {e}")


@router.post("/rename")
async def rename_file(old_path: str, new_path: str, project_path: str) -> dict:
    """重命名文件。

    Args:
        old_path: 旧路径
        new_path: 新路径
        project_path: 项目根目录

    Returns:
        dict: 成功消息
    """
    old_file = Path(project_path) / old_path
    new_file = Path(project_path) / new_path

    if not old_file.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    new_file.parent.mkdir(parents=True, exist_ok=True)
    old_file.rename(new_file)

    return {"success": True}


# ============================================================================
# Search
# ============================================================================


@router.get("/search")
async def search(query: str, project_path: str, limit: int = 20) -> SearchResponse:
    """搜索 Wiki。

    Args:
        query: 搜索查询
        project_path: 项目根目录
        limit: 返回数量上限

    Returns:
        SearchResponse: 搜索结果
    """
    project_root = Path(project_path)
    return search_wiki(project_root, query, limit)


# ============================================================================
# Ingest
# ============================================================================


@router.post("/ingest")
async def ingest(req: IngestRequest) -> IngestResult:
    """Ingest 源文档。

    Args:
        req: Ingest 请求

    Returns:
        IngestResult: Ingest 结果
    """
    project_root = Path(req.project_path)
    source_file = Path(req.source_file)

    if not source_file.exists():
        raise HTTPException(status_code=404, detail="源文件不存在")

    # 解析文档（如果是 PDF/DOCX 等）
    try:
        content = parse_document(source_file)

        # 如果是非 Markdown，先转换为临时 Markdown 文件
        if source_file.suffix.lower() not in (".md", ".markdown", ".txt"):
            import tempfile

            temp_md = Path(tempfile.mktemp(suffix=".md"))
            temp_md.write_text(content, encoding="utf-8")
            source_file = temp_md
    except Exception as e:
        logger.error(f"文档解析失败: {e}")
        raise HTTPException(status_code=400, detail=f"文档解析失败: {e}")

    # 配置
    config = IngestConfig(
        llm_base_url=req.llm_base_url,
        llm_api_key=req.llm_api_key,
        llm_model=req.llm_model,
        embed_base_url=req.embed_base_url,
        embed_api_key=req.embed_api_key,
        embed_model=req.embed_model,
    )

    # LLM 调用函数
    async def llm_call(messages: list[dict], temperature: float) -> str:
        async with httpx.AsyncClient(timeout=1800) as client:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {req.llm_api_key}",
            }

            body = {
                "model": req.llm_model,
                "messages": messages,
                "temperature": temperature,
            }

            response = await client.post(
                f"{req.llm_base_url}/chat/completions",
                headers=headers,
                json=body,
            )

            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"LLM 调用失败: {response.text}",
                )

            data = response.json()
            return data["choices"][0]["message"]["content"]

    # HTTP POST 函数（用于嵌入）
    async def http_post(url: str, headers: dict[str, str], body: dict) -> str:
        async with httpx.AsyncClient(timeout=1800) as client:
            response = await client.post(url, headers=headers, json=body)

            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"HTTP POST 失败: {response.text}",
                )

            return response.text

    # 执行 ingest
    try:
        return await ingest_source(
            config=config,
            project_root=project_root,
            source_file_path=source_file,
            llm_call=llm_call,
            http_post=http_post,
        )

    except Exception as e:
        logger.error(f"Ingest 失败: {e}")
        raise HTTPException(status_code=500, detail=f"Ingest 失败: {e}")


# ============================================================================
# Chat
# ============================================================================


@router.post("/chat")
async def chat(req: ChatRequest) -> ChatResponse:
    """与 Wiki 聊天。

    Args:
        req: Chat 请求

    Returns:
        ChatResponse: Chat 响应
    """
    project_root = Path(req.project_path)

    # 配置
    config = ChatConfig(
        llm_base_url=req.llm_base_url,
        llm_api_key=req.llm_api_key,
        llm_model=req.llm_model,
        embed_base_url=req.embed_base_url,
        embed_api_key=req.embed_api_key,
        embed_model=req.embed_model,
        max_tokens=req.max_tokens,
    )

    # LLM 调用函数
    async def llm_call(messages: list[dict], temperature: float) -> str:
        async with httpx.AsyncClient(timeout=1800) as client:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {req.llm_api_key}",
            }

            body = {
                "model": req.llm_model,
                "messages": messages,
                "temperature": temperature,
            }

            response = await client.post(
                f"{req.llm_base_url}/chat/completions",
                headers=headers,
                json=body,
            )

            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"LLM 调用失败: {response.text}",
                )

            data = response.json()
            return data["choices"][0]["message"]["content"]

    # HTTP POST 函数（用于嵌入）
    async def http_post(url: str, headers: dict[str, str], body: dict) -> str:
        async with httpx.AsyncClient(timeout=1800) as client:
            response = await client.post(url, headers=headers, json=body)

            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"HTTP POST 失败: {response.text}",
                )

            return response.text

    # 执行聊天
    try:
        outcome = await chat_with_wiki(
            config=config,
            project_root=project_root,
            query=req.query,
            llm_call=llm_call,
            http_post=http_post,
        )

        return ChatResponse(answer=outcome.answer, citations=outcome.citations)
    except Exception as e:
        logger.error(f"Chat 失败: {e}")
        raise HTTPException(status_code=500, detail=f"Chat 失败: {e}")


# ============================================================================
# Graph
# ============================================================================


@router.get("/graph")
async def get_graph(project_path: str, query: str | None = None, limit: int = 100) -> GraphData:
    """获取知识图谱。

    Args:
        project_path: 项目根目录
        query: 可选查询（过滤节点）
        limit: 节点数量上限

    Returns:
        GraphData: 图谱数据
    """
    project_root = Path(project_path)
    return get_graph_cached(project_root, query, limit)


# ============================================================================
# Community Detection
# ============================================================================


@router.get("/communities")
async def get_communities(project_path: str) -> dict:
    """获取社区检测结果。

    使用 Louvain 算法检测知识图谱中的社区结构，并计算每个社区的凝聚度。

    Args:
        project_path: 项目根目录

    Returns:
        dict: 包含社区列表和图谱数据
            - communities: 社区信息列表
            - graph: 图谱数据
    """
    from backend.wiki.community import get_communities_with_nodes

    project_root = Path(project_path)

    try:
        communities, graph_data = get_communities_with_nodes(project_root)

        return {
            "communities": [
                {
                    "community_id": c.community_id,
                    "members": c.members,
                    "cohesion": c.cohesion,
                    "size": c.size,
                }
                for c in communities
            ],
            "graph": {
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
        }
    except Exception as e:
        logger.error(f"社区检测失败: {e}")
        raise HTTPException(status_code=500, detail=f"社区检测失败: {e}")


# ============================================================================
# Graph Insights
# ============================================================================


@router.get("/insights")
async def get_insights(project_path: str) -> dict:
    """获取图谱洞察。

    分析图谱，发现惊人联系和知识缺口。

    Args:
        project_path: 项目根目录

    Returns:
        dict: 包含惊人联系、知识缺口和统计信息
            - surprising_connections: 惊人联系列表
            - knowledge_gaps: 知识缺口列表
            - stats: 统计信息
    """
    from backend.wiki.insights import analyze_graph

    project_root = Path(project_path)

    try:
        insights = analyze_graph(project_root)

        return {
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
            "stats": insights.stats,
        }
    except Exception as e:
        logger.error(f"图谱洞察分析失败: {e}")
        raise HTTPException(status_code=500, detail=f"图谱洞察分析失败: {e}")


# ============================================================================
# Deep Research
# ============================================================================


class ResearchRequest(BaseModel):
    """Deep Research 请求。"""

    topic: str
    project_path: str
    search_provider: str = "tavily"  # tavily, serpapi, searxng
    search_api_key: str = ""
    search_base_url: str = ""
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    auto_ingest: bool = True


@router.post("/research")
async def start_research(req: ResearchRequest) -> dict:
    """启动 Deep Research。

    执行多步骤研究：网络搜索 → LLM 综合 → 自动 Ingest。

    Args:
        req: Deep Research 请求

    Returns:
        dict: 研究任务状态和结果
    """
    import uuid

    from backend.wiki import (
        IngestConfig,
        ResearchTask,
        SearchProvider,
        deep_research,
    )

    project_root = Path(req.project_path)

    # 创建研究任务
    task = ResearchTask(
        id=str(uuid.uuid4()),
        topic=req.topic,
    )

    # 配置 Ingest（如果启用自动 Ingest）
    ingest_config = None
    if req.auto_ingest:
        ingest_config = IngestConfig(
            llm_base_url=req.llm_base_url,
            llm_api_key=req.llm_api_key,
            llm_model=req.llm_model,
            embed_base_url=req.llm_base_url,  # 使用相同的 API
            embed_api_key=req.llm_api_key,
            embed_model=req.llm_model,
        )

    # LLM 调用函数
    async def llm_call(messages: list[dict], temperature: float) -> str:
        import httpx

        async with httpx.AsyncClient(timeout=1800) as client:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {req.llm_api_key}",
            }

            body = {
                "model": req.llm_model,
                "messages": messages,
                "temperature": temperature,
            }

            response = await client.post(
                f"{req.llm_base_url}/chat/completions",
                headers=headers,
                json=body,
            )

            if response.status_code != 200:
                raise Exception(f"LLM 调用失败: {response.status_code} - {response.text}")

            data = response.json()
            return data["choices"][0]["message"]["content"]

    # 执行 Deep Research
    try:
        task = await deep_research(
            task=task,
            project_root=project_root,
            search_provider=SearchProvider(req.search_provider),
            search_api_key=req.search_api_key,
            search_base_url=req.search_base_url,
            llm_call=llm_call,
            ingest_config=ingest_config,
            auto_ingest=req.auto_ingest,
        )

        return {
            "id": task.id,
            "topic": task.topic,
            "status": task.status,
            "queries": task.queries,
            "web_results_count": len(task.web_results),
            "web_results": [
                {
                    "title": r.title,
                    "url": r.url,
                    "snippet": r.snippet,
                    "score": r.score,
                }
                for r in task.web_results[:10]  # 只返回前 10 个
            ],
            "synthesis": task.synthesis,
            "saved_path": task.saved_path,
            "error": task.error,
        }

    except Exception as e:
        logger.error(f"Deep Research 失败: {e}")
        raise HTTPException(status_code=500, detail=f"Deep Research 失败: {e}")


# ============================================================================
# Chrome Web Clipper
# ============================================================================


class ClipRequest(BaseModel):
    """Chrome Web Clipper 请求。"""

    title: str
    url: str
    content: str  # Markdown 内容
    project_path: str
    notes: str = ""
    auto_ingest: bool = True


@router.post("/clip")
async def clip_webpage(req: ClipRequest) -> dict:
    """保存网页剪藏到 Wiki。

    接收来自 Chrome Web Clipper 的请求，将网页内容保存为 Markdown 文件，
    并可选择自动 Ingest 到 Wiki。

    Args:
        req: 剪藏请求

    Returns:
        dict: 包含保存结果
    """
    project_root = Path(req.project_path)

    # 添加备注到内容
    full_content = req.content
    if req.notes:
        full_content = f"{req.content}\n\n---\n\n## 备注\n\n{req.notes}\n"

    # 保存为临时 Markdown 文件
    raw_sources_dir = project_root / "raw" / "sources"
    raw_sources_dir.mkdir(parents=True, exist_ok=True)

    # 生成文件名（基于 URL）
    safe_title = re.sub(r"[^a-zA-Z0-9一-鿿\-_]", "-", req.title)
    safe_title = re.sub(r"-+", "-", safe_title).strip("-")[:50]
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"webclip-{timestamp}-{safe_title}.md"
    source_file = raw_sources_dir / filename

    source_file.write_text(full_content, encoding="utf-8")

    result = {
        "source_path": f"raw/sources/{filename}",
        "wiki_page_path": "",
        "auto_ingested": False,
    }

    # 如果启用自动 Ingest
    if req.auto_ingest:
        try:
            # 从环境变量或配置获取 LLM 设置
            # 这里使用简单的 OpenAI 兼容 API
            from backend.wiki import IngestConfig, ingest_source

            # 尝试从环境变量获取配置
            llm_base_url = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8765/api/v1/llm")
            llm_api_key = os.environ.get("LLM_API_KEY", "dummy")
            llm_model = os.environ.get("LLM_MODEL", "gpt-4")
            embed_base_url = os.environ.get("EMBED_BASE_URL", llm_base_url)
            embed_api_key = os.environ.get("EMBED_API_KEY", llm_api_key)
            embed_model = os.environ.get("EMBED_MODEL", "text-embedding-3-small")

            config = IngestConfig(
                llm_base_url=llm_base_url,
                llm_api_key=llm_api_key,
                llm_model=llm_model,
                embed_base_url=embed_base_url,
                embed_api_key=embed_api_key,
                embed_model=embed_model,
            )

            # LLM 调用函数
            async def llm_call(messages, temperature=0.3):
                async with httpx.AsyncClient(timeout=1800) as client:
                    headers = {
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {llm_api_key}",
                    }
                    body = {
                        "model": llm_model,
                        "messages": messages,
                        "temperature": temperature,
                    }
                    response = await client.post(
                        f"{llm_base_url}/chat/completions",
                        headers=headers,
                        json=body,
                    )
                    if response.status_code != 200:
                        raise Exception(f"LLM 错误: {response.text}")
                    data = response.json()
                    return data["choices"][0]["message"]["content"]

            async def http_post(url, headers, body):
                async with httpx.AsyncClient(timeout=1800) as client:
                    response = await client.post(url, headers=headers, json=body)
                    if response.status_code != 200:
                        raise Exception(f"HTTP 错误: {response.text}")
                    return response.text

            ingest_result = await ingest_source(
                config=config,
                project_root=project_root,
                source_file_path=source_file,
                llm_call=llm_call,
                http_post=http_post,
            )

            result["wiki_page_path"] = ingest_result.wiki_page_path
            result["auto_ingested"] = True
        except Exception as e:
            logger.warning(f"自动 Ingest 失败，仅保存源文件: {e}")
            result["auto_ingest_error"] = str(e)

    return result


# ============================================================================
# Vision Caption
# ============================================================================


class VisionRequest(BaseModel):
    """Vision Caption 请求。"""

    image_data: str  # base64 编码的图片数据
    image_path: str = ""
    project_path: str = ""
    context: str = ""
    provider: str = "openai"  # openai, anthropic, ollama
    base_url: str = ""
    api_key: str = ""
    model: str = "gpt-4-vision-preview"
    max_tokens: int = 300


@router.post("/vision")
async def caption_image_endpoint(req: VisionRequest) -> dict:
    """为图片生成描述（Vision Caption）。

    支持多个视觉 LLM 提供者：
    - openai: GPT-4V
    - anthropic: Claude 3 with vision
    - ollama: Ollama 视觉模型

    Args:
        req: Vision Caption 请求

    Returns:
        dict: 包含图片描述结果
    """
    import base64

    from backend.wiki import VisionConfig, VisionProvider, caption_image

    # 解码 base64 图片数据
    try:
        image_data = base64.b64decode(req.image_data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"图片数据解码失败: {e}")

    # 构建配置
    config = VisionConfig(
        provider=VisionProvider(req.provider),
        base_url=req.base_url,
        api_key=req.api_key,
        model=req.model,
        max_tokens=req.max_tokens,
    )

    # 项目根目录（用于缓存）
    project_root = Path(req.project_path) if req.project_path else None

    # 生成描述
    try:
        result = await caption_image(
            config=config,
            image_data=image_data,
            image_path=req.image_path,
            project_root=project_root,
            context=req.context,
        )

        return {
            "caption": result.caption,
            "sha256": result.sha256,
            "cached": result.cached,
            "image_path": result.image_path,
        }
    except Exception as e:
        logger.error(f"Vision Caption 失败: {e}")
        raise HTTPException(status_code=500, detail=f"Vision Caption 失败: {e}")
