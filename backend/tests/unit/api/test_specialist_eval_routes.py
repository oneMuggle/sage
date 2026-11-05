# ruff: noqa: UP006, UP007 — release/win7 Python 3.8 兼容
"""M4-T4 — 黄金任务集评测路由测试（GET /specialists/golden-tasks、
POST /specialists/{agent_id}/eval）。

使用真实临时库（conftest autouse ``setup_test_db``）与最小 FastAPI app。
``default_llm_runner`` 全部 monkeypatch 为假 runner，**CI 不发真实网络请求**。
覆盖：
- 任务目录返回 10 个任务 / 5 个模板 id
- 评测返回 run_id + 报告（全通过 10/10、tokens 聚合）
- 未知专家 404；非模板实例化 400；非法 body 422
- ``task_ids`` 子集过滤；无 body = 跑全部
- 报告落库 ``agent_eval_runs``（template_id / created_at / report JSON）
- runner 全部异常不 5xx，errored 计数正确
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.specialist_routes import router as specialist_router

pytestmark = pytest.mark.unit

#: 覆盖全部 10 个任务 checks 的通用输出（不含任何 forbidden / refusal 词）
PASSING_OUTPUT = (
    "教育 AI 教学 React Vue Svelte 响应式 运行时\n"
    "量子计算 密码 后量子 Shor\n"
    "def get def put class LRUCache O(1) 时间复杂度\n"
    "SELECT orders ROW_NUMBER\n"
    "融资 产品 市场 增长 团队\n"
    "大模型 代码审查 今天 议程 分享\n"
    "远程 生产力 建议 数据\n"
    "季度 销售 Excel 地区 销售人员 列 字段\n"
    "理解 感谢 歉意"
)


@pytest.fixture()
def client(tmp_path, monkeypatch) -> TestClient:
    root = tmp_path / "specialists"
    root.mkdir()
    monkeypatch.setenv("SAGE_SPECIALISTS_DIR", str(root))
    app = FastAPI()
    app.include_router(specialist_router)
    return TestClient(app)


def _upsert_agent(agent_id: str, name: str = "写作专家") -> None:
    from backend.data.agent_repo import AgentRepository

    AgentRepository().upsert(
        {
            "id": agent_id,
            "name": name,
            "role": "specialist",
            "system_prompt": "# 身份\n\n你是一位专业助手。",
            "source": "user",
            "enabled": True,
        }
    )


@pytest.fixture()
def template_agent(client) -> str:
    """模板实例化专家（agent_id 符合 specialist-<tpl>-<6hex> 命名）。"""
    agent_id = "specialist-writing-abcdef"
    _upsert_agent(agent_id)
    return agent_id


@pytest.fixture()
def fake_runner(monkeypatch):
    """把所有任务的默认 runner 替换为返回固定通过的假实现。"""
    import backend.services.specialist_golden_eval as golden_mod

    async def _runner(profile, task):
        return {"output": PASSING_OUTPUT, "tool_calls": [], "tokens": 42}

    monkeypatch.setattr(golden_mod, "default_llm_runner", _runner)
    return _runner


# =====================================================================
# GET /specialists/golden-tasks
# =====================================================================


def test_list_golden_tasks_returns_ten_and_five_templates(
    client: TestClient,
) -> None:
    resp = client.get("/specialists/golden-tasks")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["tasks"]) == 10
    assert body["template_ids"] == [
        "writing",
        "research",
        "coding",
        "presentation",
        "office",
    ]
    for task in body["tasks"]:
        assert task["id"]
        assert task["template_id"] in body["template_ids"]
        assert task["checks"]


# =====================================================================
# POST /specialists/{agent_id}/eval  # noqa: ERA001 - section heading
# =====================================================================


def test_eval_returns_run_id_and_full_pass_report(
    client: TestClient, template_agent: str, fake_runner
) -> None:
    resp = client.post(f"/specialists/{template_agent}/eval")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["run_id"]) == 32
    report = body["report"]
    assert report["total_tasks"] == 10
    assert report["passed"] == 10
    assert report["failed"] == 0
    assert report["errored"] == 0
    assert report["pass_rate"] == 1.0
    assert report["total_tokens"] == 420
    assert set(report["by_template"]) == {
        "writing",
        "research",
        "coding",
        "presentation",
        "office",
    }
    assert report["started_at"] > 0
    assert report["finished_at"] >= report["started_at"]


def test_eval_unknown_agent_404(client: TestClient, fake_runner) -> None:
    resp = client.post("/specialists/specialist-writing-ffffff/eval")
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"]["type"] == "agent_not_found"


def test_eval_non_template_agent_400(client: TestClient, fake_runner) -> None:
    _upsert_agent("writer")
    resp = client.post("/specialists/writer/eval")
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["type"] == "agent_not_template_instantiated"


def test_eval_rejects_extra_body_fields(
    client: TestClient, template_agent: str, fake_runner
) -> None:
    resp = client.post(
        f"/specialists/{template_agent}/eval", json={"unexpected": 1}
    )
    assert resp.status_code == 422, resp.text


def test_eval_task_ids_subset_filter(
    client: TestClient, template_agent: str, fake_runner
) -> None:
    resp = client.post(
        f"/specialists/{template_agent}/eval",
        json={"task_ids": ["writing-polish-ai-education", "nonexistent-task"]},
    )
    assert resp.status_code == 200, resp.text
    report = resp.json()["report"]
    assert report["total_tasks"] == 1
    assert report["task_results"][0]["task_id"] == "writing-polish-ai-education"


def test_eval_persists_run_row(
    client: TestClient, template_agent: str, fake_runner
) -> None:
    resp = client.post(f"/specialists/{template_agent}/eval")
    assert resp.status_code == 200, resp.text
    run_id = resp.json()["run_id"]

    from backend.data.database import get_database

    conn = get_database().get_connection()
    row = conn.execute(
        "SELECT agent_id, template_id, created_at, report "
        "FROM agent_eval_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    assert row is not None
    agent_id, template_id, created_at, report_json = row
    assert agent_id == template_agent
    assert template_id == "writing"
    # 毫秒级 Unix 时间戳（与 agent_versions.created_at 约定一致）
    assert created_at > 1_000_000_000_000
    stored = json.loads(report_json)
    assert stored["total_tasks"] == 10
    assert stored["pass_rate"] == 1.0


def test_eval_runner_errors_do_not_500(
    client: TestClient, template_agent: str, monkeypatch
) -> None:
    import backend.services.specialist_golden_eval as golden_mod

    async def _boom(profile, task):
        raise RuntimeError("LLM endpoint 未配置")

    monkeypatch.setattr(golden_mod, "default_llm_runner", _boom)
    resp = client.post(f"/specialists/{template_agent}/eval")
    assert resp.status_code == 200, resp.text
    report = resp.json()["report"]
    assert report["errored"] == 10
    assert report["passed"] == 0
    assert report["pass_rate"] == 0.0
    for result in report["task_results"]:
        assert result["error"]
