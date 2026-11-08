"""AI 规则 patch 服务的单测（M5，2026-11-07）。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from backend.services import rule_patch
from backend.services.rule_patch import (
    MAX_CONTEXT_CHARS,
    MAX_PATCH_OPERATIONS,
    MAX_RULE_CHARS,
    PatchSchemaError,
    build_patch_prompt,
    build_rules_context,
    enrich_operations,
    parse_patch_response,
    preview_patch,
)
from backend.services.rules_registry import RuleEntry

PROJECT = SimpleNamespace(name="sage", project_type="coding")


def _entry(rule_id: str, **overrides) -> RuleEntry:
    values = {
        "id": rule_id,
        "layer": "constraint",
        "source_label": "项目规则",
        "scope": "全局",
        "category": "风格",
        "content": "统一使用 ruff",
        "editable": "full",
        "updated_at": 1730000000000,
    }
    values.update(overrides)
    return RuleEntry(**values)


class _Client:
    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    async def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.responses.pop(0)


def _add_op(content: str = "跑 pytest") -> dict:
    return {
        "op_id": "op-1",
        "action": "add",
        "layer": "constraint",
        "rule_id": None,
        "after": {"category": "测试", "content": content},
        "reason": "统一测试命令",
    }


def test_build_rules_context_respects_the_char_budget():
    entries = [
        _entry(f"constraint:{index}", content="规则内容" * 200)
        for index in range(40)
    ]

    context = build_rules_context(entries)

    assert len(context) <= MAX_CONTEXT_CHARS
    assert "[constraint]" in context
    assert "id=constraint:0" in context


def test_build_patch_prompt_embeds_instruction_and_limits():
    prompt = build_patch_prompt("sage", "coding", "把风格统一成 ruff", "[constraint] 风格")

    assert "把风格统一成 ruff" in prompt
    assert str(MAX_RULE_CHARS) in prompt
    assert "operations" in prompt


def test_parse_patch_response_rejects_an_unknown_action():
    raw = json.dumps({"operations": [{"action": "rename", "layer": "constraint"}]})

    with pytest.raises(PatchSchemaError):
        parse_patch_response(raw)


def test_parse_patch_response_rejects_non_json():
    with pytest.raises(PatchSchemaError):
        parse_patch_response("我来帮你改规则")


def test_parse_patch_response_caps_the_operation_count():
    operations = [_add_op() for _ in range(MAX_PATCH_OPERATIONS + 1)]

    with pytest.raises(PatchSchemaError):
        parse_patch_response(json.dumps({"operations": operations}))


def test_enrich_marks_playbook_operations_readonly():
    raw = parse_patch_response(
        json.dumps(
            {
                "operations": [
                    {"op_id": "op-1", "action": "update", "layer": "playbook", "rule_id": "playbook:design:0"}
                ]
            }
        )
    )

    enriched = enrich_operations(raw, [_entry("playbook:design:0", layer="playbook", editable="partial")])

    assert enriched[0].error == "readonly_layer"


def test_enrich_attaches_before_and_flags_missing_rules():
    raw = parse_patch_response(
        json.dumps(
            {
                "operations": [
                    {"op_id": "op-1", "action": "update", "layer": "constraint", "rule_id": "constraint:abc", "after": {"content": "用 black"}},
                    {"op_id": "op-2", "action": "delete", "layer": "constraint", "rule_id": "constraint:missing"},
                ]
            }
        )
    )

    enriched = enrich_operations(raw, [_entry("constraint:abc")])

    assert enriched[0].before["content"] == "统一使用 ruff"
    assert enriched[0].expected_updated_at == 1730000000000
    assert enriched[0].error is None
    assert enriched[1].error == "rule_not_found"


def test_enrich_rejects_oversize_content():
    raw = parse_patch_response(
        json.dumps(
            {
                "operations": [
                    {"op_id": "op-1", "action": "add", "layer": "constraint", "after": {"content": "x" * (MAX_RULE_CHARS + 1)}}
                ]
            }
        )
    )

    assert enrich_operations(raw, [_entry("constraint:abc")])[0].error == "content_too_long"


async def test_preview_retries_once_after_a_schema_failure():
    client = _Client(["不是 JSON", json.dumps({"operations": [_add_op()]})])

    result = await preview_patch(PROJECT, "加一条测试规则", [_entry("constraint:abc")], llm_client=client)

    assert len(client.prompts) == 2
    assert result["llm_available"] is True
    assert result["operations"][0]["after"]["content"] == "跑 pytest"
    assert result["operations"][0]["error"] is None


async def test_preview_reports_unavailable_llm(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(rule_patch, "_build_client", lambda: None)

    result = await preview_patch(PROJECT, "加一条规则", [_entry("constraint:abc")])

    assert result == {"llm_available": False, "message": "AI 暂不可用，可手动编辑", "operations": []}


async def test_preview_fails_explicitly_after_two_schema_errors():
    client = _Client(["不是 JSON", "还不是 JSON"])

    with pytest.raises(PatchSchemaError):
        await preview_patch(PROJECT, "加一条规则", [_entry("constraint:abc")], llm_client=client)
