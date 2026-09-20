"""P4 每周反思 + 四因子检索评分回归测试。

覆盖:
- scoring: 四个因子的边界/归一/单位防御 + composite 排序稳定性
- MemoryContext.format 优先 composite_score
- MemoryReflectionTask: 启发式近重复去重（组内、不跨归属）、
  LLM MERGE/INVALIDATE（含非法输出容错与越界序号）、
  无 memory_manager 降级、evolution_log 落盘（"上次反思时间"来源）
"""

from __future__ import annotations

import time

import pytest

from backend.data.database import Database
from backend.domain.memory import MemoryContext
from backend.memory import scoring
from backend.memory.episodic import EpisodicMemory
from backend.memory.manager import MemoryManager
from backend.memory.scoring import composite_score, rank_by_composite
from backend.memory.semantic import SemanticMemory
from backend.memory.working import WorkingMemory
from backend.scheduler.evolution import MemoryReflectionTask
from backend.tests.conftest import ensure_session

pytestmark = pytest.mark.unit

PROJ = "/tmp/p4-proj"

# 近重复对（≥0.97, 与 P3 夹具同源思路）
F1 = "用户偏好用 VS Code 编辑代码并且开启了 vim 插件模式"
F2 = "用户偏好用 VS Code 编辑代码并且开启了 vim 插件模式。"
# 同主题但不同表述（交给 LLM 合并, 启发式不动）
F3 = "用户习惯在晚上十点后集中处理邮件"
F4 = "用户觉得深夜回邮件效率最高"
# 无关
F5 = "猫在窗台上睡着了"

NOW_MS = 1_800_000_000_000


@pytest.fixture()
def db(tmp_db_path: str) -> Database:
    d = Database(db_path=tmp_db_path)
    d.init_db()
    for sid in ("s-p4",):
        ensure_session(d, sid)
    return d


@pytest.fixture()
def manager(db: Database) -> MemoryManager:
    return MemoryManager(
        working=WorkingMemory(db=db),
        episodic=EpisodicMemory(db),
        semantic=SemanticMemory(db),
    )


# ============================ 四因子评分 ============================


def test_relevance_factor():
    assert scoring.relevance_factor({}) == 0.5  # 非混合路径 → 中性
    assert scoring.relevance_factor({"rrf_score": scoring.RRF_NORM_MAX}) == pytest.approx(1.0)
    assert scoring.relevance_factor({"rrf_score": scoring.RRF_NORM_MAX * 2}) == 1.0  # 截断
    assert scoring.relevance_factor({"rrf_score": 0.0}) == 0.5


def test_recency_factor_decay_and_unit_defense():
    fresh = {"created_at": NOW_MS, "accessed_at": NOW_MS}
    assert scoring.recency_factor(fresh, now_ms=NOW_MS) == pytest.approx(1.0)
    half = {"created_at": NOW_MS - 30 * 86_400_000}
    assert scoring.recency_factor(half, now_ms=NOW_MS) == pytest.approx(0.5, abs=1e-6)
    # 秒级时间戳（历史脏数据）归一为毫秒后仍按半衰期计算
    sec = {"created_at": int(NOW_MS / 1000) - 30 * 86_400}
    assert scoring.recency_factor(sec, now_ms=NOW_MS) == pytest.approx(0.5, abs=1e-3)
    # accessed_at 更新可救活旧记忆
    revisited = {"created_at": NOW_MS - 365 * 86_400_000, "accessed_at": NOW_MS}
    assert scoring.recency_factor(revisited, now_ms=NOW_MS) == pytest.approx(1.0)
    assert scoring.recency_factor({}, now_ms=NOW_MS) == 0.5


def test_importance_and_confidence_factors():
    assert scoring.importance_factor({"importance": 10}) == pytest.approx(1.0)
    assert scoring.importance_factor({"importance": 1}) == pytest.approx(0.1)
    assert scoring.importance_factor({}) == 0.5  # semantic 行无该列 → 中性
    assert scoring.importance_factor({"importance": "bad"}) == 0.5

    assert scoring.confidence_factor({}) == 0.5
    assert scoring.confidence_factor({"source": "evolution"}) == pytest.approx(0.7)
    assert scoring.confidence_factor({"supersedes_id": "x"}) == pytest.approx(0.6)
    assert scoring.confidence_factor({"access_count": 100}) == pytest.approx(0.7)
    assert (
        scoring.confidence_factor(
            {"source": "evolution", "supersedes_id": "x", "access_count": 10}
        )
        == 1.0
    )  # 截断


def test_composite_score_range_and_ranking():
    old_lowconf = {
        "rrf_score": 0.03,
        "importance": 2,
        "created_at": NOW_MS - 120 * 86_400_000,
    }
    fresh_highconf = {
        "rrf_score": 0.02,  # 相关性略低
        "importance": 9,
        "source": "evolution",
        "supersedes_id": "x",
        "created_at": NOW_MS,
    }
    s_old = composite_score(old_lowconf, now_ms=NOW_MS)
    s_new = composite_score(fresh_highconf, now_ms=NOW_MS)
    assert 0.0 <= s_old <= 1.0
    assert 0.0 <= s_new <= 1.0
    # 四因子的意义：字面略优的陈旧低可信命中应被压过
    assert s_new > s_old


def test_rank_by_composite_marks_and_does_not_mutate():
    a = {"id": "a", "rrf_score": 0.03, "created_at": NOW_MS - 90 * 86_400_000}
    b = {"id": "b", "rrf_score": 0.02, "created_at": NOW_MS, "importance": 9}
    ranked = rank_by_composite([a, b], now_ms=NOW_MS)
    assert [r["id"] for r in ranked] == ["b", "a"]
    assert "composite_score" not in a
    assert "composite_score" not in b
    assert ranked[0]["composite_score"] > ranked[1]["composite_score"]


def test_format_prefers_composite_score():
    # importance 高的旧行若 composite 低, 应排在后面
    low_imp = {"content": "A", "importance": 1, "composite_score": 0.9}
    high_imp = {"content": "B", "importance": 9, "composite_score": 0.1}
    ctx = MemoryContext(working=[], episodic=[low_imp, high_imp], semantic=[], core=[])
    text = ctx.format(budget_tokens=1000)
    assert text.index("A") < text.index("B")


# ============================ 每周反思 ============================


def _set_created(db: Database, table: str, mid: str, ts_ms: int) -> None:
    conn = db.get_connection()
    conn.execute(f"UPDATE {table} SET created_at = ? WHERE id = ?", (ts_ms, mid))
    conn.commit()


def _save_epi(
    manager: MemoryManager,
    content: str,
    ts_ms: int = None,
    scope=None,
    project_key=None,
):
    mid = manager.memorize(
        content,
        memory_type="episodic",
        importance=6,
        session_id="s-p4",
        scope=scope,
        project_key=project_key,
    )
    if ts_ms is not None:
        # 控制 created_at 顺序（同毫秒写入排序不稳定）
        _set_created(manager.episodic.db, "memories_episodic", mid, ts_ms)
    return mid


def test_reflection_skips_without_manager(db: Database):
    task = MemoryReflectionTask(db=db, memory_manager=None, llm_client=None)
    stats = task.run()
    assert stats["deduped"] == 0
    row = db.get_connection().execute(
        "SELECT status FROM evolution_log WHERE evolution_type='memory_reflection'"
    ).fetchone()
    assert row["status"] == "skipped"


def test_reflection_heuristic_dedupe_keeps_newest(db: Database, manager: MemoryManager):
    old = _save_epi(manager, F1)
    new = _save_epi(manager, F2)
    _set_created(db, "memories_episodic", old, NOW_MS - 10 * 86_400_000)
    _set_created(db, "memories_episodic", new, NOW_MS)

    task = MemoryReflectionTask(db=db, memory_manager=manager, llm_client=object())
    # llm_client 非 None 但 chat 会抛 → _chat 降级为 ""，只测启发式路
    stats = task.run()
    assert stats["scanned"] == 2
    assert stats["deduped"] == 1
    # 旧行失效、新行存活
    assert manager.episodic.get_by_id(old)["invalid_at"] is not None
    assert manager.episodic.get_by_id(new)["invalid_at"] is None
    # 记忆级审计日志
    logs = db.get_connection().execute(
        "SELECT operation FROM memories_evolution_log WHERE memory_id = ?", (old,)
    ).fetchall()
    assert [r["operation"] for r in logs] == ["reflect_invalidate"]


def test_reflection_never_crosses_attribution(db: Database, manager: MemoryManager):
    conn = db.get_connection()
    conn.execute(
        "INSERT INTO session_workspace_bindings "
        "(session_id, workspace_path, generation, activated_at, revoked_at) "
        "VALUES (?, ?, 1, 1, NULL)",
        ("s-p4", PROJ),
    )
    conn.commit()
    user_row = _save_epi(manager, F1, scope="user")
    proj_row = _save_epi(manager, F2, scope="project", project_key=PROJ)

    task = MemoryReflectionTask(db=db, memory_manager=manager, llm_client=None)
    stats = task.run()
    assert stats["deduped"] == 0
    assert manager.episodic.get_by_id(user_row)["invalid_at"] is None
    assert manager.episodic.get_by_id(proj_row)["invalid_at"] is None


class _FakeLLM:
    """LLMPort 风格: chat(messages=[Message]) → 返回预设文本。"""

    def __init__(self, reply: str):
        self.reply = reply
        self.prompts: list = []

    async def chat(self, messages):
        self.prompts.append(messages[-1]["content"] if isinstance(messages[-1], dict) else messages[-1].content)
        return self.reply


def test_reflection_llm_merge_and_invalidate(db: Database, manager: MemoryManager):
    m1 = _save_epi(manager, F3)
    m2 = _save_epi(manager, F4)
    doomed = _save_epi(manager, F5)
    base = NOW_MS - 3 * 86_400_000
    for i, mid in enumerate((m1, m2, doomed)):
        _set_created(db, "memories_episodic", mid, base + i * 86_400_000)

    # created_at 降序样本: 1=doomed(F5), 2=m2(F4), 3=m1(F3)
    llm = _FakeLLM(
        '```json\n[{"op":"MERGE","ids":[3,2],"content":"用户习惯深夜处理邮件效率最高"},'
        '{"op":"INVALIDATE","id":1,"reason":"与主题无关的偶然记录"},'
        '{"op":"INVALIDATE","id":99,"reason":"越界序号应被忽略"}]\n```'
    )
    task = MemoryReflectionTask(db=db, memory_manager=manager, llm_client=llm)
    stats = task.run()
    assert stats["merged"] == 1
    assert stats["invalidated"] == 1
    for mid in (m1, m2, doomed):
        assert manager.episodic.get_by_id(mid)["invalid_at"] is not None

    survivors = manager.episodic.search("深夜", limit=10)
    assert len(survivors) == 1
    merged_row = survivors[0]
    assert merged_row["supersedes_id"] == m2  # 链到最新成员
    assert merged_row["scope"] == "user"
    assert merged_row["memory_type"] == "reflection"
    assert "效率最高" in merged_row["content"]


def test_reflection_llm_garbage_is_noop(db: Database, manager: MemoryManager):
    _save_epi(manager, F3)
    _save_epi(manager, F4)
    task = MemoryReflectionTask(
        db=db, memory_manager=manager, llm_client=_FakeLLM("我不知道, 这不是 JSON")
    )
    stats = task.run()
    assert stats["merged"] == 0
    assert stats["invalidated"] == 0
    assert manager.episodic.count() == 2
    row = db.get_connection().execute(
        "SELECT status FROM evolution_log WHERE evolution_type='memory_reflection'"
    ).fetchone()
    assert row["status"] == "success"  # 任务本身不因模型输出质量失败


def test_reflection_last_run_recorded(db: Database, manager: MemoryManager):
    task = MemoryReflectionTask(db=db, memory_manager=manager, llm_client=None)
    task.run()
    ts = db.get_connection().execute(
        "SELECT MAX(created_at) AS t FROM evolution_log "
        "WHERE evolution_type='memory_reflection'"
    ).fetchone()["t"]
    assert ts is not None
    # 秒级时间戳：上次反思时间
    assert abs(ts - time.time()) < 120
