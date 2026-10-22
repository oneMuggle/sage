"""AI 增强功能路由（M1-M5: 任务分解 / 知识沉淀 / 进度顾问 / 语义检索 / 代码→Wiki）。

端点：
- ``POST /projects/{project_id}/ai/decompose-tasks/preview``
  调用 LLM 分解需求为里程碑树（预览，不写入 DB）。
- ``POST /projects/{project_id}/ai/decompose-tasks/apply``
  将预览结果写入 DB（调用 create_batch）。
- ``POST /projects/{project_id}/ai/extract-knowledge``
  调用 LLM 从会话历史提取知识条目建议（预览，不写入 DB）。
- ``POST /projects/{project_id}/ai/extract-knowledge/confirm``
  将用户确认的知识条目写入 ProjectProfileStore。
- ``GET /projects/{project_id}/ai/advice``
  获取项目健康评分和建议（30min 缓存）。
- ``POST /projects/{project_id}/ai/advice/refresh``
  强制刷新项目顾问分析（忽略缓存）。
- ``GET /projects/{project_id}/ai/materials/search``
  语义检索项目资料（sqlite-vec KNN）。(M4, 2026-10-12)
- ``GET /projects/{project_id}/ai/materials/indexing-stats``
  获取资料索引统计信息。(M4, 2026-10-12)
- ``POST /projects/{project_id}/ai/materials/{material_id}/index``
  手动触发单个资料的语义索引。(M4, 2026-10-12)
- ``POST /projects/{project_id}/ai/wiki/generate``
  调用 LLM 生成项目 Wiki 文档。(M5, 2026-10-12)
- ``GET /projects/{project_id}/ai/wiki/scan-files``
  扫描项目源文件（预览）。(M5, 2026-10-12)
- ``GET /projects/{project_id}/ai/wiki/extract-symbols``
  提取项目符号信息（预览）。(M5, 2026-10-12)

调用链:
  前端 -> preview (LLM) -> 用户审核 -> apply (create_batch)
  前端 -> extract-knowledge (LLM) -> 用户审核 -> confirm (profile store)
  前端 -> advice (LLM, cached) -> 展示 -> refresh (强制刷新)
  前端 -> materials/search (语义) -> 展示匹配 chunks
  前端 -> wiki/generate (LLM) -> 扫描+提取+规划+生成 -> wiki/ 目录
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["projects-ai"])


# ── Pydantic schemas ─────────────────────────────────────────────────────────


class DecomposePreviewRequest(BaseModel):
    """任务分解预览请求。"""

    model_config = ConfigDict(extra="forbid")

    requirement: str = Field(min_length=1, max_length=4000)
    context: Optional[str] = Field(default=None, max_length=2000)


class PreviewMilestoneNode(BaseModel):
    """预览中的单个里程碑节点（可嵌套）。"""

    model_config = ConfigDict(extra="forbid")

    title: str
    description: Optional[str] = None
    stage: Optional[str] = None
    due_date: Optional[str] = None
    estimated_days: Optional[float] = None
    children: List[PreviewMilestoneNode] = Field(default_factory=list)


# 解决自引用 (pydantic v1/v2 兼容)
if hasattr(PreviewMilestoneNode, "model_rebuild"):
    PreviewMilestoneNode.model_rebuild()
else:
    PreviewMilestoneNode.update_forward_refs()


class DecomposePreviewResponse(BaseModel):
    """任务分解预览响应。"""

    model_config = ConfigDict(extra="forbid")

    reasoning: str
    milestones: List[PreviewMilestoneNode]
    total_count: int


class DecomposeApplyRequest(BaseModel):
    """任务分解应用请求（将预览结果写入 DB）。"""

    model_config = ConfigDict(extra="forbid")

    milestones: List[PreviewMilestoneNode]


class DecomposeApplyResponse(BaseModel):
    """任务分解应用响应。"""

    model_config = ConfigDict(extra="forbid")

    created_count: int
    milestone_ids: List[str]


# ── M2: 知识提取 schemas ────────────────────────────────────────────────────


class ExtractKnowledgeRequest(BaseModel):
    """知识提取请求。"""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=128)
    max_messages: int = Field(default=50, ge=1, le=200)


class KnowledgeEntryProposal(BaseModel):
    """LLM 建议的单个知识条目（待用户确认）。"""

    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=200)
    category: str = Field(default="convention")
    importance: int = Field(default=5, ge=1, le=10)
    source_message_ids: List[str] = Field(default_factory=list)
    reasoning: Optional[str] = None


class ExtractKnowledgeResponse(BaseModel):
    """知识提取响应。"""

    model_config = ConfigDict(extra="forbid")

    reasoning: str
    entries: List[KnowledgeEntryProposal]
    project_key: str


class ConfirmKnowledgeRequest(BaseModel):
    """知识确认请求（将用户勾选的条目写入画像）。"""

    model_config = ConfigDict(extra="forbid")

    entries: List[KnowledgeEntryProposal]


class ConfirmKnowledgeResponse(BaseModel):
    """知识确认响应。"""

    model_config = ConfigDict(extra="forbid")

    created: int
    skipped: int
    ids: List[str]


# ── M3: 项目进度顾问 schemas ───────────────────────────────────────────────


class AdvisorRiskResponse(BaseModel):
    """顾问识别的风险项。"""

    description: str
    severity: str
    suggestion: Optional[str] = None


class AdvisorSuggestionResponse(BaseModel):
    """顾问给出的改进建议。"""

    action: str
    reason: Optional[str] = None
    priority: str


class AdviceResponse(BaseModel):
    """项目顾问分析响应。"""

    model_config = ConfigDict(extra="forbid")

    health_score: int
    summary: str
    risks: List[AdvisorRiskResponse]
    suggestions: List[AdvisorSuggestionResponse]
    cached_at: Optional[int] = None


# ── M4: 语义检索 schemas ─────────────────────────────────────────────────────


class SemanticSearchRequest(BaseModel):
    """语义检索请求。"""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)


class SemanticSearchResultItem(BaseModel):
    """语义检索结果单项。"""

    material_id: str
    chunk_index: int
    content: str
    score: float
    project_id: str


class SemanticSearchResponse(BaseModel):
    """语义检索响应。"""

    model_config = ConfigDict(extra="forbid")

    results: List[SemanticSearchResultItem]
    total: int
    embedder_type: str
    embedder_dims: int


class IndexingStatsResponse(BaseModel):
    """索引统计响应。"""

    model_config = ConfigDict(extra="forbid")

    total_materials: int
    indexed_materials: int
    pending_materials: int
    failed_materials: int
    total_chunks: int
    embedder_type: str
    embedder_dims: int


# ── Endpoints ────────────────────────────────────────────────────────────────


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"code": code, "message": message}
    )


@router.post(
    "/{project_id}/ai/decompose-tasks/preview",
    response_model=DecomposePreviewResponse,
)
async def decompose_tasks_preview(
    project_id: str, request: DecomposePreviewRequest
) -> DecomposePreviewResponse:
    """调用 LLM 将需求分解为里程碑树（仅预览，不写入 DB）。"""
    from backend.data.project_repo import ProjectRepository
    from backend.services.project_task_decomposer import (
        ProjectTaskDecomposer,
    )

    # 验证项目存在
    project = ProjectRepository().get(project_id)
    if project is None:
        raise _error(404, "project_not_found", "项目不存在")

    decomposer = ProjectTaskDecomposer()
    if not decomposer.available:
        raise _error(
            503,
            "llm_unavailable",
            "LLM 客户端不可用，请在设置中配置 AI 端点",
        )

    try:
        result = await decomposer.decompose(
            project_id=project_id,
            requirement=request.requirement,
            context=request.context,
        )
    except ValueError as exc:
        raise _error(400, "invalid_input", str(exc)) from exc
    except RuntimeError as exc:
        raise _error(502, "llm_error", str(exc)) from exc

    preview = result.to_preview()
    # 计算总数（包括所有层级的里程碑）
    total = _count_milestones(preview)

    return DecomposePreviewResponse(
        reasoning=result.reasoning,
        milestones=[PreviewMilestoneNode(**m) for m in preview],
        total_count=total,
    )


@router.post(
    "/{project_id}/ai/decompose-tasks/apply",
    response_model=DecomposeApplyResponse,
)
def decompose_tasks_apply(
    project_id: str, request: DecomposeApplyRequest
) -> DecomposeApplyResponse:
    """将预览结果写入 DB（批量创建里程碑）。"""
    from backend.data.project_milestone_repo import ProjectMilestoneRepository
    from backend.data.project_repo import ProjectRepository

    # 验证项目存在
    project = ProjectRepository().get(project_id)
    if project is None:
        raise _error(404, "project_not_found", "项目不存在")

    if not request.milestones:
        return DecomposeApplyResponse(created_count=0, milestone_ids=[])

    # 展平树为 create_batch 接受的格式
    items = _flatten_milestones(request.milestones)

    repo = ProjectMilestoneRepository()
    created = repo.create_batch(project_id, items)

    return DecomposeApplyResponse(
        created_count=len(created),
        milestone_ids=[m.id for m in created],
    )


# ── M2: 知识提取端点 ────────────────────────────────────────────────────────


@router.post(
    "/{project_id}/ai/extract-knowledge",
    response_model=ExtractKnowledgeResponse,
)
async def extract_knowledge(
    project_id: str, request: ExtractKnowledgeRequest
) -> ExtractKnowledgeResponse:
    """调用 LLM 从会话历史提取知识条目建议（仅预览，不写入 DB）。"""
    from backend.data.project_repo import ProjectRepository
    from backend.services.project_knowledge_extractor import (
        ProjectKnowledgeExtractor,
    )

    project = ProjectRepository().get(project_id)
    if project is None:
        raise _error(404, "project_not_found", "项目不存在")

    extractor = ProjectKnowledgeExtractor()
    if not extractor.available:
        raise _error(
            503,
            "llm_unavailable",
            "LLM 客户端不可用，请在设置中配置 AI 端点",
        )

    try:
        result = await extractor.extract(
            project_id=project_id,
            session_id=request.session_id,
            max_messages=request.max_messages,
        )
    except ValueError as exc:
        raise _error(400, "invalid_input", str(exc)) from exc
    except RuntimeError as exc:
        raise _error(502, "llm_error", str(exc)) from exc

    project_key = getattr(project, "path", "") or ""
    preview = result.to_preview()

    return ExtractKnowledgeResponse(
        reasoning=result.reasoning,
        entries=[KnowledgeEntryProposal(**e) for e in preview],
        project_key=project_key,
    )


@router.post(
    "/{project_id}/ai/extract-knowledge/confirm",
    response_model=ConfirmKnowledgeResponse,
)
def confirm_knowledge(
    project_id: str, request: ConfirmKnowledgeRequest
) -> ConfirmKnowledgeResponse:
    """将用户确认的知识条目写入 ProjectProfileStore。"""
    from backend.data.project_repo import ProjectRepository
    from backend.services.project_knowledge_extractor import (
        ProjectKnowledgeExtractor,
    )

    project = ProjectRepository().get(project_id)
    if project is None:
        raise _error(404, "project_not_found", "项目不存在")

    project_key = getattr(project, "path", "") or ""
    if not project_key:
        raise _error(
            400, "no_project_key", "项目缺少 workspace 路径，无法写入画像"
        )

    if not request.entries:
        return ConfirmKnowledgeResponse(created=0, skipped=0, ids=[])

    extractor = ProjectKnowledgeExtractor()
    entry_dicts = [e.model_dump() for e in request.entries]
    result = extractor.confirm(project_key=project_key, entries=entry_dicts)

    return ConfirmKnowledgeResponse(
        created=result["created"],
        skipped=result["skipped"],
        ids=result["ids"],
    )


# ── M3: 项目进度顾问端点 ───────────────────────────────────────────────────


@router.get(
    "/{project_id}/ai/advice",
    response_model=AdviceResponse,
)
async def get_advice(project_id: str) -> AdviceResponse:
    """获取项目健康评分和建议（使用 30min 缓存）。"""
    from backend.data.project_repo import ProjectRepository
    from backend.services.project_advisor import ProjectAdvisor

    project = ProjectRepository().get(project_id)
    if project is None:
        raise _error(404, "project_not_found", "项目不存在")

    advisor = ProjectAdvisor()
    if not advisor.available:
        raise _error(
            503,
            "llm_unavailable",
            "LLM 客户端不可用，请在设置中配置 AI 端点",
        )

    try:
        result = await advisor.analyze(project_id=project_id)
    except ValueError as exc:
        raise _error(400, "invalid_input", str(exc)) from exc
    except RuntimeError as exc:
        raise _error(502, "llm_error", str(exc)) from exc

    return AdviceResponse(
        health_score=result.health_score,
        summary=result.summary,
        risks=[AdvisorRiskResponse(**r.to_dict()) for r in result.risks],
        suggestions=[
            AdvisorSuggestionResponse(**s.to_dict()) for s in result.suggestions
        ],
        cached_at=result.cached_at,
    )


@router.post(
    "/{project_id}/ai/advice/refresh",
    response_model=AdviceResponse,
)
async def refresh_advice(project_id: str) -> AdviceResponse:
    """强制刷新项目顾问分析（忽略缓存）。"""
    from backend.data.project_repo import ProjectRepository
    from backend.services.project_advisor import ProjectAdvisor

    project = ProjectRepository().get(project_id)
    if project is None:
        raise _error(404, "project_not_found", "项目不存在")

    advisor = ProjectAdvisor()
    if not advisor.available:
        raise _error(
            503,
            "llm_unavailable",
            "LLM 客户端不可用，请在设置中配置 AI 端点",
        )

    try:
        result = await advisor.analyze(
            project_id=project_id, force_refresh=True
        )
    except ValueError as exc:
        raise _error(400, "invalid_input", str(exc)) from exc
    except RuntimeError as exc:
        raise _error(502, "llm_error", str(exc)) from exc

    return AdviceResponse(
        health_score=result.health_score,
        summary=result.summary,
        risks=[AdvisorRiskResponse(**r.to_dict()) for r in result.risks],
        suggestions=[
            AdvisorSuggestionResponse(**s.to_dict()) for s in result.suggestions
        ],
        cached_at=result.cached_at,
    )


# ── M4: 语义检索端点 ─────────────────────────────────────────────────────────


@router.get(
    "/{project_id}/ai/materials/search",
    response_model=SemanticSearchResponse,
)
async def semantic_search_materials(
    project_id: str,
    query: str,
    top_k: int = 5,
) -> SemanticSearchResponse:
    """语义检索项目资料。

    将查询文本向量化，在 sqlite-vec 中做 KNN 检索，返回最相关的
    资料 chunks。仅搜索 status='ready' 且 enabled=1 的资料。

    当 sqlite-vec 不可用或 embedder 未配置时，返回空结果（不报错）。
    """
    from backend.data.project_repo import ProjectRepository
    from backend.services.project_material_indexer import ProjectMaterialIndexer

    project = ProjectRepository().get(project_id)
    if project is None:
        raise _error(404, "project_not_found", "项目不存在")

    indexer = ProjectMaterialIndexer()
    if not indexer.available:
        # sqlite-vec 不可用 → 返回空结果（优雅降级）
        return SemanticSearchResponse(
            results=[],
            total=0,
            embedder_type="unavailable",
            embedder_dims=0,
        )

    results = indexer.search(
        project_id=project_id,
        query=query,
        top_k=min(top_k, 20),
    )

    return SemanticSearchResponse(
        results=[
            SemanticSearchResultItem(
                material_id=r.material_id,
                chunk_index=r.chunk_index,
                content=r.content,
                score=r.score,
                project_id=r.project_id,
            )
            for r in results
        ],
        total=len(results),
        embedder_type=indexer.dimensions and _embedder_type_name(indexer),
        embedder_dims=indexer.dimensions,
    )


@router.get(
    "/{project_id}/ai/materials/indexing-stats",
    response_model=IndexingStatsResponse,
)
async def get_indexing_stats(project_id: str) -> IndexingStatsResponse:
    """获取项目资料索引统计信息。"""
    from backend.data.project_repo import ProjectRepository
    from backend.services.project_material_indexer import ProjectMaterialIndexer

    project = ProjectRepository().get(project_id)
    if project is None:
        raise _error(404, "project_not_found", "项目不存在")

    indexer = ProjectMaterialIndexer()
    stats = indexer.get_stats(project_id=project_id)

    return IndexingStatsResponse(
        total_materials=stats.total_materials,
        indexed_materials=stats.indexed_materials,
        pending_materials=stats.pending_materials,
        failed_materials=stats.failed_materials,
        total_chunks=stats.total_chunks,
        embedder_type=stats.embedder_type,
        embedder_dims=stats.embedder_dims,
    )


@router.post(
    "/{project_id}/ai/materials/{material_id}/index",
)
async def trigger_material_index(
    project_id: str,
    material_id: str,
) -> Dict[str, Any]:
    """手动触发单个资料的语义索引。

    通常 indexer 会自动处理 pending_index 资料，此端点供用户主动
    重新索引（例如修改了资料内容后）。
    """
    from backend.data.project_material_repo import ProjectMaterialRepository
    from backend.data.project_repo import ProjectRepository
    from backend.services.project_material_indexer import ProjectMaterialIndexer

    project = ProjectRepository().get(project_id)
    if project is None:
        raise _error(404, "project_not_found", "项目不存在")

    repo = ProjectMaterialRepository()
    material = repo.get(material_id)
    if material is None:
        raise _error(404, "material_not_found", "资料不存在")
    if material.project_id != project_id:
        raise _error(403, "material_project_mismatch", "资料不属于该项目")

    indexer = ProjectMaterialIndexer()
    if not indexer.available:
        raise _error(
            503,
            "indexer_unavailable",
            "sqlite-vec 不可用，无法进行语义索引",
        )

    # 在线程池中执行同步索引
    import asyncio
    loop = asyncio.get_event_loop()
    success = await loop.run_in_executor(None, indexer.index_material, material_id)

    if success:
        return {"status": "ok", "material_id": material_id}
    else:
        raise _error(500, "indexing_failed", "资料索引失败，请查看日志")


def _embedder_type_name(indexer: Any) -> str:
    """从 indexer 获取 embedder 类型名称。"""
    return type(indexer._embedder).__name__.lower().replace("embedder", "")


# ── M5: 代码→Wiki 生成端点 ────────────────────────────────────────────────────


class WikiGenerateRequest(BaseModel):
    """代码→Wiki 生成请求。"""

    model_config = ConfigDict(extra="forbid")

    incremental: bool = Field(default=False)


class WikiGenerateResponse(BaseModel):
    """代码→Wiki 生成响应。"""

    model_config = ConfigDict(extra="forbid")

    pages_generated: int
    pages_updated: int
    pages_skipped: int
    errors: List[str]
    wiki_paths: List[str]


class FileScanResponse(BaseModel):
    """文件扫描响应。"""

    model_config = ConfigDict(extra="forbid")

    files: List[Dict[str, Any]]
    total: int


class SymbolExtractResponse(BaseModel):
    """符号提取响应。"""

    model_config = ConfigDict(extra="forbid")

    symbols: List[Dict[str, Any]]
    total: int


@router.post(
    "/{project_id}/ai/wiki/generate",
    response_model=WikiGenerateResponse,
)
async def generate_wiki(
    project_id: str,
    request: WikiGenerateRequest,
) -> WikiGenerateResponse:
    """调用 LLM 生成项目 Wiki 文档。

    流程:
    1. 扫描 allowed_paths 内源文件
    2. Python AST 提取符号 (函数/类/方法)
    3. 构建 import/inherit 依赖图
    4. LLM 规划文档结构
    5. 逐模块生成 Markdown
    6. 写入 wiki/ 目录

    注意: 此操作会覆盖已有的 wiki/ 下自动生成的页面。
    """
    from backend.data.project_repo import ProjectRepository
    from backend.services.project_wiki_generator import ProjectWikiGenerator

    project = ProjectRepository().get(project_id)
    if project is None:
        raise _error(404, "project_not_found", "项目不存在")

    generator = ProjectWikiGenerator()
    if not generator.available:
        raise _error(
            503,
            "llm_unavailable",
            "LLM 客户端不可用，请在设置中配置 AI 端点",
        )

    try:
        result = await generator.generate(
            project_id=project_id,
            incremental=request.incremental,
        )
    except Exception as exc:
        logger.error("Wiki 生成失败: %s", exc)
        raise _error(500, "generation_failed", str(exc)) from exc

    return WikiGenerateResponse(
        pages_generated=result.pages_generated,
        pages_updated=result.pages_updated,
        pages_skipped=result.pages_skipped,
        errors=result.errors,
        wiki_paths=result.wiki_paths,
    )


@router.get(
    "/{project_id}/ai/wiki/scan-files",
    response_model=FileScanResponse,
)
async def scan_project_files(
    project_id: str,
    languages: Optional[str] = None,
) -> FileScanResponse:
    """扫描项目内的源文件（预览，不生成 Wiki）。

    用于前端展示"将要扫描哪些文件"。
    """
    from backend.data.project_repo import ProjectRepository
    from backend.services.project_wiki_generator import ProjectWikiGenerator

    project = ProjectRepository().get(project_id)
    if project is None:
        raise _error(404, "project_not_found", "项目不存在")

    lang_set = set(languages.split(",")) if languages else {"python"}

    generator = ProjectWikiGenerator()
    files = generator.scan_files(
        project_root=project.path,
        allowed_paths=project.allowed_paths,
        languages=lang_set,
    )

    return FileScanResponse(
        files=[
            {
                "path": f.path,
                "language": f.language,
                "size_bytes": f.size_bytes,
            }
            for f in files[:200]  # 限制返回数量
        ],
        total=len(files),
    )


@router.get(
    "/{project_id}/ai/wiki/extract-symbols",
    response_model=SymbolExtractResponse,
)
async def extract_project_symbols(
    project_id: str,
) -> SymbolExtractResponse:
    """提取项目内的符号信息（预览，不生成 Wiki）。

    用于前端展示"将分析哪些函数/类"。
    """
    from backend.data.project_repo import ProjectRepository
    from backend.services.project_wiki_generator import ProjectWikiGenerator

    project = ProjectRepository().get(project_id)
    if project is None:
        raise _error(404, "project_not_found", "项目不存在")

    generator = ProjectWikiGenerator()
    files = generator.scan_files(
        project_root=project.path,
        allowed_paths=project.allowed_paths,
    )
    symbols = generator.extract_symbols(files)

    return SymbolExtractResponse(
        symbols=[
            {
                "name": s.name,
                "kind": s.kind,
                "file": s.file_path,
                "lineno": s.lineno,
                "docstring": (s.docstring or "")[:200],
                "parent": s.parent,
            }
            for s in symbols[:500]  # 限制返回数量
        ],
        total=len(symbols),
    )


# ── Helpers ──────────────────────────────────────────────────────────────────


def _flatten_milestones(
    nodes: List[PreviewMilestoneNode],
) -> List[Dict[str, Any]]:
    """将嵌套的里程碑树展平为 create_batch 接受的 dict 列表。

    使用 _ref 和 parent_ref 建立父子关系。
    """
    items: List[Dict[str, Any]] = []
    counter = [0]

    def _walk(
        node: PreviewMilestoneNode,
        parent_ref: Optional[str] = None,
    ) -> str:
        counter[0] += 1
        ref = f"m{counter[0]}"
        items.append(
            {
                "_ref": ref,
                "title": node.title,
                "description": node.description,
                "stage": node.stage,
                "due_date": node.due_date,
                "estimated_days": node.estimated_days,
                "parent_id": parent_ref,
                "sort_order": len(items) - 1,
            }
        )
        for child in node.children:
            _walk(child, parent_ref=ref)
        return ref

    for node in nodes:
        _walk(node)

    return items


def _count_milestones(nodes: List[dict]) -> int:
    """递归计算里程碑总数。"""
    count = 0
    for node in nodes:
        count += 1
        children = node.get("children", [])
        if children:
            count += _count_milestones(children)
    return count


__all__ = ["router"]
