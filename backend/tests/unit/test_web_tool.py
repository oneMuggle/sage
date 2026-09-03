"""web_tool 单元测试：WebSearchTool / WebFetchTool

使用 respx 拦截 httpx 请求，避免真实网络调用。
"""

import httpx
import pytest
import respx
from httpx import Response

from backend.domain.network_policy import NetworkMode, NetworkPolicy
from backend.domain.tool_policy import ToolPolicy
from backend.tools.web_tool import WebFetchTool, WebSearchTool

pytestmark = [pytest.mark.unit]


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


def test_web_fetch_subagent_blocks_private_destinations():
    tool = WebFetchTool(policy=ToolPolicy(subagent_only=True))

    result = tool.execute(url="http://127.0.0.1:8765/health")

    assert result.success is False
    assert "subagent_web_fetch_blocked" in result.error


@pytest.mark.parametrize(
    "address",
    [
        "100.64.0.1",
        "192.0.2.1",
        "198.51.100.1",
        "203.0.113.1",
        "::ffff:100.64.0.1",
        "::ffff:192.0.2.1",
    ],
)
def test_web_fetch_subagent_blocks_non_global_literal_addresses(address):
    tool = WebFetchTool(policy=ToolPolicy(subagent_only=True))

    result = tool.execute(url=f"http://[{address}]/metadata" if ":" in address else f"http://{address}/metadata")

    assert result.success is False
    assert "subagent_web_fetch_blocked" in result.error


def test_web_fetch_subagent_rejects_hostname_to_avoid_dns_to_connect_toctou():
    tool = WebFetchTool(policy=ToolPolicy(subagent_only=True))

    result = tool.execute(url="https://public.example/page")

    assert result.success is False
    assert "字面量公共 IP" in result.error


def test_web_fetch_subagent_allows_public_literal_ip():
    with respx.mock(base_url="https://93.184.216.34", assert_all_called=False) as mock:
        mock.get("/page").mock(return_value=Response(200, text="public"))
        tool = WebFetchTool(policy=ToolPolicy(subagent_only=True))
        result = tool.execute(url="https://93.184.216.34/page")

    assert result.success is True
    assert result.content["content"] == "public"
    assert tool.client._trust_env is False


def test_web_fetch_subagent_blocks_unsafe_redirect():
    with respx.mock(base_url="https://93.184.216.34", assert_all_called=False) as mock:
        mock.get("/redirect").mock(
            return_value=Response(302, headers={"location": "http://127.0.0.1/admin"})
        )
        tool = WebFetchTool(policy=ToolPolicy(subagent_only=True))
        result = tool.execute(url="https://93.184.216.34/redirect")

    assert result.success is False
    assert "subagent_web_fetch_blocked" in result.error


def test_web_fetch_network_exception():
    """底层抛异常 → 包装成失败。"""
    with respx.mock(base_url="https://example.com", assert_all_called=False) as mock:
        mock.get("/oops").mock(side_effect=httpx.ConnectError("conn refused"))
        tool = WebFetchTool()
        result = tool.execute(url="https://example.com/oops")

    assert result.success is False
    assert "失败" in result.error


# ---------- 网络模式门禁（Task 4） ----------


def _intranet(*hosts):
    return NetworkPolicy(mode=NetworkMode.INTRANET, allowed_hosts=hosts)


def test_web_fetch_intranet_allows_whitelisted_host():
    with respx.mock(base_url="https://mirror.example.internal", assert_all_called=False) as mock:
        mock.get("/p").mock(
            return_value=Response(
                200,
                text="<html><title>镜像站</title><body><p>正文内容</p></body></html>",
                headers={"content-type": "text/html; charset=utf-8"},
            )
        )
        tool = WebFetchTool(network_policy=_intranet("*.example.internal"))
        result = tool.execute(url="https://mirror.example.internal/p")

    assert result.success is True
    assert result.content["title"] == "镜像站"
    assert "正文内容" in result.content["content"]


def test_web_fetch_intranet_rejects_non_whitelisted_host():
    tool = WebFetchTool(network_policy=_intranet("*.example.internal"))
    result = tool.execute(url="https://evil.example.com/p")

    assert result.success is False
    assert "host_not_allowed" in result.error


def test_web_fetch_intranet_with_empty_whitelist_rejects_everything():
    tool = WebFetchTool(network_policy=NetworkPolicy(mode=NetworkMode.INTRANET))
    result = tool.execute(url="https://anything.internal/p")

    assert result.success is False
    assert "host_not_allowed" in result.error


def test_web_fetch_offline_rejects():
    tool = WebFetchTool(network_policy=NetworkPolicy(mode=NetworkMode.OFFLINE))
    result = tool.execute(url="https://anything.internal/p")

    assert result.success is False
    assert "network_mode_offline" in result.error


def test_web_fetch_online_ignores_allowed_hosts():
    """online 模式下 allowed_hosts 不参与判定 —— 填了白名单不该收紧访问范围。"""
    policy = NetworkPolicy(mode=NetworkMode.ONLINE, allowed_hosts=("only.internal",))
    with respx.mock(base_url="https://example.com", assert_all_called=False) as mock:
        mock.get("/p").mock(return_value=Response(200, text="<html><body>ok</body></html>"))
        tool = WebFetchTool(network_policy=policy)
        result = tool.execute(url="https://example.com/p")

    assert result.success is True


def test_web_fetch_intranet_whitelisted_private_ip_bypasses_public_ip_check():
    """内网 host 解析出私有 IP 是预期的，白名单命中就不该被公网规则拦。"""
    with respx.mock(base_url="http://10.10.0.5", assert_all_called=False) as mock:
        mock.get("/p").mock(return_value=Response(200, text="<html><body>内网页</body></html>"))
        tool = WebFetchTool(
            policy=ToolPolicy(subagent_only=True),
            network_policy=_intranet("10.10.0.5"),
        )
        result = tool.execute(url="http://10.10.0.5/p")

    assert result.success is True
    assert "内网页" in result.content["content"]


def test_web_fetch_intranet_redirect_target_must_also_pass_whitelist():
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://mirror.example.internal/r").mock(
            return_value=Response(302, headers={"location": "https://evil.example.com/x"})
        )
        tool = WebFetchTool(network_policy=_intranet("*.example.internal"))
        result = tool.execute(url="https://mirror.example.internal/r")

    assert result.success is False
    assert "host_not_allowed" in result.error


def test_web_fetch_loads_policy_from_settings_when_not_injected(monkeypatch):
    """未注入 network_policy 时每次 execute 现读 —— 改白名单立即生效。"""
    calls = []

    def _fake_load():
        calls.append(1)
        return NetworkPolicy(mode=NetworkMode.OFFLINE)

    monkeypatch.setattr("backend.tools.web_tool.load_network_policy", _fake_load)
    tool = WebFetchTool()

    first = tool.execute(url="https://a.internal/p")
    second = tool.execute(url="https://b.internal/p")

    assert first.success is False
    assert second.success is False
    assert len(calls) == 2


# ---------- 抽取模式与编码（Task 4） ----------

_MIRROR_PAGE = (
    "<html><head><title>知网检索</title></head><body>"
    "<table><tr><th>标题</th></tr><tr><td>论文甲</td></tr></table>"
    '<a href="/detail?id=9">详情</a>'
    "<p>摘要正文</p></body></html>"
)


def test_web_fetch_decodes_gbk_page():
    with respx.mock(base_url="https://mirror.example.internal", assert_all_called=False) as mock:
        mock.get("/gbk").mock(
            return_value=Response(
                200,
                content=_MIRROR_PAGE.encode("gbk"),
                headers={"content-type": "text/html; charset=GBK"},
            )
        )
        tool = WebFetchTool(network_policy=_intranet("*.example.internal"))
        result = tool.execute(url="https://mirror.example.internal/gbk")

    assert result.success is True
    assert result.content["encoding"] == "gbk"
    assert "摘要正文" in result.content["content"]


@pytest.mark.parametrize(
    ("mode", "present", "absent"),
    [
        ("text", (), ("links", "tables")),
        ("links", ("links",), ("tables",)),
        ("tables", ("tables",), ("links",)),
    ],
)
def test_web_fetch_mode_controls_returned_sections(mode, present, absent):
    with respx.mock(base_url="https://mirror.example.internal", assert_all_called=False) as mock:
        mock.get("/p").mock(
            return_value=Response(
                200,
                text=_MIRROR_PAGE,
                headers={"content-type": "text/html; charset=utf-8"},
            )
        )
        tool = WebFetchTool(network_policy=_intranet("*.example.internal"))
        result = tool.execute(url="https://mirror.example.internal/p", mode=mode)

    assert result.success is True
    for key in present:
        assert key in result.content
    for key in absent:
        assert key not in result.content


def test_web_fetch_links_are_absolutized():
    with respx.mock(base_url="https://mirror.example.internal", assert_all_called=False) as mock:
        mock.get("/list").mock(
            return_value=Response(
                200, text=_MIRROR_PAGE, headers={"content-type": "text/html"}
            )
        )
        tool = WebFetchTool(network_policy=_intranet("*.example.internal"))
        result = tool.execute(url="https://mirror.example.internal/list", mode="links")

    urls = [link["url"] for link in result.content["links"]]
    assert "https://mirror.example.internal/detail?id=9" in urls


def test_web_fetch_tables_become_nested_lists():
    with respx.mock(base_url="https://mirror.example.internal", assert_all_called=False) as mock:
        mock.get("/t").mock(
            return_value=Response(
                200, text=_MIRROR_PAGE, headers={"content-type": "text/html"}
            )
        )
        tool = WebFetchTool(network_policy=_intranet("*.example.internal"))
        result = tool.execute(url="https://mirror.example.internal/t", mode="tables")

    assert result.content["tables"] == [[["标题"], ["论文甲"]]]


def test_web_fetch_raw_mode_returns_unextracted_html():
    with respx.mock(base_url="https://mirror.example.internal", assert_all_called=False) as mock:
        mock.get("/raw").mock(
            return_value=Response(
                200,
                text="<html><script>x=1</script>H</html>",
                headers={"content-type": "text/html"},
            )
        )
        tool = WebFetchTool(network_policy=_intranet("*.example.internal"))
        result = tool.execute(url="https://mirror.example.internal/raw", mode="raw")

    assert result.success is True
    assert "<script>" in result.content["content"]


def test_web_fetch_rejects_unknown_mode():
    tool = WebFetchTool(network_policy=_intranet("*.example.internal"))
    result = tool.execute(url="https://mirror.example.internal/p", mode="telepathy")

    assert result.success is False
    assert "mode" in result.error


def test_web_fetch_non_html_content_type_skips_extraction():
    """JSON / 纯文本响应不该被当 HTML 抽取 —— 直接给原文。"""
    with respx.mock(base_url="https://mirror.example.internal", assert_all_called=False) as mock:
        mock.get("/api").mock(
            return_value=Response(
                200,
                content=b'{"total": 2}',
                headers={"content-type": "application/json"},
            )
        )
        tool = WebFetchTool(network_policy=_intranet("*.example.internal"))
        result = tool.execute(url="https://mirror.example.internal/api")

    assert result.success is True
    assert result.content["content"] == '{"total": 2}'
    assert "title" not in result.content


def test_web_fetch_max_length_truncates_extracted_text():
    long_body = (
        '<html><head><meta charset="utf-8"></head><body><p>'
        + ("甲" * 5000)
        + "</p></body></html>"
    )
    with respx.mock(base_url="https://mirror.example.internal", assert_all_called=False) as mock:
        mock.get("/long").mock(
            return_value=Response(200, text=long_body, headers={"content-type": "text/html"})
        )
        tool = WebFetchTool(network_policy=_intranet("*.example.internal"))
        result = tool.execute(url="https://mirror.example.internal/long", max_length=100)

    assert len(result.content["content"]) == 100
