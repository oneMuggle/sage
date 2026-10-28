"""M4 — Wiki 沉淀（Zotero → wiki/zotero/*.md）+ 图谱边生成。

覆盖：
- frontmatter 合法（serialize → parse 可回环）
- wikilink 文本 = 目标页 title（label 精确匹配，_resolve_wikilink 必命中）
- build_graph 真产出 Author ↔ Item DirectLink（零改 graph.py）
- 幂等重写（内容未变不写，mtime 不变）
- 单篇失败不影响整批
- slug / 命名稳定性
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

import pytest

from backend.wiki.graph import build_graph
from backend.wiki.models import GraphSignal
from backend.zotero import wiki_export

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _sample_item(
    key: str = "ABCD1234",
    title: str = "Attention Is All You Need",
) -> Dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "date": "2017-06",
        "item_type": "journalArticle",
        "doi": "10.48550/arXiv.1706.03762",
        "abstract": "The dominant sequence transduction models...",
        "authors": [
            {"lastName": "Vaswani", "firstName": "Ashish", "creatorType": "author"},
            {"lastName": "Shazeer", "firstName": "Noam", "creatorType": "author"},
        ],
        "tags": [
            {"name": "sage:wiki", "type": 0},
            {"name": "nlp", "type": 0},
        ],
        "collections": [{"key": "CK1", "name": "NLP Reading"}],
    }


def _sample_annotations() -> List[Dict[str, Any]]:
    return [
        {
            "key": "AN1",
            "type": "highlight",
            "text": "self-attention mechanism",
            "comment": "vs RNN",
            "color": "#ffd400",
            "pageLabel": "2",
            "dateModified": "2026-10-27 10:00:00",
        }
    ]


class _FakeClient:
    """ZoteroClient 替身：items_by_tag 返回 summary，get_item 返回全量。"""

    def __init__(
        self,
        tagged_summaries: List[Dict[str, Any]] | None = None,
        full_items: Dict[str, Dict[str, Any]] | None = None,
        annotations: Dict[str, List[Dict[str, Any]]] | None = None,
        fail_keys: set | None = None,
    ):
        self.summaries = tagged_summaries or []
        self.full = full_items or {}
        self.annotations = annotations or {}
        self.fail_keys = fail_keys or set()
        self.tag_calls: list = []

    def items_by_tag(self, tag):
        self.tag_calls.append(tag)
        return list(self.summaries)

    def get_item(self, key):
        if key in self.fail_keys:
            raise RuntimeError(f"simulated failure for {key}")
        return self.full.get(key, {"key": key, "title": key, "authors": []})

    def get_annotations(self, key):
        return self.annotations.get(key, [])


# ---------------------------------------------------------------------------
# 渲染 / frontmatter
# ---------------------------------------------------------------------------


def test_render_item_page_has_legal_frontmatter():
    """item 页 frontmatter 经 parse/serialize 可回环；type 写的是 source。"""
    text = wiki_export.render_item_page(_sample_item(), _sample_annotations())
    assert text.startswith("---\n")
    assert text.count("---") >= 2

    from backend.wiki.frontmatter import parse

    parsed = parse(text)
    assert parsed.frontmatter.title == "Attention Is All You Need"
    assert parsed.frontmatter.page_type == "source"
    assert "sage:wiki" in parsed.frontmatter.tags
    assert "nlp" in parsed.frontmatter.tags
    assert parsed.frontmatter.sources == ["zotero:ABCD1234"]
    # 关键：related 必须等于作者显示名（label 精确匹配）
    assert parsed.frontmatter.related == ["Vaswani, A.", "Shazeer, N."]


def test_render_item_page_body_has_annotations():
    text = wiki_export.render_item_page(_sample_item(), _sample_annotations())
    assert "# Attention Is All You Need" in text
    assert "**Authors**: Vaswani, A.; Shazeer, N." in text
    assert "Year: 2017 | Type: journalArticle" in text
    assert "**DOI**: [10.48550/arXiv.1706.03762]" in text
    assert "## Abstract" in text
    assert "## Annotations" in text
    assert "self-attention mechanism" in text
    assert "vs RNN" in text


def test_render_author_page_has_legal_frontmatter():
    author = {"lastName": "Vaswani", "firstName": "Ashish"}
    items = [_sample_item()]
    text = wiki_export.render_author_page(author, items)

    from backend.wiki.frontmatter import parse

    parsed = parse(text)
    assert parsed.frontmatter.title == "Vaswani, A."
    assert parsed.frontmatter.page_type == "entity"
    assert parsed.frontmatter.tags == ["author"]
    assert "Attention Is All You Need" in parsed.frontmatter.related
    assert parsed.frontmatter.sources == ["zotero:ABCD1234"]


def test_wikilink_text_matches_author_title():
    """关键约束：item 页 related 里的 wikilink 文本 = author 页 title。

    否则 _resolve_wikilink 走不到 label 精确匹配分支，DirectLink 不生成。
    """
    item = _sample_item()
    author = item["authors"][0]
    item_page = wiki_export.render_item_page(item)
    author_page = wiki_export.render_author_page(author, [item])

    from backend.wiki.frontmatter import parse

    item_parsed = parse(item_page)
    author_parsed = parse(author_page)

    assert author_parsed.frontmatter.title in item_parsed.frontmatter.related


# ---------------------------------------------------------------------------
# 导出（写盘 + build_graph 真产出边）
# ---------------------------------------------------------------------------


def test_export_wiki_writes_items_and_authors(tmp_path):
    item = _sample_item()
    client = _FakeClient(
        tagged_summaries=[{"key": item["key"]}],
        full_items={item["key"]: item},
        annotations={item["key"]: _sample_annotations()},
    )

    result = wiki_export.export_wiki(client, tmp_path)

    assert result.items_exported == 1
    assert result.authors_exported == 2
    assert result.errors == []

    items_dir = tmp_path / "wiki" / "zotero" / "items"
    authors_dir = tmp_path / "wiki" / "zotero" / "authors"
    assert (items_dir / "ABCD1234.md").exists()
    assert (authors_dir / "vaswani-a.md").exists()
    assert (authors_dir / "shazeer-n.md").exists()


def test_export_wiki_build_graph_emits_author_item_directlink(tmp_path):
    """build_graph 真产出 Author ↔ Item 双向 DirectLink（零改 graph.py 的前提成立）。"""
    item = _sample_item()
    client = _FakeClient(
        tagged_summaries=[{"key": item["key"]}],
        full_items={item["key"]: item},
        annotations={item["key"]: _sample_annotations()},
    )

    wiki_export.export_wiki(client, tmp_path)
    graph = build_graph(tmp_path)

    # 节点 id 约定：相对路径 slash 分隔
    item_id = "wiki/zotero/items/ABCD1234.md"
    vaswani_id = "wiki/zotero/authors/vaswani-a.md"
    shazeer_id = "wiki/zotero/authors/shazeer-n.md"

    node_ids = {n.id for n in graph.nodes}
    assert item_id in node_ids
    assert vaswani_id in node_ids
    assert shazeer_id in node_ids

    direct_edges = {
        (e.source, e.target) for e in graph.edges if e.signal == GraphSignal.DirectLink
    }
    # item → 作者（item 页 related 写的是 [[Vaswani, A.]]）
    assert (item_id, vaswani_id) in direct_edges
    assert (item_id, shazeer_id) in direct_edges
    # 作者 → item（author 页 related 写的是 [[Attention Is All You Need]]）
    assert (vaswani_id, item_id) in direct_edges
    assert (shazeer_id, item_id) in direct_edges


def test_export_wiki_type_affinity_between_marked_items(tmp_path):
    """两篇标记文献（都是 type: source）→ TypeAffinity 双向边。"""
    item_a = _sample_item(key="KEY1", title="Paper A")
    item_b = _sample_item(key="KEY2", title="Paper B")
    client = _FakeClient(
        tagged_summaries=[{"key": "KEY1"}, {"key": "KEY2"}],
        full_items={"KEY1": item_a, "KEY2": item_b},
    )

    wiki_export.export_wiki(client, tmp_path)
    graph = build_graph(tmp_path)

    type_edges = {
        (e.source, e.target) for e in graph.edges if e.signal == GraphSignal.TypeAffinity
    }
    # 两篇 type=source 文献页之间 TypeAffinity 双向边
    assert ("wiki/zotero/items/KEY1.md", "wiki/zotero/items/KEY2.md") in type_edges
    assert ("wiki/zotero/items/KEY2.md", "wiki/zotero/items/KEY1.md") in type_edges


# ---------------------------------------------------------------------------
# 幂等性
# ---------------------------------------------------------------------------


def test_export_wiki_idempotent_no_rewrite_when_unchanged(tmp_path):
    """第二次 export_wiki 不重写文件（mtime 不变 + 内容相同）。"""
    item = _sample_item()
    client = _FakeClient(
        tagged_summaries=[{"key": item["key"]}],
        full_items={item["key"]: item},
        annotations={item["key"]: _sample_annotations()},
    )

    wiki_export.export_wiki(client, tmp_path)

    target = tmp_path / "wiki" / "zotero" / "items" / "ABCD1234.md"
    first_content = target.read_text(encoding="utf-8")
    first_mtime = target.stat().st_mtime_ns

    # 等至少 10ms，确保如果重写 mtime 会变化
    time.sleep(0.01)

    wiki_export.export_wiki(client, tmp_path)

    assert target.read_text(encoding="utf-8") == first_content
    assert target.stat().st_mtime_ns == first_mtime


# ---------------------------------------------------------------------------
# 容错 / 配置
# ---------------------------------------------------------------------------


def test_export_wiki_single_item_failure_does_not_abort_batch(tmp_path):
    """单篇 get_item 失败记入 errors，其余文献正常导出。"""
    good = _sample_item(key="GOOD1", title="Good Paper")
    bad_key = "BADKEY"

    client = _FakeClient(
        tagged_summaries=[{"key": good["key"]}, {"key": bad_key}],
        full_items={good["key"]: good},
        fail_keys={bad_key},
    )

    result = wiki_export.export_wiki(client, tmp_path)

    assert result.items_exported == 1
    assert (tmp_path / "wiki" / "zotero" / "items" / "GOOD1.md").exists()
    assert not (tmp_path / "wiki" / "zotero" / "items" / f"{bad_key}.md").exists()
    assert any(bad_key in err for err in result.errors)


def test_export_wiki_uses_explicit_tag_over_config(tmp_path, monkeypatch):
    """显式传 wiki_tag 优先级高于 wiki_tag_config()。"""
    item = _sample_item()
    client = _FakeClient(
        tagged_summaries=[{"key": item["key"]}],
        full_items={item["key"]: item},
    )

    wiki_export.export_wiki(client, tmp_path, wiki_tag="custom:tag")

    assert client.tag_calls == ["custom:tag"]


def test_export_wiki_reads_default_tag_from_settings(tmp_path, monkeypatch):
    """wiki_tag 为 None 时，读 wiki_tag_config() 覆盖值。"""
    monkeypatch.setattr(wiki_export, "wiki_tag_config", lambda: "custom:default")
    client = _FakeClient()

    wiki_export.export_wiki(client, tmp_path)

    assert client.tag_calls == ["custom:default"]


# ---------------------------------------------------------------------------
# slug 稳定性
# ---------------------------------------------------------------------------


def test_slugify_author_rules():
    assert wiki_export.slugify_author({"lastName": "Vaswani", "firstName": "Ashish"}) == "vaswani-a"
    assert wiki_export.slugify_author({"lastName": "LeCun", "firstName": "Yann"}) == "lecun-y"
    # 仅有 lastName
    assert wiki_export.slugify_author({"lastName": "Bengio"}) == "bengio"


def test_slugify_author_cjk_preserved():
    """H2 — CJK 作者名保留原字符，不再全部塌缩到 unknown。"""
    # 中日韩混用 → 保留 CJK + 首字母分隔
    assert wiki_export.slugify_author({"lastName": "王小明", "firstName": "Xiaoming"}) == "王小明-x"
    # 纯 CJK 姓名 → 直接保留
    assert wiki_export.slugify_author({"lastName": "张伟", "firstName": "伟"}) == "张伟-伟"
    # 纯 CJK 且不同姓 → 不同 slug（旧版会全压成 unknown）
    assert wiki_export.slugify_author({"lastName": "李四"}) == "李四"
    assert wiki_export.slugify_author({"lastName": "王五"}) == "王五"
    assert wiki_export.slugify_author({"lastName": "李四"}) != wiki_export.slugify_author({"lastName": "王五"})


def test_slugify_author_fallback_hash_when_no_cjk_or_ascii():
    """极端输入：纯 emoji / 符号 → 回退到 lastName 前 8 位 SHA，保证稳定唯一。"""
    slug1 = wiki_export.slugify_author({"lastName": "🚀🚀"})
    slug2 = wiki_export.slugify_author({"lastName": "🎉"})
    assert slug1 != slug2
    assert len(slug1) == 8
    # 同一输入稳定
    assert wiki_export.slugify_author({"lastName": "🚀🚀"}) == slug1
    # 完全空 → unknown
    assert wiki_export.slugify_author({}) == "unknown"


def test_author_display_name_rules():
    assert wiki_export.author_display_name({"lastName": "Vaswani", "firstName": "Ashish"}) == "Vaswani, A."
    assert wiki_export.author_display_name({"lastName": "LeCun"}) == "LeCun"
    assert wiki_export.author_display_name({"firstName": "Yann"}) == "Yann"
    assert wiki_export.author_display_name({}) == "Unknown"
