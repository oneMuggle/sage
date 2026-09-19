"""plan_preflight 单测 —— 编排拆解前的澄清门 + 侦察先行（2026-09-19）。

覆盖契约面：
- 总闸/旋钮关闭、无 LLM、gate 缺失、畸形 LLM 输出 → 一律降级为 None；
- 澄清闭环：need_clarify → ask_user_question 事件 → gate 应答 → 结论注入；
- 澄清超时 → 写"按合理默认执行"假设（fail-open，不阻塞）；
- 侦察：事实截断 + 超时跳过 + _run_scout_agent 的 done 提取与工作区清理。
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

import pytest

from backend.orchestration import plan_preflight
from backend.orchestration.orch_settings import OrchSettings
from backend.services.question_gate import UserQuestionGate

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# 测试替身
# ---------------------------------------------------------------------------


class FakeLLM:
    """按序返回 canned 响应的 LLM client 桩。"""

    def __init__(self, *responses: str):
        self._responses = list(responses)
        self.prompts: list[str] = []

    async def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self._responses:
            raise AssertionError("FakeLLM 收到超出预期的调用")
        return self._responses.pop(0)


def _default_settings(**overrides) -> OrchSettings:
    settings = OrchSettings()
    for key, value in overrides.items():
        setattr(settings, key, value)
    return settings


def _enable(monkeypatch, client=None, **settings_overrides) -> None:
    """开启 preflight 的公共样板：env 总闸 + 隔离 settings/LLM 工厂读取。

    ``client`` 非 None 时 patch ``build_llm_client_from_settings`` 返回它
    （``run_plan_preflight`` 内部经工厂自建 client，测试注入桩）。
    """
    monkeypatch.setenv("SAGE_ORCH_PLAN_PREFLIGHT", "1")
    monkeypatch.setattr(
        plan_preflight, "load_orch_settings", lambda: _default_settings(**settings_overrides)
    )
    if client is not None:
        from backend.orchestration import llm_factory

        monkeypatch.setattr(llm_factory, "build_llm_client_from_settings", lambda: client)


async def _collect_emit(events: list) -> None:
    async def _emit(event) -> None:
        events.append(event)

    return _emit


# ---------------------------------------------------------------------------
# 降级纪律
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_master_switch_off_returns_none_without_llm_call(monkeypatch):
    """总闸关闭（tests conftest 默认态）→ 直接 None，零副作用。"""
    monkeypatch.delenv("SAGE_ORCH_PLAN_PREFLIGHT", raising=False)
    monkeypatch.setenv("SAGE_ORCH_PLAN_PREFLIGHT", "0")
    events: list = []
    result = await plan_preflight.run_plan_preflight(
        "复杂目标", emit=await _collect_emit(events)
    )
    assert result is None
    assert events == []


@pytest.mark.asyncio()
async def test_no_llm_client_returns_none(monkeypatch):
    """无 LLM 配置 → None（与 Planner 的 single-task 降级同口径）。"""
    _enable(monkeypatch)

    from backend.orchestration import llm_factory

    monkeypatch.setattr(llm_factory, "build_llm_client_from_settings", lambda: None)
    result = await plan_preflight.run_plan_preflight("复杂目标", emit=None)
    assert result is None


@pytest.mark.asyncio()
async def test_settings_knob_off_returns_none(monkeypatch):
    """orch 段 planPreflightEnabled=false → None（env 总闸开也停）。"""
    _enable(monkeypatch, plan_preflight_enabled=False)
    result = await plan_preflight.run_plan_preflight("复杂目标", emit=None)
    assert result is None


@pytest.mark.asyncio()
async def test_blank_message_returns_none(monkeypatch):
    _enable(monkeypatch)
    result = await plan_preflight.run_plan_preflight("   ", emit=None)
    assert result is None


# ---------------------------------------------------------------------------
# 澄清门
# ---------------------------------------------------------------------------


_CLARIFY_JSON = json.dumps(
    {
        "need_clarify": True,
        "questions": [
            {
                "question": "最终交付什么格式？",
                "header": "交付格式",
                "multi_select": False,
                "options": [
                    {"label": "Markdown 文档", "description": None},
                    {"label": "Word 文档", "description": None},
                ],
            }
        ],
    },
    ensure_ascii=False,
)


@pytest.mark.asyncio()
async def test_clarify_full_loop_collects_answer(monkeypatch):
    """need_clarify → ask_user_question 事件 → gate 应答 → 结论注入 context。"""
    client = FakeLLM(_CLARIFY_JSON)
    _enable(monkeypatch, client=client, plan_scout_enabled=False)
    gate = UserQuestionGate()

    async def _answer_when_pending() -> None:
        for _ in range(500):
            await asyncio.sleep(0.01)
            pending = gate.pending()
            if pending:
                gate.answer(pending[0].request_id, answers=["Markdown 文档"])
                return
        raise AssertionError("澄清提问未出现在 gate 中")

    monkeypatch.setattr(plan_preflight, "get_question_gate", lambda: gate)
    asyncio.get_running_loop().create_task(_answer_when_pending())

    events: list = []
    result = await plan_preflight.run_plan_preflight(
        "整理一份学习资料", emit=await _collect_emit(events)
    )

    assert result is not None
    clarifications = result["clarifications"]
    assert len(clarifications) == 1
    assert "最终交付什么格式" in clarifications[0]
    assert "Markdown 文档" in clarifications[0]

    states = [e["state"] for e in events]
    assert states[0] == "orch_preflight"
    assert events[0]["phase"] == "clarify"
    ask_events = [e for e in events if e["state"] == "ask_user_question"]
    assert len(ask_events) == 1
    assert ask_events[0]["user_question"]["question"] == "最终交付什么格式？"


@pytest.mark.asyncio()
async def test_clarify_not_needed_skips_questions(monkeypatch):
    client = FakeLLM(json.dumps({"need_clarify": False, "questions": []}))
    _enable(monkeypatch, client=client, plan_scout_enabled=False)
    monkeypatch.setattr(
        plan_preflight, "get_question_gate", lambda: UserQuestionGate()
    )

    events: list = []
    result = await plan_preflight.run_plan_preflight(
        "目标明确", emit=await _collect_emit(events)
    )
    assert result is None
    assert not [e for e in events if e["state"] == "ask_user_question"]


@pytest.mark.asyncio()
async def test_clarify_malformed_llm_output_degrades(monkeypatch):
    """畸形输出（非 JSON）→ 无提问、整体 None，绝不抛错。"""
    client = FakeLLM("这不是 JSON，，，")
    _enable(monkeypatch, client=client, plan_scout_enabled=False)
    monkeypatch.setattr(
        plan_preflight, "get_question_gate", lambda: UserQuestionGate()
    )
    result = await plan_preflight.run_plan_preflight("目标", emit=None)
    assert result is None


@pytest.mark.asyncio()
async def test_clarify_llm_failure_degrades(monkeypatch):
    """澄清判定 LLM 调用抛错 → 跳过澄清，不阻塞。"""

    class ExplodingLLM:
        async def complete(self, prompt: str) -> str:
            raise RuntimeError("upstream down")

    client = ExplodingLLM()
    _enable(monkeypatch, client=client, plan_scout_enabled=False)
    monkeypatch.setattr(
        plan_preflight, "get_question_gate", lambda: UserQuestionGate()
    )
    result = await plan_preflight.run_plan_preflight("目标", emit=None)
    assert result is None


@pytest.mark.asyncio()
async def test_clarify_gate_missing_skips(monkeypatch):
    """gate 未装配 → 在 LLM 判定调用之前就跳过（省一次无谓往返），不挂起。"""
    client = FakeLLM(_CLARIFY_JSON)
    _enable(monkeypatch, client=client, plan_scout_enabled=False)
    monkeypatch.setattr(plan_preflight, "get_question_gate", lambda: None)
    result = await plan_preflight.run_plan_preflight("目标", emit=None)
    assert result is None
    assert client.prompts == []  # gate 缺失 → 连判定调用都不发


@pytest.mark.asyncio()
async def test_clarify_timeout_writes_assumption(monkeypatch):
    """提问超时 → fail-open：注入"按合理默认执行并写明假设"结论。"""
    client = FakeLLM(_CLARIFY_JSON)
    _enable(monkeypatch, client=client, plan_scout_enabled=False)
    monkeypatch.setenv("SAGE_ORCH_CLARIFY_TIMEOUT", "0.05")
    monkeypatch.setattr(
        plan_preflight, "get_question_gate", lambda: UserQuestionGate()
    )
    result = await plan_preflight.run_plan_preflight("目标", emit=None)
    assert result is not None
    assert any("合理默认值" in c for c in result["clarifications"])


@pytest.mark.asyncio()
async def test_clarify_invalid_questions_filtered(monkeypatch):
    """options 不合法的问题被过滤（validate_ask_user_args 校验），不炸 UI。"""
    bad_json = json.dumps(
        {
            "need_clarify": True,
            "questions": [
                {"question": "只有一个选项", "options": [{"label": "A"}]},
                {"question": "", "options": [{"label": "A"}, {"label": "B"}]},
            ],
        },
        ensure_ascii=False,
    )
    client = FakeLLM(bad_json)
    _enable(monkeypatch, client=client, plan_scout_enabled=False)
    monkeypatch.setattr(
        plan_preflight, "get_question_gate", lambda: UserQuestionGate()
    )
    result = await plan_preflight.run_plan_preflight("目标", emit=None)
    assert result is None


# ---------------------------------------------------------------------------
# 侦察先行
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_scout_facts_injected_and_truncated(monkeypatch):
    """侦察产出注入 context 并截断到 SCOUT_FACTS_MAX_CHARS。"""
    client = FakeLLM(json.dumps({"need_clarify": False, "questions": []}))
    _enable(monkeypatch, client=client, plan_scout_enabled=True)
    monkeypatch.setattr(
        plan_preflight, "get_question_gate", lambda: UserQuestionGate()
    )

    async def fake_scout_agent(client, goal):
        assert "工作区调研任务" in goal  # 侦察目标含用户 message
        return "f" * (plan_preflight.SCOUT_FACTS_MAX_CHARS + 100)

    monkeypatch.setattr(plan_preflight, "_run_scout_agent", fake_scout_agent)

    result = await plan_preflight.run_plan_preflight("工作区调研任务", emit=None)
    assert result is not None
    assert len(result["scout_facts"]) == plan_preflight.SCOUT_FACTS_MAX_CHARS


@pytest.mark.asyncio()
async def test_scout_disabled_by_settings(monkeypatch):
    client = FakeLLM(json.dumps({"need_clarify": False, "questions": []}))
    _enable(monkeypatch, client=client, plan_scout_enabled=False)
    monkeypatch.setattr(
        plan_preflight, "get_question_gate", lambda: UserQuestionGate()
    )

    async def _fail(*args, **kwargs):
        raise AssertionError("plan_scout_enabled=False 时不应派侦察")

    monkeypatch.setattr(plan_preflight, "_run_scout_agent", _fail)
    result = await plan_preflight.run_plan_preflight("目标", emit=None)
    assert result is None


@pytest.mark.asyncio()
async def test_scout_timeout_degrades(monkeypatch):
    """侦察墙钟超时 → 跳过事实注入，不阻塞拆解。"""
    client = FakeLLM(json.dumps({"need_clarify": False, "questions": []}))
    _enable(monkeypatch, client=client, plan_scout_enabled=True)
    monkeypatch.setenv("SAGE_ORCH_SCOUT_TIMEOUT", "0.05")
    monkeypatch.setattr(
        plan_preflight, "get_question_gate", lambda: UserQuestionGate()
    )

    async def slow_scout(client, goal):
        await asyncio.sleep(5)
        return "too late"

    monkeypatch.setattr(plan_preflight, "_run_scout_agent", slow_scout)
    result = await plan_preflight.run_plan_preflight("目标", emit=None)
    assert result is None


@pytest.mark.asyncio()
async def test_scout_failure_degrades(monkeypatch):
    client = FakeLLM(json.dumps({"need_clarify": False, "questions": []}))
    _enable(monkeypatch, client=client, plan_scout_enabled=True)
    monkeypatch.setattr(
        plan_preflight, "get_question_gate", lambda: UserQuestionGate()
    )

    async def broken_scout(client, goal):
        raise RuntimeError("scout crashed")

    monkeypatch.setattr(plan_preflight, "_run_scout_agent", broken_scout)
    result = await plan_preflight.run_plan_preflight("目标", emit=None)
    assert result is None


@pytest.mark.asyncio()
async def test_run_scout_agent_extracts_done_and_cleans_workspace(monkeypatch):
    """_run_scout_agent：done 事件取答案；finally 清理只读工作区。"""
    from backend.core.legacy import agent as agent_module

    cleaned: list = []
    monkeypatch.setattr(
        "backend.tools.agent_tool._cleanup_subagent_workspace",
        lambda root: cleaned.append(root),
    )

    class FakeSubagent:
        def __init__(self, *args, **kwargs):
            self.tool_registry = None
            self.llm_client = None
            # _run_scout_agent 会用只读注册表的 owned root 覆盖此值
            self._owned_workspace_root = None
            self.run_loop_kwargs = None

        async def run_loop(self, messages, max_iterations=6, **kwargs):
            self.run_loop_kwargs = {"max_iterations": max_iterations}
            assert messages[0]["role"] == "system"
            assert "侦察" in messages[0]["content"]

            class _Ev:
                state = "done"
                content = "关键事实清单"

            yield _Ev()

    monkeypatch.setattr(agent_module, "SageAgent", FakeSubagent)

    answer = await plan_preflight._run_scout_agent(object(), "目标")
    assert answer == "关键事实清单"
    # 清理拿到的是只读注册表创建的临时工作区（真实 Path），且只清一次
    assert len(cleaned) == 1
    assert cleaned[0] is not None


# ---------------------------------------------------------------------------
# Planner prompt 渲染（plan_preflight 注入的具名 context）
# ---------------------------------------------------------------------------


def _bare_planner():
    from backend.orchestration.planner import Planner

    return Planner(
        task_registry=MagicMock(),
        team_registry=MagicMock(),
        llm_client=None,
        auto_configure=False,
    )


def test_decomposition_prompt_renders_preflight_sections():
    prompt = _bare_planner()._build_decomposition_prompt(
        "整理学习资料",
        {
            "clarifications": ["问: 交付格式？\n用户已回答:\n- Markdown 文档"],
            "scout_facts": "1. 工作区含 backend/ 目录",
            "custom": {"k": 1},
        },
    )
    assert "侦察发现" in prompt
    assert "1. 工作区含 backend/ 目录" in prompt
    assert "用户澄清结论" in prompt
    assert "Markdown 文档" in prompt
    assert "必须遵守" in prompt  # 拆解约束提示
    assert "其他上下文" in prompt  # 其余键维持 JSON dump
    assert '"k": 1' in prompt


def test_decomposition_prompt_without_preflight_context():
    prompt = _bare_planner()._build_decomposition_prompt("目标", None)
    assert "Context:\nNone" in prompt
    assert "侦察发现" not in prompt
    assert "用户澄清结论" not in prompt
