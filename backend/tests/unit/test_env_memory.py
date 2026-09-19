# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""PR 环境记忆化（通道 B）单元测试。

覆盖:
- env_probe 工具观察缓冲（record/pop/去重/上限）
- extractor prompt 含 environment 类别与 tool_observations / existing_facts 段
- extract_and_store_memory：environment 路由画像、existing_facts 去重接线、
  tool_observations 透传
- UserProfileStore：environment 白名单 + 条数上限（保留最新）
- evolution：environment 标签豁免 prune / importance 降权
- BashTool._decorate：fallback note 进观察缓冲
"""

from __future__ import annotations

import json
import time
import uuid
from types import SimpleNamespace

import pytest

from backend.application.services.chat_service import extract_and_store_memory
from backend.data.database import Database
from backend.memory.extractor import MemoryExtractor
from backend.memory.user_profile import ENVIRONMENT_MAX_ENTRIES, UserProfileStore
from backend.scheduler.evolution import ImportanceReevaluationTask, MemoryPruningTask
from backend.tools import env_probe
from backend.tools.bash_tool import BashTool
from backend.tools.shell_resolver import ShellSpec

pytestmark = pytest.mark.unit

SECONDS_PER_DAY = 24 * 3600


def _now_s() -> int:
    return int(time.time())


# ---- env_probe 观察缓冲 --------------------------------------------------- #


class TestObservationBuffer:
    def test_record_and_pop_roundtrip(self):
        env_probe.record_observation("s1", " 改用 PowerShell 2.0 执行 ")
        assert env_probe.pop_observations("s1") == "改用 PowerShell 2.0 执行"
        # pop 即清空
        assert env_probe.pop_observations("s1") == ""

    def test_dedup_and_cap(self):
        for i in range(5):
            env_probe.record_observation("s2", f"观察-{i}")
        env_probe.record_observation("s2", "观察-4")  # 重复不入队
        text = env_probe.pop_observations("s2")
        lines = text.splitlines()
        assert len(lines) == env_probe._OBS_MAX_PER_SESSION
        assert lines == ["观察-2", "观察-3", "观察-4"]

    def test_empty_session_noop(self):
        env_probe.record_observation(None, "x")
        env_probe.record_observation("s3", "")
        assert env_probe.pop_observations("s3") == ""
        assert env_probe.pop_observations(None) == ""


# ---- extractor prompt ------------------------------------------------------ #


class CapturingLLM:
    def __init__(self):
        self.prompt = None

    async def chat(self, messages, **kwargs):
        first = messages[0]
        self.prompt = first.content if hasattr(first, "content") else first["content"]
        return SimpleNamespace(content="[]")


@pytest.mark.asyncio()
async def test_extract_prompt_has_environment_category_and_observations():
    llm = CapturingLLM()
    extractor = MemoryExtractor(llm_client=llm)
    facts = await extractor.extract(
        user_message="在 win7 上跑脚本又报 -Directory 不支持了" + "x" * 20,
        assistant_message="改用 PSIsContainer 写法后成功",
        existing_facts=["已知事实甲"],
        tool_observations="未找到 bash，改用 Windows PowerShell 2.0 执行。",
    )
    assert facts == []
    assert "environment" in llm.prompt
    assert "工具执行观察" in llm.prompt
    assert "改用 Windows PowerShell 2.0 执行" in llm.prompt
    assert "已知事实甲" in llm.prompt


# ---- extract_and_store_memory 路由与接线 ---------------------------------- #


class FakeExtractor:
    def __init__(self, facts):
        self.facts = facts
        self.received = None

    async def extract(self, user_message, assistant_message, existing_facts=None, tool_observations=None):
        self.received = {
            "existing_facts": existing_facts,
            "tool_observations": tool_observations,
        }
        return self.facts


class FullFakePort:
    def __init__(self):
        self.stored = []
        self.profiles = []

    async def store(self, content, session_id=None, importance=5, tags=None):
        self.stored.append({"content": content, "importance": importance, "tags": tags})
        return "m-" + content[:4]

    async def store_profile(self, content, category, importance, session_id=None):
        self.profiles.append({"content": content, "category": category})
        return "p-" + content[:4]

    def recent_fact_contents(self, limit=20):
        return ["近期事实A", "近期事实B"]


class BarePort:
    """无 recent_fact_contents / store_profile 的最小 port。"""

    def __init__(self):
        self.stored = []

    async def store(self, content, session_id=None, importance=5, tags=None):
        self.stored.append(content)
        return "m1"


@pytest.mark.asyncio()
async def test_environment_fact_routed_to_profile_with_dedup_inputs():
    port = FullFakePort()
    extractor = FakeExtractor(
        [
            {"content": "win7 PS2.0 用 PSIsContainer 替代 -Directory", "importance": 9, "category": "environment", "tags": ["environment"]},
            {"content": "普通事实", "importance": 5, "category": "fact", "tags": ["conversation"]},
        ]
    )
    stored = await extract_and_store_memory(
        memory_port=port,
        extractor=extractor,
        user_text="u" * 30,
        assistant_text="a" * 60,
        session_id="s1",
        enabled=True,
        tool_observations="shell fallback note",
    )
    assert stored == 2
    assert port.profiles[0]["category"] == "environment"
    assert port.stored[0]["content"] == "普通事实"
    # existing_facts 修复：不再是恒空
    assert extractor.received["existing_facts"] == ["近期事实A", "近期事实B"]
    assert extractor.received["tool_observations"] == "shell fallback note"


@pytest.mark.asyncio()
async def test_bare_port_falls_back_gracefully():
    port = BarePort()
    extractor = FakeExtractor(
        [{"content": "环境事实", "importance": 9, "category": "environment", "tags": []}]
    )
    stored = await extract_and_store_memory(
        memory_port=port,
        extractor=extractor,
        user_text="u" * 30,
        assistant_text="a" * 60,
        session_id=None,
        enabled=True,
    )
    assert stored == 1
    # 无 store_profile → environment 走普通 store；无 recent_fact_contents → 空列表
    assert port.stored == ["环境事实"]
    assert extractor.received["existing_facts"] == []
    assert extractor.received["tool_observations"] == ""


# ---- UserProfileStore environment ------------------------------------------ #


@pytest.fixture()
def db(tmp_path):
    database = Database(db_path=str(tmp_path / "test_env_profile.db"))
    database.init_db()
    yield database
    database.close()


@pytest.fixture()
def store(db):
    s = UserProfileStore(db)
    s.load()
    return s


class TestUserProfileEnvironment:
    def test_environment_category_not_downgraded(self, store):
        pid = store.add("本机 PowerShell 为 2.0", category="environment", importance=9)
        assert pid
        entry = next(e for e in store._entries if e["id"] == pid)
        assert entry["category"] == "environment"
        assert "PowerShell" in store.get_snapshot()

    def test_environment_cap_keeps_latest(self, store):
        contents = [f"环境事实{i}：python 路径变体 {i}" for i in range(ENVIRONMENT_MAX_ENTRIES + 2)]
        for content in contents:
            assert store.add(content, category="environment", importance=9)
        env_entries = [e for e in store._entries if e["category"] == "environment"]
        assert len(env_entries) == ENVIRONMENT_MAX_ENTRIES
        snapshot = store.get_snapshot()
        assert contents[-1] in snapshot
        assert contents[0] not in snapshot
        # DB 与内存同步
        rows = store.db.get_connection().execute(
            "SELECT COUNT(*) AS c FROM user_profile WHERE category='environment'"
        ).fetchone()
        assert rows["c"] == ENVIRONMENT_MAX_ENTRIES


# ---- evolution environment 豁免 -------------------------------------------- #


def _insert_episodic(db, content, *, importance, tags, created_at, access_count=0):
    memory_id = str(uuid.uuid4())
    db.get_connection().execute(
        """
        INSERT INTO memories_episodic
        (id, session_id, content, summary, memory_type, importance, source, tags,
         created_at, access_count, is_valid, expires_at)
        VALUES (?, NULL, ?, ?, 'conversation', ?, 'auto', ?, ?, ?, 1, NULL)
        """,
        (memory_id, content, content[:50], importance, json.dumps(tags), created_at, access_count),
    )
    db.get_connection().commit()
    return memory_id


def _fetch_row(db, memory_id):
    row = db.get_connection().execute(
        "SELECT importance FROM memories_episodic WHERE id = ?", (memory_id,)
    ).fetchone()
    return dict(row) if row else None


@pytest.mark.asyncio()
async def test_prune_spares_environment_tagged_memory(setup_test_db):
    db = setup_test_db
    old = _now_s() - 31 * SECONDS_PER_DAY
    env_id = _insert_episodic(db, "win7 PS2.0 替代写法", importance=1, tags=["environment"], created_at=old)
    plain_id = _insert_episodic(db, "普通低价值", importance=1, tags=["conversation"], created_at=old)
    task = MemoryPruningTask(db=db)
    await task.run_async()
    assert _fetch_row(db, env_id) is not None
    assert _fetch_row(db, plain_id) is None


@pytest.mark.asyncio()
async def test_importance_reevaluation_spares_environment_tagged_memory(setup_test_db):
    db = setup_test_db
    eight_days_ago = _now_s() - 8 * SECONDS_PER_DAY
    env_id = _insert_episodic(db, "python 路径事实", importance=9, tags=["environment"], created_at=eight_days_ago)
    plain_id = _insert_episodic(db, "普通高价值", importance=9, tags=["fact"], created_at=eight_days_ago)
    task = ImportanceReevaluationTask(db=db)
    await task.run_async()
    assert _fetch_row(db, env_id)["importance"] == 9
    assert _fetch_row(db, plain_id)["importance"] == 8


# ---- BashTool fallback note → 观察缓冲 ------------------------------------ #


def test_decorate_records_fallback_observation(monkeypatch):
    recorded = []
    monkeypatch.setattr(env_probe, "record_observation", lambda sid, text: recorded.append((sid, text)))
    monkeypatch.setattr(
        "backend.tools.context.current_tool_context",
        lambda: SimpleNamespace(session_id="sess-env"),
    )
    fallback = ShellSpec("C:\\powershell.exe", ("-NoProfile", "-Command"), "powershell")
    content = BashTool._decorate(object.__new__(BashTool), {}, fallback, None)
    assert "shell_fallback" in content
    assert len(recorded) == 1
    assert recorded[0][0] == "sess-env"
    assert "PowerShell" in recorded[0][1]


def test_decorate_no_observation_without_fallback(monkeypatch):
    recorded = []
    monkeypatch.setattr(env_probe, "record_observation", lambda sid, text: recorded.append((sid, text)))
    bash = ShellSpec("C:\\Git\\bin\\bash.exe", ("-c",), "bash")
    BashTool._decorate(object.__new__(BashTool), {}, bash, None)
    assert recorded == []


# ---- profiles prompt ------------------------------------------------------- #


def test_system_base_declares_env_persistence():
    from backend.agents.profiles import build_system_base

    assert "环境经验固化" in build_system_base()
