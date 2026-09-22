"""ci-rerun.yml（round45 / SOP §4.2）— 结构契约测试。

保证「CI 事件去重流程化」的手动重验 workflow 始终：
1) 触发器只有 ref/target 两个输入；
2) backend 套件按 target 语义分流（win7→py38 套件，main→py3.11 套件）；
3) frontend 与 electron-smoke 永远运行（必过项）；
4) all-green 汇总门检查全部四个结果。
"""

from pathlib import Path

import yaml

WORKFLOW = Path(__file__).parents[2] / ".github" / "workflows" / "ci-rerun.yml"


def load():
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    on = data.get(True) or data.get("on")  # YAML 1.1 把裸 on 解析为布尔键
    return data, on


def test_trigger_inputs():
    _data, on = load()
    inputs = on["workflow_dispatch"]["inputs"]
    assert set(inputs.keys()) == {"ref", "target"}
    assert inputs["target"]["options"] == ["main", "release/win7"]


def test_backend_jobs_split_by_target():
    data, _on = load()
    jobs = data["jobs"]
    assert jobs["backend-py38"]["if"].strip() == "inputs.target == 'release/win7'"
    assert jobs["backend"]["if"].strip() == "inputs.target == 'main'"


def test_frontend_and_smoke_always_run():
    data, _on = load()
    for job in ("frontend", "electron-smoke"):
        assert "if" not in data["jobs"][job], job


def test_all_green_gate_aggregates_all():
    data, _on = load()
    gate = data["jobs"]["all-green"]
    assert set(gate["needs"]) >= {
        "backend",
        "backend-py38",
        "frontend",
        "electron-smoke",
    }
    run = gate["steps"][0]["run"]
    for key in (
        "needs.backend.result",
        "needs.backend-py38.result",
        "needs.frontend.result",
        "needs.electron-smoke.result",
    ):
        assert key in run
