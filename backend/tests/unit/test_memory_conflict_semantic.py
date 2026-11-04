"""Task 2.4 —— 冲突消解的语义相似度判定。

背景：字面相似度（SequenceMatcher 字符级）对中文语义不敏感，
"用户喜欢简洁回答" vs "用户偏好简短回复" 只有 0.50，永远落在 ADD 区，
语义重复的记忆无法被合并。

本文件的约定：
- NOOP（丢弃新事实）只认字面近重复 —— 语义近但取值不同的两条记忆
  （如"用户住在上海" vs "用户住在北京"）必须让新事实取代旧事实，
  NOOP 会把过时事实留在库里；
- 语义近邻只触发 UPDATE（写新行 + 旧行失效）；
- 语义路径仅在语义嵌入器（``is_semantic=True``）可用时开启，
  缺省 HashEmbedder 下整条路径关闭，行为与改造前完全一致。
"""

from __future__ import annotations

import pytest

from backend.data.database import Database
from backend.memory.conflict import (
    NOOP_THRESHOLD,
    OP_ADD,
    OP_NOOP,
    OP_UPDATE,
    SEMANTIC_TARGET_MARGIN,
    SEMANTIC_UPDATE_THRESHOLD,
    UPDATE_THRESHOLD,
    MemoryConflictResolver,
    _cosine_similarity,
    _has_negation,
    _similarity,
)
from backend.memory.embedder import HashEmbedder
from backend.memory.episodic import EpisodicMemory
from backend.memory.manager import MemoryManager
from backend.memory.scope import SCOPE_USER
from backend.memory.semantic import SemanticMemory
from backend.memory.working import WorkingMemory
from backend.tests.conftest import ensure_session

pytestmark = pytest.mark.unit

#: 字面相似度 0.50（远低于 UPDATE 阈值 0.78），语义等价
OLD = "用户喜欢简洁回答"
NEW = "用户偏好简短回复"
#: 与 OLD 既不同词也不同义
OTHER = "用户最近在尝试使用 Rust 编写分布式调度组件"
#: 字面相似度 0.84 → UPDATE 带；字面近重复（+句号）→ NOOP 带
LITERAL_UPDATE = "用户喜欢非常简洁的回答"
LITERAL_NOOP = "用户在项目里约定所有 Python 代码使用 ruff 格式化并且强制要求类型注解"
LITERAL_NOOP_DUP = LITERAL_NOOP + "。"
#: 只插入一个"不"：字面 0.988（>= 0.97）但事实相反
NEGATED_NOOP = "用户在项目里约定所有 Python 代码不使用 ruff 格式化并且强制要求类型注解"

VEC_CONCISE = [1.0, 0.0, 0.0, 0.0]
#: 与 VEC_CONCISE 的余弦分别为 0.905 / 0.895 / 0.95（阈值 0.90 的两侧）
VEC_NEAR_ABOVE = [0.905, 0.42541, 0.0, 0.0]
VEC_NEAR_BELOW = [0.895, 0.44607, 0.0, 0.0]
VEC_RUST = [0.95, 0.31225, 0.0, 0.0]


class FakeSemanticEmbedder:
    """确定性玩具语义嵌入器：关键词命中即给对应向量，未命中给零向量。"""

    is_semantic = True
    dimensions = 4

    def __init__(self, table=None, fail: bool = False) -> None:
        self._table = table if table is not None else {}
        self._fail = fail
        self.calls: list = []

    def encode(self, text: str) -> list:
        if self._fail:
            raise RuntimeError("encode boom")
        self.calls.append(text)
        for key, vec in self._table.items():
            if key in text:
                return list(vec)
        return [0.0] * self.dimensions

    def encode_batch(self, texts) -> list:
        if self._fail:
            raise RuntimeError("encode boom")
        return [self.encode(t) for t in texts]


def _concise_embedder() -> FakeSemanticEmbedder:
    return FakeSemanticEmbedder(
        {
            "简洁回答": VEC_CONCISE,
            "简短回复": VEC_CONCISE,
            "简洁": VEC_CONCISE,
            "简短": VEC_CONCISE,
        }
    )


class _ShortBatchEmbedder(FakeSemanticEmbedder):
    """encode_batch 返回条数与输入不符 —— 标注必须整体放弃。"""

    def encode_batch(self, texts) -> list:
        return [list(VEC_CONCISE)]


@pytest.fixture()
def db(tmp_db_path: str) -> Database:
    d = Database(db_path=tmp_db_path)
    d.init_db()
    # memories_episodic.session_id 有 FK 约束, 先建好夹具会话
    ensure_session(d, "s1")
    return d


def _manager(db: Database, embedder=None) -> MemoryManager:
    return MemoryManager(
        working=WorkingMemory(db=db),
        episodic=EpisodicMemory(db),
        semantic=SemanticMemory(db),
        embedder=embedder,
    )


def _resolver(db: Database, embedder=None) -> MemoryConflictResolver:
    return MemoryConflictResolver(EpisodicMemory(db), SemanticMemory(db), embedder=embedder)


# ---------- 前置：字面相似度确实不够 ----------


def test_literal_similarity_is_too_low_for_paraphrase() -> None:
    """前提：改述对的字面相似度落在 ADD 区 —— 这正是要修的问题。"""
    assert _similarity(OLD, NEW) < UPDATE_THRESHOLD
    assert _similarity(OLD, OTHER) < UPDATE_THRESHOLD


def test_literal_fixture_bands() -> None:
    """前提：字面 UPDATE / NOOP 夹具对落在预期区间。"""
    assert UPDATE_THRESHOLD <= _similarity(OLD, LITERAL_UPDATE) < 0.97
    assert _similarity(LITERAL_NOOP, LITERAL_NOOP_DUP) >= 0.97


# ---------- 语义路径开关 ----------


def test_no_embedder_keeps_literal_only_behaviour(db: Database) -> None:
    """缺省（无嵌入器）→ 语义路径关闭，改述对仍是 ADD（行为不变）。"""
    manager = _manager(db)
    manager.memorize(OLD, memory_type="episodic", importance=6, session_id="s1")
    assert manager.get_conflict_resolver().resolve(NEW, session_id="s1").op == OP_ADD


def test_hash_embedder_does_not_enable_semantic_path(db: Database) -> None:
    """HashEmbedder 不是语义嵌入器（is_semantic=False）→ 语义路径不开启。"""
    manager = _manager(db, embedder=HashEmbedder())
    manager.memorize(OLD, memory_type="episodic", importance=6, session_id="s1")
    assert manager.get_conflict_resolver().resolve(NEW, session_id="s1").op == OP_ADD


def test_model_embedder_is_marked_semantic() -> None:
    """HTTP 嵌入端点也是语义嵌入器 —— 缺标记会让语义去重与向量检索一起失效。"""
    from backend.memory.embedder import ModelEmbedder

    assert ModelEmbedder.is_semantic is True


# ---------- 语义近邻 → UPDATE ----------


def test_semantic_paraphrase_triggers_update(db: Database) -> None:
    """语义等价的改述 → UPDATE（取代旧行），而不是各写一条。"""
    manager = _manager(db, embedder=_concise_embedder())
    old_id = manager.memorize(OLD, memory_type="episodic", importance=6, session_id="s1")

    decision = manager.get_conflict_resolver().resolve(NEW, session_id="s1")
    assert decision.op == OP_UPDATE
    assert decision.superseded_ids == [old_id]


def test_semantic_paraphrase_never_triggers_noop(db: Database) -> None:
    """NOOP 会把新事实丢掉 —— 语义近但字面不同的情况绝不能判 NOOP。"""
    manager = _manager(db, embedder=_concise_embedder())
    manager.memorize(OLD, memory_type="episodic", importance=6, session_id="s1")
    decision = manager.get_conflict_resolver().resolve(NEW, session_id="s1")
    assert decision.op != OP_NOOP


def test_semantic_different_content_stays_add(db: Database) -> None:
    """语义上无关的内容仍走 ADD（零向量 → 余弦 0）。"""
    manager = _manager(db, embedder=_concise_embedder())
    manager.memorize(OLD, memory_type="episodic", importance=6, session_id="s1")
    assert manager.get_conflict_resolver().resolve(OTHER, session_id="s1").op == OP_ADD


def test_literal_near_duplicate_still_noop_with_semantic_embedder(db: Database) -> None:
    """字面近重复（≥0.97）仍判 NOOP —— NOOP 带优先于语义带。"""
    manager = _manager(db, embedder=_concise_embedder())
    manager.memorize(
        LITERAL_NOOP, memory_type="episodic", importance=6, session_id="s1"
    )
    decision = manager.get_conflict_resolver().resolve(LITERAL_NOOP_DUP, session_id="s1")
    assert decision.op == OP_NOOP


# ---------- 否定极性 ----------


def test_literal_negation_still_within_noop_band() -> None:
    """前提：只插入一个"不"的字面相似度仍 >= 0.97 —— 这正是要修的缺陷。"""
    assert _similarity(LITERAL_NOOP, NEGATED_NOOP) >= NOOP_THRESHOLD


def test_has_negation_markers() -> None:
    """中英文否定词识别。"""
    assert _has_negation("用户不喜欢冗长回答")
    assert _has_negation("I do not prefer long answers")
    assert _has_negation("The user doesn't like verbose replies")
    assert not _has_negation("用户喜欢简洁回答")


def test_flipped_negation_is_not_noop(db: Database) -> None:
    """字面近重复但否定极性相反 → UPDATE，不能 NOOP 丢新事实。"""
    manager = _manager(db)
    old_id = manager.memorize(
        LITERAL_NOOP, memory_type="episodic", importance=6, session_id="s1"
    )
    decision = manager.get_conflict_resolver().resolve(NEGATED_NOOP, session_id="s1")
    assert decision.op == OP_UPDATE
    assert decision.superseded_ids == [old_id]


def test_flipped_negation_write_path_swaps_rows(db: Database) -> None:
    """端到端：否定事实落库，旧行失效，检索只剩新事实。"""
    manager = _manager(db)
    id1, _ = manager.memorize_with_conflict_check(
        LITERAL_NOOP, memory_type="episodic", importance=6, session_id="s1"
    )
    id2, op = manager.memorize_with_conflict_check(
        NEGATED_NOOP, memory_type="episodic", importance=6, session_id="s1"
    )
    assert op == OP_UPDATE
    assert manager.episodic.get_by_id(id1)["invalid_at"] is not None
    assert manager.episodic.get_by_id(id2)["supersedes_id"] == id1
    assert manager.episodic.count() == 1


def test_same_negation_polarity_duplicate_still_noop(db: Database) -> None:
    """两边都含否定词 → 极性相同，近重复仍判 NOOP（不误伤去重）。"""
    manager = _manager(db)
    manager.memorize(
        NEGATED_NOOP, memory_type="episodic", importance=6, session_id="s1"
    )
    decision = manager.get_conflict_resolver().resolve(
        NEGATED_NOOP + "。", session_id="s1"
    )
    assert decision.op == OP_NOOP


# ---------- 嵌入器故障降级 ----------


def test_embedder_failure_degrades_to_literal_without_raising(db: Database) -> None:
    """嵌入器炸了也不能阻断写入 —— 退化为纯字面判定。"""
    manager = _manager(db, embedder=FakeSemanticEmbedder(fail=True))
    manager.memorize(OLD, memory_type="episodic", importance=6, session_id="s1")
    resolver = manager.get_conflict_resolver()
    # 字面低于阈值 → 与改造前一致，判 ADD
    assert resolver.resolve(NEW, session_id="s1").op == OP_ADD
    # 字面在 UPDATE 区 → 仍然能消解
    assert resolver.resolve(LITERAL_UPDATE, session_id="s1").op == OP_UPDATE


def test_embedder_provider_is_resolved_per_call(db: Database) -> None:
    """embedder 传工厂函数 → 每次判定取当前实例（支持热切换）。"""
    state = {"embedder": None}
    manager = _manager(db, embedder=lambda: state["embedder"])
    manager.memorize(OLD, memory_type="episodic", importance=6, session_id="s1")
    resolver = manager.get_conflict_resolver()

    assert resolver.resolve(NEW, session_id="s1").op == OP_ADD
    state["embedder"] = _concise_embedder()
    assert resolver.resolve(NEW, session_id="s1").op == OP_UPDATE


def test_embedder_provider_exception_degrades(db: Database) -> None:
    """工厂函数抛异常 → 按无语义嵌入器处理，不阻断写入。"""

    def boom():
        raise RuntimeError("no embedder today")

    manager = _manager(db, embedder=boom)
    manager.memorize(OLD, memory_type="episodic", importance=6, session_id="s1")
    assert manager.get_conflict_resolver().resolve(NEW, session_id="s1").op == OP_ADD


# ---------- 相似度计算辅助方法 ----------


def test_calculate_similarity_takes_max_of_literal_and_semantic(db: Database) -> None:
    resolver = _resolver(db, embedder=_concise_embedder())
    assert resolver._calculate_similarity(OLD, NEW) >= SEMANTIC_UPDATE_THRESHOLD
    assert resolver._calculate_similarity(OLD, OLD) == pytest.approx(1.0)


def test_calculate_similarity_falls_back_to_literal(db: Database) -> None:
    resolver = _resolver(db, embedder=HashEmbedder())
    assert resolver._calculate_similarity(OLD, NEW) == pytest.approx(
        _similarity(OLD, NEW)
    )


def test_annotate_semantic_records_similarity(db: Database) -> None:
    """候选被 FTS 召回后，语义相似度写入 Candidate。"""
    manager = _manager(db, embedder=_concise_embedder())
    manager.memorize(OLD, memory_type="episodic", importance=6, session_id="s1")
    resolver = manager.get_conflict_resolver()

    candidates = resolver._find_candidates(NEW, SCOPE_USER, None)
    assert candidates, "改述对应能通过 FTS 召回旧记忆"
    resolver._annotate_semantic(NEW, candidates)
    assert candidates[0].semantic_similarity == pytest.approx(1.0)


# ---------- 端到端：写路径 ----------


def test_memorize_with_conflict_check_semantic_update_swaps_rows(db: Database) -> None:
    """语义改述走 UPDATE —— 新行写入、旧行失效，检索只剩一条。"""
    manager = _manager(db, embedder=_concise_embedder())
    id1, op1 = manager.memorize_with_conflict_check(
        OLD, memory_type="episodic", importance=6, session_id="s1"
    )
    assert op1 == OP_ADD

    id2, op2 = manager.memorize_with_conflict_check(
        NEW, memory_type="episodic", importance=6, session_id="s1"
    )
    assert op2 == OP_UPDATE
    assert id2
    assert id2 != id1
    assert manager.episodic.get_by_id(id1)["invalid_at"] is not None
    assert manager.episodic.get_by_id(id2)["supersedes_id"] == id1
    assert manager.episodic.count() == 1  # 没有碎片化重复


# ---------- 阈值边界 ----------


def test_semantic_similarity_just_above_threshold_triggers_update(db: Database) -> None:
    """余弦 0.905（略高于 0.90）→ UPDATE。"""
    EpisodicMemory(db).save("用户喜欢使用 Python", importance=6, session_id="s1")
    resolver = _resolver(
        db, embedder=FakeSemanticEmbedder({"Python": VEC_CONCISE, "Rust": VEC_NEAR_ABOVE})
    )
    assert resolver.resolve("用户喜欢使用 Rust 编程语言", session_id="s1").op == OP_UPDATE


def test_semantic_similarity_just_below_threshold_stays_add(db: Database) -> None:
    """余弦 0.895（略低于 0.90）→ ADD，阈值不含糊。"""
    EpisodicMemory(db).save("用户喜欢使用 Python", importance=6, session_id="s1")
    resolver = _resolver(
        db, embedder=FakeSemanticEmbedder({"Python": VEC_CONCISE, "Rust": VEC_NEAR_BELOW})
    )
    assert resolver.resolve("用户喜欢使用 Rust 编程语言", session_id="s1").op == OP_ADD


def test_semantic_update_only_collapses_near_tied_candidates(db: Database) -> None:
    """语义分高于阈值但明显落后于最佳候选 → 不被一并失效。

    短模板句的余弦普遍偏高（这里 Rust 对 Python 是 0.95），若不设裕度，
    写一条 Python 事实会顺手把"喜欢用 Rust"也判失效 —— 那是丢正确记忆。
    """
    epi = EpisodicMemory(db)
    py_id = epi.save("用户喜欢使用 Python", importance=6, session_id="s1")
    rust_id = epi.save("用户喜欢使用 Rust 开发后端服务", importance=6, session_id="s1")

    resolver = _resolver(
        db, embedder=FakeSemanticEmbedder({"Python": VEC_CONCISE, "Rust": VEC_RUST})
    )
    decision = resolver.resolve("用户喜欢使用 Python 语言", session_id="s1")

    assert decision.op == OP_UPDATE
    assert decision.superseded_ids == [py_id]
    assert rust_id not in decision.superseded_ids
    # 0.95 高于阈值，但 1.00 - 0.95 > SEMANTIC_TARGET_MARGIN
    assert SEMANTIC_TARGET_MARGIN < 1.0 - 0.95


# ---------- 余弦相似度边界 ----------


def test_cosine_similarity_edge_cases() -> None:
    assert _cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0  # 零向量
    assert _cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert _cosine_similarity([-1.0, 0.0], [1.0, 0.0]) == pytest.approx(-1.0)
    assert _cosine_similarity([1.0], [1.0, 0.0]) == 0.0  # 维度不符
    assert _cosine_similarity([], []) == 0.0


# ---------- 批量编码异常 ----------


def test_annotate_semantic_ignores_malformed_batch(db: Database) -> None:
    """encode_batch 返回条数不符 → 全部保持 None，判定退化为纯字面。"""
    manager = _manager(db)
    manager.memorize(OLD, memory_type="episodic", importance=6, session_id="s1")

    resolver = _resolver(db, embedder=_ShortBatchEmbedder())
    candidates = resolver._find_candidates(NEW, SCOPE_USER, None)
    assert candidates

    resolver._annotate_semantic(NEW, candidates)
    assert all(c.semantic_similarity is None for c in candidates)
