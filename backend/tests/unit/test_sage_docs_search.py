"""sage_docs.search 单元测试：中文召回、无命中、fail-open。"""

from pathlib import Path

import pytest

from backend.services.sage_docs import search

pytestmark = pytest.mark.unit


def _docs_root(tmp_path: Path) -> Path:
    root = tmp_path / "docs"
    files = {
        "user-manual/07-chat.md": (
            "# 对话\n\nSage 默认的重试次数是三次。\n\n"
            "## 重试设置\n\n在设置页面可以调整重试次数与超时时间。\n"
        ),
        "user-manual/08-settings.md": (
            "# 设置\n\n权限模式分为只读、提示、工作区写入、完全访问四种。\n"
        ),
        "technical/README.md": "# 技术手册\n\n后端服务默认监听 8765 端口。\n",
    }
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def test_search_chinese_query_returns_hit_with_location(tmp_path):
    root = _docs_root(tmp_path)

    hits = search.search_sage_docs("重试次数", docs_root=root, index_dir=tmp_path / "index")

    assert hits
    assert hits[0].rel_path == "user-manual/07-chat.md"
    assert hits[0].heading
    assert hits[0].start_line >= 1
    assert "重试" in hits[0].content


def test_search_routes_by_content(tmp_path):
    root = _docs_root(tmp_path)

    hits = search.search_sage_docs("权限模式", docs_root=root, index_dir=tmp_path / "index")

    assert hits
    assert hits[0].rel_path == "user-manual/08-settings.md"


def test_search_respects_limit(tmp_path):
    root = _docs_root(tmp_path)

    hits = search.search_sage_docs("设置", limit=1, docs_root=root, index_dir=tmp_path / "index")

    assert len(hits) <= 1


def test_search_zero_limit_returns_empty(tmp_path):
    root = _docs_root(tmp_path)

    assert search.search_sage_docs("重试次数", limit=0, docs_root=root) == []


def test_search_blank_query_returns_empty(tmp_path):
    root = _docs_root(tmp_path)

    assert search.search_sage_docs("   ", docs_root=root) == []


def test_search_without_documents_returns_empty(tmp_path):
    empty_root = tmp_path / "docs"
    empty_root.mkdir()

    hits = search.search_sage_docs(
        "重试次数", docs_root=empty_root, index_dir=tmp_path / "index"
    )

    assert hits == []


def test_search_no_match_returns_empty(tmp_path):
    root = _docs_root(tmp_path)

    hits = search.search_sage_docs(
        "量子纠缠实验", docs_root=root, index_dir=tmp_path / "index"
    )

    assert hits == []


def test_search_fails_open_when_index_unusable(tmp_path):
    root = _docs_root(tmp_path)
    index_dir = tmp_path / "index"
    (index_dir / "index.sqlite3").mkdir(parents=True)

    assert search.search_sage_docs("重试次数", docs_root=root, index_dir=index_dir) == []
