"""Phase 2 集成测试：记忆质量改造的端到端链路。

单点单测各自覆盖了提取门槛、已知事实注入、偏好学习、语义消解，
但没有验证它们在**真实写入链**上组合后的效果。本文件驱动
``MemoryLifecycleManager.on_turn_complete`` → 真实 ``MemoryManager``
→ SQLite，断言用户可见的结果：

1. 语义改述事实跨轮次塌缩成一条（碎片化收敛）；
2. 语义近但取值相反的事实判 UPDATE，最新事实生效（绝不被 NOOP 丢弃）；
3. 缺省 HashEmbedder 下行为与改造前一致（两条并存，opt-in 语义路径）；
4. 嵌入器故障时写入不中断；
5. Task 2.2 的已知事实确实被注入提取器。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from backend.data.database import Database
from backend.memory.embedder import HashEmbedder
from backend.memory.episodic import EpisodicMemory
from backend.memory.lifecycle import MemoryLifecycleManager
from backend.memory.manager import MemoryManager
from backend.memory.semantic import SemanticMemory
from backend.memory.working import WorkingMemory
from backend.tests.conftest import ensure_session

pytestmark = pytest.mark.integration

SESSION = "s1"

#: 字面相似度 0.50，语义等价 —— 单靠字面永远落在 ADD 区
PARAPHRASE_A = "用户喜欢简洁回答"
PARAPHRASE_B = "用户偏好简短回复"
#: 取值相反但句式几乎相同（字面约 0.60，语义余弦 1.0）
CITY_A = "用户住在上海市浦东区"
CITY_B = "用户住在北京市朝阳区"


class FakeSemanticEmbedder:
    """确定性玩具语义嵌入器：关键词命中给对应向量，未命中给零向量。"""

    is_semantic = True
    dimensions = 4

    def __init__(self, table: Optional[Dict[str, List[float]]] = None) -> None:
        self._table = table or {}

    def encode(self, text: str) -> List[float]:
        for key, vec in self._table.items():
            if key in text:
                return list(vec)
        return [0.0] * self.dimensions

    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        return [self.encode(t) for t in texts]


class BrokenEmbedder(FakeSemanticEmbedder):
    """编码必炸 —— 验证写入链路降级而不是抛错。"""

    def encode(self, text: str) -> List[float]:
        raise RuntimeError("embedder boom")

    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        raise RuntimeError("embedder boom")


class ScriptedExtractor:
    """每轮返回预置事实，并记录收到的 ``existing_facts``。"""

    def __init__(self) -> None:
        self.next_facts: List[Dict[str, Any]] = []
        self.existing_facts_seen: List[Optional[List[str]]] = []

    async def extract(
        self,
        user_message: str,
        assistant_message: str,
        existing_facts: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        self.existing_facts_seen.append(existing_facts)
        return list(self.next_facts)


class RecordingHooks:
    def __init__(self) -> None:
        self.events: List[tuple] = []

    async def emit(self, name: str, payload: Any) -> None:
        self.events.append((name, payload))

    def written_ids(self) -> List[str]:
        return [p.memory_id for n, p in self.events if n == "memory_written"]


class _TruePrefs:
    async def get(self, key: str) -> Optional[str]:
        return "true"


@pytest.fixture()
def db(tmp_db_path: str) -> Database:
    d = Database(db_path=tmp_db_path)
    d.init_db()
    ensure_session(d, SESSION)
    return d


def _manager(db: Database, embedder: Any = None) -> MemoryManager:
    return MemoryManager(
        working=WorkingMemory(db=db),
        episodic=EpisodicMemory(db),
        semantic=SemanticMemory(db),
        embedder=embedder,
    )


def _lifecycle(manager: MemoryManager, extractor: ScriptedExtractor, hooks: RecordingHooks):
    return MemoryLifecycleManager(
        memory_manager=manager,
        hooks=hooks,
        preferences_repo=_TruePrefs(),
        extractor=extractor,
    )


async def _run_turn(
    lifecycle: MemoryLifecycleManager,
    extractor: ScriptedExtractor,
    content: str,
    importance: int = 6,
) -> None:
    extractor.next_facts = [
        {"content": content, "category": "user_preference", "importance": importance}
    ]
    await lifecycle.on_turn_complete(
        SESSION,
        [
            {"role": "user", "content": content},
            {"role": "assistant", "content": "好的，我记下了"},
        ],
    )


def _active_contents(db: Database) -> List[str]:
    return [row["content"] for row in EpisodicMemory(db).get_recent(session_id=SESSION)]


def test_fixture_pairs_are_literal_misses() -> None:
    """前提：两对测试事实的字面相似度都不足以触发字面 UPDATE。"""
    from backend.memory.conflict import _similarity

    assert _similarity(PARAPHRASE_A, PARAPHRASE_B) < 0.78
    assert _similarity(CITY_A, CITY_B) < 0.78


@pytest.mark.asyncio()
async def test_semantic_paraphrase_collapses_across_turns(db: Database) -> None:
    """两轮学到同一偏好的不同措辞 → 只剩一条有效记忆。"""
    embedder = FakeSemanticEmbedder(
        {"简洁回答": [1.0, 0.0, 0.0, 0.0], "简短回复": [1.0, 0.0, 0.0, 0.0]}
    )
    manager = _manager(db, embedder=embedder)
    extractor, hooks = ScriptedExtractor(), RecordingHooks()
    lifecycle = _lifecycle(manager, extractor, hooks)

    await _run_turn(lifecycle, extractor, PARAPHRASE_A)
    await _run_turn(lifecycle, extractor, PARAPHRASE_B)

    assert manager.episodic.count(session_id=SESSION) == 1
    assert _active_contents(db) == [PARAPHRASE_B]  # 最新措辞生效

    old_id, new_id = hooks.written_ids()
    assert manager.episodic.get_by_id(old_id)["invalid_at"] is not None
    assert manager.episodic.get_by_id(new_id)["supersedes_id"] == old_id


@pytest.mark.asyncio()
async def test_contradictory_fact_updates_and_latest_wins(db: Database) -> None:
    """语义极高的相反事实必须 UPDATE（写新 + 旧失效），不能 NOOP 丢新事实。"""
    embedder = FakeSemanticEmbedder(
        {"上海市浦东区": [1.0, 0.0, 0.0, 0.0], "北京市朝阳区": [1.0, 0.0, 0.0, 0.0]}
    )
    manager = _manager(db, embedder=embedder)
    extractor, hooks = ScriptedExtractor(), RecordingHooks()
    lifecycle = _lifecycle(manager, extractor, hooks)

    await _run_turn(lifecycle, extractor, CITY_A)
    await _run_turn(lifecycle, extractor, CITY_B)

    assert manager.episodic.count(session_id=SESSION) == 1
    assert _active_contents(db) == [CITY_B]


@pytest.mark.asyncio()
async def test_default_hash_embedder_keeps_prior_behaviour(db: Database) -> None:
    """缺省嵌入器不开启语义路径 → 改述对仍各写一条（行为零变更）。"""
    manager = _manager(db, embedder=HashEmbedder())
    extractor, hooks = ScriptedExtractor(), RecordingHooks()
    lifecycle = _lifecycle(manager, extractor, hooks)

    await _run_turn(lifecycle, extractor, PARAPHRASE_A)
    await _run_turn(lifecycle, extractor, PARAPHRASE_B)

    assert manager.episodic.count(session_id=SESSION) == 2
    assert set(_active_contents(db)) == {PARAPHRASE_A, PARAPHRASE_B}


@pytest.mark.asyncio()
async def test_embedder_outage_still_persists_every_fact(db: Database) -> None:
    """嵌入器故障不得吞掉事实，也不得让 on_turn_complete 抛异常。"""
    manager = _manager(db, embedder=BrokenEmbedder())
    extractor, hooks = ScriptedExtractor(), RecordingHooks()
    lifecycle = _lifecycle(manager, extractor, hooks)

    await _run_turn(lifecycle, extractor, PARAPHRASE_A)
    await _run_turn(lifecycle, extractor, PARAPHRASE_B)

    assert manager.episodic.count(session_id=SESSION) == 2
    assert len(hooks.written_ids()) == 2


@pytest.mark.asyncio()
async def test_semantic_dedup_does_not_merge_unrelated_facts(db: Database) -> None:
    """语义路径只塌缩语义近邻，无关事实照常追加。"""
    embedder = FakeSemanticEmbedder(
        {"简洁回答": [1.0, 0.0, 0.0, 0.0], "简短回复": [1.0, 0.0, 0.0, 0.0]}
    )
    manager = _manager(db, embedder=embedder)
    extractor, hooks = ScriptedExtractor(), RecordingHooks()
    lifecycle = _lifecycle(manager, extractor, hooks)

    await _run_turn(lifecycle, extractor, PARAPHRASE_A)
    await _run_turn(lifecycle, extractor, "用户最近在尝试用 Rust 写分布式调度组件")

    assert manager.episodic.count(session_id=SESSION) == 2


@pytest.mark.asyncio()
async def test_known_facts_are_injected_into_extraction(db: Database) -> None:
    """Task 2.2：上一轮写入的事实应出现在下一轮提取的 existing_facts 中。"""
    manager = _manager(db)  # 缺省嵌入器即可，recall 走 FTS5
    extractor, hooks = ScriptedExtractor(), RecordingHooks()
    lifecycle = _lifecycle(manager, extractor, hooks)

    first = "用户喜欢使用 Python 做数据分析"
    await _run_turn(lifecycle, extractor, first)
    await _run_turn(lifecycle, extractor, "用户喜欢使用 Python 写后端服务")

    second_round_facts = extractor.existing_facts_seen[1]
    assert second_round_facts is not None
    assert any(first in fact for fact in second_round_facts)
