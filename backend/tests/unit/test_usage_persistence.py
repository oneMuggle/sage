# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""L8 用量落库 + F5 花费限额 + F6 用户级规则 (批次 C) 后端单元测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from backend.services.usage_tracker import UsageTracker

pytestmark = pytest.mark.unit


@pytest.fixture()
def tracker_with_db(monkeypatch, tmp_path: Path) -> UsageTracker:
    """内存库 + 每测试独立 tracker(清全局单例状态不必要——自建实例)。"""
    from backend.data import database as database_module
    from backend.data.database import Database

    test_db = Database(":memory:")
    test_db.init_db()
    monkeypatch.setattr(database_module, "_db", test_db)
    return UsageTracker()


def test_record_persists_to_usage_events(tracker_with_db: UsageTracker):
    from backend.data.database import get_database

    tracker_with_db.record("gpt-4o", 100, 50, session_id="s1")
    tracker_with_db.record("gpt-4o", 10, 5, session_id=None)

    rows = get_database().get_connection().execute(
        "SELECT session_id, model, prompt_tokens, completion_tokens, total_tokens"
        " FROM usage_events ORDER BY prompt_tokens DESC"
    ).fetchall()
    assert len(rows) == 2
    # 第一行 = s1 的 100+50; 另一行未归因(session_id IS NULL)
    assert rows[0]["session_id"] == "s1"
    assert rows[0]["total_tokens"] == 150
    assert rows[1]["session_id"] is None


def test_session_summary_aggregates(tracker_with_db: UsageTracker):
    tracker_with_db.record("gpt-4o", 100, 50, session_id="s1")
    tracker_with_db.record("gpt-4o-mini", 20, 10, session_id="s1")
    tracker_with_db.record("gpt-4o", 999, 999, session_id="s2")  # 别的会话

    summary = tracker_with_db.session_summary("s1")
    assert summary["requests"] == 2
    assert summary["prompt_tokens"] == 120
    assert summary["completion_tokens"] == 60
    assert summary["total_tokens"] == 180
    assert summary["estimated_cost_usd"] > 0


def test_session_summary_missing_session_returns_zeroes(tracker_with_db: UsageTracker):
    summary = tracker_with_db.session_summary("nope")
    assert summary["requests"] == 0
    assert summary["estimated_cost_usd"] == 0.0


def test_today_cost_usd_sums_all_sessions(tracker_with_db: UsageTracker):
    from backend.data.database import get_database

    # 成本估算依赖内置价格表; 用已知模型保证 > 0
    tracker_with_db.record("gpt-4o", 1_000_000, 1_000_000, session_id="s1")
    tracker_with_db.record("gpt-4o", 1_000_000, 0, session_id="s2")
    expected = (
        get_database()
        .get_connection()
        .execute("SELECT COALESCE(SUM(estimated_cost_usd),0) AS t FROM usage_events")
        .fetchone()["t"]
    )
    assert expected > 0
    assert abs(tracker_with_db.today_cost_usd() - expected) < 1e-6


def test_tracker_fail_open_on_db_error(monkeypatch):
    """DB 故障 → record 不抛、内存聚合照常(用量是增强信息)。"""
    tracker = UsageTracker()

    import backend.data.database as db_mod

    class _Boom:
        def get_connection(self):
            raise RuntimeError("db down")

        def close(self):
            return None

        def init_db(self):
            return None

    monkeypatch.setattr(db_mod, "_db", _Boom())
    # get_database() 读取 _db 失败 → _persist 静默
    entry = tracker.record("gpt-4o", 10, 5, session_id="s1")
    assert entry.prompt_tokens == 10
    assert tracker.summary()["totals"]["prompt_tokens"] == 10


@pytest.mark.asyncio()
async def test_run_loop_session_attribution():
    from backend.core.legacy.agent import SageAgent
    from backend.core.legacy.llm_client import LLMClient, LLMConfig, LLMResponse

    agent = SageAgent()
    client = LLMClient(LLMConfig(provider="openai", model="m"))
    agent.llm_client = client
    client.chat = AsyncMock(return_value=LLMResponse(content="ok"))

    async for _ in agent.run_loop([{"role": "user", "content": "x"}], session_id="s9"):
        pass

    assert client.session_id == "s9"


# ---- F6 用户级规则 ----


def test_user_level_sage_md_discovered(monkeypatch, tmp_path: Path):
    import backend.chat.project_context as pc

    fake_home = tmp_path / "home"
    (fake_home / ".sage").mkdir(parents=True)
    (fake_home / ".sage" / "SAGE.md").write_text("全局规则:总是用中文回复", encoding="utf-8")
    monkeypatch.setattr(pc.Path, "home", staticmethod(lambda: fake_home))

    ws = tmp_path / "ws"
    ws.mkdir()
    ctx = pc.discover_project_context(ws)
    sources = [e.source for e in ctx.entries]
    assert "user_sage_md" in sources
    assert ctx.entries[0].source == "user_sage_md"  # 全局层排在最前
    assert "总是用中文回复" in ctx.render()


def test_user_level_missing_file_is_noop(monkeypatch, tmp_path: Path):
    import backend.chat.project_context as pc

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(pc.Path, "home", staticmethod(lambda: fake_home))

    ws = tmp_path / "ws"
    ws.mkdir()
    ctx = pc.discover_project_context(ws)
    assert ctx.entries == []
