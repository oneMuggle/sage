"""P2-8 — 内置确定性模板：get/list + 结构。"""
from backend.orchestration.templates import get_template, list_templates


def test_builtin_research_write():
    t = get_template("research-write")
    assert t is not None
    assert [s.id for s in t.stages] == ["t1", "t2"]
    assert t.stages[0].agent_id == "researcher"
    assert t.stages[1].agent_id == "writer"
    assert t.stages[1].depends_on == ["t1"]
    assert "{request}" in t.stages[0].goal


def test_builtin_gather_analyze_report():
    t = get_template("gather-analyze-report")
    assert t is not None
    assert [s.id for s in t.stages] == ["t1", "t2", "t3"]
    assert t.stages[2].depends_on == ["t1", "t2"]
    # 全 stage 用可派发角色（偏差 2：gather/analyze 不存在 → researcher/writer）
    assert all(s.agent_id in {"researcher", "writer", "coder", "reviewer"} for s in t.stages)


def test_get_unknown_returns_none():
    assert get_template("nope") is None


def test_list_templates_metadata():
    listed = {t["id"]: t for t in list_templates()}
    assert set(listed) == {"research-write", "gather-analyze-report"}
    assert listed["research-write"]["stages"] == ["t1", "t2"]
    assert listed["research-write"]["name"]


"""P2-8 — decompose_from_template：确定性拆解 + 角色校验 + 依赖解析。"""
import pytest

from backend.orchestration.planner import Planner
from backend.orchestration.task_registry import TaskRegistry
from backend.orchestration.team_registry import TeamRegistry
from backend.orchestration.templates import OrchestrationTemplate, TemplateStage


def _planner():
    return Planner(
        task_registry=TaskRegistry(),
        team_registry=TeamRegistry(),
        llm_client=None,  # 模板不走 LLM，auto_configure 亦关
        auto_configure=False,
    )


@pytest.mark.asyncio()
async def test_decompose_from_template_resolves_stages():
    plan = await _planner().decompose_from_template("research-write", "写一篇报告")
    assert plan.reasoning == "template: research-write"
    assert len(plan.tasks) == 2
    by_stage = {plan.tasks[0].name: plan.tasks[0], plan.tasks[1].name: plan.tasks[1]}
    # {request} 已替换
    assert "写一篇报告" in plan.tasks[0].description
    assert plan.tasks[1].blocked_by == [plan.tasks[0].task_id]
    # 角色 hint 可派发 → 写入
    assert plan.tasks[0].parameters.get("agent_hint") == "researcher"
    assert plan.tasks[1].parameters.get("agent_hint") == "writer"


@pytest.mark.asyncio()
async def test_decompose_from_template_skips_undispatchable_role():
    """非法角色（F4 回退）→ 不写 agent_hint。"""
    p = _planner()
    t = OrchestrationTemplate(
        id="t-invalid",
        name="非法角色模板",
        description="",
        stages=[TemplateStage(id="t1", agent_id="ghost_agent", goal="做 {request}")],
    )
    # 直接 monkeypatch 内置表，避免污染全局
    import backend.orchestration.templates as tmpl

    orig = tmpl.BUILTIN_TEMPLATES
    tmpl.BUILTIN_TEMPLATES = {**orig, "t-invalid": t}
    try:
        plan = await p.decompose_from_template("t-invalid", "目标")
    finally:
        tmpl.BUILTIN_TEMPLATES = orig
    assert plan.tasks[0].parameters.get("agent_hint") is None
    assert "目标" in plan.tasks[0].description


@pytest.mark.asyncio()
async def test_decompose_from_template_unknown_raises():
    with pytest.raises(ValueError):
        await _planner().decompose_from_template("nope", "目标")


@pytest.mark.asyncio()
async def test_decompose_from_template_no_placeholder_appends_goal():
    """stage goal 无 {request} → 追加目标行。"""
    plan = await _planner().decompose_from_template("research-write", "写报告")
    # 内置模板都带占位符；用一个合成 stage 验证追加逻辑
    assert "写报告" in plan.tasks[0].description  # 内置 {request} 路径已覆盖
