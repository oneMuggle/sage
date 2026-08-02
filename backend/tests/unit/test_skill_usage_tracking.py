"""Skill usage tracking 单元测试

覆盖:
- SkillUsageStore: bump / success=False / get / get_all / 持久化
- InprocSkillAdapter.execute 成功路径自动计数（内存 + DB）
- execute 失败 / 不存在技能不计数
- bump_usage 的 DB best-effort 持久化
"""

from typing import Any, Dict

import pytest

from backend.adapters.out.skill.inproc import InprocSkillAdapter
from backend.data.database import Database
from backend.skills.base import BaseSkill, SkillResult, SkillSchema
from backend.skills.registry import SkillRegistry
from backend.skills.usage import SkillUsageStore, get_usage_store, reset_usage_store

pytestmark = pytest.mark.unit


# ============================================================================
# helpers
# ============================================================================


def _make_skill(name: str, succeed: bool = True) -> BaseSkill:
    """构造一个总是成功（或失败）的 fake skill。"""

    class _S(BaseSkill):
        def _build_schema(self) -> SkillSchema:
            return SkillSchema(
                name=name,
                description=f"{name} skill",
                triggers=[name],
                parameters={"type": "object", "properties": {}, "required": []},
            )

        def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> SkillResult:
            if succeed:
                return SkillResult(content=f"{name} done", success=True)
            return SkillResult(success=False, error="simulated failure")

    return _S()


def _make_adapter(db: Database, succeed: bool = True) -> InprocSkillAdapter:
    registry = SkillRegistry()
    registry.register(_make_skill("search", succeed=succeed))
    return InprocSkillAdapter(registry=registry)


@pytest.fixture()
def db(tmp_path):
    database = Database(db_path=str(tmp_path / "test_skill_usage.db"))
    database.init_db()
    yield database
    database.close()


@pytest.fixture()
def store(db):
    return SkillUsageStore(db)


@pytest.fixture(autouse=True)
def _reset_singletons():
    reset_usage_store()
    yield
    reset_usage_store()


# ============================================================================
# SkillUsageStore
# ============================================================================


class TestSkillUsageStore:
    def test_bump_increments(self, store):
        store.bump("search", success=True)
        stat = store.get("search")
        assert stat["use_count"] == 1
        assert stat["success_count"] == 1

    def test_bump_accumulates(self, store):
        store.bump("search", success=True)
        store.bump("search", success=True)
        store.bump("search", success=False)
        stat = store.get("search")
        assert stat["use_count"] == 3
        assert stat["success_count"] == 2

    def test_bump_empty_name_noop(self, store):
        store.bump("", success=True)
        assert store.get_all() == []

    def test_get_missing_returns_none(self, store):
        assert store.get("nonexistent") is None

    def test_get_all_sorted_by_last_used(self, store):
        store.bump("a", success=True)
        store.bump("b", success=True)
        names = [s["name"] for s in store.get_all()]
        # b 后写入 → last_used_at 更大, 排前面
        assert names[0] == "b"

    def test_persists_across_store_instances(self, db):
        s1 = SkillUsageStore(db)
        s1.bump("search", success=True)
        s2 = SkillUsageStore(db)
        assert s2.get("search")["use_count"] == 1

    def test_bump_best_effort_on_bad_db(self, tmp_path):
        """DB 连接失效时 bump 不抛错（best-effort）。"""
        store = SkillUsageStore(db=None)
        # 指向不存在的表名场景通过 monkeypatch db 为坏对象模拟
        store.db = object()  # type: ignore[assignment]
        store.bump("search", success=True)  # 不应抛异常


# ============================================================================
# InprocSkillAdapter.execute 接线
# ============================================================================


class TestAdapterExecuteUsage:
    @pytest.mark.asyncio()
    async def test_execute_success_bumps_memory_and_db(self, db):
        adapter = _make_adapter(db, succeed=True)
        result = await adapter.execute("search", "run", {})
        assert result.success
        # 内存计数
        assert adapter.usage_count("search") == 1
        # DB 持久化
        assert get_usage_store(db).get("search")["use_count"] == 1

    @pytest.mark.asyncio()
    async def test_execute_failure_does_not_bump(self, db):
        adapter = _make_adapter(db, succeed=False)
        result = await adapter.execute("search", "run", {})
        assert not result.success
        assert adapter.usage_count("search") == 0
        assert get_usage_store(db).get("search") is None

    @pytest.mark.asyncio()
    async def test_execute_missing_skill_no_bump(self, db):
        adapter = _make_adapter(db, succeed=True)
        result = await adapter.execute("nonexistent", "run", {})
        assert not result.success
        assert adapter.usage_count("nonexistent") == 0

    def test_bump_usage_persists_to_db(self, db):
        adapter = _make_adapter(db, succeed=True)
        adapter.bump_usage("search")
        assert get_usage_store(db).get("search")["use_count"] == 1

    @pytest.mark.asyncio()
    async def test_usage_hydrated_from_db_on_reinit(self, db):
        """新建 adapter 从 skill_usage 表回填持久化计数（重启不归零）。"""
        adapter1 = _make_adapter(db, succeed=True)
        await adapter1.execute("search", "run", {})
        assert adapter1.usage_count("search") == 1

        # 模拟进程重启: 新建 adapter → 从 DB 回填
        adapter2 = _make_adapter(db, succeed=True)
        assert adapter2.usage_count("search") == 1
