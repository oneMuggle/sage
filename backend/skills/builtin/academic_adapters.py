"""学术检索站点适配器。

把"通用关键词检索"映射到具体文献站点的 URL 模板。

设计原则(YAGNI):
- 适配器只负责 URL 构造,**不**做 HTML 解析 —— 结果解析由 LLM 在 skill
  描述/SKILL.md 里针对具体站点编写。
- 站点注册通过简单 dict 维护,不引入 plugin 系统(后续真有 N 个站点再升级)。
- 当前内置 ``cnki`` 一个适配器,作为 ``AcademicSearchSkill`` 的默认 backend。

扩展点:
- 新增站点只需:实现满足 ``AcademicSiteAdapter`` 协议的类 →
  在 ``_DEFAULT_ADAPTERS`` 注册 → ``AcademicSearchSkill(site="new_site")`` 即可。
"""

from __future__ import annotations

from typing import Any, Dict, Protocol, runtime_checkable


@runtime_checkable
class AcademicSiteAdapter(Protocol):
    """学术文献站点的检索接口契约。

    实现需提供:
    - ``name``:站点标识(小写字母,kebab-case)
    - ``build_search_url(query, **kwargs) -> str``:构造该站点的检索结果页 URL
    """

    name: str

    def build_search_url(self, query: str, **kwargs: Any) -> str: ...


class CNKIAdapter:
    """中国知网(CNKI)检索适配器 —— 仅负责 URL 模板,不做 HTML 解析。

    URL 模板基于 ``https://www.cnki.net/old/`` 的传统检索入口,
    通过 query string 传递关键词 / 每页条数。实际页面解析留给 LLM。
    """

    name = "cnki"
    BASE_URL = "https://www.cnki.net/old/kns/brief/default_result.aspx"

    def build_search_url(self, query: str, **kwargs: Any) -> str:
        """构造 CNKI 检索结果页 URL。

        Args:
            query: 检索关键词。
            **kwargs: 支持 ``limit``(每页条数,默认 10),忽略其他键。

        Returns:
            完整的检索结果页 URL(query string 编码后)。
        """
        from urllib.parse import urlencode

        limit = int(kwargs.get("limit", 10))
        params = {
            "QueryID": "0",
            "Txt": query,
            "PageName": "ASP.brief_result_aspx",
            "DbPrefix": "SCDB",
            "DbCatalog": "中国学术期刊网络出版总库",
            "ConfigFile": "SCDB.xml",
            "research": "off",
            "t": str(limit),
        }
        return f"{self.BASE_URL}?{urlencode(params)}"


_DEFAULT_ADAPTERS: Dict[str, AcademicSiteAdapter] = {
    "cnki": CNKIAdapter(),
}


def get_site_adapter(name: str) -> AcademicSiteAdapter:
    """根据站点名获取已注册的 adapter。

    Args:
        name: 站点标识,如 ``"cnki"``。

    Raises:
        ValueError: 未注册的站点名。

    Returns:
        满足 ``AcademicSiteAdapter`` 协议的对象。
    """
    if name not in _DEFAULT_ADAPTERS:
        available = sorted(_DEFAULT_ADAPTERS)
        raise ValueError(f"Unknown academic site: {name!r}. Available: {available}")
    return _DEFAULT_ADAPTERS[name]


def register_site_adapter(adapter: AcademicSiteAdapter) -> None:
    """注册新的站点适配器(测试用 + 未来扩展点)。

    Args:
        adapter: 满足 ``AcademicSiteAdapter`` 协议的对象。
            ``adapter.name`` 作为注册 key。
    """
    _DEFAULT_ADAPTERS[adapter.name] = adapter


__all__ = [
    "AcademicSiteAdapter",
    "CNKIAdapter",
    "get_site_adapter",
    "register_site_adapter",
]
