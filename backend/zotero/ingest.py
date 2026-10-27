"""Zotero 文献库向量索引层（2026-10-27 feat/zotero-llm-visible M2）。

把 Zotero 库里的每条文献渲染成**一篇一个 chunk** 的文本，嵌入后写入独立
向量库 ``<data_root>/rag/zotero.json``，供 ``zotero_search`` 语义检索使用。

设计取舍：

- **依赖全部显式注入**（client / storage_path / embed_config / http_post），
  与 ``backend/services/attachment_rag.py`` 同口径，测试可换 fake，不碰网络。
- **维度不写死**：``load_embedding_config()`` 不返回 dim，首次嵌入后从首个
  向量推断；其后从存储文件读（``read_stored_dim``）。维度变化 → 清库重建。
- **降级不阻塞**：嵌入未配置 / 嵌入调用失败 → 记 error、返回结果，不抛异常。
  语义检索不可用时上层退回 SQL LIKE 检索。
- **纯 dataclass + typing 注解**，不引入 pydantic 模型、不用 ``X | Y``
  运行期注解，兼容 release/win7 的 Python 3.8。

同步状态持久化在 settings ``zotero_sync_state``：

.. code-block:: json

    {"last_sync_ts": "2026-09-22 10:00:00", "items": 1284, "wiki_pages": 12, "errors": []}

``last_sync_ts`` 存 Zotero ``items.dateModified`` 的**原样字符串**
（``YYYY-MM-DD HH:MM:SS`` UTC），因为增量过滤靠它与 SQL 列做字典序比较；
换成 ISO 8601 的 ``T``/``Z`` 分隔符会与库内格式错位，导致同一天的条目被漏掉。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from backend.wiki.embeddings import (
    EmbeddingConfig,
    build_embed_request,
    parse_embed_response,
)
from backend.wiki.vectorstore import VectorStore, read_stored_dim

logger = logging.getLogger(__name__)

# 向量库中文献页的 page_path 前缀
ZOTERO_PAGE_PREFIX = "zotero/"

# settings 里存同步状态的 key
SYNC_STATE_KEY = "zotero_sync_state"

# 进入 wiki 沉淀的默认 Zotero tag（settings key "zotero_wiki_tag" 可覆盖）
DEFAULT_WIKI_TAG = "sage:wiki"

# 摘要截断长度（字符）
MAX_ABSTRACT_CHARS = 4000

# 嵌入批大小与并发度
DEFAULT_BATCH_SIZE = 32
DEFAULT_CONCURRENCY = 4

# 嵌入调用签名：(url, headers, body) -> 响应体文本
HttpPost = Callable[[str, Dict[str, str], dict], Awaitable[str]]


def zotero_vector_store_path(data_root: Path) -> Path:
    """返回 Zotero 向量库路径（与附件库 ``rag/attachments.json`` 并列）。"""
    return Path(data_root) / "rag" / "zotero.json"


def build_embedding_config(
    base_url: str, api_key: str, model: str
) -> EmbeddingConfig:
    """构造嵌入配置。

    ``dim=0`` 表示**未知**——``load_embedding_config()`` 不返回维度，
    维度由首次嵌入的实际向量推断，配置里的值一律忽略。
    """
    return EmbeddingConfig(base_url=base_url, api_key=api_key, model=model, dim=0)


@dataclass
class SyncResult:
    """一次同步的结果。"""

    items: int = 0
    chunks: int = 0
    dim: int = 0
    last_sync_ts: str = ""
    skipped: bool = False
    elapsed_ms: int = 0
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """转成可 JSON 序列化的 dict（REST / MCP 返回体）。"""
        return {
            "items": self.items,
            "chunks": self.chunks,
            "dim": self.dim,
            "last_sync_ts": self.last_sync_ts,
            "skipped": self.skipped,
            "elapsed_ms": self.elapsed_ms,
            "errors": list(self.errors),
        }


# ---------------------------------------------------------------------------
# chunk 渲染
# ---------------------------------------------------------------------------


def _extract_year(date_text: str) -> str:
    """从 Zotero ``date`` 字段抽出年份（``2024`` / ``2024-05-01`` → ``2024``）。"""
    text = (date_text or "").strip()
    if len(text) >= 4 and text[:4].isdigit():
        return text[:4]
    return ""


def render_item_chunk(
    item: Dict[str, Any], annotations: Optional[List[Dict[str, Any]]] = None
) -> str:
    """把一条文献渲染成一个 chunk 文本。

    模板::

        {title}
        Authors: {authors}
        Year: {year} | Type: {item_type} | DOI: {doi}
        Tags: {tags}
        Collections: {collections}

        {abstract}

        Annotations:
        - [{color}] {annotation_text} {comment}

    摘要截断到 ``MAX_ABSTRACT_CHARS``；缺省的 DOI / 标签 / 集合 / 批注整行省略。
    """
    lines: List[str] = []

    title = (item.get("title") or "").strip()
    lines.append(title or "(无标题)")

    authors = [a for a in (item.get("authors") or []) if a]
    lines.append("Authors: " + (", ".join(authors) if authors else "(未知作者)"))

    meta = "Year: {year} | Type: {item_type}".format(
        year=_extract_year(item.get("date") or ""),
        item_type=(item.get("item_type") or "").strip() or "unknown",
    )
    doi = (item.get("doi") or "").strip()
    if doi:
        meta += " | DOI: " + doi
    lines.append(meta)

    tags = [t for t in (item.get("tags") or []) if t]
    if tags:
        lines.append("Tags: " + ", ".join(tags))

    collections = [c for c in (item.get("collections") or []) if c]
    if collections:
        lines.append("Collections: " + ", ".join(collections))

    abstract = (item.get("abstract") or "").strip()
    if abstract:
        if len(abstract) > MAX_ABSTRACT_CHARS:
            abstract = abstract[:MAX_ABSTRACT_CHARS]
        lines.append("")
        lines.append(abstract)

    if annotations:
        lines.append("")
        lines.append("Annotations:")
        for anno in annotations:
            color = (anno.get("color") or "").strip() or "none"
            text = (anno.get("text") or "").strip()
            comment = (anno.get("comment") or "").strip()
            piece = f"- [{color}] {text}"
            if comment:
                piece += " " + comment
            lines.append(piece)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 同步状态存储
# ---------------------------------------------------------------------------


class SyncStateStore:
    """同步状态的读写口。"""

    def load(self) -> Dict[str, Any]:
        raise NotImplementedError

    def save(self, state: Dict[str, Any]) -> None:
        raise NotImplementedError


class SettingsSyncStateStore(SyncStateStore):
    """把同步状态写进 preferences 表（key = ``zotero_sync_state``）。"""

    def __init__(self) -> None:
        self._repo = None

    def _repository(self):
        if self._repo is None:
            from backend.data.settings_repo import SettingsRepository

            self._repo = SettingsRepository()
        return self._repo

    def load(self) -> Dict[str, Any]:
        try:
            data = self._repository().get_json(SYNC_STATE_KEY)
        except Exception:  # pragma: no cover - 启动期 DB 不可用等
            logger.debug("zotero sync state load failed", exc_info=True)
            return {}
        return dict(data) if isinstance(data, dict) else {}

    def save(self, state: Dict[str, Any]) -> None:
        self._repository().set_json(SYNC_STATE_KEY, state)


class MemorySyncStateStore(SyncStateStore):
    """内存态（测试用）。"""

    def __init__(self, initial: Optional[Dict[str, Any]] = None) -> None:
        self._state: Dict[str, Any] = dict(initial or {})

    def load(self) -> Dict[str, Any]:
        return dict(self._state)

    def save(self, state: Dict[str, Any]) -> None:
        self._state = dict(state)


# ---------------------------------------------------------------------------
# 索引器
# ---------------------------------------------------------------------------


class ZoteroIngestor:
    """Zotero 库 → 向量库。"""

    def __init__(
        self,
        client: Any,
        storage_path: Path,
        embed_config: Optional[EmbeddingConfig] = None,
        http_post: Optional[HttpPost] = None,
        state_store: Optional[SyncStateStore] = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        concurrency: int = DEFAULT_CONCURRENCY,
    ) -> None:
        """
        Args:
            client: 提供 ``iter_items_for_index`` / ``annotations_by_parent``
                的 Zotero 客户端（``ZoteroClient``）。
            storage_path: 向量库文件路径。
            embed_config: 嵌入配置；``None`` 表示未配置嵌入模型 → 同步跳过。
            http_post: 嵌入 HTTP 调用；``None`` 同上。
            state_store: 同步状态存储；缺省写 settings。
            batch_size: 单次嵌入请求的文本条数。
            concurrency: 嵌入请求并发度。
        """
        self._client = client
        self._storage_path = Path(storage_path)
        self._embed_config = embed_config
        self._http_post = http_post
        self._state_store = state_store or SettingsSyncStateStore()
        self._batch_size = max(1, batch_size)
        self._concurrency = max(1, concurrency)

    # -- 公开 API ---------------------------------------------------------

    async def sync_incremental(
        self, since_ts: Optional[str] = None
    ) -> SyncResult:
        """增量同步：只处理 ``dateModified >= since_ts`` 的文献。

        Args:
            since_ts: 增量水位；``None`` 表示从同步状态里读（首次没有 → 全量）。
        """
        if since_ts is None:
            since_ts = self._load_state().get("last_sync_ts") or None
        return await self._sync(since_ts=since_ts, rebuild=False)

    async def sync_full(self) -> SyncResult:
        """全量重建：清空既有向量库后重新索引全库。"""
        return await self._sync(since_ts=None, rebuild=True)

    # -- 内部实现 ---------------------------------------------------------

    def _load_state(self) -> Dict[str, Any]:
        try:
            data = self._state_store.load()
        except Exception:  # pragma: no cover - 状态存储不可用
            logger.debug("zotero sync state load failed", exc_info=True)
            return {}
        return dict(data) if isinstance(data, dict) else {}

    def _save_state(self, state: Dict[str, Any]) -> None:
        try:
            self._state_store.save(state)
        except Exception:  # pragma: no cover - 状态存储不可用
            logger.warning("zotero sync state save failed", exc_info=True)

    def _clear_store(self) -> None:
        try:
            self._storage_path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("zotero vector store clear failed: %s", exc)

    async def _sync(self, since_ts: Optional[str], rebuild: bool) -> SyncResult:  # noqa: PLR0911 — 状态机多早退分支
        started = time.monotonic()
        result = SyncResult()

        if self._embed_config is None or self._http_post is None:
            result.errors.append("embedding_not_configured")
            result.skipped = True
            result.last_sync_ts = since_ts or ""
            result.elapsed_ms = int((time.monotonic() - started) * 1000)
            self._persist_state(result, advance=False)
            return result

        try:
            items = list(self._client.iter_items_for_index(since_ts))
        except Exception as exc:
            logger.warning("zotero index read failed: %s", exc)
            result.errors.append(f"zotero_read_failed: {exc}")
            result.last_sync_ts = since_ts or ""
            result.elapsed_ms = int((time.monotonic() - started) * 1000)
            self._persist_state(result, advance=False)
            return result

        if not items:
            result.last_sync_ts = since_ts or ""
            result.elapsed_ms = int((time.monotonic() - started) * 1000)
            self._persist_state(result, advance=False)
            return result

        annotations = self._collect_annotations(items)

        records: List[Tuple[str, str, str]] = []
        for item in items:
            page_path = ZOTERO_PAGE_PREFIX + str(item.get("key") or "")
            text = render_item_chunk(item, annotations.get(item.get("itemID"), []))
            records.append((page_path, text, str(item.get("dateModified") or "")))

        batches = [
            records[i : i + self._batch_size]
            for i in range(0, len(records), self._batch_size)
        ]
        vectors, errors = await self._embed_batches(batches)
        result.errors.extend(errors)

        dim = 0
        pages: Dict[str, List[Tuple[int, str, List[float]]]] = {}
        ok_ts: List[str] = []
        failed_ts: List[str] = []
        for batch, batch_vectors in zip(batches, vectors):  # noqa: B905 — py3.8
            if not batch_vectors:
                failed_ts.extend(record[2] for record in batch)
                continue
            for record, vector in zip(batch, batch_vectors):  # noqa: B905 — py3.8
                page_path, text, ts = record
                if dim and len(vector) != dim:
                    result.errors.append("embed_dim_inconsistent")
                    continue
                dim = dim or len(vector)
                pages[page_path] = [(0, text, vector)]
                ok_ts.append(ts)

        if not pages:
            result.last_sync_ts = since_ts or ""
            result.elapsed_ms = int((time.monotonic() - started) * 1000)
            self._persist_state(result, advance=False)
            return result

        stored_dim = read_stored_dim(self._storage_path)
        if stored_dim is None and since_ts:
            # 水位已持久化但向量库被删 / 损坏——增量只补 delta，
            # 会把旧文献漏掉；这里触发一次完整重建避免静默缺数据
            logger.warning(
                "zotero vector store missing but watermark present (%s); rebuilding",
                since_ts,
            )
            self._persist_state(result, advance=False)
            return await self._sync(since_ts=None, rebuild=True)
        if stored_dim is not None and stored_dim != dim:
            # 换了嵌入模型 → 维度变了，旧向量不可比，清库重建
            logger.info(
                "zotero vector dim changed (%s -> %s), rebuilding", stored_dim, dim
            )
            self._clear_store()
            return await self._sync(since_ts=None, rebuild=True)

        if rebuild:
            # 全量重建：先清旧库再写，保证不留已删除文献的残留向量
            self._clear_store()

        try:
            store = VectorStore.open_at(self._storage_path, dim)
            store.upsert_pages(pages)
        except (OSError, ValueError) as exc:
            logger.warning("zotero vector store write failed: %s", exc)
            result.errors.append(f"vector_store_write_failed: {exc}")
            result.last_sync_ts = since_ts or ""
            result.elapsed_ms = int((time.monotonic() - started) * 1000)
            self._persist_state(result, advance=False)
            return result

        result.items = len(store.records)
        result.chunks = sum(len(chunks) for chunks in pages.values())
        result.dim = dim
        result.last_sync_ts = self._next_watermark(ok_ts, failed_ts, since_ts)
        result.elapsed_ms = int((time.monotonic() - started) * 1000)
        self._persist_state(result, advance=True)
        return result

    def _collect_annotations(
        self, items: List[Dict[str, Any]]
    ) -> Dict[int, List[Dict[str, Any]]]:
        """批量取批注；失败时降级为空（不影响主流程）。"""
        item_ids = [i.get("itemID") for i in items if i.get("itemID") is not None]
        if not item_ids:
            return {}
        try:
            return self._client.annotations_by_parent(item_ids)
        except Exception as exc:
            logger.warning("zotero annotations fetch failed: %s", exc)
            return {}

    def _next_watermark(
        self, ok_ts: List[str], failed_ts: List[str], since_ts: Optional[str]
    ) -> str:
        """算下一轮的水位。

        成功条目的最大 ``dateModified``；若有失败条目则回退到**失败条目里最早**
        的时间戳，保证失败条目下一轮仍会被捞出来（增量过滤是 ``>=``）。
        """
        if not ok_ts:
            return since_ts or ""
        watermark = max(ok_ts)
        if failed_ts:
            watermark = min(watermark, *failed_ts)
        return watermark

    async def _embed_batches(
        self, batches: List[List[Tuple[str, str, str]]]
    ) -> Tuple[List[Optional[List[List[float]]]], List[str]]:
        """并发嵌入各批，返回 (每批向量或 None, 错误列表)。"""
        results: List[Optional[List[List[float]]]] = [None] * len(batches)
        errors: List[str] = []
        semaphore = asyncio.Semaphore(self._concurrency)

        async def _run(index: int, batch: List[Tuple[str, str, str]]) -> None:
            async with semaphore:
                texts = [record[1] for record in batch]
                try:
                    vectors = await self._embed_batch(texts)
                except Exception as exc:
                    logger.warning("zotero embed batch %d failed: %s", index, exc)
                    errors.append(f"embed_failed: {exc}")
                    return
                if len(vectors) != len(texts):
                    errors.append(
                        f"embed_count_mismatch: expected {len(texts)} got {len(vectors)}"
                    )
                    return
                results[index] = vectors

        await asyncio.gather(
            *[_run(index, batch) for index, batch in enumerate(batches)]
        )
        return results, errors

    async def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        request = build_embed_request(self._embed_config, texts)
        body = await self._http_post(request.url, request.headers, request.body)
        if not isinstance(body, str):
            body = json.dumps(body, ensure_ascii=False)
        # expected_dim=0：维度由调用方从首个向量推断
        return parse_embed_response(body, expected_dim=0)

    def _persist_state(self, result: SyncResult, advance: bool) -> None:
        """把本轮结果写进同步状态。

        ``advance=False``（跳过 / 失败）时保留原水位，只更新错误与时间戳。
        """
        state = self._load_state()
        if advance and result.last_sync_ts:
            state["last_sync_ts"] = result.last_sync_ts
        state["items"] = result.items if advance else state.get("items", 0)
        state["errors"] = list(result.errors)[:10]
        state["last_sync_at"] = datetime.now(timezone.utc).strftime(  # noqa: UP017
            "%Y-%m-%dT%H:%M:%SZ"
        )
        state.setdefault("wiki_pages", 0)
        self._save_state(state)
