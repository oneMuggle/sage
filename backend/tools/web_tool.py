"""
Web 工具 - 网络搜索和网页获取
"""

# win7 py3.8: PEP 604 (X | Y) / PEP 585 (set[...]) 注解惰性化，避免 def 定义时报错
from __future__ import annotations

import ipaddress
import re
from html import unescape
from ipaddress import IPv4Address, IPv6Address
from typing import Any, Dict, Optional, Set, Union
from urllib.parse import parse_qs, urljoin, urlparse

import httpx

from backend.domain.network_policy import NetworkMode, NetworkPolicy
from backend.domain.risk import RiskClass
from backend.domain.tool_policy import ToolPolicy
from backend.tools.network_config import load_network_policy
from backend.wiki.html_extract import decode_html, extract

from . import web_render
from .base import BaseTool, ToolResult, ToolSchema
from .web_render import RenderError


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

            content: Dict[str, Any] = {"query": query, "results": results}
            if not results:
                # W3：解析为空是合法状态 —— 明示无结果，绝不返回伪造占位
                # 条目（那会被模型当真实结果引用，成为幻觉源）。
                content["note"] = "搜索源未返回可解析结果（可能被限流），请勿编造结果"
            return ToolResult(success=True, content=content)

        except httpx.HTTPError as e:
            return ToolResult(success=False, error=f"HTTP 请求失败: {str(e)}")
        except Exception as e:
            return ToolResult(success=False, error=f"搜索失败: {str(e)}")

    #: DDG html 版结果标题锚点；attrs 里取 href（属性顺序不固定）
    _RESULT_ANCHOR_RE = re.compile(
        r"<a\s([^>]*class=\"[^\"]*result__a[^\"]*\"[^>]*)>(.*?)</a>",
        re.IGNORECASE | re.DOTALL,
    )
    #: 结果摘要锚点（与标题锚点同序出现，按下标配对）
    _SNIPPET_ANCHOR_RE = re.compile(
        r"<a\s[^>]*class=\"[^\"]*result__snippet[^\"]*\"[^>]*>(.*?)</a>",
        re.IGNORECASE | re.DOTALL,
    )
    _HREF_ATTR_RE = re.compile(r"href=\"([^\"]*)\"", re.IGNORECASE)

    def _parse_results(self, html: str, limit: int, query: str) -> list:
        """
        解析 DuckDuckGo HTML 搜索结果（标题 / 真实 URL / 摘要）

        Args:
            html: DDG html 版响应
            limit: 限制数量
            query: 搜索查询（保留参数兼容旧签名；解析为空返回空列表）

        Returns:
            结果列表（可能为空 —— 调用方负责无结果语义）
        """
        results = []
        for attrs, inner in self._RESULT_ANCHOR_RE.findall(html):
            if len(results) >= limit:
                break
            href_match = self._HREF_ATTR_RE.search(attrs)
            results.append(
                {
                    "title": self._clean_html(inner),
                    "url": self._resolve_result_url(href_match.group(1) if href_match else ""),
                    "snippet": "",
                }
            )
        for index, inner in enumerate(self._SNIPPET_ANCHOR_RE.findall(html)):
            if index >= len(results):
                break
            results[index]["snippet"] = self._clean_html(inner)
        return results

    def _resolve_result_url(self, raw_href: str) -> str:
        """还原结果真实 URL。

        DDG html 版把外链包在 ``//duckduckgo.com/l/?uddg=<urlencoded>``
        跳转里（W3：此前解析器拿不到 URL 就是这个原因）；其余形态
        （测试 fixture 的相对 href 等）原样返回。
        """
        href = unescape(raw_href or "").strip()
        if not href or "uddg=" not in href:
            return href
        target = href if "//" in href else "https:" + href
        try:
            values = parse_qs(urlparse(target).query).get("uddg", [])
        except ValueError:
            return ""
        return values[0] if values else ""

    def _clean_html(self, text: str) -> str:
        """清理 HTML 标签并解码实体"""
        clean = re.sub(r"<[^>]+>", "", text)
        return unescape(clean).strip()


class WebFetchTool(BaseTool):
    """获取网页内容工具"""

    # A1: 出网调用 — 最严门禁（只读模式禁止，交互模式询问）
    risk = RiskClass.EXTERNAL

    #: mode 合法取值。text 只给正文，links/tables 额外带对应段，raw 给原始 HTML
    VALID_MODES = ("text", "links", "tables", "raw")

    #: render 合法取值：auto=检出 JS 壳自动渲染（默认）；always=强制；never=仅静态
    VALID_RENDER_MODES = ("auto", "never", "always")

    #: 只对这些 content-type 做 HTML 抽取；JSON / 纯文本直接给原文
    _HTML_CONTENT_TYPES = ("text/html", "application/xhtml")

    #: 手动跟随重定向的最大跳数
    _MAX_REDIRECTS = 5

    #: 网页响应体硬上限，避免 max_length 事后截断导致无限缓冲
    _MAX_RESPONSE_BYTES = 4 * 1024 * 1024

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
                "SPA/JS 动态页自动经受控 headless 浏览器渲染后取正文"
                "（render=auto 默认；always 强制渲染；never 仅静态 HTML）。"
                "渲染分支内部会启动受控 headless 浏览器，不单独走启动审批。"
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
                    "render": {
                        "type": "string",
                        "enum": list(self.VALID_RENDER_MODES),
                        "description": "JS 渲染策略 (默认 auto：检出 SPA 壳自动渲染)",
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
        self,
        url: str,
        mode: str = "text",
        max_length: int = 10000,
        render: str = "auto",
        **kwargs,
    ) -> ToolResult:
        """获取网页并按 ``mode`` 抽取。

        Args:
            url:        网页 URL
            mode:       ``text`` / ``links`` / ``tables`` / ``raw``
            max_length: 正文最大长度
            render:     ``auto``（默认，检出 JS 壳自动渲染）/ ``always`` / ``never``
        """
        if mode not in self.VALID_MODES:
            return ToolResult(
                success=False,
                error=f"无效的 mode {mode!r}，可选：{', '.join(self.VALID_MODES)}",
            )
        if render not in self.VALID_RENDER_MODES:
            return ToolResult(
                success=False,
                error=f"无效的 render {render!r}，可选：{', '.join(self.VALID_RENDER_MODES)}",
            )
        if not url.startswith(("http://", "https://")):
            return ToolResult(success=False, error="无效的 URL，必须以 http:// 或 https:// 开头")

        network_policy = self._effective_network_policy()
        url_error = self._validate_target_url(url)
        if url_error:
            return ToolResult(success=False, error=url_error)
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
            response, final_url = self._get_with_redirects(url, network_policy, gated_by_whitelist)
            response.raise_for_status()
            content = self._render(final_url, response, mode, max_length)
            if self._should_render(render, response, content, max_length):
                content = self._render_dynamic(
                    final_url, network_policy, mode, max_length, content
                )
            return ToolResult(success=True, content=content)
        except httpx.HTTPError as e:
            return ToolResult(success=False, error=f"HTTP 请求失败: {str(e)}")
        except RenderError as e:
            # 渲染失败单独语义：明确指引手动路径，不吞成"获取网页失败"
            return ToolResult(success=False, error=str(e))
        except Exception as e:
            return ToolResult(success=False, error=f"获取网页失败: {str(e)}")

    @staticmethod
    def _validate_target_url(url: str) -> Optional[str]:
        try:
            parsed = urlparse(url)
        except ValueError:
            return "无效的 URL，必须包含 http:// 或 https:// 以及主机名"
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return "无效的 URL，必须包含 http:// 或 https:// 以及主机名"
        return None

    def _get_with_redirects(
        self,
        url: str,
        network_policy: NetworkPolicy,
        gated_by_whitelist: bool,
    ) -> tuple:
        current_url = url
        for redirect_count in range(self._MAX_REDIRECTS + 1):
            url_error = self._validate_target_url(current_url)
            if url_error:
                raise ValueError(url_error)
            host_rejection = network_policy.check_host(current_url)
            if host_rejection:
                raise ValueError(host_rejection)
            if self._policy.subagent_only and not gated_by_whitelist:
                validation_error = self._validate_subagent_url(current_url)
                if validation_error:
                    raise ValueError(validation_error)

            with httpx.Client(
                timeout=30.0,
                follow_redirects=False,
                verify=not network_policy.allows_insecure_tls(current_url),
                trust_env=not self._policy.subagent_only,
            ) as client:
                request = client.build_request("GET", current_url)
                response = client.send(request, stream=True)
                try:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if redirect_count >= self._MAX_REDIRECTS:
                            raise ValueError(
                                f"redirect_limit_exceeded: 重定向次数超过 {self._MAX_REDIRECTS} 次"
                            )
                        if not location:
                            raise ValueError("invalid_redirect: 重定向缺少 Location")
                        current_url = urljoin(current_url, location)
                        continue

                    response.raise_for_status()
                    declared = response.headers.get("content-length", "")
                    if declared.isdigit() and int(declared) > self._MAX_RESPONSE_BYTES:
                        raise ValueError(
                            f"response_exceeds_limit: 响应超过 {self._MAX_RESPONSE_BYTES} 字节"
                        )
                    content = bytearray()
                    for chunk in response.iter_bytes(64 * 1024):
                        content.extend(chunk)
                        if len(content) > self._MAX_RESPONSE_BYTES:
                            raise ValueError(
                                f"response_exceeds_limit: 响应超过 {self._MAX_RESPONSE_BYTES} 字节"
                            )
                    buffered_response = httpx.Response(
                        response.status_code,
                        headers=response.headers,
                        content=bytes(content),
                        request=response.request,
                    )
                finally:
                    response.close()
                response = buffered_response
            return response, current_url

        raise ValueError("redirect_limit_exceeded: 重定向次数超限")

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

    def _should_render(
        self, render: str, response: httpx.Response, content: Dict[str, Any], max_length: int
    ) -> bool:
        """判定静态结果是否需要 JS 渲染降级（W1）。

        raw / 非 HTML 恒不渲染；``never`` 关闭；``always`` 强制；``auto``
        交给 ``looks_like_js_shell``。max_length 低于壳判定阈值时跳过 auto
        —— 正文先被截断会使"正文过短"判定失真（长文的截断版像壳）。
        """
        if render == "never":
            return False
        if content.get("mode") == "raw":
            return False
        content_type = response.headers.get("content-type", "")
        is_html = any(marker in content_type.lower() for marker in self._HTML_CONTENT_TYPES)
        if not is_html:
            return False
        if render == "always":
            return True
        if max_length < web_render.SHELL_TEXT_MIN_CHARS:
            return False
        html_text, _ = decode_html(response.content, content_type)
        return web_render.looks_like_js_shell(html_text, str(content.get("content", "")))

    def _render_dynamic(
        self,
        url: str,
        network_policy: NetworkPolicy,
        mode: str,
        max_length: int,
        static_content: Dict[str, Any],
    ) -> Dict[str, Any]:
        """JS 壳命中后的渲染降级：headless 取渲染后正文（W1）。

        渲染失败抛 ``RenderError``（execute 单独捕获，不吞成通用失败）。
        """
        rendered = web_render.render_page(url, network_policy)
        content = dict(static_content)  # 保留 status_code / content_type / encoding / mode
        # 渲染结果仅正文：丢弃静态抽取的 links/tables（对应 shell 的残缺值）
        content.pop("links", None)
        content.pop("tables", None)
        content.update(rendered)
        content["content"] = str(rendered.get("content", ""))[:max_length]
        if mode in ("links", "tables"):
            # 渲染结果目前仅正文；links/tables 需渲染后 outerHTML（方案 W6 backlog）
            content["note"] = "渲染页暂不支持 links/tables 抽取，仅返回正文"
        return content
