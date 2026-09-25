"""R118 — 中文分词器单元测试（FTS5 预处理底座）。

tokenize：中文分词空格连接、空串、中英混合、无空 token。
tokenize_for_search：FTS5 OR 查询格式、引号转义、空查询 '""'。
不变量断言优先，不锁定 jieba 具体切分结果（跨版本稳定）。
"""

from __future__ import annotations

import pytest

from backend.memory.chinese_tokenizer import tokenize, tokenize_for_search

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# tokenize
# ---------------------------------------------------------------------------


def test_tokenize_chinese_space_joined():
    result = tokenize("用户喜欢火锅")
    assert result == "用户 喜欢 火锅"


def test_tokenize_english_unchanged():
    assert tokenize("hello world") == "hello world"


def test_tokenize_empty_and_whitespace():
    assert tokenize("") == ""
    assert tokenize("   ") == ""
    assert tokenize("\t\n") == ""


def test_tokenize_mixed_script_tokens_nonempty():
    result = tokenize("我喜欢Python编程")
    tokens = result.split(" ")
    assert all(t for t in tokens)
    assert any("Python" in t for t in tokens)


def test_tokenize_no_whitespace_tokens():
    # 带多余空白与标点的输入：输出不允许出现空白 token
    result = tokenize("你好， 世界！")
    assert all(t.strip() == t and t for t in result.split(" "))


# ---------------------------------------------------------------------------
# tokenize_for_search
# ---------------------------------------------------------------------------


def test_search_query_or_format():
    result = tokenize_for_search("用户喜欢火锅")
    tokens = result.split(" OR ")
    assert len(tokens) == 3
    for quoted in tokens:
        assert quoted.startswith('"')
        assert quoted.endswith('"')
        assert quoted[1:-1]  # 引号内 token 非空


def test_search_query_empty_returns_empty_quoted():
    assert tokenize_for_search("") == '""'
    assert tokenize_for_search("   ") == '""'


def test_search_query_escapes_double_quotes():
    # 引号按 FTS5 规则翻倍转义，不破坏查询结构
    result = tokenize_for_search('他说"你好"')
    assert '""' in result  # 内嵌引号被翻倍
    assert " OR " in result


def test_search_query_no_whitespace_tokens():
    result = tokenize_for_search("你好，世界")
    for quoted in result.split(" OR "):
        inner = quoted[1:-1]
        assert inner == inner.strip()
        assert inner


def test_search_query_english_terms():
    result = tokenize_for_search("hello world")
    assert result == '"hello" OR "world"'


def test_search_query_none_like_empty_string_kept_as_token():
    # "0"/"False" 这类 falsy 字符串是合法查询词，不得按空处理
    result = tokenize_for_search("0")
    assert result == '"0"'
