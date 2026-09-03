"""html_extract 单元测试：正文抽取 + 编码嗅探。

只有 stdlib 一条实现路径（见 Task 3 的"设计变更"说明）—— 不做 lxml 双实现，
因为两者在嵌套表格上产出不同，而 requirements.txt 并不声明 lxml，结果会取决于
环境里碰巧装了什么。
"""

import pytest

from backend.wiki.html_extract import (
    ExtractedPage,
    charset_from_content_type,
    decode_html,
    extract,
)

pytestmark = [pytest.mark.unit]

_PAGE = """<html><head><title>  知网 检索  </title>
<style>.a{color:red}</style><script>var x="不该出现";</script></head>
<body><h1>文献列表</h1><p>共 2 条结果&amp;更多</p>
<noscript>请开启 JS</noscript>
<table><tr><th>标题</th><th>作者</th></tr>
<tr><td>论文 A</td><td>张三</td></tr></table>
<a href="/detail?id=1">论文 A 详情</a>
<a href="javascript:void(0)">脚本链接</a>
<a href="#frag">锚点</a>
</body></html>"""

_BASE = "https://mirror.example.internal/search"


def test_title_is_whitespace_normalized():
    assert extract(_PAGE, _BASE).title == "知网 检索"


def test_script_style_noscript_content_is_dropped():
    text = extract(_PAGE, _BASE).text
    assert "不该出现" not in text
    assert "color:red" not in text
    assert "请开启" not in text


def test_text_keeps_visible_content_and_decodes_entities():
    text = extract(_PAGE, _BASE).text
    assert "文献列表" in text
    assert "共 2 条结果&更多" in text


def test_relative_links_are_absolutized():
    links = extract(_PAGE, _BASE).links
    assert {"text": "论文 A 详情", "url": "https://mirror.example.internal/detail?id=1"} in links


@pytest.mark.parametrize("noise", ["javascript:void(0)", "#frag"])
def test_non_navigational_links_are_skipped(noise):
    urls = [link["url"] for link in extract(_PAGE, _BASE).links]
    assert all(noise not in url for url in urls)


def test_tables_become_nested_lists():
    assert extract(_PAGE, _BASE).tables == [
        [["标题", "作者"], ["论文 A", "张三"]]
    ]


def test_empty_html_yields_empty_page():
    page = extract("", _BASE)
    assert page == ExtractedPage(title="", text="", links=[], tables=[])


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ('<table><tr><td>单元格<a href="/x">链</table>', [[["单元格链"]]]),
        ("<table><tr><td>孤儿", [[["孤儿"]]]),
        ("<table><td>无 tr</td></table>", []),
        ("<tr><td>无 table</td></tr>", []),
        ("<table></table>", []),
        (
            "<table><tr><td><table><tr><td>内</td></tr></table></td></tr></table>",
            [[["内"]]],
        ),
    ],
)
def test_malformed_table_markup_does_not_crash(html, expected):
    assert extract(html, _BASE).tables == expected


def test_nested_tables_are_kept_separate():
    """内层表格的文字不能并进外层单元格 —— 这是不用 lxml 的原因（见设计变更）。"""
    html = "<table><tr><td>外<table><tr><td>内</td></tr></table></td><td>右</td></tr></table>"
    assert extract(html, _BASE).tables == [[["内"]], [["外", "右"]]]


# ---------- 编码嗅探 ----------


def test_charset_from_content_type_reads_param():
    assert charset_from_content_type("text/html; charset=GBK") == "GBK"


@pytest.mark.parametrize("value", [None, "", "text/html"])
def test_charset_from_content_type_absent(value):
    assert charset_from_content_type(value) is None


@pytest.mark.parametrize(
    ("encoding", "content_type"),
    [
        ("gbk", "text/html; charset=GBK"),
        ("gb18030", "text/html"),
        ("utf-8", "text/html; charset=utf-8"),
        ("utf-8", None),
    ],
)
def test_decode_html_recovers_chinese(encoding, content_type):
    body = "知网检索结果".encode(encoding)
    text, _used = decode_html(body, content_type)
    assert "知网检索结果" in text


def test_decode_html_uses_meta_charset_when_header_silent():
    body = b'<meta charset="gbk">' + "知网".encode("gbk")
    text, used = decode_html(body, "text/html")
    assert "知网" in text
    assert used == "gbk"


def test_decode_html_uses_meta_http_equiv():
    body = (
        b'<meta http-equiv="Content-Type" content="text/html; charset=gb2312">'
        + "知网".encode("gbk")
    )
    text, used = decode_html(body, None)
    assert "知网" in text
    assert used == "gb2312"


def test_decode_html_survives_unknown_codec_in_header():
    body = "知网".encode("gb18030")
    text, used = decode_html(body, "text/html; charset=nonexistent-codec")
    assert "知网" in text
    assert used == "gb18030"


def test_decode_html_empty_body():
    text, used = decode_html(b"", "text/html")
    assert text == ""
    assert used == "utf-8"
