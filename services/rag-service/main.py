"""RAG 服务 - 独立记忆检索服务。

提供 HTTP API 进行记忆存储、检索和删除。
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api.routes import router
from .core.storage import RAGStorage

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。"""
    # 启动时初始化存储
    logger.info("初始化 RAG 服务...")
    app.state.storage = RAGStorage()
    await app.state.storage.initialize()
    logger.info("RAG 服务已启动")

    yield

    # 关闭时清理资源
    logger.info("关闭 RAG 服务...")
    await app.state.storage.shutdown()
    logger.info("RAG 服务已关闭")


app = FastAPI(
    title="Sage RAG Service",
    description="独立记忆检索服务",
    version="0.1.0",
    lifespan=lifespan,
)

# 注册路由
app.include_router(router)


@app.get("/health")
async def health():
    """健康检查端点。"""
    return {
        "status": "healthy",
        "service": "rag-service",
        "version": "0.1.0",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8766)
