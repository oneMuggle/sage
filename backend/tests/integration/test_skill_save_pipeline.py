"""skill_save 工具的 pipeline 集成测试。

与 ``test_skill_save_tool.py``(单元测试,mock 掉 review_service + draft_store)
的区别:本测试用真实的 ``ReviewService`` + 真实的 ``SkillDraftStore``(SQLite),
只把 LLM provider 换成 in-memory fake。覆盖 happy path,验证:

1. LLM fake 输出被 review pipeline 正确解析 + 校验 → 生成 SkillDraft
2. draft.id / name / status="pending" 正确返回到 skill_save 调用方
3. store.insert 真的把行写进了 SQLite
4. store.get(draft_id) 反序列化后字段全部对得上
5. trigger_type="user_explicit_save"、source_session_id、source_context.tool_calls
   都按预期持久化

不覆盖:
- review pipeline 的 JSON 解析 / 字段校验细节(那是 unit 测试的范围)
- SQLite schema 本身(test_storage_schema 已经覆盖)

依赖:
- ``backend.tools.skill_save_tool.SkillSaveTool``
- ``backend.skills.review_service.ReviewService``
- ``backend.skills.draft_store.SkillDraftStore``
- 单例 reset hook: ``reset_review_service()`` / ``reset_skill_draft_store()``
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pytest

from backend.skills.draft_store import (
    SkillDraftStore,
    get_skill_draft_store,
    reset_skill_draft_store,
)
from backend.skills.review_service import (
    ReviewService,
    get_review_service,
    reset_review_service,
)
from backend.tools.skill_save_tool import SkillSaveTool

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# 真实 SQLite skill_drafts 表的建表 SQL(从 backend/data/database.py 抽出,
# 保持与生产 schema 一致)
# ---------------------------------------------------------------------------

_CREATE_SKILL_DRAFTS_TABLE = """
CREATE TABLE IF NOT EXISTS skill_drafts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    when_to_use TEXT NOT NULL,
    content TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    source_session_id TEXT,
    source_context TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at INTEGER NOT NULL,
    reviewed_at INTEGER,
    reviewed_by_user_id TEXT
)
"""


# ---------------------------------------------------------------------------
# Fake LLM provider — 模拟 review pipeline 期望的 ProviderClient 接口
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _AssistantTurn:
    """review_service.py line 173 读 ``turn.text``,所以只需要 .text 属性。"""

    text: str


class _FakeLLMProvider:
    """返回一份符合 ReviewService._validate_skill_schema 的 JSON 草稿。"""

    def __init__(self, response_json: Dict[str, Any]) -> None:
        self._response_text = json.dumps(response_json, ensure_ascii=False)
        self.call_count = 0
        self.last_model: Optional[str] = None
        self.last_messages: Optional[List[Any]] = None

    async def complete(self, **kwargs: Any) -> _AssistantTurn:
        self.call_count += 1
        self.last_model = kwargs.get("model")
        self.last_messages = kwargs.get("messages")
        return _AssistantTurn(text=self._response_text)


def _good_draft_payload() -> Dict[str, Any]:
    """构造一份能通过 ReviewService 全部校验的草稿 JSON。

    - name:kebab-case,3-40 字符,通过 _validate_skill_name(无 .. / / \\)
    - description:≤80 字符
    - when_to_use:≥30 字符
    - content:必须含 ## 步骤 / ## 触发条件 / ## 示例
    """
    return {
        "name": "academic-search-cnki",
        "description": "在 CNKI 上检索学术文献并整理摘要",
        "when_to_use": "当用户需要检索 CNKI 上的学术论文并按主题整理摘要时使用",
        "content": (
            "# Academic Search CNKI\n\n"
            "## 步骤\n"
            "1. 接收关键词\n"
            "2. 调用 CNKI 检索\n"
            "3. 整理摘要\n\n"
            "## 触发条件\n"
            "用户表达检索学术文献的意图\n\n"
            "## 示例\n"
            "用户:帮我找 5 篇大语言模型综述\n"
        ),
    }


@pytest.fixture()
def seeded_db(tmp_path):
    """提供一个真实 SQLite + 已建表的 skill_drafts 表。"""
    db_path = str(tmp_path / "test_skill_save.db")
    with sqlite3.connect(db_path) as conn:
        conn.execute(_CREATE_SKILL_DRAFTS_TABLE)
    return db_path


@pytest.fixture(autouse=True)
def _reset_singletons():
    """每个测试前后重置 review_service / draft_store 单例,避免跨测试污染。"""
    reset_review_service()
    reset_skill_draft_store()
    yield
    reset_review_service()
    reset_skill_draft_store()


# ===========================================================================
# 端到端 happy path
# ===========================================================================


class TestSkillSavePipelineIntegration:
    """真实 review pipeline + 真实 SQLite + 真实 skill_save 工具。"""

    def test_skill_save_persists_real_draft_to_sqlite(self, seeded_db):
        """Fake LLM 返回合法 JSON → review pipeline 生成 SkillDraft →
        store.insert 写入 SQLite → store.get 反序列化字段对得上。
        """
        # Arrange: fake provider + 预热单例
        fake_provider = _FakeLLMProvider(_good_draft_payload())
        service = get_review_service(llm_provider=fake_provider)
        assert isinstance(service, ReviewService)

        store = get_skill_draft_store(db_path=seeded_db)
        assert isinstance(store, SkillDraftStore)
        assert store.db_path == seeded_db

        tool = SkillSaveTool()
        tool_sequence = [
            {"tool": "web_fetch", "args": {"url": "https://cnki.net/..."}},
            {"tool": "ask_user_question", "args": {"q": "需要哪类文献?"}},
        ]

        # Act:不再 patch,走完整 async bridge + SQLite 落盘
        result = tool.execute(
            name="academic-search-cnki",
            description="在 CNKI 上检索学术文献并整理摘要",
            when_to_use="当用户需要检索 CNKI 上的学术论文并按主题整理摘要时使用",
            tool_sequence=tool_sequence,
            session_id="sess-int-001",
        )

        # Assert 1:SkillSaveTool 返回成功 + draft_id
        assert result.success is True, f"unexpected error: {result.error}"
        assert result.output is not None
        draft_id = result.content["draft_id"]
        assert draft_id == result.output
        assert result.content["name"] == "academic-search-cnki"
        assert result.content["status"] == "pending"

        # Assert 2:fake LLM 被调用过(确认 async bridge 通了)
        assert fake_provider.call_count == 1
        assert fake_provider.last_model is not None  # 触发了 model 解析

        # Assert 3:SQLite 里真的有了这条草稿
        persisted = store.get(draft_id)
        assert persisted is not None, f"draft {draft_id} not found in SQLite"
        assert persisted.id == draft_id
        assert persisted.name == "academic-search-cnki"
        assert persisted.description == "在 CNKI 上检索学术文献并整理摘要"
        assert persisted.when_to_use.startswith("当用户需要检索")
        assert "## 步骤" in persisted.content
        assert "## 触发条件" in persisted.content
        assert "## 示例" in persisted.content

        # Assert 4:trigger_type / source_session_id / source_context 正确持久化
        assert persisted.trigger_type == "user_explicit_save"
        assert persisted.source_session_id == "sess-int-001"

        # source_context 是从 JSON 反序列化的 dict,字段全对
        ctx = persisted.source_context
        assert ctx["session_id"] == "sess-int-001"
        assert ctx["user_provided_name"] == "academic-search-cnki"
        assert ctx["user_provided_when_to_use"].startswith("当用户需要检索")
        # normalizer 把 tool_sequence 过滤干净后传给 review pipeline
        assert len(ctx["tool_calls"]) == 2
        assert ctx["tool_calls"][0]["tool"] == "web_fetch"
        assert ctx["tool_calls"][1]["tool"] == "ask_user_question"

        # Assert 5:created_at 写入了毫秒时间戳,review 字段为 NULL
        assert persisted.created_at > 0
        assert persisted.status == "pending"

        # 单独 query reviewed_at / reviewed_by_user_id 应该都是 NULL
        with sqlite3.connect(seeded_db) as conn:
            row = conn.execute(
                "SELECT reviewed_at, reviewed_by_user_id FROM skill_drafts WHERE id = ?",
                (draft_id,),
            ).fetchone()
        assert row == (None, None)
