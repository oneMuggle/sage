"""M2 — Zotero 索引层（``backend.zotero.ingest``）单测。

覆盖四件事：

1. chunk 渲染（元数据 + 摘要 + 批注，摘要截断）
2. 全量 / 增量同步（水位推进、幂等替换、状态持久化）
3. 向量维度推断（首嵌取 ``len(vectors[0])``；维度变化 → 清库重建）
4. 降级（嵌入未配置 / 嵌入失败 → 记 error、不抛异常、不阻塞上层）

嵌入调用全部走 fake ``http_post``（与 ``test_attachment_rag.py`` 同口径），
测试不碰网络。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.wiki.vectorstore import VectorStore, read_stored_dim
from backend.zotero import ZoteroClient
from backend.zotero.ingest import (
    MAX_ABSTRACT_CHARS,
    MemorySyncStateStore,
    ZoteroIngestor,
    build_embedding_config,
    render_item_chunk,
    zotero_vector_store_path,
)

pytestmark = pytest.mark.unit

DIM = 4
FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "zotero.sqlite"


# ---------------------------------------------------------------------------
# 测试替身
# ---------------------------------------------------------------------------


def _item(key: str = "ABCD1234", item_id: int = 1, **overrides):
    """构造一条 index 形态的文献记录（形状同 ``ZoteroClient.iter_items_for_index``）。"""
    base = {
        "itemID": item_id,
        "key": key,
        "item_type": "journalArticle",
        "title": "Neural Network Survey Paper",
        "date": "2024",
        "abstract": "A comprehensive survey of neural network architectures.",
        "doi": "10.1234/jmlr.2024.001",
        "authors": ["Jane Doe", "John Smith"],
        "tags": ["machine-learning", "neural-networks"],
        "collections": ["NLP Papers"],
        "dateModified": "2026-09-22 10:00:00",
    }
    base.update(overrides)
    return base


class _FakeClient:
    """鸭子类型的 Zotero 客户端替身。"""

    def __init__(self, items=None, annotations=None):
        self.items = items if items is not None else [_item()]
        self.annotations = annotations or {}
        self.since_seen = []

    def iter_items_for_index(self, since_ts=None):
        self.since_seen.append(since_ts)
        for item in self.items:
            if since_ts is None or item["dateModified"] >= since_ts:
                yield item

    def annotations_by_parent(self, parent_item_ids):
        return {i: self.annotations.get(i, []) for i in parent_item_ids}


def _fake_http_post(dim: int = DIM, fail: bool = False, short: bool = False):
    """返回固定向量的 fake http_post，并记录每次请求的文本。"""
    calls = []

    async def _post(url, headers, body):
        calls.append(list(body["input"]))
        assert url.endswith("/embeddings")
        assert headers["Authorization"] == "Bearer k-test"
        if fail:
            raise RuntimeError("embedding backend down")
        count = len(body["input"])
        if short:
            count = max(0, count - 1)
        return json.dumps(
            {"data": [{"embedding": [(i + 1) / 10.0] * dim} for i in range(count)]}
        )

    _post.calls = calls  # type: ignore[attr-defined]
    return _post


def _config():
    return build_embedding_config("https://embed.example/v1", "k-test", "embed-test")


def _ingestor(tmp_path, client=None, http_post=None, state_store=None, **kwargs):
    return ZoteroIngestor(
        client=client if client is not None else _FakeClient(),
        storage_path=zotero_vector_store_path(tmp_path),
        embed_config=_config() if http_post is not None else None,
        http_post=http_post,
        state_store=state_store or MemorySyncStateStore(),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# chunk 渲染
# ---------------------------------------------------------------------------


class TestRenderItemChunk:
    def test_contains_metadata(self):
        text = render_item_chunk(_item())
        assert text.startswith("Neural Network Survey Paper")
        assert "Authors: Jane Doe, John Smith" in text
        assert "Year: 2024 | Type: journalArticle | DOI: 10.1234/jmlr.2024.001" in text
        assert "Tags: machine-learning, neural-networks" in text
        assert "Collections: NLP Papers" in text
        assert "A comprehensive survey of neural network architectures." in text

    def test_annotations_appended(self):
        annotations = [
            {
                "color": "#ff0000",
                "text": "neural networks achieve state of the art",
                "comment": "Key result",
            }
        ]
        text = render_item_chunk(_item(), annotations)
        assert "Annotations:" in text
        assert "- [#ff0000] neural networks achieve state of the art Key result" in text

    def test_abstract_truncated(self):
        long_abstract = "x" * (MAX_ABSTRACT_CHARS + 500)
        text = render_item_chunk(_item(abstract=long_abstract))
        assert "x" * MAX_ABSTRACT_CHARS in text
        assert "x" * (MAX_ABSTRACT_CHARS + 1) not in text

    def test_optional_fields_omitted(self):
        text = render_item_chunk(_item(doi="", tags=[], collections=[], abstract=""))
        assert "DOI:" not in text
        assert "Tags:" not in text
        assert "Collections:" not in text
        assert "Annotations:" not in text
        assert "Year: 2024 | Type: journalArticle" in text

    def test_empty_title_placeholder(self):
        assert render_item_chunk(_item(title="  ")).startswith("(无标题)")

    def test_year_extracted_from_full_date(self):
        assert "Year: 2024" in render_item_chunk(_item(date="2024-05-01"))
        assert "Year: " in render_item_chunk(_item(date="n.d."))

    def test_no_authors_placeholder(self):
        assert "Authors: (未知作者)" in render_item_chunk(_item(authors=[]))


# ---------------------------------------------------------------------------
# 存储路径
# ---------------------------------------------------------------------------


class TestStoragePath:
    def test_path_under_rag(self, tmp_path):
        assert zotero_vector_store_path(tmp_path) == tmp_path / "rag" / "zotero.json"


# ---------------------------------------------------------------------------
# 全量同步
# ---------------------------------------------------------------------------


class TestSyncFull:
    async def test_writes_one_chunk_per_item(self, tmp_path):
        client = _FakeClient(items=[_item("ABCD1234", 1), _item("EFGH5678", 2)])
        ingestor = _ingestor(tmp_path, client=client, http_post=_fake_http_post())

        result = await ingestor.sync_full()

        assert result.errors == []
        assert result.items == 2
        assert result.chunks == 2
        store = VectorStore.open_at(zotero_vector_store_path(tmp_path), DIM)
        assert sorted(r.page_path for r in store.records) == [
            "zotero/ABCD1234",
            "zotero/EFGH5678",
        ]
        assert all(r.chunk_index == 0 for r in store.records)

    async def test_dim_probed_from_first_vector(self, tmp_path):
        ingestor = _ingestor(tmp_path, http_post=_fake_http_post(dim=7))

        result = await ingestor.sync_full()

        assert result.dim == 7
        assert read_stored_dim(zotero_vector_store_path(tmp_path)) == 7

    async def test_state_persisted(self, tmp_path):
        store = MemorySyncStateStore()
        ingestor = _ingestor(tmp_path, http_post=_fake_http_post(), state_store=store)

        await ingestor.sync_full()

        state = store.load()
        assert state["last_sync_ts"] == "2026-09-22 10:00:00"
        assert state["items"] == 1
        assert state["errors"] == []
        assert "last_sync_at" in state

    async def test_reindex_is_idempotent(self, tmp_path):
        ingestor = _ingestor(tmp_path, http_post=_fake_http_post())

        await ingestor.sync_full()
        result = await ingestor.sync_full()

        assert result.items == 1
        store = VectorStore.open_at(zotero_vector_store_path(tmp_path), DIM)
        assert len(store.records) == 1

    async def test_annotations_included_in_chunk(self, tmp_path):
        client = _FakeClient(
            items=[_item()],
            annotations={1: [{"color": "#ff0000", "text": "spotlight", "comment": ""}]},
        )
        ingestor = _ingestor(tmp_path, client=client, http_post=_fake_http_post())

        await ingestor.sync_full()

        store = VectorStore.open_at(zotero_vector_store_path(tmp_path), DIM)
        assert "- [#ff0000] spotlight" in store.records[0].content

    async def test_rebuild_drops_stale_pages(self, tmp_path):
        storage = zotero_vector_store_path(tmp_path)
        seeded = VectorStore.open_at(storage, 2)
        seeded.upsert_pages({"zotero/GONE0001": [(0, "stale", [0.1, 0.2])]})

        ingestor = _ingestor(tmp_path, http_post=_fake_http_post())
        await ingestor.sync_full()

        store = VectorStore.open_at(storage, DIM)
        assert [r.page_path for r in store.records] == ["zotero/ABCD1234"]


# ---------------------------------------------------------------------------
# 增量同步
# ---------------------------------------------------------------------------


class TestSyncIncremental:
    async def test_only_modified_items_indexed(self, tmp_path):
        client = _FakeClient(
            items=[
                _item("OLD00001", 1, dateModified="2026-09-01 09:00:00"),
                _item("NEW00001", 2, dateModified="2026-09-22 10:00:00"),
            ]
        )
        # 预置向量库含 OLD 文献向量，否则 ingest 的安全重建路径
        # （水位存在但向量库缺失 → 全量重建）会被触发，导致两条文献都被索引
        VectorStore.open_at(zotero_vector_store_path(tmp_path), DIM).upsert_pages(
            {"zotero/OLD00001": [(0, "old", [0.1, 0.2, 0.3, 0.4])]}
        )
        ingestor = _ingestor(tmp_path, client=client, http_post=_fake_http_post())

        result = await ingestor.sync_incremental("2026-09-20 00:00:00")

        assert client.since_seen == ["2026-09-20 00:00:00"]
        # result.items 是 store 总条目（OLD 预置 + NEW 增量），
        # 不是本轮处理数
        assert result.items == 2
        store = VectorStore.open_at(zotero_vector_store_path(tmp_path), DIM)
        assert sorted(r.page_path for r in store.records) == [
            "zotero/NEW00001",
            "zotero/OLD00001",
        ]

    async def test_boundary_item_included(self, tmp_path):
        """``dateModified == 水位`` 的条目必须被重新索引（过滤是 ``>=`` 不是 ``>``）。"""
        client = _FakeClient(items=[_item(dateModified="2026-09-22 10:00:00")])
        ingestor = _ingestor(tmp_path, client=client, http_post=_fake_http_post())

        result = await ingestor.sync_incremental("2026-09-22 10:00:00")

        assert result.items == 1

    async def test_watermark_read_from_state(self, tmp_path):
        client = _FakeClient(items=[_item(dateModified="2026-09-22 10:00:00")])
        store = MemorySyncStateStore({"last_sync_ts": "2026-09-20 00:00:00"})
        # 预置向量库避免安全重建路径触发
        VectorStore.open_at(zotero_vector_store_path(tmp_path), DIM).upsert_pages(
            {"zotero/DUMMY01": [(0, "x", [0.1, 0.2, 0.3, 0.4])]}
        )
        ingestor = _ingestor(
            tmp_path, client=client, http_post=_fake_http_post(), state_store=store
        )

        await ingestor.sync_incremental()

        assert client.since_seen == ["2026-09-20 00:00:00"]

    async def test_incremental_keeps_previous_pages(self, tmp_path):
        client = _FakeClient(items=[_item("AAAA0001", 1)])
        ingestor = _ingestor(tmp_path, client=client, http_post=_fake_http_post())
        await ingestor.sync_incremental()

        client.items = [_item("BBBB0001", 2)]
        result = await ingestor.sync_incremental("2026-09-20 00:00:00")

        assert result.items == 2
        store = VectorStore.open_at(zotero_vector_store_path(tmp_path), DIM)
        assert sorted(r.page_path for r in store.records) == [
            "zotero/AAAA0001",
            "zotero/BBBB0001",
        ]

    async def test_no_changes_keeps_watermark(self, tmp_path):
        store = MemorySyncStateStore(
            {"last_sync_ts": "2026-09-20 00:00:00", "items": 7}
        )
        ingestor = _ingestor(
            tmp_path,
            client=_FakeClient(items=[_item(dateModified="2026-09-01 09:00:00")]),
            http_post=_fake_http_post(),
            state_store=store,
        )

        result = await ingestor.sync_incremental()

        assert result.items == 0
        assert store.load()["last_sync_ts"] == "2026-09-20 00:00:00"
        assert store.load()["items"] == 7


class TestNextWatermark:
    """``_next_watermark`` 的部分失败回退逻辑。"""

    def test_ok_only_uses_max(self, tmp_path):
        ingestor = _ingestor(tmp_path, http_post=_fake_http_post())
        assert (
            ingestor._next_watermark(
                ["2026-10-27 11:00:00", "2026-10-27 12:00:00"], [], None
            )
            == "2026-10-27 12:00:00"
        )

    def test_failure_reverts_to_min_failed(self, tmp_path):
        """失败条目的最早时间戳兜底，保证它们下一轮仍被增量过滤捞出来。"""
        ingestor = _ingestor(tmp_path, http_post=_fake_http_post())
        watermark = ingestor._next_watermark(
            ok_ts=["2026-10-27 11:00:00", "2026-10-27 12:00:00"],
            failed_ts=["2026-10-27 10:00:00", "2026-10-27 13:00:00"],
            since_ts="2026-10-27 09:00:00",
        )
        assert watermark == "2026-10-27 10:00:00"

    def test_no_ok_keeps_since(self, tmp_path):
        ingestor = _ingestor(tmp_path, http_post=_fake_http_post())
        assert (
            ingestor._next_watermark([], ["2026-10-27 10:00:00"], "2026-10-27 09:00:00")
            == "2026-10-27 09:00:00"
        )

    def test_empty_everything_returns_empty(self, tmp_path):
        ingestor = _ingestor(tmp_path, http_post=_fake_http_post())
        assert ingestor._next_watermark([], [], None) == ""


# ---------------------------------------------------------------------------
# 维度变化
# ---------------------------------------------------------------------------


class TestDimensionChange:
    async def test_dim_change_rebuilds_store(self, tmp_path):
        storage = zotero_vector_store_path(tmp_path)
        seeded = VectorStore.open_at(storage, 2)
        seeded.upsert_pages({"zotero/OLD0001": [(0, "old", [0.1, 0.2])]})

        ingestor = _ingestor(tmp_path, http_post=_fake_http_post(dim=4))
        result = await ingestor.sync_full()

        assert result.dim == 4
        assert read_stored_dim(storage) == 4
        store = VectorStore.open_at(storage, 4)
        assert [r.page_path for r in store.records] == ["zotero/ABCD1234"]


# ---------------------------------------------------------------------------
# 降级
# ---------------------------------------------------------------------------


class TestDegradation:
    async def test_embedding_not_configured(self, tmp_path):
        store = MemorySyncStateStore()
        ingestor = _ingestor(tmp_path, http_post=None, state_store=store)

        result = await ingestor.sync_incremental()

        assert result.skipped is True
        assert result.errors == ["embedding_not_configured"]
        assert not zotero_vector_store_path(tmp_path).exists()
        assert store.load()["errors"] == ["embedding_not_configured"]

    async def test_embed_failure_does_not_raise(self, tmp_path):
        store = MemorySyncStateStore({"last_sync_ts": "2026-09-20 00:00:00"})
        ingestor = _ingestor(
            tmp_path, http_post=_fake_http_post(fail=True), state_store=store
        )

        result = await ingestor.sync_incremental()

        assert result.items == 0
        assert any(e.startswith("embed_failed") for e in result.errors)
        assert not zotero_vector_store_path(tmp_path).exists()
        # 失败不推进水位
        assert store.load()["last_sync_ts"] == "2026-09-20 00:00:00"

    async def test_embed_count_mismatch_recorded(self, tmp_path):
        ingestor = _ingestor(tmp_path, http_post=_fake_http_post(short=True))

        result = await ingestor.sync_full()

        assert result.items == 0
        assert any(e.startswith("embed_count_mismatch") for e in result.errors)

    async def test_client_read_failure_recorded(self, tmp_path):
        class _Broken:
            def iter_items_for_index(self, since_ts=None):
                raise RuntimeError("database is locked")

            def annotations_by_parent(self, parent_item_ids):
                return {}

        ingestor = _ingestor(
            tmp_path, client=_Broken(), http_post=_fake_http_post()
        )

        result = await ingestor.sync_full()

        assert result.items == 0
        assert any(e.startswith("zotero_read_failed") for e in result.errors)

    async def test_annotation_failure_degrades_to_empty(self, tmp_path):
        class _NoAnnotations(_FakeClient):
            def annotations_by_parent(self, parent_item_ids):
                raise RuntimeError("boom")

        ingestor = _ingestor(
            tmp_path, client=_NoAnnotations(), http_post=_fake_http_post()
        )

        result = await ingestor.sync_full()

        assert result.items == 1
        assert result.errors == []


# ---------------------------------------------------------------------------
# 与真实 Zotero 客户端的集成
# ---------------------------------------------------------------------------


@pytest.fixture()
def fixture_client() -> ZoteroClient:
    if not FIXTURE_PATH.exists():
        from backend.tests.fixtures.generate_zotero_fixture import build_fixture

        build_fixture(FIXTURE_PATH)
    return ZoteroClient(db_path=FIXTURE_PATH)


class TestWithRealClient:
    def test_index_iterator_excludes_internal_types(self, fixture_client):
        items = list(fixture_client.iter_items_for_index())
        keys = sorted(item["key"] for item in items)
        assert keys == ["ABCD1234", "BOOK0001", "CONF0001", "EFGH5678", "THES0001"]
        assert all(
            item["item_type"] not in ("attachment", "note", "annotation")
            for item in items
        )

    def test_index_iterator_filter_is_inclusive(self, fixture_client):
        # fixture 里所有条目的 dateModified 相同 → 边界值必须全部命中
        items = list(fixture_client.iter_items_for_index("2026-09-22 10:00:00"))
        assert len(items) == 5
        assert list(fixture_client.iter_items_for_index("2026-09-22 10:00:01")) == []

    def test_authors_are_names_not_joined_string(self, fixture_client):
        items = {i["key"]: i for i in fixture_client.iter_items_for_index()}
        assert items["ABCD1234"]["authors"] == ["Jane Doe", "John Smith"]
        assert items["BOOK0001"]["authors"] == ["Jane Doe", "Bob Williams"]

    def test_annotations_grouped_by_bibliographic_parent(self, fixture_client):
        grouped = fixture_client.annotations_by_parent([1, 2])
        assert len(grouped[1]) == 2
        assert len(grouped[2]) == 1
        assert grouped[1][0]["text"] == "neural networks achieve state of the art"
        assert grouped[1][0]["color"] == "#ff0000"

    async def test_full_sync_over_fixture(self, tmp_path, fixture_client):
        ingestor = ZoteroIngestor(
            client=fixture_client,
            storage_path=zotero_vector_store_path(tmp_path),
            embed_config=_config(),
            http_post=_fake_http_post(),
            state_store=MemorySyncStateStore(),
        )

        result = await ingestor.sync_full()

        assert result.errors == []
        assert result.items == 5
        store = VectorStore.open_at(zotero_vector_store_path(tmp_path), DIM)
        contents = {r.page_path: r.content for r in store.records}
        assert "zotero/ABCD1234" in contents
        assert "Neural Network Survey Paper" in contents["zotero/ABCD1234"]
        assert "Authors: Jane Doe, John Smith" in contents["zotero/ABCD1234"]
