"""RED tests for batches 3 step 6 — 3-tier memory API surface.

Spec §4.3 step 6 (line 150):

    API 增加按 session 查询摘要和三层记忆列表的明确字段；修复
    ``type=None`` 只返回 episodic、page 未转 offset 的问题。前端
    Memory 页面显示 summary/working/core 来源，并保留来源 session
    跳转。

Contract under test (lives on the FastAPI surface):

1. ``GET /memory/list`` with ``type=None`` (or ``'all'`` / ``''``) MUST
   return items from **all four** layers — working, session_summary,
   episodic, semantic — not just episodic + semantic as it does today.
2. ``GET /memory/list`` MUST accept an ``offset`` query parameter so
   callers that already maintain an offset cursor don't have to throw
   it away when switching to the envelope contract.
3. ``GET /memory/list`` MUST accept a ``session_id`` query parameter
   so a view scoped to one session can be retrieved without a
   client-side filter.
4. ``GET /memory/list`` MUST echo the new ``source_breakdown`` keys
   ``working`` and ``session_summary`` (today only ``episodic`` and
   ``semantic`` exist).
5. ``GET /memory/summaries?session_id=<sid>`` MUST return an envelope
   with the READY/PENDING/FAILED summary rows for that session —
   newest first — and MUST 400 when ``session_id`` is missing (the
   cross-session leak guard from step 5 forbids "all sessions" reads).
"""

from __future__ import annotations

import pytest

from backend.tests.conftest import ensure_session

pytestmark = pytest.mark.integration

PREFIX = "/api/v1"


# ──────────────────────────────────────────────────────────────────────
# /memory/list — type=None now returns 3-tier (working + summary + episodic + semantic)
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio()
async def test_memory_list_all_layers_includes_working_and_summary(
    client,
    setup_test_db,
):
    """``type=None`` (``'all'`` / ``''``) MUST include the new layers
    — working and session_summary — in addition to episodic + semantic,
    provided ``session_id`` is given so we have a scope for the
    session-scoped rows (spec step 5 forbids "all sessions" reads).

    Today the endpoint only fetches episodic + semantic, so this
    fails (RED) until the fix lands.
    """
    from backend.memory.registry import get_memory_manager, reset_memory_manager

    reset_memory_manager()
    mm = get_memory_manager()
    ensure_session(setup_test_db, "s-api-1")
    mm.add_to_working("user", "live in-progress message", session_id="s-api-1")

    # 2. Seed a READY session summary for the same session
    mm.summary_store.create(
        session_id="s-api-1",
        content="session-summary-text",
        status="ready",
    )

    # 3. Seed one episodic and one semantic row
    mm.episodic.save(
        content="episodic fact",
        importance=5,
        session_id="s-api-1",
    )
    mm.semantic.save(
        content="semantic fact",
        session_id="s-api-1",
    )

    resp = await client.get(
        f"{PREFIX}/memory/list", params={"session_id": "s-api-1"}
    )
    assert resp.status_code == 200
    body = resp.json()

    sources = {item.get("source") for item in body["items"]}
    # All four sources should be present in a session-scoped list.
    assert "episodic" in sources
    assert "semantic" in sources
    assert "working" in sources
    assert "session_summary" in sources


@pytest.mark.asyncio()
async def test_memory_list_source_breakdown_has_working_and_session_summary(
    client,
    setup_test_db,
):
    """``source_breakdown`` MUST echo ``working`` and ``session_summary``
    counts so the UI can render layer badges without re-counting.
    """
    from backend.memory.registry import get_memory_manager, reset_memory_manager

    reset_memory_manager()
    mm = get_memory_manager()
    ensure_session(setup_test_db, "s-api-2")
    mm.add_to_working("user", "msg1", session_id="s-api-2")
    mm.add_to_working("user", "msg2", session_id="s-api-2")
    mm.summary_store.create(
        session_id="s-api-2", content="summary", status="ready"
    )
    mm.episodic.save(content="e", importance=5, session_id="s-api-2")
    mm.semantic.save(content="s", session_id="s-api-2")

    resp = await client.get(
        f"{PREFIX}/memory/list", params={"session_id": "s-api-2"}
    )
    body = resp.json()

    breakdown = body["source_breakdown"]
    # Existing keys remain.
    assert "episodic" in breakdown
    assert "semantic" in breakdown
    # New keys appear.
    assert "working" in breakdown
    assert "session_summary" in breakdown
    assert breakdown["working"] >= 2
    assert breakdown["session_summary"] >= 1


@pytest.mark.asyncio()
async def test_memory_list_omits_session_summary_without_session_id(
    client,
    setup_test_db,
):
    """Step 5 leak guard: when no ``session_id`` is supplied, the
    endpoint MUST NOT inject any session_summary rows (we don't know
    which session they belong to). Working + episodic + semantic still
    surface because they're not session-scoped.
    """
    from backend.memory.registry import get_memory_manager, reset_memory_manager

    reset_memory_manager()
    mm = get_memory_manager()
    ensure_session(setup_test_db, "orphan")
    # Note: we DO create the summary row, but the API call below does
    # NOT pass session_id, so the summary MUST stay invisible.
    mm.summary_store.create(
        session_id="orphan",
        content="never-visible",
        status="ready",
    )
    ensure_session(setup_test_db, "s-noscope")
    mm.episodic.save(content="e", importance=5, session_id="s-noscope")

    resp = await client.get(f"{PREFIX}/memory/list")
    body = resp.json()
    sources = {item.get("source") for item in body["items"]}
    assert "session_summary" not in sources
    assert breakdown_safe(body["source_breakdown"])["session_summary"] == 0


def breakdown_safe(b):
    return b if isinstance(b, dict) else {}


# ──────────────────────────────────────────────────────────────────────
# /memory/list — offset parameter
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio()
async def test_memory_list_accepts_offset(client, setup_test_db):
    """``offset`` query param MUST work as a sibling of ``page``.

    A caller holding a cursor (offset) shouldn't have to round-trip
    through page math when switching to the envelope contract.
    """
    from backend.memory.registry import get_memory_manager, reset_memory_manager

    reset_memory_manager()
    mm = get_memory_manager()
    for i in range(5):
        ensure_session(setup_test_db, f"s-{i}")
        mm.episodic.save(
            content=f"row-{i}", importance=5, session_id=f"s-{i}"
        )

    resp = await client.get(f"{PREFIX}/memory/list", params={"offset": 2, "page_size": 2})
    assert resp.status_code == 200
    body = resp.json()
    # Echoed in envelope.
    assert "offset" in body
    assert body["offset"] == 2
    # The slice at offset=2 size=2 should be a subset of the full list.
    assert len(body["items"]) == 2


# ──────────────────────────────────────────────────────────────────────
# /memory/list — session_id filter
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio()
async def test_memory_list_session_id_filter(client, setup_test_db):
    """``session_id`` query param MUST scope the result to that session.

    Without this, a view for one session would still see rows from
    other sessions — defeating the session-isolation invariant from
    step 5.
    """
    from backend.memory.registry import get_memory_manager, reset_memory_manager

    reset_memory_manager()
    mm = get_memory_manager()
    ensure_session(setup_test_db, "s-A")
    ensure_session(setup_test_db, "s-B")
    mm.episodic.save(content="s1 row", importance=5, session_id="s-A")
    mm.episodic.save(content="s2 row", importance=5, session_id="s-B")

    resp = await client.get(
        f"{PREFIX}/memory/list", params={"session_id": "s-A"}
    )
    assert resp.status_code == 200
    body = resp.json()
    contents = [item.get("content", "") for item in body["items"]]
    assert any("s1 row" in c for c in contents)
    assert not any("s2 row" in c for c in contents)


# ──────────────────────────────────────────────────────────────────────
# /memory/summaries — new endpoint
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio()
async def test_memory_summaries_missing_session_id_returns_400(
    client, setup_test_db
):
    """``session_id`` is REQUIRED. Listing "all sessions' summaries"
    would let one session leak into another's view (step 5 invariant).
    """
    resp = await client.get(f"{PREFIX}/memory/summaries")
    assert resp.status_code == 400


@pytest.mark.asyncio()
async def test_memory_summaries_returns_envelope_for_session(
    client, setup_test_db
):
    """The endpoint MUST return the standard envelope with summaries
    sorted newest first, including READY/FAILED/PENDING rows so the
    UI can show status badges.
    """
    from backend.memory.registry import get_memory_manager, reset_memory_manager

    reset_memory_manager()
    mm = get_memory_manager()
    ensure_session(setup_test_db, "s-sum")
    mm.summary_store.create(
        session_id="s-sum",
        content="ready summary",
        status="ready",
    )
    mm.summary_store.create(
        session_id="s-sum",
        content="",
        status="failed",
        error_message="boom",
    )

    resp = await client.get(
        f"{PREFIX}/memory/summaries", params={"session_id": "s-sum"}
    )
    assert resp.status_code == 200
    body = resp.json()

    assert body["session_id"] == "s-sum"
    assert body["total"] >= 2
    assert "items" in body
    statuses = {item["status"] for item in body["items"]}
    assert "ready" in statuses
    assert "failed" in statuses


@pytest.mark.asyncio()
async def test_memory_summaries_only_returns_target_session(
    client, setup_test_db
):
    """Step 5 leak guard: s-A MUST NOT see s-B summaries.
    """
    from backend.memory.registry import get_memory_manager, reset_memory_manager

    reset_memory_manager()
    mm = get_memory_manager()
    ensure_session(setup_test_db, "s-A")
    ensure_session(setup_test_db, "s-B")
    mm.summary_store.create(
        session_id="s-A", content="A only", status="ready"
    )
    mm.summary_store.create(
        session_id="s-B", content="B only", status="ready"
    )

    resp = await client.get(
        f"{PREFIX}/memory/summaries", params={"session_id": "s-A"}
    )
    body = resp.json()
    sids = {item["session_id"] for item in body["items"]}
    assert sids == {"s-A"}
    contents = [item["content"] for item in body["items"]]
    assert "A only" in contents
    assert "B only" not in contents


@pytest.mark.asyncio()
async def test_memory_summaries_pagination(client, setup_test_db):
    """The envelope MUST respect ``page`` / ``page_size`` and echo them.
    """
    from backend.memory.registry import get_memory_manager, reset_memory_manager

    reset_memory_manager()
    mm = get_memory_manager()
    ensure_session(setup_test_db, "s-pag")
    for i in range(7):
        mm.summary_store.create(
            session_id="s-pag",
            content=f"summary {i}",
            status="ready",
        )

    resp = await client.get(
        f"{PREFIX}/memory/summaries",
        params={"session_id": "s-pag", "page": 1, "page_size": 3},
    )
    body = resp.json()
    assert body["total"] == 7
    assert body["page"] == 1
    assert body["page_size"] == 3
    assert len(body["items"]) == 3
