"""Wiki stub routes (Task 4): 5 endpoints for wiki ingest/search/insights.

Routes registered here:

- POST   /api/v1/wiki/ingest          — accept text, return {doc_id, chunks}
- POST   /api/v1/wiki/extract         — accept text, return {title, body, links}
- POST   /api/v1/wiki/search          — accept query, return {items, total}
- GET    /api/v1/wiki/insights/{iid}  — return {summary, tags}
- POST   /api/v1/wiki/deep-research   — return {steps, status}

Contract:
    register_wiki_routes(registry: dict) -> None

    ``registry`` is the shared route dict keyed by ``(method, path_regex)``
    tuples, values are callables with signature
    ``fn(ctx: StubContext, body: dict, **path_groups) -> None``.
"""
from __future__ import annotations

import hashlib
import time
import uuid

from .common import send_json


def register_wiki_routes(registry: dict) -> None:
    registry[("POST", r"^/api/v1/wiki/ingest$")] = _ingest
    registry[("POST", r"^/api/v1/wiki/extract$")] = _extract
    registry[("POST", r"^/api/v1/wiki/search$")] = _search
    registry[("GET", r"^/api/v1/wiki/insights/(?P<iid>[^/]+)$")] = _insights
    registry[("POST", r"^/api/v1/wiki/deep-research$")] = _deep_research


def _ensure_table(ctx):
    ctx.db.executescript(
        """
        CREATE TABLE IF NOT EXISTS wiki_docs(
            doc_id TEXT PRIMARY KEY, title TEXT, body TEXT,
            tags TEXT, created_at INTEGER);
    """
    )


def _score(query: str, doc_id: str) -> float:
    """Deterministic score: md5(q+d) / 2**32, range [0,1)."""
    h = hashlib.md5((query + doc_id).encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def _ingest(ctx, body, **_):
    _ensure_table(ctx)
    doc_id = "doc_" + uuid.uuid4().hex[:8]
    title = body.get("title", "")
    content = body.get("content", "")
    chunks = max(1, len(content) // 500)
    ctx.db.execute(
        "INSERT INTO wiki_docs VALUES (?,?,?,?,?)",
        (doc_id, title, content, "", int(time.time() * 1000)),
    )
    ctx.db.commit()
    send_json(ctx, 200, {"doc_id": doc_id, "chunks": chunks})


def _extract(ctx, body, **_):
    content = body.get("content", "")
    title = content.split(".")[0][:80] if content else "untitled"
    body_text = content[:1000]
    links = []
    send_json(ctx, 200, {"title": title, "body": body_text, "links": links})


def _search(ctx, body, **_):
    _ensure_table(ctx)
    q = body.get("query", "")
    limit = int(body.get("limit", 5))
    docs = ctx.db.execute("SELECT doc_id, title FROM wiki_docs").fetchall()
    items = sorted(
        [{"doc_id": d[0], "title": d[1], "score": _score(q, d[0])} for d in docs],
        key=lambda x: -x["score"],
    )[:limit]
    send_json(ctx, 200, {"items": items, "total": len(items)})


def _insights(ctx, body, iid, **_):
    send_json(
        ctx,
        200,
        {
            "doc_id": iid,
            "summary": "Auto-generated summary for {}".format(iid),
            "tags": ["stub", "fixture"],
        },
    )


def _deep_research(ctx, body, **_):
    topic = body.get("topic", "")
    send_json(
        ctx,
        200,
        {
            "steps": [
                {"step": 1, "action": "search", "query": topic},
                {"step": 2, "action": "synthesize", "sources": 3},
                {"step": 3, "action": "draft"},
            ],
            "status": "pending",
        },
    )
