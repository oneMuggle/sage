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
