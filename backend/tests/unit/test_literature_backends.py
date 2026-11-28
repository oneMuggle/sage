"""文献库枚举与探测（spec §6.2 / §6.3 / §6.4）。"""

import pytest

from backend.literature.backends import (
    classify_probe,
    parse_backend_entries,
    probe_backend,
)

pytestmark = pytest.mark.unit

_SNAPSHOT = """
<a href="/dbItem/3">中国知网</a>
<a href="/dbItem/1">万方</a>
<a href="/dbItem/12">维普</a>
<a href="/other/page">别的</a>
"""


def test_parse_backend_entries_from_snapshot() -> None:
    entries = parse_backend_entries(_SNAPSHOT, "https://demo.example/dbList/")
    ids = [entry.id for entry in entries]
    assert "db3" in ids
    assert "db1" in ids
    assert "db12" in ids
    assert len(entries) == 3
    entry = [item for item in entries if item.id == "db3"][0]
    assert entry.entry_url == "https://demo.example/dbItem/3"
    assert entry.status == "unknown"
    assert entry.label


def test_parse_backend_entries_empty_snapshot() -> None:
    assert parse_backend_entries("", "https://demo.example/dbList/") == []


def test_classify_probe_detects_blocked() -> None:
    status, reason = classify_probe("请拖动滑块完成安全验证")
    assert status == "blocked"
    assert "滑块" in reason


def test_classify_probe_detects_unavailable() -> None:
    status, reason = classify_probe("代理访问失败，请稍后重试")
    assert status == "unavailable"
    assert reason


def test_classify_probe_detects_ready() -> None:
    status, reason = classify_probe("请输入检索关键词")
    assert status == "ready"
    assert reason == ""


def test_classify_probe_defaults_to_unknown() -> None:
    status, _ = classify_probe("一些无法判断的页面内容")
    assert status == "unknown"


def test_probe_backend_uses_classification() -> None:
    status, reason = probe_backend(
        "https://demo.example/dbItem/1",
        lambda url: "检索结果",  # noqa: ARG005
        lambda url: "代理访问失败",  # noqa: ARG005
    )
    assert status == "unavailable"
    assert reason


def test_probe_backend_blocked_is_never_auto_retried() -> None:
    """blocked 状态必须带原因，便于提示用户人工介入。"""
    status, reason = probe_backend(
        "https://demo.example/dbItem/2",
        lambda url: "安全验证",  # noqa: ARG005
        lambda url: "请完成验证码",  # noqa: ARG005
    )
    assert status == "blocked"
    assert reason
