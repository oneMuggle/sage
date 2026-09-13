# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""web_search 多引擎实现（方案 2026-09-13 §2.2）。

设计要点：

- **引擎协议**：``name`` + ``search(query, limit, client) -> list[dict]``，
  结果条目与 web_search schema 同构（title / url / snippet）。引擎只做
  "请求 + 解析"，失败抛异常、空结果返回 ``[]``，fallback 决策在调用方
  （``WebSearchTool`` 沿链遍历）。
- **零新依赖**：全部 httpx + 正则/JSON，HTML 解析手法与原 DDG 实现一致
  （原实现自 web_tool.py 原样迁入 ``DuckDuckGoEngine``）。
- **Bing 首选**：大陆可达（DDG 被墙），结果 URL 常包在
  ``bing.com/ck/a?...&u=a1<base64url>`` 跳转里，解析时还原真实 URL。
- **API 引擎**（Tavily / 智谱）可选启用，key 由 ``SearchConfig`` 携带，
  未配 key 时 ``resolve_engine_chain`` 直接跳过。

py3.8 纪律：from __future__ import annotations + typing.*（win7 对齐）。
"""

from __future__ import annotations

import base64
import re
from html import unescape
from typing import Dict, List, Optional
from urllib.parse import parse_qs, urlparse

import httpx

from .search_config import SearchConfig


class SearchEngine:
    """搜索引擎基类。子类实现 ``search``；异常向上抛由调用方 fallback。"""

    name = "base"

    def search(self, query: str, limit: int, client: httpx.Client) -> List[Dict[str, str]]:
        raise NotImplementedError

    @staticmethod
    def _clean_html(text: str) -> str:
        """清理 HTML 标签并解码实体（与原 WebSearchTool._clean_html 同实现）。"""
        clean = re.sub(r"<[^>]+>", "", text)
        return unescape(clean).strip()


# ---------------------------------------------------------------------------
# DuckDuckGo（原 web_tool 实现，原样迁入）
# ---------------------------------------------------------------------------


class DuckDuckGoEngine(SearchEngine):
    """DuckDuckGo HTML 版（html.duckduckgo.com/html/）——大陆不可达，作后备。"""

    name = "ddg"

    #: 结果标题锚点；attrs 里取 href（属性顺序不固定）
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

    def search(self, query: str, limit: int, client: httpx.Client) -> List[Dict[str, str]]:
        response = client.get("https://html.duckduckgo.com/html/", params={"q": query})
        response.raise_for_status()
        return self._parse_results(response.text, limit)

    def _parse_results(self, html: str, limit: int) -> List[Dict[str, str]]:
        results: List[Dict[str, str]] = []
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
        """还原结果真实 URL：DDG 把外链包在 ``//duckduckgo.com/l/?uddg=`` 跳转里。"""
        href = unescape(raw_href or "").strip()
        if not href or "uddg=" not in href:
            return href
        target = href if "//" in href else "https:" + href
        try:
            values = parse_qs(urlparse(target).query).get("uddg", [])
        except ValueError:
            return ""
        return values[0] if values else ""


# ---------------------------------------------------------------------------
# Bing（默认首选，大陆可达）
# ---------------------------------------------------------------------------


class BingEngine(SearchEngine):
    """Bing 网页版（www.bing.com/search）—— 大陆可达，默认首选。"""

    name = "bing"

    _ENDPOINT = "https://www.bing.com/search"

    #: 结果容器（b_algo），块内再抽 h2 锚点与摘要
    _RESULT_LI_RE = re.compile(
        r"<li[^>]*class=\"[^\"]*b_algo[^\"]*\"[^>]*>(.*?)</li>",
        re.IGNORECASE | re.DOTALL,
    )
    _ANCHOR_RE = re.compile(
        r"<h2[^>]*>\s*<a[^>]+href=\"([^\"]+)\"[^>]*>(.*?)</a>",
        re.IGNORECASE | re.DOTALL,
    )
    _SNIPPET_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.IGNORECASE | re.DOTALL)

    def search(self, query: str, limit: int, client: httpx.Client) -> List[Dict[str, str]]:
        response = client.get(self._ENDPOINT, params={"q": query, "count": str(limit)})
        response.raise_for_status()
        results: List[Dict[str, str]] = []
        for block in self._RESULT_LI_RE.findall(response.text):
            if len(results) >= limit:
                break
            anchor = self._ANCHOR_RE.search(block)
            if not anchor:
                continue
            snippet_match = self._SNIPPET_RE.search(block)
            results.append(
                {
                    "title": self._clean_html(anchor.group(2)),
                    "url": self._resolve_result_url(anchor.group(1)),
                    "snippet": self._clean_html(snippet_match.group(1)) if snippet_match else "",
                }
            )
        return results

    def _resolve_result_url(self, raw_href: str) -> str:
        """还原 ``bing.com/ck/a?...&u=a1<base64url>`` 跳转里的真实 URL。

        base64url 无 padding，且真实 URL 前有 ``a1`` 版本前缀；解不出则原样
        返回（直接 href 形态的 Bing 站点不走跳转包装）。
        """
        href = unescape(raw_href or "").strip()
        if "bing.com/ck/" not in href or "u=" not in href:
            return href
        try:
            values = parse_qs(urlparse(href).query).get("u", [])
        except ValueError:
            return href
        encoded = values[0] if values else ""
        if not encoded.startswith("a1"):
            return href
        payload = encoded[2:]
        payload += "=" * (-len(payload) % 4)
        try:
            return base64.urlsafe_b64decode(payload).decode("utf-8", "replace")
        except (ValueError, TypeError):
            return href


# ---------------------------------------------------------------------------
# API 引擎（可选启用，key 走 SearchConfig）
# ---------------------------------------------------------------------------


class TavilyEngine(SearchEngine):
    """Tavily 搜索 API（api.tavily.com/search）。"""

    name = "tavily"

    _ENDPOINT = "https://api.tavily.com/search"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def search(self, query: str, limit: int, client: httpx.Client) -> List[Dict[str, str]]:
        response = client.post(
            self._ENDPOINT,
            json={"api_key": self._api_key, "query": query, "max_results": limit},
        )
        response.raise_for_status()
        payload = response.json()
        results: List[Dict[str, str]] = []
        for item in (payload or {}).get("results", [])[:limit]:
            if not isinstance(item, dict):
                continue
            results.append(
                {
                    "title": str(item.get("title") or ""),
                    "url": str(item.get("url") or ""),
                    "snippet": str(item.get("content") or ""),
                }
            )
        return results


class ZhipuEngine(SearchEngine):
    """智谱 web-search API（open.bigmodel.cn/api/paas/v4/web_search）。"""

    name = "zhipu"

    _ENDPOINT = "https://open.bigmodel.cn/api/paas/v4/web_search"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def search(self, query: str, limit: int, client: httpx.Client) -> List[Dict[str, str]]:
        response = client.post(
            self._ENDPOINT,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={"search_engine": "search_std", "search_query": query, "count": limit},
        )
        response.raise_for_status()
        payload = response.json()
        results: List[Dict[str, str]] = []
        for item in (payload or {}).get("search_result", [])[:limit]:
            if not isinstance(item, dict):
                continue
            results.append(
                {
                    "title": str(item.get("title") or ""),
                    "url": str(item.get("link") or item.get("url") or ""),
                    "snippet": str(item.get("content") or ""),
                }
            )
        return results


# ---------------------------------------------------------------------------
# 引擎链解析
# ---------------------------------------------------------------------------

_ENGINE_TYPES: Dict[str, type] = {
    "bing": BingEngine,
    "ddg": DuckDuckGoEngine,
}


def resolve_engine_chain(
    config: Optional[SearchConfig] = None,
) -> List[SearchEngine]:
    """按配置顺序构造引擎实例链。

    API 引擎未配 key 时跳过（不进链）；未知引擎名在 ``load_search_config``
    已过滤，这里兜底跳过。
    """
    from .search_config import DEFAULT_ENGINE_ORDER

    if config is None:
        config = SearchConfig()
    chain: List[SearchEngine] = []
    for name in config.engine_order or DEFAULT_ENGINE_ORDER:
        if name == "bing":
            chain.append(BingEngine())
        elif name == "ddg":
            chain.append(DuckDuckGoEngine())
        elif name == "tavily" and config.tavily_key:
            chain.append(TavilyEngine(config.tavily_key))
        elif name == "zhipu" and config.zhipu_key:
            chain.append(ZhipuEngine(config.zhipu_key))
    return chain


__all__ = [
    "BingEngine",
    "DuckDuckGoEngine",
    "SearchEngine",
    "TavilyEngine",
    "ZhipuEngine",
    "resolve_engine_chain",
]
