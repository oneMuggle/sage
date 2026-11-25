"""Unit tests for the AI refine engine (rule_refine_llm)."""

from __future__ import annotations

import json
from typing import Any, List

import pytest

from backend.office.rule_refine_llm import (
    RefineError,
    normalize_actions,
    parse_refine_payload,
    refine_rules,
)

CURRENT_RULES: List[dict] = [
    {
        "temp_id": "draft_0",
        "name": "正文字体",
        "kind": "style.font",
        "params": {"cjk_font": "宋体", "size_pt": 12},
        "severity": "warning",
        "description": "",
        "ai_prompt": "检查正文字体",
        "type": "format",
        "scope": "body",
    },
    {
        "temp_id": "draft_1",
        "name": "行间距",
        "kind": "style.paragraph",
        "params": {"line_spacing_pt": 20},
        "severity": "warning",
        "description": "",
        "ai_prompt": "检查行间距",
        "type": "format",
        "scope": "body",
    },
]


class FakeClient:
    """Minimal async LLM client stub returning a canned response."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: List[str] = []

    async def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


def test_parse_refine_payload_tolerates_markdown_fences() -> None:
    text = '```json\n[{"type":"explain","explanation":"ok"}]\n```'
    assert parse_refine_payload(text) == [{"type": "explain", "explanation": "ok"}]


def test_parse_refine_payload_rejects_non_array() -> None:
    with pytest.raises(RefineError):
        parse_refine_payload('{"type":"explain"}')


def test_normalize_actions_validates_temp_ids_and_patches() -> None:
    items: List[Any] = [
        {"type": "modify", "temp_id": "draft_1", "patch": {"params": {"line_spacing": 1.5}}},
        {"type": "modify", "temp_id": "draft_missing", "patch": {"name": "x"}},
        {"type": "delete", "temp_id": "draft_0"},
        {"type": "delete", "temp_id": "nope"},
        {"type": "add", "rule": {"name": "参考文献格式", "kind": "content.citation"}},
        {"type": "add", "rule": {}},  # missing name → rejected
        {"type": "explain", "explanation": "说明"},
        {"type": "bogus"},
        "not-an-object",
    ]
    actions, rejected = normalize_actions(items, CURRENT_RULES)

    assert rejected == 5  # missing temp_id, nope, empty add, bogus, non-object
    assert [action["type"] for action in actions] == ["modify", "delete", "add", "explain"]
    add_action = actions[2]
    assert add_action["rule"]["name"] == "参考文献格式"
    assert add_action["rule"]["severity"] == "warning"
    assert add_action["rule"]["type"] == "custom"
    assert add_action["rule"]["scope"] == "body"
    assert add_action["rule"]["ai_prompt"]  # synthesized fallback


def test_normalize_actions_sanitizes_invalid_patch_values() -> None:
    items = [
        {
            "type": "modify",
            "temp_id": "draft_0",
            "patch": {"severity": "fatal", "scope": "nonsense", "params": "nope"},
        }
    ]
    actions, rejected = normalize_actions(items, CURRENT_RULES)
    # Only invalid values were in the patch → patch empty → action rejected.
    assert rejected == 1
    assert actions == []


@pytest.mark.asyncio()
async def test_refine_rules_end_to_end_with_fake_client() -> None:
    response = json.dumps(
        [
            {
                "type": "modify",
                "temp_id": "draft_1",
                "patch": {"params": {"line_spacing": 1.5}},
                "explanation": "改为 1.5 倍行距",
            },
            {
                "type": "add",
                "rule": {"name": "参考文献格式", "kind": "content.citation"},
                "explanation": "补充引用规范",
            },
        ],
        ensure_ascii=False,
    )
    client = FakeClient(response)
    actions, warnings = await refine_rules(
        CURRENT_RULES, "行间距改成1.5倍，并加上参考文献格式要求", client=client
    )

    assert warnings == []
    assert [action["type"] for action in actions] == ["modify", "add"]
    assert actions[0]["patch"] == {"params": {"line_spacing": 1.5}}
    # The prompt carries the current rules and the instruction.
    assert "draft_0" in client.prompts[0]
    assert "行间距改成1.5倍" in client.prompts[0]
    # Doubled braces must be collapsed by .format(), not leaked to the LLM.
    assert "{{" not in client.prompts[0]
    assert "}}" not in client.prompts[0]


@pytest.mark.asyncio()
async def test_refine_rules_degrades_on_llm_failure() -> None:
    class BoomClient:
        async def complete(self, prompt: str) -> str:  # noqa: ARG002
            raise RuntimeError("connection reset")

    actions, warnings = await refine_rules(CURRENT_RULES, "改一下", client=BoomClient())
    assert actions == []
    assert warnings
    assert warnings[0]["code"] == "llm_failed"


@pytest.mark.asyncio()
async def test_refine_rules_reports_parse_failure() -> None:
    client = FakeClient("这不是 JSON")
    actions, warnings = await refine_rules(CURRENT_RULES, "改一下", client=client)
    assert actions == []
    assert warnings
    assert warnings[0]["code"] == "llm_parse_failed"
