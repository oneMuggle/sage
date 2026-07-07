"""RAG 服务客户端。

提供对独立 RAG 服务的 HTTP 客户端封装。
"""

from __future__ import annotations
from typing import Dict, List, Optional

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class RAGServiceClient:
    """RAG 服务客户端。"""

    def __init__(
        self,
        base_url: str = "http://localhost:8766",
        timeout: float = 10.0,
    ):
        """初始化客户端。

        Args:
            base_url: RAG 服务地址
            timeout: 请求超时时间（秒）
        """
        self.base_url = base_url
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        """异步上下文管理器入口。"""
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口。"""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def search(
        self,
        query: str,
        top_k: int = 5,
        filters: Optional[dict] = None,
    ) -> List[Dict[str, Any]]:
        """检索记忆。

        Args:
            query: 查询文本
            top_k: 返回结果数量
            filters: 过滤条件

        Returns:
            检索结果列表
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with' context manager.")

        try:
            response = await self._client.post(
                "/api/v1/search",
                json={
                    "query": query,
                    "top_k": top_k,
                    "filters": filters or {},
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["results"]
        except httpx.HTTPError as e:
            logger.error(f"RAG service search failed: {e}")
            raise

    async def index(self, documents: List[dict]) -> int:
        """索引文档。

        Args:
            documents: 文档列表

        Returns:
            索引数量
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with' context manager.")

        try:
            response = await self._client.post(
                "/api/v1/index",
                json={"documents": documents},
            )
            response.raise_for_status()
            data = response.json()
            return data["indexed_count"]
        except httpx.HTTPError as e:
            logger.error(f"RAG service index failed: {e}")
            raise

    async def delete(self, ids: List[str]) -> int:
        """删除文档。

        Args:
            ids: 文档 ID 列表

        Returns:
            删除数量
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with' context manager.")

        try:
            response = await self._client.request(
                "DELETE",
                "/api/v1/documents",
                json={"ids": ids},
            )
            response.raise_for_status()
            data = response.json()
            return data["deleted_count"]
        except httpx.HTTPError as e:
            logger.error(f"RAG service delete failed: {e}")
            raise

    async def health(self) -> dict:
        """健康检查。

        Returns:
            健康状态
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with' context manager.")

        try:
            response = await self._client.get("/health")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"RAG service health check failed: {e}")
            raise
