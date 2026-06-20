"""RAG 服务 API 路由。"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .storage import RAGStorage

router = APIRouter(prefix="/api/v1")


# ==================== 请求/响应模型 ====================


class SearchRequest(BaseModel):
    """检索请求。"""

    query: str
    top_k: int = 5
    filters: dict | None = None


class SearchResult(BaseModel):
    """检索结果。"""

    id: str
    content: str
    score: float
    metadata: dict


class SearchResponse(BaseModel):
    """检索响应。"""

    results: list[SearchResult]


class IndexRequest(BaseModel):
    """索引请求。"""

    documents: list[dict]


class IndexResponse(BaseModel):
    """索引响应。"""

    indexed_count: int


class DeleteRequest(BaseModel):
    """删除请求。"""

    ids: list[str]


class DeleteResponse(BaseModel):
    """删除响应。"""

    deleted_count: int


# ==================== API 端点 ====================


@router.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest, request: Request) -> SearchResponse:
    """检索记忆。

    Args:
        req: 检索请求
        request: FastAPI 请求对象

    Returns:
        检索结果列表
    """
    storage: RAGStorage = request.app.state.storage

    try:
        results = await storage.search(
            query=req.query,
            top_k=req.top_k,
            filters=req.filters,
        )

        return SearchResponse(
            results=[
                SearchResult(
                    id=r["id"],
                    content=r["content"],
                    score=r["score"],
                    metadata=r["metadata"],
                )
                for r in results
            ]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/index", response_model=IndexResponse)
async def index(req: IndexRequest, request: Request) -> IndexResponse:
    """索引文档。

    Args:
        req: 索引请求
        request: FastAPI 请求对象

    Returns:
        索引数量
    """
    storage: RAGStorage = request.app.state.storage

    try:
        count = await storage.index(req.documents)
        return IndexResponse(indexed_count=count)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/documents", response_model=DeleteResponse)
async def delete_documents(req: DeleteRequest, request: Request) -> DeleteResponse:
    """删除文档。

    Args:
        req: 删除请求
        request: FastAPI 请求对象

    Returns:
        删除数量
    """
    storage: RAGStorage = request.app.state.storage

    try:
        count = await storage.delete(req.ids)
        return DeleteResponse(deleted_count=count)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
