"""POST /api/v1/orch/plan-items —— 已批准计划文本 → 结构化编排任务项。

Round 2 (2026-09-19, docs/plans/2026-09-19_orch-plan-preflight-round2-plan.md):
- 占位依赖 idx:k → t{k+1} 映射；
- LLM 响应解析（围栏剥离 / 畸形 → None）；
- 端点行为：正常结构化 200 / 无 LLM 503 / 畸形输出 502 / 病态输入 422；
- 非法 agent_hint 落 default primary（sanitize_llm_plan_tasks 纪律）。
"""

from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest
from httpx import ASGITransport

from backend.api.orch_routes import (
    _parse_plan_items_response,
    placeholder_deps_to_ids,
)
from backend.main import app

pytestmark = pytest.mark.integration

PLAN_ITEMS_PATH = "/api/v1/orch/plan-items"


# ---------------------------------------------------------------------------
# 纯函数
# ---------------------------------------------------------------------------


def test_placeholder_deps_to_ids_maps_and_drops_junk():
    assert placeholder_deps_to_ids(["idx:0", "idx:2"]) == ["t1", "t3"]
    assert placeholder_deps_to_ids(["t1", "abc", "idx:x"]) == []
    assert placeholder_deps_to_ids([]) == []


def test_parse_plan_items_response_valid_with_fence():
    raw = "```json\n" + json.dumps(
        {
            "tasks": [
                {"id": "t1", "title": "调研", "description": "收集资料", "depends_on": []},
                {
                    "id": "t2",
                    "title": "写作",
                    "description": "成文",
                    "depends_on": ["t1"],
                    "agent_hint": "writer",
                },
            ],
            "reasoning": "先调研后写作",
        },
        ensure_ascii=False,
    ) + "\n```"
    parsed = _parse_plan_items_response(raw)
    assert parsed is not None
    tasks, reasoning = parsed
    assert [t["name"] for t in tasks] == ["调研", "写作"]
    assert tasks[1]["blocked_by"] == ["idx:0"]  # 只引更早任务的占位
    assert tasks[1]["parameters"]["agent_hint"] == "writer"
    assert reasoning == "先调研后写作"


def test_parse_plan_items_response_malforms_degrade_to_none():
    assert _parse_plan_items_response("不是 JSON") is None
    assert _parse_plan_items_response('{"tasks": []}') is None
    assert _parse_plan_items_response(None) is None
    assert _parse_plan_items_response('{"reasoning": "无任务"}') is None


def test_parse_plan_items_response_non_dispatchable_hint_dropped():
    raw = json.dumps(
        {
            "tasks": [
                {
                    "id": "t1",
                    "title": "x",
                    "description": "y",
                    "agent_hint": "不存在的角色",
                }
            ]
        },
        ensure_ascii=False,
    )
    parsed = _parse_plan_items_response(raw)
    assert parsed is not None
    tasks, _ = parsed
    assert tasks[0]["parameters"] == {}  # 非法 hint 静默丢弃 → 端点回退 primary


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------


def _valid_llm_response() -> str:
    return json.dumps(
        {
            "tasks": [
                {"id": "t1", "title": "调研", "description": "收集量化交易资料"},
                {
                    "id": "t2",
                    "title": "整理",
                    "description": "整理成学习指南",
                    "depends_on": ["t1"],
                    "agent_hint": "writer",
                },
            ],
            "reasoning": "先调研后整理",
        },
        ensure_ascii=False,
    )


class FakeLLM:
    def __init__(self, response: str):
        self._response = response

    async def complete(self, prompt: str) -> str:
        return self._response


@pytest.mark.asyncio()
async def test_plan_items_structures_approved_plan(monkeypatch):
    monkeypatch.setenv("SAGE_ORCH_PLAN_PREFLIGHT", "0")  # 与本端点无关，保持环境干净
    with patch(
        "backend.orchestration.llm_factory.build_llm_client_from_settings",
        return_value=FakeLLM(_valid_llm_response()),
    ):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.post(PLAN_ITEMS_PATH, json={"text": "## 分步计划\n1. 调研\n2. 整理"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [it["task_id"] for it in body["items"]] == ["t1", "t2"]
    assert body["items"][0]["agent_id"] == "primary"  # 无 hint → primary
    assert body["items"][1]["agent_id"] == "writer"
    assert body["items"][1]["depends_on"] == ["t1"]
    assert body["reasoning"] == "先调研后整理"
    # goal 自包含（执行者只能看到它）
    assert "学习指南" in body["items"][1]["goal"]


class RecordingLLM:
    def __init__(self, response: str):
        self._response = response
        self.prompts: list[str] = []

    async def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self._response


@pytest.mark.asyncio()
async def test_plan_items_with_current_plan_uses_revision_prompt():
    """current_plan 非空 → 修订语义：当前计划与修订说明都进入 prompt。"""
    llm = RecordingLLM(_valid_llm_response())
    current_plan = [
        {"task_id": "t1", "agent_id": "researcher", "goal": "调研量化交易资料"},
        {"task_id": "t2", "agent_id": "writer", "goal": "整理学习指南"},
    ]
    with patch(
        "backend.orchestration.llm_factory.build_llm_client_from_settings",
        return_value=llm,
    ):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.post(
                PLAN_ITEMS_PATH,
                json={"text": "把第 2 项拆成两步", "current_plan": current_plan},
            )

    assert resp.status_code == 200, resp.text
    assert len(llm.prompts) == 1
    prompt = llm.prompts[0]
    assert "编排计划修订助手" in prompt
    assert "调研量化交易资料" in prompt
    assert "整理学习指南" in prompt
    assert "把第 2 项拆成两步" in prompt
    assert "未提及的任务必须原样保留" in prompt
    assert "{current_plan}" not in prompt
    assert "{max_tasks}" not in prompt
    assert "{text}" not in prompt


@pytest.mark.asyncio()
async def test_plan_items_without_current_plan_keeps_first_time_prompt():
    """current_plan 缺省 → 首次拆解语义不变（向后兼容）。"""
    llm = RecordingLLM(_valid_llm_response())
    with patch(
        "backend.orchestration.llm_factory.build_llm_client_from_settings",
        return_value=llm,
    ):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.post(PLAN_ITEMS_PATH, json={"text": "1. 调研 2. 整理"})

    assert resp.status_code == 200, resp.text
    prompt = llm.prompts[0]
    assert "编排计划结构化助手" in prompt
    assert "编排计划修订助手" not in prompt


@pytest.mark.asyncio()
async def test_plan_items_503_without_llm(monkeypatch):
    monkeypatch.delenv("SAGE_ORCH_PLAN_PREFLIGHT", raising=False)
    with patch(
        "backend.orchestration.llm_factory.build_llm_client_from_settings",
        return_value=None,
    ):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.post(PLAN_ITEMS_PATH, json={"text": "计划"})
    assert resp.status_code == 503
    assert "no_llm_configured" in resp.json()["detail"]


@pytest.mark.asyncio()
async def test_plan_items_502_on_malformed_llm_output():
    with patch(
        "backend.orchestration.llm_factory.build_llm_client_from_settings",
        return_value=FakeLLM("垃圾输出，，"),
    ):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.post(PLAN_ITEMS_PATH, json={"text": "计划"})
    assert resp.status_code == 502
    assert "plan_items_parse_failed" in resp.json()["detail"]


@pytest.mark.asyncio()
async def test_plan_items_502_on_llm_error():
    class ExplodingLLM:
        async def complete(self, prompt: str) -> str:
            raise RuntimeError("upstream down")

    with patch(
        "backend.orchestration.llm_factory.build_llm_client_from_settings",
        return_value=ExplodingLLM(),
    ):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.post(PLAN_ITEMS_PATH, json={"text": "计划"})
    assert resp.status_code == 502
    assert "llm_call_failed" in resp.json()["detail"]


@pytest.mark.asyncio()
async def test_plan_items_422_on_pathological_input():
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        empty = await ac.post(PLAN_ITEMS_PATH, json={"text": ""})
        too_long = await ac.post(PLAN_ITEMS_PATH, json={"text": "x" * 20001})
    assert empty.status_code == 422
    assert too_long.status_code == 422


@pytest.mark.asyncio()
async def test_plan_items_422_on_current_plan_overflow():
    """修订通道 current_plan 上限（MEDIUM-4）：它会被 json.dumps 直接拼进
    prompt，不设上限时一个病态 body 能撑出百万 token 的 prompt。

    上限用显式运行时校验而非 pydantic Field(max_items=...) —— pydantic v1 的
    list 约束参数名是 max_items、v2 是 max_length，写字段约束会踩双版本差异。
    """
    from backend.api.orch_routes import MAX_CURRENT_PLAN_ITEMS

    overflow = [
        {"task_id": f"t{i}", "agent_id": "primary", "goal": f"g{i}"}
        for i in range(MAX_CURRENT_PLAN_ITEMS + 1)
    ]
    with patch(
        "backend.orchestration.llm_factory.build_llm_client_from_settings",
        return_value=FakeLLM(_valid_llm_response()),
    ):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            at_limit = await ac.post(
                PLAN_ITEMS_PATH,
                json={
                    "text": "改一下",
                    "current_plan": overflow[:MAX_CURRENT_PLAN_ITEMS],
                },
            )
            over = await ac.post(
                PLAN_ITEMS_PATH, json={"text": "改一下", "current_plan": overflow}
            )
    # 边界值本身合法（真实计划最多 ~10 项）
    assert at_limit.status_code == 200, at_limit.text
    assert over.status_code == 422
    assert "current_plan" in over.json()["detail"]
