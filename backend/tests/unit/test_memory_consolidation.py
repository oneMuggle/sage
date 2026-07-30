"""验证 ConsolidationPipeline 的摘要与压缩流程。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from backend.data.database import Database
from backend.memory.consolidation import ConsolidationPipeline
from backend.memory.episodic import EpisodicMemory
from backend.memory.manager import MemoryManager
from backend.memory.semantic import SemanticMemory
from backend.memory.working import WorkingMemory

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


def test_compress_llm_returns_empty_falls_back() -> None:
    llm = _FakeLLM(response="   ")
    pipe = ConsolidationPipeline(llm_client=llm)
    msgs: List[Dict[str, Any]] = [{"role": "user", "content": "hi"}]
    summary = pipe.compress_working_memory(msgs)
    assert summary is not None
    assert "条消息" in summary or "对话围绕" in summary


def test_compress_llm_exception_falls_back() -> None:
    pipe = ConsolidationPipeline(llm_client=_ErrorLLM())
    msgs: List[Dict[str, Any]] = [
        {"role": "user", "content": "talk about cats"},
        {"role": "assistant", "content": "ok"},
    ]
    summary = pipe.compress_working_memory(msgs)
    assert summary is not None


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
    """save_compressed 应按 EpisodicMemory 契约保存摘要及会话关联。"""
    pipe = ConsolidationPipeline()

    memory_id = pipe.save_compressed(
        episodic_memory=manager.episodic,
        summary="my summary",
        session_id="s1",
        importance=6,
        message_count=4,
    )

    saved = manager.episodic.get_by_id(memory_id)
    assert saved is not None
    assert saved["content"] == "对话摘要: my summary"
    assert saved["summary"] == "对话摘要: my summary"
    assert saved["session_id"] == "s1"
    assert saved["memory_type"] == "summary"


def test_consolidate_full_flow_persists_and_clears_session(
    manager: MemoryManager,
) -> None:
    """consolidate 成功落库后只清空被压缩的 session。"""
    pipe = ConsolidationPipeline()
    manager.add_to_working("user", "hi", session_id="abc")
    manager.add_to_working("assistant", "hello", session_id="abc")
    manager.add_to_working("user", "keep me", session_id="other")

    memory_id = pipe.consolidate(manager, session_id="abc")

    assert memory_id is not None
    assert manager.working.get_context("abc") == []
    assert [item["content"] for item in manager.working.get_context("other")] == [
        "keep me"
    ]
    saved = manager.episodic.get_by_id(memory_id)
    assert saved is not None
    assert saved["session_id"] == "abc"
    assert saved["memory_type"] == "summary"


def test_consolidate_empty_returns_none(manager: MemoryManager) -> None:
    pipe = ConsolidationPipeline()
    assert pipe.consolidate(manager) is None


def test_consolidate_summary_failure_returns_none(manager: MemoryManager) -> None:
    """compress 返回 None 时整流程返回 None。"""
    pipe = ConsolidationPipeline()
    manager.add_to_working("user", "msg")
    pipe.compress_working_memory = lambda messages: None
    assert pipe.consolidate(manager) is None


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
