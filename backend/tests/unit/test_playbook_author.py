"""Unit tests for AI-assisted playbook authoring (2026-10-31)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from backend.services.playbook_author import build_author_preview


class FakeLLM:
    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.prompts = []

    async def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
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


def _llm_payload() -> str:
    return json.dumps(
        {
            "rationale": "按学校要求划分三阶段",
            "playbook": {
                "schema_version": "1.0",
                "id": "custom-school-grant",
                "name": "学校课题规程",
                "description": "开题-中期-结题",
                "applies_to": {"project_types": ["research"], "sub_types": []},
                "directory_layout": [
                    {"path": "01_开题", "required": True, "purpose": "开题"}
                ],
                "stages": [
                    {
                        "id": "proposal",
                        "label": "开题",
                        "order": 1,
                        "artifacts": [
                            {
                                "id": "proposal_report",
                                "label": "开题报告",
                                "required": True,
                                "match": {"globs": ["**/开题报告*"]},
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


@pytest.mark.asyncio()
async def test_llm_authoring_returns_validated_spec() -> None:
    client = FakeLLM(_llm_payload())
    result = await build_author_preview(_project(), {"notes": "学校要求"}, llm_client=client)
    assert result.source == "llm"
    assert result.llm_available is True
    assert result.playbook["name"] == "学校课题规程"
    assert result.playbook["stages"][0]["id"] == "proposal"
    assert "学校要求" in client.prompts[0]


@pytest.mark.asyncio()
async def test_invalid_llm_output_falls_back() -> None:
    client = FakeLLM("这不是 JSON")
    result = await build_author_preview(
        _project(), {"name": "我的规程"}, llm_client=client
    )
    assert result.source == "deterministic"
    assert result.llm_available is False
    assert result.playbook["name"] == "我的规程"
    assert result.playbook["stages"]


@pytest.mark.asyncio()
async def test_deterministic_answers_build_stages() -> None:
    answers = {
        "name": "答辩规程",
        "stages": [
            {
                "id": "proposal",
                "label": "开题",
                "deliverables": ["开题报告", "文献综述"],
            },
            {"id": "defense", "label": "答辩", "deliverables": ["答辩PPT"]},
        ],
    }
    result = await build_author_preview(_project(), answers, use_llm=False)
    assert result.source == "deterministic"
    assert result.playbook["name"] == "答辩规程"
    labels = [stage["label"] for stage in result.playbook["stages"]]
    assert labels == ["开题", "答辩"]
    artifacts = result.playbook["stages"][0]["artifacts"]
    assert {item["label"] for item in artifacts} == {"开题报告", "文献综述"}


@pytest.mark.asyncio()
async def test_no_llm_uses_suggested_builtin_base() -> None:
    result = await build_author_preview(_project(), {}, use_llm=False)
    assert result.source == "deterministic"
    assert result.playbook["stages"][0]["id"] == "proposal"
