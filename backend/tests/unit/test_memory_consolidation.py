"""验证 ConsolidationPipeline 的摘要与压缩流程。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from backend.data.database import Database
from backend.memory.consolidation import ConsolidationPipeline
from backend.memory.episodic import EpisodicMemory
from backend.memory.manager import MemoryManager
from backend.memory.semantic import SemanticMemory
from backend.memory.summary import (
    FAILED,
    SessionSummaryStore,
    list_summaries_for_session,
)
from backend.memory.working import WorkingMemory
from backend.tests.conftest import ensure_session

pytestmark = pytest.mark.unit


class _FakeLLM:
    """最小 LLMClient stub。"""

    def __init__(self, response: Optional[str] = "summary text") -> None:
        self._response = response
        self.calls: List[str] = []

    def complete(self, prompt: str) -> str | None:
        self.calls.append(prompt)
        return self._response


class _ErrorLLM:
    def complete(self, prompt: str) -> str:
        raise RuntimeError("boom")


@pytest.fixture()
def manager(tmp_db_path: str) -> MemoryManager:
    db = Database(db_path=tmp_db_path)
    db.init_db()
    return MemoryManager(
        working=WorkingMemory(max_size=10, max_tokens=2000),
        episodic=EpisodicMemory(db),
        semantic=SemanticMemory(db),
    )


def test_init_no_llm() -> None:
    pipe = ConsolidationPipeline()
    assert pipe.llm_client is None


def test_compress_empty_returns_none() -> None:
    pipe = ConsolidationPipeline()
    assert pipe.compress_working_memory([]) is None


def test_compress_with_llm_uses_llm_response() -> None:
    llm = _FakeLLM(response="LLM 摘要")
    pipe = ConsolidationPipeline(llm_client=llm)
    summary = pipe.compress_working_memory(
        [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "ok"}]
    )
    assert summary == "LLM 摘要"
    assert len(llm.calls) == 1


def test_compress_llm_returns_empty_returns_none() -> None:
    """LLM 已配置但返回空内容 → 走 FAILED 分支,绝不 fallback 伪装成 READY。

    spec §4.3 step 4:LLM 摘要失败/空响应向 consolidate() 传播,
    由调用方写 status=FAILED 行,不掩盖失败。
    """
    llm = _FakeLLM(response="   ")
    pipe = ConsolidationPipeline(llm_client=llm)
    msgs: List[Dict[str, Any]] = [{"role": "user", "content": "hi"}]
    summary = pipe.compress_working_memory(msgs)
    assert summary is None


def test_compress_llm_exception_returns_none() -> None:
    """LLM 异常 → 走 FAILED 分支,绝不 fallback。"""
    pipe = ConsolidationPipeline(llm_client=_ErrorLLM())
    msgs: List[Dict[str, Any]] = [
        {"role": "user", "content": "talk about cats"},
        {"role": "assistant", "content": "ok"},
    ]
    summary = pipe.compress_working_memory(msgs)
    assert summary is None


def test_compress_no_llm_uses_fallback() -> None:
    pipe = ConsolidationPipeline()
    msgs: List[Dict[str, Any]] = [
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "answer"},
    ]
    summary = pipe.compress_working_memory(msgs)
    assert summary is not None
    assert "first question" in summary


def test_fallback_summary_without_user_messages() -> None:
    pipe = ConsolidationPipeline()
    msgs: List[Dict[str, Any]] = [
        {"role": "assistant", "content": "only assistant"},
    ]
    summary = pipe._fallback_summary(msgs)
    assert "1" in summary


def test_save_compressed_persists_summary(manager: MemoryManager) -> None:
    """save_compressed 调用 episodic.save(summary=...)。EpisodicMemory.save 现在接受
    该 kwarg（F2 修复）— 摘要被持久化到 summary 列，而不是抛 TypeError。"""
    pipe = ConsolidationPipeline()
    # §1.3a: FK enforcement — parent session row must exist.
    ensure_session(manager.episodic.db, "s1")
    memory_id = pipe.save_compressed(
        episodic_memory=manager.episodic,
        summary="my summary",
        session_id="s1",
        importance=6,
        message_count=4,
    )
    assert memory_id
    found = manager.episodic.get_by_id(memory_id)
    assert found is not None
    assert found["summary"] == "my summary"
    assert found["session_id"] == "s1"
    assert found["importance"] == 6


def test_consolidate_full_flow_succeeds(manager: MemoryManager) -> None:
    """consolidate 走通完整流程（F2 修复）：工作记忆压缩为摘要存入情景记忆并返回
    memory_id，而不是抛 TypeError。"""
    pipe = ConsolidationPipeline()
    # §1.3a: FK enforcement — parent session must exist.
    ensure_session(manager.episodic.db, "abc")
    manager.add_to_working("user", "hi")
    manager.add_to_working("assistant", "hello")
    memory_id = pipe.consolidate(manager, session_id="abc")
    assert memory_id
    assert len(manager.working.messages) == 0
    recent = manager.episodic.get_recent(limit=5)
    assert any(r["id"] == memory_id for r in recent)


def test_consolidate_empty_returns_none(manager: MemoryManager) -> None:
    pipe = ConsolidationPipeline()
    assert pipe.consolidate(manager) is None


def test_consolidate_summary_failure_returns_none(manager: MemoryManager) -> None:
    """compress 返回 None 时整流程返回 None。"""
    pipe = ConsolidationPipeline()
    manager.add_to_working("user", "msg")
    pipe.compress_working_memory = lambda messages: None
    assert pipe.consolidate(manager) is None


def test_consolidate_with_llm_failure_writes_failed_summary_not_ready(
    manager: MemoryManager,
) -> None:
    """LLM 配置但摘要失败时 consolidate 写 status=FAILED,不伪装为 READY。

    spec §4.3 step 4:不伪装为普通事实。FAILED 行必须带
    error_message,前端可据此区分"等待 LLM"与"已失败重试"。
    """
    # §1.3a: FK enforcement — parent session row must exist
    ensure_session(manager.episodic.db, "abc")
    store = SessionSummaryStore(manager.episodic.db)
    pipe = ConsolidationPipeline(llm_client=_ErrorLLM(), summary_store=store)
    manager.add_to_working("user", "hi", session_id="abc")
    manager.add_to_working("assistant", "hello", session_id="abc")

    memory_id = pipe.consolidate(manager, session_id="abc")

    assert memory_id is None
    rows = list_summaries_for_session(manager.episodic.db, "abc")
    assert len(rows) == 1
    row = rows[0]
    assert row.status == FAILED
    assert row.content == ""
    assert row.error_message  # 必须有诊断信息
    # 同时,工作记忆应保留（失败时不消费原文）
    assert len(manager.working.get_context("abc")) == 2


def test_sage_agent_wires_summary_store_to_consolidation(
    tmp_db_path: str,
    monkeypatch,
) -> None:
    """SageAgent 注入 summary_store 到 ConsolidationPipeline（防回归）。

    spec §4.3 step 4 + reviewer HIGH-2:legacy SageAgent 之前
    创建 ConsolidationPipeline 时不传 summary_store,导致 consolidate
    失败时不会写 FAILED 行。本测试保护接线关系。
    """
    import sys

    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[3]))
    # SageAgent 内部通过 get_database() 拿 db,把它 patch 成我们的 tmp db
    from backend.core.legacy import agent as agent_module

    db = Database(db_path=tmp_db_path)
    db.init_db()
    monkeypatch.setattr(agent_module, "get_database", lambda: db)

    agent = agent_module.SageAgent()
    assert agent.memory_manager is not None
    assert agent.memory_manager.summary_store is not None, (
        "SageAgent.memory_manager 必须暴露 summary_store(spec §4.3 step 3)"
    )
    assert agent.consolidation is not None
    assert agent.consolidation.summary_store is agent.memory_manager.summary_store, (
        "SageAgent.consolidation 必须共享 memory_manager.summary_store,"
        "否则 consolidate() 失败时不会写 FAILED 行"
    )


def test_extract_key_facts_preferences() -> None:
    pipe = ConsolidationPipeline()
    facts = pipe.extract_key_facts(
        [
            {"role": "user", "content": "我喜欢吃米饭"},
            {"role": "user", "content": "请记得我的生日"},
            {"role": "user", "content": "今天天气好"},
        ]
    )
    assert len(facts) >= 2
    assert all(f["type"] == "preference" for f in facts)


def test_extract_key_facts_empty() -> None:
    pipe = ConsolidationPipeline()
    assert pipe.extract_key_facts([]) == []
