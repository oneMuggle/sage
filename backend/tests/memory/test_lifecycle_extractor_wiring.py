"""Important-3 (final review): the lifecycle-path extractor must be
LLM-backed, not keyword-only.

``backend/main.py`` previously constructed ``MemoryLifecycleManager``
WITHOUT ``extractor=``, so ``on_turn_complete`` silently fell back to the
keyword-only ``MemoryExtractor(llm_client=None)`` heuristic (weak: only
preference keywords, ≤3 facts, requires >20/50 chars). The legacy
``_extract_and_store_memory`` uses the LLM extractor; the lifecycle path
must match that production quality.

These tests prove:
  1. ``on_turn_complete`` calls the INJECTED extractor (mock extractor
     asserted) — the wiring contract,
  2. a real ``MemoryExtractor`` with a mock LLM produces LLM-backed facts
     (the facts come from the LLM's JSON reply, not the keyword heuristic),
  3. ``backend.main``'s wiring helper builds a ``MemoryExtractor`` with a
     real LLM adapter (so the production lifespan passes an LLM client).
"""

from __future__ import annotations

import pytest

from backend.memory.lifecycle import MemoryLifecycleManager

pytestmark = pytest.mark.unit


class _TruePrefs:
    async def get(self, key):  # noqa: ARG002 — fixture
        return "true"


def _real_memory_manager(tmp_db_path: str):
    from backend.data.database import Database
    from backend.memory.episodic import EpisodicMemory
    from backend.memory.manager import MemoryManager
    from backend.memory.semantic import SemanticMemory
    from backend.memory.working import WorkingMemory

    db = Database(db_path=tmp_db_path)
    db.init_db()
    return MemoryManager(
        working=WorkingMemory(max_size=10, max_tokens=2000),
        episodic=EpisodicMemory(db),
        semantic=SemanticMemory(db),
    )


@pytest.mark.asyncio()
async def test_on_turn_complete_uses_injected_extractor(tmp_db_path):
    """The lifecycle must call the extractor injected by the caller, not a
    hidden keyword-only default. Mock the extractor and assert it's called."""
    from unittest.mock import AsyncMock, Mock

    from backend.memory.hooks import HookRegistry

    manager = _real_memory_manager(tmp_db_path)
    hooks = HookRegistry()
    written: list = []
    hooks.on("memory_written", lambda e: written.append(e))

    extractor = Mock()
    extractor.extract = AsyncMock(
        return_value=[
            {
                "content": "用户喜欢打羽毛球",
                "importance": 7,
                "category": "user_pref",
                "tags": ["sport"],
            }
        ]
    )

    mgr = MemoryLifecycleManager(
        memory_manager=manager,
        hooks=hooks,
        preferences_repo=_TruePrefs(),
        extractor=extractor,
    )
    mgr.set_current_turn("turn-9")
    await mgr.on_turn_complete(
        "session-9",
        [
            {"role": "user", "content": "我喜欢打羽毛球，每周都去俱乐部练两次"},
            {"role": "assistant", "content": "好的，记下了"},
        ],
    )

    # 1) the injected extractor was used
    extractor.extract.assert_awaited_once()

    # 2) its fact was persisted + emitted (the injected extractor's output
    #    drives the pipeline — NOT a keyword default)
    assert len(written) == 1
    assert written[0].content == "用户喜欢打羽毛球"
    rows = manager.episodic.get_recent(limit=10, session_id="session-9")
    assert len(rows) == 1
    assert rows[0]["content"] == "用户喜欢打羽毛球"


@pytest.mark.asyncio()
async def test_real_extractor_with_mock_llm_produces_llm_backed_facts(tmp_db_path):
    """A real MemoryExtractor wired to an LLM client must return the LLM's
    JSON facts — not the keyword heuristic (which cannot produce this
    content because the message contains no preference keyword)."""
    from backend.memory.extractor import MemoryExtractor
    from backend.memory.hooks import HookRegistry

    llm = type(
        "FakeLLM",
        (),
        {
            "chat": _async_chat(
                '[{"content": "用户的项目正在从 Electron 迁移到 Tauri", '
                '"importance": 6, "category": "project_fact", "tags": ["stack"]}]'
            )
        },
    )()

    manager = _real_memory_manager(tmp_db_path)
    hooks = HookRegistry()
    written: list = []
    hooks.on("memory_written", lambda e: written.append(e))

    mgr = MemoryLifecycleManager(
        memory_manager=manager,
        hooks=hooks,
        preferences_repo=_TruePrefs(),
        extractor=MemoryExtractor(llm_client=llm),
    )
    # No preference keyword in the user message → the keyword heuristic would
    # return [] (≤3 keyword facts, only preference keywords); only the LLM
    # path can produce this fact.
    await mgr.on_turn_complete(
        "session-10",
        [
            {
                "role": "user",
                "content": "我们最近决定把桌面应用从 Electron 迁移到 Tauri 框架",
            },
            {"role": "assistant", "content": "迁移确实能大幅减小安装包体积"},
        ],
    )

    assert len(written) == 1, "expected the LLM-backed fact to be emitted"
    assert "Tauri" in written[0].content
    assert written[0].memory_category == "project_fact"


def _async_chat(payload: str):
    """Build an async ``chat`` bound method returning a Message-like object."""

    async def _chat(self, messages, **kwargs):  # noqa: ARG001
        class _Resp:
            content = payload

        return _Resp()

    return _chat


def test_main_wiring_helper_builds_llm_backed_extractor():
    """backend.main's extractor factory must return a MemoryExtractor whose
    llm_client is a real HttpxLLMAdapter (not the keyword-only default)."""
    from backend.main import _build_lifecycle_extractor

    extractor = _build_lifecycle_extractor()
    assert extractor is not None
    assert extractor._llm is not None, "extractor must carry an LLM client"
