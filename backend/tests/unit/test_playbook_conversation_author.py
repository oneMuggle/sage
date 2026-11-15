"""Unit tests for conversational playbook authoring (2026-11-14)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, List

import pytest

from backend.data import database as database_module
from backend.data.database import Database
from backend.data.playbook_author_conversation_repo import (
    PlaybookAuthorConversationRepository,
)
from backend.data.playbook_repo import PlaybookRepository
from backend.data.project_repo import ProjectRepository
from backend.services.playbook_conversation_author import (
    MAX_TURNS,
    PlaybookConversationAuthor,
)


class FakeLLM:
    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.prompts: List[str] = []

    async def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def _project() -> SimpleNamespace:
    return SimpleNamespace(
        id="proj-1",
        name="示例课题",
        project_type="research",
        project_sub_type="grant_proposal",
        description="示例描述",
        detected_type=None,
    )


def _llm_payload(stage_label: str = "评审") -> str:
    return json.dumps(
        {
            "reply": "已把评审阶段加进来。",
            "playbook": {
                "schema_version": "1.0",
                "id": "custom-review",
                "name": "评审规程",
                "description": "开题-实施-评审",
                "applies_to": {"project_types": ["research"], "sub_types": []},
                "directory_layout": [],
                "stages": [
                    {
                        "id": "review",
                        "label": stage_label,
                        "order": 1,
                        "artifacts": [
                            {
                                "id": "review_report",
                                "label": "评审意见",
                                "required": True,
                                "match": {"globs": ["**/评审*"]},
                            }
                        ],
                    }
                ],
                "global_rules": [],
                "todos": [],
                "ai_guidance": {},
                "meta": {},
            },
        },
        ensure_ascii=False,
    )


def _serialized(spec: Any) -> str:
    return json.dumps(spec, sort_keys=True, ensure_ascii=False)


@pytest.fixture()
def db(monkeypatch: pytest.MonkeyPatch) -> Database:
    test_db = Database(":memory:")
    test_db.init_db()
    monkeypatch.setattr(database_module, "_db", test_db)
    return test_db


@pytest.fixture()
def author(db: Database) -> PlaybookConversationAuthor:
    return PlaybookConversationAuthor()


@pytest.mark.asyncio()
async def test_start_seeds_reference_draft(author, db) -> None:
    conversation = await author.start(_project())
    assert conversation.status == "active"
    assert len(conversation.messages) == 1
    seed = conversation.messages[0]
    assert seed["role"] == "assistant"
    assert seed["turn_index"] == 0
    assert seed["playbook_snapshot"] == conversation.current_spec
    assert conversation.current_spec
    assert conversation.current_spec["stages"]
    assert isinstance(seed["created_at"], int)
    persisted = PlaybookAuthorConversationRepository().get(conversation.id)
    assert persisted is not None
    assert persisted.project_id == "proj-1"


@pytest.mark.asyncio()
async def test_deterministic_turn_keeps_draft(author) -> None:
    conversation = await author.start(_project())
    before = _serialized(conversation.current_spec)
    result = await author.send_message(
        _project(), conversation, "  这是一个需要中期检查的项目  ", use_llm=False
    )
    assert result.turn_index == 1
    assert result.source == "deterministic"
    assert result.llm_available is False
    assert _serialized(result.playbook) == before
    assert [item["role"] for item in result.conversation["messages"]] == [
        "assistant",
        "user",
        "assistant",
    ]
    user_message = result.conversation["messages"][1]
    assert user_message["content"] == "这是一个需要中期检查的项目"
    assert user_message["playbook_snapshot"] is None


@pytest.mark.asyncio()
async def test_blank_message_rejected(author) -> None:
    conversation = await author.start(_project())
    with pytest.raises(ValueError, match="消息不能为空"):
        await author.send_message(_project(), conversation, "   ")


@pytest.mark.asyncio()
async def test_llm_turn_updates_draft(author) -> None:
    conversation = await author.start(_project())
    client = FakeLLM(_llm_payload())
    result = await author.send_message(
        _project(), conversation, "加一个评审阶段", llm_client=client
    )
    assert result.source == "llm"
    assert result.llm_available is True
    assert result.reply == "已把评审阶段加进来。"
    assert result.playbook["id"] == "custom-review"
    assert conversation.current_spec["id"] == "custom-review"
    assistant = conversation.messages[-1]
    assert assistant["playbook_snapshot"]["stages"][0]["label"] == "评审"
    assert "加一个评审阶段" in client.prompts[0]


@pytest.mark.asyncio()
async def test_llm_failure_keeps_draft(author) -> None:
    conversation = await author.start(_project())
    before = _serialized(conversation.current_spec)
    client = FakeLLM(RuntimeError("upstream 500"))
    result = await author.send_message(
        _project(), conversation, "加一个评审阶段", llm_client=client
    )
    assert result.source == "deterministic"
    assert result.llm_available is False
    assert _serialized(result.playbook) == before
    assert len(conversation.messages) == 3


@pytest.mark.asyncio()
async def test_rollback_restores_seeded_draft(author) -> None:
    conversation = await author.start(_project())
    base_id = conversation.current_spec["id"]
    await author.send_message(
        _project(), conversation, "加一个评审阶段", llm_client=FakeLLM(_llm_payload())
    )
    assert conversation.current_spec["id"] == "custom-review"

    restored, spec = author.rollback(conversation, 0)
    assert spec["id"] == base_id
    assert len(restored.messages) == 1
    persisted = PlaybookAuthorConversationRepository().get(restored.id)
    assert persisted is not None
    assert len(persisted.messages) == 1
    assert persisted.current_spec["id"] == base_id


@pytest.mark.asyncio()
async def test_rollback_to_previous_llm_turn(author) -> None:
    conversation = await author.start(_project())
    await author.send_message(
        _project(), conversation, "第一轮", llm_client=FakeLLM(_llm_payload("设计"))
    )
    await author.send_message(
        _project(), conversation, "第二轮", llm_client=FakeLLM(_llm_payload("评审"))
    )
    restored, spec = author.rollback(conversation, 1)
    assert spec["stages"][0]["label"] == "设计"
    assert len(restored.messages) == 3


@pytest.mark.asyncio()
async def test_rollback_unknown_turn_raises(author) -> None:
    conversation = await author.start(_project())
    with pytest.raises(ValueError, match="没有可回退的规程快照"):
        author.rollback(conversation, 7)


@pytest.mark.asyncio()
async def test_commit_binds_snapshot(author, tmp_path) -> None:
    root = tmp_path / "demo"
    root.mkdir()
    project = ProjectRepository().register(str(root), project_type="research")
    conversation = await author.start(project)
    result = author.commit(conversation.project_id, conversation)
    assert result["conversation"]["status"] == "committed"
    snapshot = result["snapshot"]
    assert snapshot["source"] == "ai-authored"
    assert snapshot["version"] == 1
    active = PlaybookRepository().get_active(conversation.project_id)
    assert active is not None
    assert active.spec["id"] == conversation.current_spec["id"]


@pytest.mark.asyncio()
async def test_commit_without_draft_raises(author) -> None:
    conversation = await author.start(_project())
    conversation.current_spec = None
    with pytest.raises(ValueError, match="还没有可绑定的规程草案"):
        author.commit(conversation.project_id, conversation)


@pytest.mark.asyncio()
async def test_turn_limit_enforced(author) -> None:
    conversation = await author.start(_project())
    conversation.messages = [
        {
            "role": "assistant",
            "content": "seed",
            "turn_index": MAX_TURNS,
            "playbook_snapshot": None,
            "created_at": 0,
        }
    ]
    with pytest.raises(ValueError, match="上限"):
        await author.send_message(_project(), conversation, "继续", use_llm=False)
