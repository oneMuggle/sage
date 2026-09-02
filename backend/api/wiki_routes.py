"""Wiki HTTP API 路由。

提供 Wiki 子系统的 HTTP API：文件操作、搜索、Ingest、Chat、Graph、Research、Clip。
"""

from __future__ import annotations

import logging
import os
import re
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, List, Optional, Tuple

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from backend.wiki import (
    ChatConfig,
    GraphData,
    IngestConfig,
    SearchResponse,
    chat_with_wiki_stream,
    get_graph_cached,
    ingest_source_stream,
    search_wiki,
)
from backend.wiki.extract import MAX_FILE_BYTES
from backend.wiki.file_parser import parse_document
from backend.wiki.files import (
    iter_wiki_markdown,
    secure_delete_path,
    secure_ensure_directory,
    secure_list_directory,
    secure_open_file,
    secure_read_file,
    secure_read_file_bounded,
    secure_read_text,
    secure_rename_path,
    secure_write_file,
    secure_write_file_if_missing,
    secure_write_temp_bytes,
    secure_write_temp_file,
)
from backend.wiki.llm_context import make_llm_context
from backend.wiki.project_authorization import (
    authorize_registered_project,
    authorize_registration,
    canonical_project_path,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wiki", tags=["wiki"])


def _cleanup_temp_paths(*paths: Optional[Path], project_root: Optional[Path] = None) -> None:
    """Best-effort cleanup that preserves the operation's original failure."""
    for path in paths:
        if path is not None:
            with suppress(OSError):
                if project_root is None:
                    path.unlink(missing_ok=True)
                else:
                    secure_delete_path(project_root, path)


def _canonical_project_root(project_path: str) -> Path:
    """Return a canonical root and reject invalid declarations."""
    canonical = canonical_project_path(project_path)
    if canonical is None:
        raise HTTPException(status_code=400, detail="项目路径无效")
    return canonical


def _path_is_within(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root)
    except (OSError, ValueError):
        return False
    return True


def _reject_symlink_components(root: Path, candidate: Path) -> None:
    """Reject symlinks in a user-controlled path, including missing leaves."""
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="路径不在项目目录内") from exc
    current = root
    for component in relative.parts:
        current /= component
        try:
            if current.is_symlink():
                raise HTTPException(status_code=400, detail="路径不能是符号链接")
        except OSError as exc:
            raise HTTPException(status_code=400, detail="路径无效") from exc


def _resolve_project_file(project_path: str, path: str) -> Tuple[Path, Path]:
    """Resolve a relative project path and enforce canonical containment."""
    root = _canonical_project_root(project_path)
    if not path or "\x00" in path:
        raise HTTPException(status_code=400, detail="路径无效")
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        raise HTTPException(status_code=400, detail="路径必须是项目目录内的相对路径")
    lexical = root / candidate
    try:
        _reject_symlink_components(root, lexical)
        resolved = lexical.resolve(strict=False)
        resolved.relative_to(root)
    except HTTPException:
        raise
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="路径不在项目目录内") from exc
    return root, resolved


def _resolve_source_file(project_path: str, source_file: str) -> Tuple[Path, Path]:
    """Resolve an ingest source (legacy absolute or relative) within the root."""
    root = _canonical_project_root(project_path)
    if not source_file or "\x00" in source_file:
        raise HTTPException(status_code=400, detail="源文件路径无效")
    supplied = Path(source_file).expanduser()
    lexical = supplied if supplied.is_absolute() else root / supplied
    try:
        _reject_symlink_components(root, lexical)
        resolved = lexical.resolve(strict=False)
        resolved.relative_to(root)
    except HTTPException:
        raise
    except (OSError, ValueError) as exc:
        if supplied.is_absolute() and not lexical.exists():
            try:
                lexical.relative_to(root)
            except ValueError as containment_exc:
                raise HTTPException(status_code=400, detail="源文件必须位于项目目录内") from containment_exc
            raise HTTPException(status_code=404, detail="源文件不存在") from exc
        raise HTTPException(status_code=400, detail="源文件必须位于项目目录内") from exc
    return root, resolved


def _http_exception_from_llm(e: Exception, fallback_detail: str) -> HTTPException:
    """Map upstream failures without exposing provider response data."""
    if isinstance(e, httpx.HTTPStatusError):
        status_code = e.response.status_code if e.response is not None else 502
        logger.warning(
            "wiki upstream HTTP failure: status=%s error_type=%s",
            status_code,
            type(e).__name__,
        )
        return HTTPException(
            status_code=status_code,
            detail=f"{fallback_detail} (upstream HTTP {status_code})",
        )
    logger.warning("wiki operation failed: error_type=%s", type(e).__name__)
    return HTTPException(status_code=500, detail=fallback_detail)


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

    secure_ensure_directory(project_path.parent, project_path)

    # 创建标准目录
    for relative_dir in (
        "raw/sources",
        "raw/assets",
        "wiki/entities",
        "wiki/concepts",
        "wiki/sources",
        "wiki/queries",
        ".llm-wiki",
    ):
        secure_ensure_directory(project_path, project_path / relative_dir)

    # 创建 schema.md
    schema_file = project_path / "wiki" / "schema.md"
    if not schema_file.exists():
        secure_write_file_if_missing(
            project_path,
            schema_file,
            "# Schema\n\n"
            "本项目的 Wiki 结构定义。\n\n"
            "## 目录结构\n\n"
            "- `raw/sources/` - 原始文档（不可变）\n"
            "- `raw/assets/` - 附件资源\n"
            "- `wiki/entities/` - 实体页面\n"
            "- `wiki/concepts/` - 概念页面\n"
            "- `wiki/sources/` - 源文档摘要页面\n"
            "- `wiki/queries/` - 查询结果页面\n",
        )

    # 创建 overview.md
    overview_file = project_path / "wiki" / "overview.md"
    if not overview_file.exists():
        secure_write_file_if_missing(
            project_path,
            overview_file,
            f"# {project_path.name}\n\n"
            f"创建于 {datetime.now(tz=timezone.utc).isoformat()}\n\n"  # noqa: UP017
            "## 概述\n\n"
            "这是一个新的 Wiki 项目。开始添加源文档来构建知识库。\n",
        )

    # 创建 index.md
    index_file = project_path / "wiki" / "index.md"
    if not index_file.exists():
        secure_write_file_if_missing(
            project_path,
            index_file,
            f"# Wiki 索引\n\n"
            f"自动生成于 {datetime.now(tz=timezone.utc).isoformat()}\n\n"  # noqa: UP017
            "## 页面\n\n"
            "_暂无页面_\n",
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

    project_path = _canonical_project_root(req.base_path)

    if not project_path.exists():
        try:
            _create_wiki_structure(project_path)
        except Exception as e:
            logger.error(f"创建项目失败: {e}")
            raise HTTPException(status_code=500, detail="创建项目失败") from e
    elif not (project_path / "wiki").exists():
        # 路径存在但不是 Wiki 项目，创建目录结构
        _create_wiki_structure(project_path)

    # 生成项目 ID
    project_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(project_path)))
    record_recent(str(project_path), req.name, "create")

    return ProjectInfo(
        id=project_id,
        name=req.name,
        path=str(project_path),
        created_at=datetime.now(tz=timezone.utc).isoformat(),  # noqa: DTZ011, UP017
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

    project_path = _canonical_project_root(req.path)

    if not project_path.exists():
        raise HTTPException(status_code=404, detail="项目路径不存在")

    if not (project_path / "wiki").exists():
        raise HTTPException(status_code=400, detail="不是一个有效的 Wiki 项目（缺少 wiki/ 目录）")

    # 生成项目 ID
    project_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(project_path)))
    record_recent(str(project_path), project_path.name, "open")

    # 检查是否有内容
    has_content = False
    for md_file in iter_wiki_markdown(project_path):
        if md_file.name not in ("index.md", "schema.md", "overview.md"):
            has_content = True
            break

    return ProjectInfo(
        id=project_id,
        name=project_path.name,
        path=str(project_path),
        created_at=datetime.now(tz=timezone.utc).isoformat(),  # noqa: DTZ011, UP017
        has_content=has_content,
    )


@router.get("/project/list")
async def list_projects(base_path: str = "") -> List[ProjectInfo]:
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
        if item.is_symlink() or not item.is_dir():
            continue
        if not (item / "wiki").exists():
            continue

        project_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(item)))
        has_content = any(
            md.name not in ("index.md", "schema.md", "overview.md")
            for md in iter_wiki_markdown(item)
        )

        projects.append(
            ProjectInfo(
                id=project_id,
                name=item.name,
                path=str(item),
                created_at=datetime.now(tz=timezone.utc).isoformat(),  # noqa: DTZ011, UP017
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


# ============================================================================
# File Operations
# ============================================================================


def list_directory_impl(path: str, project_path: str, depth: int = 10) -> List[dict]:
    """Recursively list directories via no-follow dirfd snapshots."""
    project_root, base = _resolve_project_file(project_path, path or ".")

    def walk(current: Path, remaining: int) -> dict:
        entries = secure_list_directory(project_root, current)
        node = {
            "name": current.name,
            "path": str(current.relative_to(project_root)).replace("\\", "/")
            if current != project_root
            else ".",
            "is_dir": True,
            "children": [],
        }
        if remaining <= 0:
            return node
        children = []
        for name, is_dir in sorted(entries, key=lambda item: (not item[1], item[0].lower())):
            if name.startswith("."):
                continue
            child = current / name
            child_node = {
                "name": name,
                "path": str(child.relative_to(project_root)).replace("\\", "/"),
                "is_dir": is_dir,
                "children": [],
            }
            if is_dir and remaining > 0:
                child_node = walk(child, remaining - 1)
            children.append(child_node)
        node["children"] = children
        return node

    return [walk(base, depth)]


@router.get("/list")
async def list_directory(path: str, project_path: str) -> List[dict]:
    """列出目录内容。

    Args:
        path: 相对路径（相对于 project_path）
        project_path: 项目根目录

    Returns:
        list[dict]: 文件节点列表

    Raises:
        HTTPException: 如果目标路径不存在
    """
    authorize_registered_project(project_path)
    _, target_dir = _resolve_project_file(project_path, path or ".")

    if not target_dir.exists():
        raise HTTPException(status_code=404, detail="目录不存在")

    return list_directory_impl(path, project_path)


@router.get("/read")
async def read_file(path: str, project_path: str) -> str:
    """读取文件内容。

    Args:
        path: 相对路径
        project_path: 项目根目录

    Returns:
        str: 文件内容
    """
    project_root = authorize_registered_project(project_path)
    _, file_path = _resolve_project_file(project_path, path)

    try:
        content = secure_read_text(project_root, file_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="文件不存在") from exc
    except (OSError, UnicodeError) as exc:
        logger.warning("Wiki 读取拒绝: error_type=%s", type(exc).__name__)
        raise HTTPException(status_code=400, detail="文件读取失败") from exc

    return content


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
    project_root = authorize_registered_project(project_path)
    _, file_path = _resolve_project_file(project_path, path)
    try:
        secure_write_file(project_root, file_path, content)
    except OSError as exc:
        logger.warning("Wiki 写入拒绝: error_type=%s", type(exc).__name__)
        raise HTTPException(status_code=400, detail="文件写入失败") from exc

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
    authorize_registered_project(project_path)
    project_root, file_path = _resolve_project_file(project_path, path)
    try:
        secure_delete_path(project_root, file_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="文件不存在") from exc
    except OSError as exc:
        logger.warning("Wiki 删除拒绝: error_type=%s", type(exc).__name__)
        raise HTTPException(status_code=400, detail="文件删除失败") from exc

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

    project_root = authorize_registered_project(project_path)
    project_root, source_file = _resolve_project_file(project_path, source_path)

    if not source_file.exists():
        raise HTTPException(status_code=404, detail="Source 文件不存在")

    # 先删除原始 source 文件
    try:
        secure_delete_path(project_root, source_file)
    except Exception as e:
        logger.error("删除 source 文件失败: error_type=%s", type(e).__name__)
        raise HTTPException(status_code=500, detail="删除 source 文件失败") from e

    # 执行级联删除
    try:
        stats = cascade_delete_source(project_root, source_path)
        return {
            "success": True,
            "source_deleted": source_path,
            **stats,
        }
    except Exception as e:
        logger.error("级联删除失败: error_type=%s", type(e).__name__)
        raise HTTPException(status_code=500, detail="级联删除失败") from e


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
    authorize_registered_project(project_path)
    project_root, old_file = _resolve_project_file(project_path, old_path)
    _, new_file = _resolve_project_file(project_path, new_path)

    try:
        secure_rename_path(project_root, old_file, new_file)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="文件不存在") from exc
    except OSError as exc:
        logger.warning("Wiki 重命名拒绝: error_type=%s", type(exc).__name__)
        raise HTTPException(status_code=400, detail="文件重命名失败") from exc

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
    project_root = authorize_registered_project(project_path)
    return search_wiki(project_root, query, limit)


# ============================================================================
# Ingest
# ============================================================================


@router.post("/ingest/stream")
async def ingest_stream(req: IngestRequest) -> StreamingResponse:
    """Ingest 源文档 (NDJSON 流式进度)。

    返回 ``application/x-ndjson`` 流,每行一条 JSON 事件:

    - ``{"event":"progress","data":{"stage":"...","percent":N,"message":"..."}}`` — 每个阶段一条
    - 末尾由 ``ingest_source_stream`` yield ``completed`` (100%) 关闭流
    - 异常路径 yield ``failed`` (0%) 后 re-raise 让 FastAPI 关流

    文档解析保留同步(fast, <1s):失败时在 stream 开启前抛 ``HTTPException``。
    LLM/HTTP 实际工作由 ``ingest_source_stream`` 异步生成器驱动。

    Args:
        req: Ingest 请求

    Returns:
        StreamingResponse: NDJSON 流式响应
    """
    authorize_registered_project(req.project_path)
    project_root, source_file = _resolve_source_file(req.project_path, req.source_file)

    source_snapshot: Optional[Path] = None
    temp_md: Optional[Path] = None
    parse_path: Optional[Path] = None
    try:
        payload = secure_read_file_bounded(project_root, source_file, MAX_FILE_BYTES)
        suffix = source_file.suffix.lower() or ".bin"
        source_snapshot = secure_write_temp_bytes(
            project_root, project_root / ".llm-wiki", suffix, payload
        )
        parse_path = source_snapshot
        parse_fd = secure_open_file(project_root, parse_path)
        try:
            content = parse_document(parse_path, opened_fd=parse_fd)
        finally:
            os.close(parse_fd)

        # If non-Markdown, convert to a private temporary Markdown snapshot.
        if suffix not in (".md", ".markdown", ".txt"):
            temp_md = secure_write_temp_file(
                project_root, project_root / ".llm-wiki", ".md", content
            )
            parse_path = temp_md
    except FileNotFoundError as exc:
        _cleanup_temp_paths(temp_md, source_snapshot, project_root=project_root)
        raise HTTPException(status_code=404, detail="源文件不存在") from exc
    except (OSError, UnicodeError, ValueError, ImportError) as exc:
        logger.error("文档解析失败: error_type=%s", type(exc).__name__)
        _cleanup_temp_paths(temp_md, source_snapshot, project_root=project_root)
        raise HTTPException(status_code=400, detail="文档解析失败") from exc

    config = IngestConfig(
        llm_base_url=req.llm_base_url,
        llm_api_key=req.llm_api_key,
        llm_model=req.llm_model,
        embed_base_url=req.embed_base_url,
        embed_api_key=req.embed_api_key,
        embed_model=req.embed_model,
    )

    # LLM/HTTP 能力（PR-2/3 用 ctx.llm_stream_call 切换 NDJSON）
    ctx = make_llm_context(
        llm_base_url=req.llm_base_url,
        llm_api_key=req.llm_api_key,
        llm_model=req.llm_model,
    )

    async def _stream_with_cleanup() -> AsyncIterator[bytes]:
        try:
            async for chunk in ingest_source_stream(
                config,
                project_root,
                source_snapshot,
                ctx,
                logical_filename=source_file.name,
            ):
                yield chunk
        finally:
            _cleanup_temp_paths(temp_md, source_snapshot, project_root=project_root)

    return StreamingResponse(
        _stream_with_cleanup(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================================================
# Chat (PR-2: 流式 NDJSON 端点, 替换原 /chat 同步端点)
# ============================================================================


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    """与 Wiki 流式聊天 (NDJSON)。

    返回 ``application/x-ndjson`` 流,每行一条 JSON 事件:

    - ``{"event":"chunk","data":"<text>"}`` — 每个 LLM delta 一条
    - ``{"event":"done","data":{"citations":[...]}}`` — 流末尾
    - ``{"event":"error","data":"<msg>"}`` — 仅在异常路径出现

    Args:
        req: Chat 请求

    Returns:
        StreamingResponse: NDJSON 流式响应
    """
    project_root = authorize_registered_project(req.project_path)

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

    # LLM/HTTP 能力（PR-2/3 用 ctx.llm_stream_call 切换 NDJSON）
    ctx = make_llm_context(
        llm_base_url=req.llm_base_url,
        llm_api_key=req.llm_api_key,
        llm_model=req.llm_model,
    )

    return StreamingResponse(
        chat_with_wiki_stream(config, project_root, req.query, ctx),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================================================
# Graph
# ============================================================================


@router.get("/graph")
async def get_graph(project_path: str, query: Optional[str] = None, limit: int = 100) -> GraphData:
    """获取知识图谱。

    Args:
        project_path: 项目根目录
        query: 可选查询（过滤节点）
        limit: 节点数量上限

    Returns:
        GraphData: 图谱数据
    """
    project_root = authorize_registered_project(project_path)
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

    project_root = authorize_registered_project(project_path)

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
        logger.error("社区检测失败: error_type=%s", type(e).__name__)
        raise _http_exception_from_llm(e, "社区检测失败")


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

    project_root = authorize_registered_project(project_path)

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
        logger.error("图谱洞察分析失败: error_type=%s", type(e).__name__)
        raise _http_exception_from_llm(e, "图谱洞察分析失败")


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

    project_root = authorize_registered_project(req.project_path)

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

    # LLM/HTTP 能力
    ctx = make_llm_context(
        llm_base_url=req.llm_base_url,
        llm_api_key=req.llm_api_key,
        llm_model=req.llm_model,
    )

    # 执行 Deep Research
    try:
        task = await deep_research(
            task=task,
            project_root=project_root,
            search_provider=SearchProvider(req.search_provider),
            search_api_key=req.search_api_key,
            search_base_url=req.search_base_url,
            llm_call=ctx.llm_call,
            ingest_config=ingest_config,
            auto_ingest=req.auto_ingest,
            http_post=ctx.http_post,
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
        logger.error("Deep Research failed: error_type=%s", type(e).__name__)
        raise _http_exception_from_llm(e, "Deep Research 失败")


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
    project_root = authorize_registered_project(req.project_path)

    # 添加备注到内容
    full_content = req.content
    if req.notes:
        full_content = f"{req.content}\n\n---\n\n## 备注\n\n{req.notes}\n"

    # 保存为临时 Markdown 文件
    raw_sources_dir = project_root / "raw" / "sources"

    # 生成文件名（基于 URL）
    safe_title = re.sub(r"[^a-zA-Z0-9一-鿿\-_]", "-", req.title)
    safe_title = re.sub(r"-+", "-", safe_title).strip("-")[:50]
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"webclip-{timestamp}-{safe_title}.md"
    source_file = raw_sources_dir / filename

    try:
        secure_write_file(project_root, source_file, full_content)
    except OSError as exc:
        logger.warning("Wiki 剪藏写入拒绝: error_type=%s", type(exc).__name__)
        raise HTTPException(status_code=400, detail="剪藏文件写入失败") from exc

    result = {
        "source_path": f"raw/sources/{filename}",
        "wiki_page_path": "",
        "auto_ingested": False,
    }

    # 如果启用自动 Ingest
    if req.auto_ingest:
        source_snapshot: Optional[Path] = None
        try:
            # Snapshot the authorized file before handing a pathname to ingest.
            # The saved source may be replaced after this point; ingest only sees
            # this private, 0600 temporary copy.
            payload = secure_read_file(project_root, source_file)
            source_snapshot = secure_write_temp_bytes(
                project_root,
                project_root / ".llm-wiki",
                source_file.suffix or ".bin",
                payload,
            )

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

            # LLM/HTTP 能力（从环境变量构造，因为 ClipRequest 不带 LLM 字段）
            ctx = make_llm_context(
                llm_base_url=llm_base_url,
                llm_api_key=llm_api_key,
                llm_model=llm_model,
            )

            ingest_result = await ingest_source(
                config=config,
                project_root=project_root,
                source_file_path=source_snapshot,
                llm_call=ctx.llm_call,
                http_post=ctx.http_post,
                logical_filename=filename,
            )

            result["wiki_page_path"] = ingest_result.wiki_page_path
            result["auto_ingested"] = True
        except Exception as e:
            logger.warning("自动 Ingest 失败，仅保存源文件: error_type=%s", type(e).__name__)
            result["auto_ingest_error"] = "自动 Ingest 失败"
        finally:
            _cleanup_temp_paths(source_snapshot, project_root=project_root)

    return result


# ============================================================================
# Vision Caption
# ============================================================================


MAX_VISION_IMAGE_DATA_BYTES = 10 * 1024 * 1024
MAX_VISION_BASE64_CHARS = 14 * 1024 * 1024


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
    if len(req.image_data) > MAX_VISION_BASE64_CHARS:
        raise HTTPException(status_code=413, detail="图片数据超过大小限制")
    try:
        image_data = base64.b64decode(req.image_data, validate=True)
    except Exception as e:
        raise HTTPException(status_code=400, detail="图片数据解码失败") from e
    if len(image_data) > MAX_VISION_IMAGE_DATA_BYTES:
        raise HTTPException(status_code=413, detail="图片数据超过大小限制")

    # 构建配置
    config = VisionConfig(
        provider=VisionProvider(req.provider),
        base_url=req.base_url,
        api_key=req.api_key,
        model=req.model,
        max_tokens=req.max_tokens,
    )

    # 项目根目录（用于缓存）
    project_root = authorize_registered_project(req.project_path) if req.project_path else None

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
        logger.error("Vision Caption failed: error_type=%s", type(e).__name__)
        raise HTTPException(status_code=500, detail="Vision Caption 失败") from e


# --- Project folder picker support (added 2026-06-27) ---------------------

from typing import Literal  # noqa: E402

from backend.storage.recent_projects import (  # noqa: E402
    RecentProject,
    load_recent,
    record_recent,
)


class ProjectCheckResponse(BaseModel):
    exists: bool
    writable: bool
    is_project: bool
    parent_writable: bool
    warning: Optional[str] = None
    error: Optional[str] = None


class RecordRecentRequest(BaseModel):
    path: str
    name: str
    intent: Literal["create", "open"]


def _check_project_impl(path_str: str, intent: str) -> ProjectCheckResponse:  # noqa: PLR0911
    """Pure-Python check; returns ProjectCheckResponse.

    - intent='create': target may not exist; if exists must NOT contain wiki/
    - intent='open':   target must exist + be a dir + contain wiki/
    """
    p = Path(path_str).expanduser()

    def _is_writable_dir(d: Path) -> bool:
        if not d.exists():
            return False
        return os.access(d, os.W_OK)

    exists = p.exists()
    is_dir = exists and p.is_dir()
    is_project = is_dir and (p / "wiki").is_dir()

    if intent == "open":
        if not exists:
            return ProjectCheckResponse(
                exists=False,
                writable=False,
                is_project=False,
                parent_writable=False,
                error="路径不存在",
            )
        if not is_dir:
            return ProjectCheckResponse(
                exists=True,
                writable=False,
                is_project=False,
                parent_writable=False,
                error="不是目录",
            )
        if not is_project:
            return ProjectCheckResponse(
                exists=True,
                writable=_is_writable_dir(p),
                is_project=False,
                parent_writable=False,
                error="不是 wiki 项目（缺少 wiki/ 子目录）",
            )
        return ProjectCheckResponse(
            exists=True,
            writable=_is_writable_dir(p),
            is_project=True,
            parent_writable=True,
        )

    # create branch: target may not exist; if exists must NOT contain wiki/
    if exists and not is_dir:
        return ProjectCheckResponse(
            exists=True,
            writable=False,
            is_project=False,
            parent_writable=False,
            error="不是目录",
        )
    if exists and is_project:
        return ProjectCheckResponse(
            exists=True,
            writable=_is_writable_dir(p),
            is_project=True,
            parent_writable=True,
            error="已经是 wiki 项目，请用「打开」",
        )
    if exists:
        return ProjectCheckResponse(
            exists=True,
            writable=_is_writable_dir(p),
            is_project=False,
            parent_writable=True,
            warning="将建立 wiki/ 结构",
        )
    parent = p.parent
    parent_writable = parent.exists() and _is_writable_dir(parent)
    if not parent_writable:
        return ProjectCheckResponse(
            exists=False,
            writable=False,
            is_project=False,
            parent_writable=False,
            error="父目录不存在或不可写",
        )
    return ProjectCheckResponse(
        exists=False,
        writable=False,
        is_project=False,
        parent_writable=True,
    )


@router.get("/project/check", response_model=ProjectCheckResponse)
async def check_project(path: str, intent: Literal["create", "open"]) -> ProjectCheckResponse:
    """Pre-flight validation for folder picker (does NOT mutate filesystem)."""
    return _check_project_impl(path, intent)


@router.get("/recent-projects", response_model=List[RecentProject])
async def get_recent_projects() -> List[RecentProject]:
    """Most-recent first, capped at MAX_RECENT."""
    return load_recent()


@router.post(
    "/recent-projects/record",
    status_code=204,
    response_class=Response,
    response_model=None,
)
async def record_recent_project(req: RecordRecentRequest) -> None:
    """Persist a successful create/open for next-time default-path."""
    canonical = authorize_registration(req.path, req.intent)
    name = req.name or canonical.name
    record_recent(str(canonical), name, req.intent)
