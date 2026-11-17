"""阶段 2：待办 AI 能力测试（提炼解析 / 简报 / 周回顾 / 来源字段）。"""
import tempfile
from pathlib import Path
from typing import List
from unittest.mock import AsyncMock  # noqa: F401 — 保留给后续用例扩展

import pytest

from backend.data.database import Database
from backend.services import todo_ai
from backend.services.todo_service import TodoService


@pytest.fixture()
def todo_service():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = Database(db_path=str(db_path))
        db.init_db()
        service = TodoService(db)
        yield service
        db.close()


class _FakeLLMClient:
    def __init__(self, response: str):
        self.response = response
        self.prompts: List[str] = []

    async def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


# --- 候选解析 ---


def test_parse_candidates_handles_fenced_json():
    raw = """```json
[
  {"title": "交周报", "due_at": "2026-11-20T18:00:00", "priority": "high", "tags": ["工作"]},
  {"title": "  ", "priority": "high"},
  {"title": "约张老师", "tags": ["论文", "论文", "x", "y", "z"]}
]
```"""
    result = todo_ai._parse_candidates(raw)

    assert [c["title"] for c in result] == ["交周报", "约张老师"]
    assert result[1]["due_at"] is None
    assert result[1]["priority"] is None
    assert result[1]["tags"] == ["论文", "论文", "x"]  # 上限 3，保持原序


def test_parse_candidates_rejects_invalid_priority_and_json():
    assert todo_ai._parse_candidates("not json at all") == []
    result = todo_ai._parse_candidates('[{"title": "T", "priority": "urgent"}]')
    assert result[0]["priority"] is None


def test_parse_candidates_caps_at_ten():
    items = ",".join(f'{{"title": "任务{i}"}}' for i in range(15))
    result = todo_ai._parse_candidates(f"[{items}]")
    assert len(result) == todo_ai.MAX_CANDIDATES


def test_parse_candidates_normalizes_z_suffix_due_at():
    result = todo_ai._parse_candidates(
        '[{"title": "T", "due_at": "2026-11-20T10:00:00Z"}]'
    )
    assert result[0]["due_at"] is not None
    assert result[0]["due_at"].endswith(":00")
    assert "+" not in result[0]["due_at"]


# --- extract_todos ---


async def test_extract_todos_raises_when_llm_unconfigured(monkeypatch):
    def _raise():
        raise todo_ai.LLMNotConfiguredError("LLM 未配置")

    monkeypatch.setattr(todo_ai, "_load_conversation", lambda sid, mids: "[用户] 你好")
    monkeypatch.setattr(todo_ai, "_client", _raise)

    with pytest.raises(todo_ai.LLMNotConfiguredError):
        await todo_ai.extract_todos("session-1")


async def test_extract_todos_uses_llm_response(monkeypatch):
    client = _FakeLLMClient(
        '[{"title": "交报告", "priority": "high", "tags": ["工作"]}]'
    )
    monkeypatch.setattr(todo_ai, "_client", lambda: client)
    monkeypatch.setattr(
        todo_ai, "_load_conversation", lambda sid, mids: "[用户] 明天下午三点交报告"
    )

    result = await todo_ai.extract_todos("session-1")

    assert result == [
        {"title": "交报告", "due_at": None, "priority": "high", "tags": ["工作"]}
    ]
    assert "明天下午三点交报告" in client.prompts[0]


async def test_extract_todos_returns_empty_for_empty_conversation(monkeypatch):
    monkeypatch.setattr(todo_ai, "_load_conversation", lambda sid, mids: "   ")
    assert await todo_ai.extract_todos("session-1") == []


# --- 简报 / 周回顾 ---


async def test_daily_brief_returns_llm_text(monkeypatch):
    client = _FakeLLMClient("• 先处理逾期项")
    monkeypatch.setattr(todo_ai, "_client", lambda: client)

    content = await todo_ai.generate_daily_brief(
        {
            "overdue": [{"title": "旧任务"}],
            "today": [],
            "upcoming": [],
            "high_priority": [],
            "total_completed_today": 2,
        }
    )

    assert content == "• 先处理逾期项"
    assert "旧任务" in client.prompts[0]


async def test_daily_brief_falls_back_when_llm_empty(monkeypatch):
    monkeypatch.setattr(todo_ai, "_client", lambda: _FakeLLMClient(""))
    content = await todo_ai.generate_daily_brief({})
    assert "暂无待办压力" in content


async def test_weekly_review_returns_llm_text(monkeypatch):
    client = _FakeLLMClient("## 完成情况\n不错")
    monkeypatch.setattr(todo_ai, "_client", lambda: client)

    content = await todo_ai.generate_weekly_review(
        {"total": 5, "overdue": 1, "completed_today": 2, "by_status": {"pending": 3}},
        ["交周报"],
        ["写方案"],
    )

    assert content.startswith("## 完成情况")
    assert "写方案" in client.prompts[0]


# --- 来源字段 ---


def test_create_todo_with_source(todo_service):
    todo = todo_service.create_todo(
        title="来自对话",
        source_type="chat",
        source_ref="session-abc",
    )
    assert todo.source_type == "chat"
    assert todo.source_ref == "session-abc"


def test_create_many(todo_service):
    created = todo_service.create_many(
        [
            {"title": "A", "source_type": "chat", "source_ref": "s1"},
            {"title": "B", "priority": "high"},
        ]
    )
    assert [t.title for t in created] == ["A", "B"]
    assert created[0].source_ref == "s1"
