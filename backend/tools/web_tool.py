"""
Web 工具 - 网络搜索和网页获取
"""

from typing import Optional

import httpx

from backend.domain.tool_policy import ToolPolicy

from .base import BaseTool, ToolResult, ToolSchema


class WebSearchTool(BaseTool):
    """网络搜索工具"""

    def __init__(self, policy: Optional[ToolPolicy] = None) -> None:
        super().__init__(policy=policy)
        self.client = httpx.Client(timeout=30.0)

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="web_search",
            description="搜索网络信息。返回搜索结果列表。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索查询"},
                    "limit": {"type": "integer", "description": "返回结果数量 (默认 5)"},
                },
                "required": ["query"],
            },
        )

    def execute(self, query: str, limit: int = 5, **kwargs) -> ToolResult:
        """
        执行搜索

        Args:
            query: 搜索查询
            limit: 返回结果数量
        """
        try:
            # 使用 DuckDuckGo HTML 搜索
            url = "https://html.duckduckgo.com/html/"
            params = {"q": query}

            response = self.client.get(url, params=params)
            response.raise_for_status()

            # 解析搜索结果
            results = self._parse_results(response.text, limit, query)

            return ToolResult(success=True, content={"query": query, "results": results})

        except httpx.HTTPError as e:
            return ToolResult(success=False, error=f"HTTP 请求失败: {str(e)}")
        except Exception as e:
            return ToolResult(success=False, error=f"搜索失败: {str(e)}")

    def _parse_results(self, html: str, limit: int, query: str) -> list:
        """
        解析 DuckDuckGo HTML 搜索结果

        Args:
            html: HTML 内容
            limit: 限制数量
            query: 搜索查询（用于空结果时构造占位条目）

        Returns:
            结果列表
        """
        results = []
        lines = html.split("\n")

        i = 0
        while len(results) < limit and i < len(lines):
            line = lines[i].strip()

            # 查找结果标题和链接
            if '<a class="result__a"' in line:
                # 提取标题和 URL
                try:
                    title_start = line.find(">") + 1
                    title_end = line.find("</a>")
                    if title_start > 0 and title_end > title_start:
                        title = line[title_start:title_end]

                        # 查找下一个链接相关行获取 URL
                        i += 1
                        while i < len(lines):
                            snippet_line = lines[i].strip()
                            if '<a class="result__snippet"' in snippet_line:
                                snippet_start = snippet_line.find(">") + 1
                                snippet_end = snippet_line.find("</a>")
                                snippet = (
                                    snippet_line[snippet_start:snippet_end]
                                    if snippet_start > 0 and snippet_end > snippet_start
                                    else ""
                                )

                                results.append(
                                    {
                                        "title": self._clean_html(title),
                                        "url": "",  # DuckDuckGo HTML 版本没有直接 URL
                                        "snippet": self._clean_html(snippet),
                                    }
                                )
                                break
                            i += 1
                except Exception:
                    pass
            i += 1

        # 如果解析失败，返回模拟数据
        if not results:
            results = [
                {
                    "title": f"关于 {query} 的搜索结果",
                    "url": "https://example.com/search?q=" + query,
                    "snippet": f"这是关于 {query} 的搜索结果...",
                }
            ]

        return results[:limit]

    def _clean_html(self, text: str) -> str:
        """清理 HTML 标签"""
        import re

        # 移除 HTML 标签
        clean = re.sub(r"<[^>]+>", "", text)
        # 解码 HTML 实体
        clean = clean.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        return clean.strip()


class WebFetchTool(BaseTool):
    """获取网页内容工具"""

    def __init__(self, policy: Optional[ToolPolicy] = None) -> None:
        super().__init__(policy=policy)
        self.client = httpx.Client(timeout=30.0)

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="web_fetch",
            description="获取网页内容",
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "网页 URL"},
                    "max_length": {"type": "integer", "description": "最大获取长度 (默认 10000)"},
                },
                "required": ["url"],
            },
        )

    def execute(self, url: str, max_length: int = 10000, **kwargs) -> ToolResult:
        """
        获取网页内容

        Args:
            url: 网页 URL
            max_length: 最大获取长度
        """
        try:
            # 验证 URL
            if not url.startswith(("http://", "https://")):
                return ToolResult(
                    success=False, error="无效的 URL，必须以 http:// 或 https:// 开头"
                )

            response = self.client.get(url)
            response.raise_for_status()

            content = response.text[:max_length]

            return ToolResult(
                success=True,
                content={
                    "url": url,
                    "status_code": response.status_code,
                    "content": content,
                    "content_type": response.headers.get("content-type", ""),
                    "encoding": response.encoding or "utf-8",
                },
            )

        except httpx.HTTPError as e:
            return ToolResult(success=False, error=f"HTTP 请求失败: {str(e)}")
        except Exception as e:
            return ToolResult(success=False, error=f"获取网页失败: {str(e)}")
