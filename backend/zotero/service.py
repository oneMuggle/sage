"""Zotero 服务层装配 —— 同步与语义检索的共用接线。

REST API（``backend/api/zotero_sync_routes.py``）与 MCP server
（``backend/mcp/servers/zotero/server.py``）跑在不同进程，但需要**同一套**
接线逻辑：

- 数据根目录（``MEDIA_ROOT.parent``）与向量库路径（``rag/zotero.json``）
- Zotero 客户端构造（DB 路径来自 settings → env → 默认）
- 嵌入配置解析（``app_settings.modelSelections.embeddingModel``）
- 嵌入 HTTP 调用（OpenAI 兼容 ``/embeddings``）
- ``ZoteroIngestor`` 组装
- 语义检索（嵌入 query → 向量检索 → item 摘要）

把这些放在一个**不依赖 FastAPI** 的模块里，避免 REST 与 MCP 两处接线漂移。
之前它们各写一份，改一处忘另一处就是「工具能调但检索不到」的复发路径。

降级契约
--------
``semantic_search()`` 返回 ``None`` 表示 **RAG 不可用**（未配置 embedding /
向量库不存在 / 嵌入调用失败 / 维度不匹配），调用方必须退回 SQL LIKE 检索。
返回 ``[]`` 表示 RAG 可用但无命中。**绝不抛异常打断检索**。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from backend.services.multimodal.media_store import MEDIA_ROOT
from backend.wiki.embeddings import (
    EmbeddingConfig,
    build_embed_request,
    parse_embed_response,
)
from backend.wiki.vectorstore import VectorStore, read_stored_dim
from backend.zotero.ingest import (
    ZOTERO_PAGE_PREFIX,
    ZoteroIngestor,
    build_embedding_config,
    zotero_vector_store_path,
)
from backend.zotero.paths import resolve_zotero_db_path

logger = logging.getLogger(__name__)

#: 语义检索摘要里回给 LLM 的 chunk 预览长度（字符）
SNIPPET_CHARS = 600


# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------


def data_root() -> Path:
    """数据根目录（``data/``）；向量库在 ``data/rag/`` 下。"""
    return MEDIA_ROOT.parent


def storage_path() -> Path:
    """Zotero 向量库路径。"""
    return zotero_vector_store_path(data_root())


# ---------------------------------------------------------------------------
# 客户端 / 嵌入配置
# ---------------------------------------------------------------------------


def build_client() -> Optional[Any]:
    """构造 ZoteroClient；库路径未配置或文件不存在时返回 None。"""
    db_path = resolve_zotero_db_path()
    if not db_path:
        return None
    if not Path(db_path).exists():
        return None
    try:
        from backend.zotero.client import ZoteroClient

        return ZoteroClient(db_path=db_path)
    except Exception as exc:  # pragma: no cover - SQLite 打开失败
        logger.warning("zotero client init failed: %s", exc)
        return None


def embed_config() -> Optional[EmbeddingConfig]:
    """读 embedding 配置；未配置返回 None。"""
    from backend.tools.workspace_index import load_embedding_config

    try:
        raw = load_embedding_config()
    except Exception:  # pragma: no cover - settings DB 不可用
        logger.debug("embedding config unavailable", exc_info=True)
        return None
    if raw is None:
        return None
    return build_embedding_config(raw["base_url"], raw["api_key"], raw["model"])


async def embed_http_post(url: str, headers: Dict[str, str], body: dict) -> str:
    """单次嵌入 HTTP POST（超时 60s）。"""
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        return resp.text


def build_ingestor(client: Any) -> ZoteroIngestor:
    """组装 ``ZoteroIngestor``（嵌入未配置时 http_post 为 None → 同步跳过）。"""
    config = embed_config()
    return ZoteroIngestor(
        client=client,
        storage_path=storage_path(),
        embed_config=config,
        http_post=embed_http_post if config is not None else None,
    )


# ---------------------------------------------------------------------------
# 语义检索
# ---------------------------------------------------------------------------


def _parse_chunk_header(content: str) -> Dict[str, str]:
    """从 chunk 头部解析标题 / 作者 / 年份 / 类型。

    chunk 模板由 ``backend.zotero.ingest.render_item_chunk`` 生成：首行标题，
    随后 ``Authors: ...`` 与 ``Year: ... | Type: ... | DOI: ...``。解析失败
    时返回空串，不影响检索结果展示。
    """
    lines = content.splitlines()
    meta: Dict[str, str] = {
        "title": lines[0].strip() if lines else "",
        "authors": "",
        "year": "",
        "item_type": "",
    }
    for line in lines[1:4]:
        if line.startswith("Authors:"):
            meta["authors"] = line[len("Authors:") :].strip()
        elif line.startswith("Year:"):
            for segment in line.split("|"):
                piece = segment.strip()
                if piece.startswith("Year:"):
                    meta["year"] = piece[len("Year:") :].strip()
                elif piece.startswith("Type:"):
                    meta["item_type"] = piece[len("Type:") :].strip()
    return meta


def _summarize_hit(page_path: str, content: str, score: float) -> Dict[str, Any]:
    """把一条向量命中压成回给 LLM 的摘要。"""
    key = (
        page_path[len(ZOTERO_PAGE_PREFIX) :]
        if page_path.startswith(ZOTERO_PAGE_PREFIX)
        else page_path
    )
    meta = _parse_chunk_header(content)
    snippet = content if len(content) <= SNIPPET_CHARS else content[:SNIPPET_CHARS] + "…"
    return {
        "key": key,
        "score": round(float(score), 4),
        "title": meta["title"],
        "authors": meta["authors"],
        "year": meta["year"],
        "item_type": meta["item_type"],
        "snippet": snippet,
    }


async def embed_query(
    text: str, config: EmbeddingConfig, dim: int
) -> Optional[List[float]]:
    """把查询文本嵌入成单条向量；失败返回 None。"""
    try:
        request = build_embed_request(config, [text])
        body = await embed_http_post(request.url, request.headers, request.body)
        vectors = parse_embed_response(body, expected_dim=dim)
    except Exception as exc:
        logger.warning("zotero query embed failed: %s", exc)
        return None
    if not vectors:
        return None
    return vectors[0]


async def _prepare_query(text: str) -> Optional[Tuple[Path, int, List[float]]]:
    """准备查询向量：``(存储路径, 维度, 向量)``；任一环节不可用返回 None。"""
    path = storage_path()
    dim = read_stored_dim(path)
    if dim is None:
        return None
    config = embed_config()
    if config is None:
        return None
    query_vec = await embed_query(text, config, dim)
    if query_vec is None:
        return None
    return path, dim, query_vec


def _search_store(path: Path, dim: int, query_vec: List[float], limit: int):
    """打开向量库并检索；任何存储/维度问题返回 None（视为 RAG 不可用）。"""
    try:
        store = VectorStore.open_at(path, dim)
        return store.search(query_vec, limit=limit)
    except (OSError, ValueError) as exc:
        logger.warning("zotero vector search failed: %s", exc)
        return None


async def semantic_search(
    query: str,
    limit: int = 20,
    client: Optional[Any] = None,
) -> Optional[List[Dict[str, Any]]]:
    """向量检索 Zotero 文献库。

    Returns:
        ``None`` — RAG 不可用，调用方应退回 SQL LIKE；
        ``[]``   — RAG 可用但无命中；
        ``[{key, score, title, authors, year, item_type, snippet}, ...]``
    """
    text = (query or "").strip()
    if not text:
        return []

    prepared = await _prepare_query(text)
    if prepared is None:
        return None
    path, dim, query_vec = prepared

    hits = _search_store(path, dim, query_vec, limit)
    if hits is None:
        return None

    return [
        _summarize_hit(hit.page_path, hit.content, hit.score)
        for hit in hits
        if hit.page_path.startswith(ZOTERO_PAGE_PREFIX)
    ]


def stored_summary() -> Tuple[Optional[int], int]:
    """返回 (向量库维度, 记录数)；库不存在时 ``(None, 0)``。"""
    path = storage_path()
    dim = read_stored_dim(path)
    if dim is None:
        return None, 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return dim, len(data.get("records", []))
    except (OSError, ValueError):
        return dim, 0


# ---------------------------------------------------------------------------
# wiki 侧的相关文献（M4 沉淀层的读侧）
# ---------------------------------------------------------------------------

_WIKI_SOURCE_PREFIX = "zotero:"


def _wiki_source_keys(doc: Any) -> List[str]:
    """从页面 frontmatter ``sources`` 里抽 Zotero item key。"""
    keys: List[str] = []
    for entry in doc.frontmatter.sources or []:
        text = str(entry).strip()
        if text.startswith(_WIKI_SOURCE_PREFIX):
            key = text[len(_WIKI_SOURCE_PREFIX) :].strip()
            if key:
                keys.append(key)
    return keys


def wiki_related_keys(project_root: Optional[str], item_key: str) -> List[str]:
    """从 wiki 页面推导与 ``item_key`` 相关的其它文献 key。

    规则（对应方案 §3.6 的第 2 步）：

    1. **共引**：任何 ``sources`` 里含有 ``zotero:<item_key>`` 的页面，它引用的
       其它 ``zotero:*`` 条目也是相关文献（同一作者页 / 同一主题页）。
    2. **一跳**：该页面 ``related`` wikilink 指向的页面，其 ``sources`` 里的
       文献同样纳入（文献页 → 作者页 → 该作者的其它文献）。

    只读、尽力而为：目录不存在或任一文件解析失败都返回空/跳过，绝不抛异常。
    """
    if not project_root:
        return []
    wiki_root = Path(project_root) / "wiki"
    if not wiki_root.is_dir():
        return []

    from backend.wiki.frontmatter import parse

    pages: List[Tuple[str, Any, List[str]]] = []
    try:
        candidates = sorted(wiki_root.rglob("*.md"))
    except OSError:
        return []

    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            doc = parse(text)
        except Exception:  # pragma: no cover - 畸形 frontmatter 不应中断检索
            continue
        pages.append((path.stem, doc, _wiki_source_keys(doc)))

    # 别名 → 页面索引（wikilink 解析：label 精确匹配 → 文件名 stem）
    by_alias: Dict[str, int] = {}
    for index, (stem, doc, _keys) in enumerate(pages):
        by_alias.setdefault(stem, index)
        title = (doc.frontmatter.title or "").strip()
        if title:
            by_alias.setdefault(title, index)

    related: List[str] = []
    seen = {item_key}
    for _stem, doc, keys in pages:
        if item_key not in keys:
            continue
        candidates_keys = list(keys)
        for link in doc.frontmatter.related or []:
            target = by_alias.get(str(link).strip())
            if target is not None:
                candidates_keys.extend(pages[target][2])
        for key in candidates_keys:
            if key not in seen:
                seen.add(key)
                related.append(key)
    return related

