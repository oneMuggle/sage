"""网络搜索抽象。

支持多个搜索 API：Tavily、SerpApi、SearXNG。
实现多查询策略，收集多个来源的信息。
"""
import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from typing import List

import httpx

logger = logging.getLogger(__name__)


class SearchProvider(str, Enum):
    """搜索提供者。"""

    TAVILY = "tavily"
    SERPAPI = "serpapi"
    SEARXNG = "searxng"


@dataclass
class WebSearchResult:
    """网络搜索结果。"""

    title: str
    url: str
    snippet: str
    score: float = 1.0  # 相关性分数


@dataclass
class WebSearchResponse:
    """网络搜索响应。"""

    query: str
    results: List[WebSearchResult]
    total: int


class WebSearchClient:
    """网络搜索客户端。"""

    def __init__(
        self,
        provider: SearchProvider,
        api_key: str = "",
        base_url: str = "",
    ):
        """初始化搜索客户端。

        Args:
            provider: 搜索提供者
            api_key: API 密钥（Tavily/SerpApi 需要）
            base_url: 基础 URL（SearXNG 需要）
        """
        self.provider = provider
        self.api_key = api_key
        self.base_url = base_url

    async def search(self, query: str, max_results: int = 10) -> WebSearchResponse:
        """执行网络搜索。

        Args:
            query: 搜索查询
            max_results: 最大结果数

        Returns:
            WebSearchResponse: 搜索结果
        """
        if self.provider == SearchProvider.TAVILY:
            return await self._search_tavily(query, max_results)
        elif self.provider == SearchProvider.SERPAPI:
            return await self._search_serpapi(query, max_results)
        elif self.provider == SearchProvider.SEARXNG:
            return await self._search_searxng(query, max_results)
        else:
            raise ValueError(f"不支持的搜索提供者: {self.provider}")

    async def _search_tavily(self, query: str, max_results: int) -> WebSearchResponse:
        """使用 Tavily API 搜索。

        Tavily 是专为 AI Agent 设计的搜索 API，返回结构化结果。
        """
        if not self.api_key:
            raise ValueError("Tavily 需要 API 密钥")

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self.api_key,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "advanced",
                    "include_answer": False,
                },
            )

            if response.status_code != 200:
                raise Exception(f"Tavily API 错误: {response.status_code} - {response.text}")

            data = response.json()
            results = [
                WebSearchResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    snippet=r.get("content", ""),
                    score=r.get("score", 1.0),
                )
                for r in data.get("results", [])
            ]

            return WebSearchResponse(query=query, results=results, total=len(results))

    async def _search_serpapi(self, query: str, max_results: int) -> WebSearchResponse:
        """使用 SerpApi 搜索。

        SerpApi 提供 Google 搜索结果的 API。
        """
        if not self.api_key:
            raise ValueError("SerpApi 需要 API 密钥")

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                "https://serpapi.com/search.json",
                params={
                    "q": query,
                    "api_key": self.api_key,
                    "engine": "google",
                    "num": max_results,
                },
            )

            if response.status_code != 200:
                raise Exception(f"SerpApi 错误: {response.status_code} - {response.text}")

            data = response.json()
            results = [
                WebSearchResult(
                    title=r.get("title", ""),
                    url=r.get("link", ""),
                    snippet=r.get("snippet", ""),
                    score=1.0,
                )
                for r in data.get("organic_results", [])
            ]

            return WebSearchResponse(query=query, results=results, total=len(results))

    async def _search_searxng(self, query: str, max_results: int) -> WebSearchResponse:
        """使用 SearXNG 搜索。

        SearXNG 是自托管的隐私保护搜索引擎。
        """
        if not self.base_url:
            raise ValueError("SearXNG 需要 base_url")

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{self.base_url}/search",
                params={
                    "q": query,
                    "format": "json",
                    "pageno": 1,
                },
            )

            if response.status_code != 200:
                raise Exception(f"SearXNG 错误: {response.status_code} - {response.text}")

            data = response.json()
            results = [
                WebSearchResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    snippet=r.get("content", ""),
                    score=1.0,
                )
                for r in data.get("results", [])[:max_results]
            ]

            return WebSearchResponse(query=query, results=results, total=len(results))


async def multi_query_search(
    queries: List[str],
    provider: SearchProvider,
    api_key: str = "",
    base_url: str = "",
    max_results_per_query: int = 5,
) -> List[WebSearchResult]:
    """执行多查询搜索。

    对多个查询并行执行搜索，合并结果并去重。

    Args:
        queries: 查询列表
        provider: 搜索提供者
        api_key: API 密钥
        base_url: 基础 URL
        max_results_per_query: 每个查询的最大结果数

    Returns:
        list[WebSearchResult]: 合并后的搜索结果（去重）
    """
    client = WebSearchClient(provider, api_key, base_url)

    # 并行执行所有查询
    tasks = [client.search(query, max_results_per_query) for query in queries]
    responses = await asyncio.gather(*tasks, return_exceptions=True)

    # 合并结果
    all_results = []
    seen_urls = set()

    for response in responses:
        if isinstance(response, Exception):
            logger.error(f"搜索失败: {response}")
            continue

        for result in response.results:
            if result.url not in seen_urls:
                all_results.append(result)
                seen_urls.add(result.url)

    # 按分数排序
    all_results.sort(key=lambda r: r.score, reverse=True)

    return all_results
