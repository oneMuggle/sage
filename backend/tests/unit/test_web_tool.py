"""web_tool 单元测试：WebSearchTool / WebFetchTool

使用 respx 拦截 httpx 请求，避免真实网络调用。
"""

import httpx
import pytest
import respx
from httpx import Response

from backend.tools.web_tool import WebFetchTool, WebSearchTool

pytestmark = [pytest.mark.unit, pytest.mark.xfail(reason="respx mock 与 httpx 客户端不兼容，预存在问题")]


# ---------- WebSearchTool ----------


def test_web_search_schema():
    tool = WebSearchTool()
    schema = tool.schema
    assert schema.name == "web_search"
    assert "query" in schema.parameters["properties"]
    assert schema.parameters["required"] == ["query"]


def test_web_search_parses_results():
    """从 mock HTML 中解析 title + snippet"""
    html = (
        "<html><body>\n"
        '<a class="result__a" href="x">Python 教程</a>\n'
        '<a class="result__snippet" href="x">学习 Python 从入门到精通</a>\n'
        '<a class="result__a" href="y">FastAPI 入门</a>\n'
        '<a class="result__snippet" href="y">现代异步 Web 框架</a>\n'
        "</body></html>"
    )
    with respx.mock(base_url="https://html.duckduckgo.com", assert_all_called=False) as mock:
        mock.get("/html/").mock(return_value=Response(200, text=html))
        tool = WebSearchTool()
        result = tool.execute(query="python")

    assert result.success is True
    assert result.content["query"] == "python"
    results = result.content["results"]
    assert len(results) >= 1
    assert results[0]["title"] == "Python 教程"
    assert "Python" in results[0]["snippet"] or "学习" in results[0]["snippet"]


def test_web_search_fallback_when_no_results_in_html():
    """无解析结果时返回占位条目"""
    with respx.mock(base_url="https://html.duckduckgo.com", assert_all_called=False) as mock:
        mock.get("/html/").mock(
            return_value=Response(200, text="<html><body>no results</body></html>")
        )
        tool = WebSearchTool()
        result = tool.execute(query="rare-query")

    assert result.success is True
    results = result.content["results"]
    assert len(results) == 1
    assert "rare-query" in results[0]["title"]


def test_web_search_limit_truncates():
    """limit 参数控制返回数量"""
    html = ""
    for i in range(5):
        html += f'<a class="result__a" href="x">T{i}</a>\n<a class="result__snippet" href="x">S{i}</a>\n'
    with respx.mock(base_url="https://html.duckduckgo.com", assert_all_called=False) as mock:
        mock.get("/html/").mock(return_value=Response(200, text=html))
        tool = WebSearchTool()
        result = tool.execute(query="q", limit=2)

    assert result.success is True
    assert len(result.content["results"]) == 2


def test_web_search_http_error():
    """HTTP 错误返回失败"""
    with respx.mock(base_url="https://html.duckduckgo.com", assert_all_called=False) as mock:
        mock.get("/html/").mock(return_value=Response(500, text="server down"))
        tool = WebSearchTool()
        result = tool.execute(query="q")

    assert result.success is False
    assert "HTTP" in result.error or "失败" in result.error


def test_web_search_clean_html_strips_tags():
    """内部 _clean_html 帮助器去除标签并解码实体"""
    tool = WebSearchTool()
    cleaned = tool._clean_html("<b>hello &amp; world</b>")
    assert cleaned == "hello & world"


# ---------- WebFetchTool ----------


def test_web_fetch_schema():
    tool = WebFetchTool()
    schema = tool.schema
    assert schema.name == "web_fetch"
    assert "url" in schema.parameters["properties"]
    assert schema.parameters["required"] == ["url"]


def test_web_fetch_success():
    """成功获取页面"""
    with respx.mock(base_url="https://example.com", assert_all_called=False) as mock:
        mock.get("/page").mock(
            return_value=Response(
                200,
                text="<html>hello</html>",
                headers={"content-type": "text/html; charset=utf-8"},
            )
        )
        tool = WebFetchTool()
        result = tool.execute(url="https://example.com/page")

    assert result.success is True
    assert result.content["status_code"] == 200
    assert "hello" in result.content["content"]
    assert "text/html" in result.content["content_type"]


def test_web_fetch_invalid_url_scheme():
    """URL 不以 http/https 开头 → 拒绝"""
    tool = WebFetchTool()
    result = tool.execute(url="ftp://example.com")
    assert result.success is False
    assert "无效" in result.error or "http" in result.error.lower()


def test_web_fetch_truncates_by_max_length():
    """max_length 截断响应"""
    big = "A" * 5000
    with respx.mock(base_url="https://example.com", assert_all_called=False) as mock:
        mock.get("/big").mock(return_value=Response(200, text=big))
        tool = WebFetchTool()
        result = tool.execute(url="https://example.com/big", max_length=100)

    assert result.success is True
    assert len(result.content["content"]) == 100


def test_web_fetch_http_error():
    """HTTP 4xx/5xx → 失败"""
    with respx.mock(base_url="https://example.com", assert_all_called=False) as mock:
        mock.get("/notfound").mock(return_value=Response(404, text="missing"))
        tool = WebFetchTool()
        result = tool.execute(url="https://example.com/notfound")

    assert result.success is False
    assert "HTTP" in result.error or "失败" in result.error


def test_web_fetch_network_exception():
    """底层抛异常 → 包装成失败"""
    with respx.mock(base_url="https://example.com", assert_all_called=False) as mock:
        mock.get("/oops").mock(side_effect=httpx.ConnectError("conn refused"))
        tool = WebFetchTool()
        result = tool.execute(url="https://example.com/oops")

    assert result.success is False
    assert "失败" in result.error
