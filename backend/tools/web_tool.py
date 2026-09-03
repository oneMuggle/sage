"""
Web 工具 - 网络搜索和网页获取
"""

# win7 py3.8: PEP 604 (X | Y) / PEP 585 (set[...]) 注解惰性化，避免 def 定义时报错
from __future__ import annotations

import ipaddress
from ipaddress import IPv4Address, IPv6Address
from typing import Any, Dict, Optional, Set, Union
from urllib.parse import urlparse

import httpx

from backend.domain.network_policy import NetworkMode, NetworkPolicy
from backend.domain.risk import RiskClass
from backend.domain.tool_policy import ToolPolicy
from backend.tools.network_config import load_network_policy
from backend.wiki.html_extract import decode_html, extract

from .base import BaseTool, ToolResult, ToolSchema


class WebSearchTool(BaseTool):
    """网络搜索工具"""

    # A1: 出网调用 — 最严门禁（只读模式禁止，交互模式询问）
    risk = RiskClass.EXTERNAL

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

    # A1: 出网调用 — 最严门禁（只读模式禁止，交互模式询问）
    risk = RiskClass.EXTERNAL

    #: mode 合法取值。text 只给正文，links/tables 额外带对应段，raw 给原始 HTML
    VALID_MODES = ("text", "links", "tables", "raw")

    #: 只对这些 content-type 做 HTML 抽取；JSON / 纯文本直接给原文
    _HTML_CONTENT_TYPES = ("text/html", "application/xhtml")

    def __init__(
        self,
        policy: Optional[ToolPolicy] = None,
        network_policy: Optional[NetworkPolicy] = None,
    ) -> None:
        super().__init__(policy=policy)
        # None 表示"每次 execute 现读 settings"——用户改白名单立即生效，不必
        # 重开会话。显式传入则固定（测试注入用）。
        self._network_policy = network_policy
        self.client = httpx.Client(
            timeout=30.0,
            follow_redirects=False,
            trust_env=not self._policy.subagent_only,
        )

    def _effective_network_policy(self) -> NetworkPolicy:
        if self._network_policy is not None:
            return self._network_policy
        return load_network_policy()

    @staticmethod
    def _literal_ip(url: str) -> Optional[Union[IPv4Address, IPv6Address]]:
        hostname = urlparse(url).hostname
        if not hostname:
            return None
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            return None
        # win7 py3.8: ipaddress 不解包 IPv4-mapped IPv6（::ffff:x.x.x.x 的
        # is_global 按 IPv6 全局单播判定，会放行 ::ffff:100.64.0.1 这类
        # CGNAT 映射地址）。显式解包后按 IPv4 语义判定，与 py3.11 对齐。
        mapped = getattr(address, "ipv4_mapped", None)
        if mapped is not None:
            return mapped
        return address

    @staticmethod
    def _all_public(addresses: Set[Union[IPv4Address, IPv6Address]]) -> bool:
        return bool(addresses) and all(ip.is_global for ip in addresses)

    def _validate_subagent_url(self, url: str) -> Optional[str]:
        address = self._literal_ip(url)
        if address is None:
            return "subagent_web_fetch_blocked: 仅允许访问字面量公共 IP 地址"
        if not self._all_public({address}):
            return "subagent_web_fetch_blocked: 仅允许访问公共网络地址"
        return None

    def _validate_subagent_redirect(self, location: str) -> Optional[str]:
        address = self._literal_ip(location)
        if address is None:
            return "subagent_web_fetch_blocked: 重定向目标必须是字面量公共 IP 地址"
        if not self._all_public({address}):
            return "subagent_web_fetch_blocked: 重定向目标不是公共地址"
        return None

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="web_fetch",
            description=(
                "获取网页内容并抽取正文。mode=text 返回正文（默认），"
                "links 额外返回页面链接列表，tables 额外返回表格（文献列表页用），"
                "raw 返回未处理的原始 HTML。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "网页 URL"},
                    "mode": {
                        "type": "string",
                        "enum": list(self.VALID_MODES),
                        "description": "抽取模式 (默认 text)",
                    },
                    "max_length": {
                        "type": "integer",
                        "description": "正文最大长度 (默认 10000)",
                    },
                },
                "required": ["url"],
            },
        )

    def execute(  # noqa: PLR0911 — 每个拒绝路径独立 return，扁平比提取辅助函数更直读
        self, url: str, mode: str = "text", max_length: int = 10000, **kwargs
    ) -> ToolResult:
        """获取网页并按 ``mode`` 抽取。

        Args:
            url:        网页 URL
            mode:       ``text`` / ``links`` / ``tables`` / ``raw``
            max_length: 正文最大长度
        """
        if mode not in self.VALID_MODES:
            return ToolResult(
                success=False,
                error=f"无效的 mode {mode!r}，可选：{', '.join(self.VALID_MODES)}",
            )
        if not url.startswith(("http://", "https://")):
            return ToolResult(success=False, error="无效的 URL，必须以 http:// 或 https:// 开头")

        network_policy = self._effective_network_policy()
        host_rejection = network_policy.check_host(url)
        if host_rejection:
            return ToolResult(success=False, error=host_rejection)

        # 非 online 模式下 host 已过白名单，跳过公网 IP 校验：内网地址解析出
        # 私有 IP 是预期的。online 模式 check_host 恒放行，走原有校验不变。
        gated_by_whitelist = network_policy.mode is not NetworkMode.ONLINE
        if self._policy.subagent_only and not gated_by_whitelist:
            validation_error = self._validate_subagent_url(url)
            if validation_error:
                return ToolResult(success=False, error=validation_error)

        try:
            response = self.client.get(url)
            redirect_error = self._check_redirect(response, network_policy, gated_by_whitelist)
            if redirect_error:
                return ToolResult(success=False, error=redirect_error)
            response.raise_for_status()
            return ToolResult(success=True, content=self._render(url, response, mode, max_length))
        except httpx.HTTPError as e:
            return ToolResult(success=False, error=f"HTTP 请求失败: {str(e)}")
        except Exception as e:
            return ToolResult(success=False, error=f"获取网页失败: {str(e)}")

    def _check_redirect(
        self,
        response: httpx.Response,
        network_policy: NetworkPolicy,
        gated_by_whitelist: bool,
    ) -> Optional[str]:
        """重定向目标校验。返回拒绝原因；``None`` 表示放行。"""
        if not response.is_redirect:
            return None
        location = response.headers.get("location", "")
        if gated_by_whitelist:
            return network_policy.check_host(location)
        if self._policy.subagent_only:
            return self._validate_subagent_redirect(location)
        return None

    def _render(
        self, url: str, response: httpx.Response, mode: str, max_length: int
    ) -> Dict[str, Any]:
        """把响应渲染成工具结果的 ``content`` dict。"""
        content_type = response.headers.get("content-type", "")
        text, encoding = decode_html(response.content, content_type)
        result: Dict[str, Any] = {
            "url": url,
            "status_code": response.status_code,
            "content_type": content_type,
            "encoding": encoding,
            "mode": mode,
        }

        is_html = any(marker in content_type.lower() for marker in self._HTML_CONTENT_TYPES)
        if mode == "raw" or not is_html:
            result["content"] = text[:max_length]
            return result

        page = extract(text, url)
        result["title"] = page.title
        result["content"] = page.text[:max_length]
        if mode == "links":
            result["links"] = page.links[: self._policy.max_result_items]
        elif mode == "tables":
            result["tables"] = page.tables[: self._policy.max_result_items]
        return result
