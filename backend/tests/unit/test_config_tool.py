"""test_config_tool — 自省与配置工具 (read_sage_config / update_sage_config) 单元测试。

验证：
1. read_sage_config 各 section 读取与 apiKey 敏感字段脱敏
2. update_sage_config 允许修改的项正常持久化 (orch / agent / general)
3. update_sage_config 非法或越权字段 (endpoints / tools / unknown keys) 拒绝拦截
4. 风险类别声明一致性 (read=READ, update=WRITE_LOCAL)
"""
from __future__ import annotations

from backend.domain.risk import RiskClass
from backend.tools.config_tool import ReadSageConfigTool, UpdateSageConfigTool


def test_tool_risk_classes():
    read_tool = ReadSageConfigTool()
    update_tool = UpdateSageConfigTool()
    assert read_tool.risk == RiskClass.READ
    assert update_tool.risk == RiskClass.WRITE_LOCAL


def test_read_sage_config_redacts_api_key(monkeypatch):
    tool = ReadSageConfigTool()

    fake_settings = {
        "temperature": 0.7,
        "endpoints": [
            {
                "id": "ep-1",
                "name": "Local LLM",
                "baseUrl": "https://api.example.com",
                "apiKey": "sk-secret-token-12345",
            }
        ],
        "orch": {
            "maxLaneIterations": 8,
            "maxSubagentIterations": 6,
        },
    }

    class FakeSettingsRepo:
        def get_json(self, key):
            if key == "app_settings":
                return fake_settings
            return None

    monkeypatch.setattr("backend.tools.config_tool.SettingsRepository", FakeSettingsRepo)

    res = tool.execute(section="all")
    assert res.success is True
    data = res.content["data"]
    endpoints = data["settings"]["endpoints"]
    assert len(endpoints) == 1
    assert "sk-secret" not in str(endpoints)
    assert endpoints[0].get("apiKey") == "***" or endpoints[0].get("hasApiKey") is True


def test_read_sage_config_sections(monkeypatch):
    tool = ReadSageConfigTool()

    fake_settings = {
        "temperature": 0.5,
        "orch": {
            "maxLaneIterations": 10,
            "maxSubagentIterations": 5,
        },
    }

    class FakeSettingsRepo:
        def get_json(self, key):
            return fake_settings

    class FakeAgentRepo:
        def list_all(self):
            return [
                {
                    "id": "primary",
                    "name": "Sage 主助手",
                    "role": "coordinator",
                    "max_iterations": 15,
                    "enabled": True,
                },
                {
                    "id": "coder",
                    "name": "编码 Agent",
                    "role": "coder",
                    "max_iterations": 15,
                    "enabled": True,
                },
            ]

    monkeypatch.setattr("backend.tools.config_tool.SettingsRepository", FakeSettingsRepo)
    monkeypatch.setattr("backend.tools.config_tool.AgentRepository", FakeAgentRepo)

    # 查 orch
    res_orch = tool.execute(section="orch")
    assert res_orch.success is True
    assert res_orch.content["data"]["maxLaneIterations"] == 10

    # 查 agents
    res_agents = tool.execute(section="agents")
    assert res_agents.success is True
    agents_list = res_agents.content["data"]
    assert len(agents_list) == 2
    assert agents_list[0]["id"] == "primary"
    assert agents_list[0]["max_iterations"] == 15


def test_update_sage_config_orch_success(monkeypatch):
    tool = UpdateSageConfigTool()

    saved_settings = {}

    class FakeSettingsRepo:
        def get_json(self, key):
            return {"orch": {"maxLaneIterations": 8, "maxSubagentIterations": 6}}

        def set_json(self, key, value):
            saved_settings[key] = value

    monkeypatch.setattr("backend.tools.config_tool.SettingsRepository", FakeSettingsRepo)

    res = tool.execute(
        target="orch",
        updates={"maxLaneIterations": 12, "maxSubagentIterations": 8},
    )
    assert res.success is True
    orch = saved_settings["app_settings"]["orch"]
    assert orch["maxLaneIterations"] == 12
    assert orch["maxSubagentIterations"] == 8


def test_update_sage_config_agent_iterations_success(monkeypatch):
    tool = UpdateSageConfigTool()

    updated_agents = {}

    class FakeAgentRepo:
        def get(self, agent_id):
            if agent_id == "primary":
                return {
                    "id": "primary",
                    "name": "Sage 主助手",
                    "max_iterations": 15,
                    "model_config": {"model": "gpt-4", "temperature": 0.7},
                }
            return None

        def update(self, agent_id, updates):
            updated_agents[agent_id] = updates
            return True

    monkeypatch.setattr("backend.tools.config_tool.AgentRepository", FakeAgentRepo)

    res = tool.execute(
        target="agent",
        agent_id="primary",
        updates={"max_iterations": 20, "temperature": 0.4},
    )
    assert res.success is True
    assert updated_agents["primary"]["max_iterations"] == 20
    assert updated_agents["primary"]["model_config"]["temperature"] == 0.4


def test_update_sage_config_rejects_invalid_timezone_before_persisting(monkeypatch):
    tool = UpdateSageConfigTool()
    saved_settings = []

    class FakeSettingsRepo:
        def get_json(self, key):
            return {"timezone": "UTC", "orch": {"maxLaneIterations": 8}}

        def set_json(self, key, value):
            saved_settings.append((key, value))

    monkeypatch.setattr("backend.tools.config_tool.SettingsRepository", FakeSettingsRepo)

    res = tool.execute(target="general", updates={"timezone": "Not/A-Timezone"})

    assert res.success is False
    assert "配置校验失败" in res.error
    assert saved_settings == []


def test_update_sage_config_rejects_invalid_orch_value(monkeypatch):
    tool = UpdateSageConfigTool()
    res = tool.execute(target="orch", updates={"maxLaneIterations": 0})
    assert res.success is False
    assert "maxLaneIterations" in res.error


def test_update_sage_config_rejects_forbidden_fields():
    tool = UpdateSageConfigTool()

    # 试图篡改 tools 权限白名单 -> 拒绝
    res = tool.execute(
        target="agent",
        agent_id="primary",
        updates={"tools": ["bash", "read_file"]},
    )
    assert res.success is False
    assert "tools" in res.error

    # 试图篡改 endpoints / apiKey -> 拒绝
    res2 = tool.execute(
        target="general",
        updates={"apiKey": "malicious_token"},
    )
    assert res2.success is False
    assert "apiKey" in res2.error


# ---- P119 Config Advisor (Phase 1.2): LLM 重试 / 超时字段 ----


def _fake_repo_for_general_updates(initial=None):
    """返回一个 FakeSettingsRepo 类 + saved_settings 收集器。"""
    initial = initial or {}
    saved = {}

    class FakeRepo:
        def get_json(self, key):
            if key == "app_settings":
                return dict(initial)
            return None

        def set_json(self, key, value):
            saved[key] = value

    return FakeRepo, saved


def test_update_general_accepts_llm_retry_fields(monkeypatch):
    tool = UpdateSageConfigTool()
    FakeRepo, saved = _fake_repo_for_general_updates()
    monkeypatch.setattr("backend.tools.config_tool.SettingsRepository", FakeRepo)

    res = tool.execute(
        target="general",
        updates={
            "llmRetryMaxAttempts": 5,
            "llmRetryBaseDelayS": 1.5,
            "llmRetryMaxDelayS": 30.0,
            "llmTotalTimeoutS": 600,
        },
    )
    assert res.success is True, res.error
    persisted = saved["app_settings"]
    assert persisted["llmRetryMaxAttempts"] == 5
    assert persisted["llmRetryBaseDelayS"] == 1.5
    assert persisted["llmRetryMaxDelayS"] == 30.0
    assert persisted["llmTotalTimeoutS"] == 600


def test_update_general_rejects_out_of_range_llm_retry(monkeypatch):
    tool = UpdateSageConfigTool()
    FakeRepo, _ = _fake_repo_for_general_updates()
    monkeypatch.setattr("backend.tools.config_tool.SettingsRepository", FakeRepo)

    # llmRetryMaxAttempts 上限 20
    res = tool.execute(target="general", updates={"llmRetryMaxAttempts": 100})
    assert res.success is False
    assert "llmRetryMaxAttempts" in res.error

    # llmRetryBaseDelayS 必须 > 0
    res2 = tool.execute(target="general", updates={"llmRetryBaseDelayS": 0})
    assert res2.success is False
    assert "llmRetryBaseDelayS" in res2.error

    # llmTotalTimeoutS 上限 86400
    res3 = tool.execute(target="general", updates={"llmTotalTimeoutS": 100000})
    assert res3.success is False
    assert "llmTotalTimeoutS" in res3.error


def test_update_general_rejects_wrong_type_llm_retry(monkeypatch):
    tool = UpdateSageConfigTool()
    FakeRepo, _ = _fake_repo_for_general_updates()
    monkeypatch.setattr("backend.tools.config_tool.SettingsRepository", FakeRepo)

    # llmRetryMaxAttempts 必须 int，不接受 float
    res = tool.execute(target="general", updates={"llmRetryMaxAttempts": 3.5})
    assert res.success is False
    assert "llmRetryMaxAttempts" in res.error

    # llmTotalTimeoutS 必须 int
    res2 = tool.execute(target="general", updates={"llmTotalTimeoutS": True})
    assert res2.success is False
    assert "llmTotalTimeoutS" in res2.error


def test_update_general_rejects_base_delay_exceeds_max_delay(monkeypatch):
    tool = UpdateSageConfigTool()
    FakeRepo, _ = _fake_repo_for_general_updates()
    monkeypatch.setattr("backend.tools.config_tool.SettingsRepository", FakeRepo)

    # 同时传 base > max -> 一致性校验拦截
    res = tool.execute(
        target="general",
        updates={
            "llmRetryBaseDelayS": 60.0,
            "llmRetryMaxDelayS": 10.0,
        },
    )
    assert res.success is False
    assert "llmRetryBaseDelayS" in res.error and "llmRetryMaxDelayS" in res.error


# ---- P119 Config Advisor (Phase 2.2): DiagnoseSageConfigTool ----


def _install_diagnose_imports():
    """Lazily import DiagnoseSageConfigTool + helpers。"""
    from backend.tools.config_tool import DiagnoseSageConfigTool, _build_diagnosis_summary
    return DiagnoseSageConfigTool, _build_diagnosis_summary


def _empty_metrics():
    return {
        "window": {"from": None, "to": None, "run_count": 0},
        "completion": {"success": 0, "failed": 0, "cancelled": 0, "other": 0},
        "failure_kind": {},
        "tokens": {"mean_per_task": 0, "total": 0, "task_count_with_tokens": 0},
        "latency_ms": {"mean": 0, "p50": 0, "p95": 0},
        "retries": {"mean_per_task": 0.0, "tasks_with_retry_pct": 0.0},
    }


def test_diagnose_tool_risk_class_is_read():
    DiagnoseSageConfigTool, _ = _install_diagnose_imports()
    tool = DiagnoseSageConfigTool()
    assert tool.risk == RiskClass.READ


def test_diagnose_tool_returns_config_and_metrics(monkeypatch):
    DiagnoseSageConfigTool, _ = _install_diagnose_imports()
    tool = DiagnoseSageConfigTool()

    fake_settings = {
        "temperature": 0.7,
        "orch": {"maxLaneIterations": 25},
    }

    class FakeSettingsRepo:
        def get_json(self, key):
            if key == "app_settings":
                return fake_settings
            return None

    fake_metrics = {
        "window": {"from": "2026-10-20T00:00:00", "to": "2026-10-24T12:00:00", "run_count": 5},
        "completion": {"success": 3, "failed": 1, "cancelled": 1, "other": 0},
        "failure_kind": {"max_iterations_exceeded": 1},
        "tokens": {"mean_per_task": 1000, "total": 5000, "task_count_with_tokens": 5},
        "latency_ms": {"mean": 500, "p50": 400, "p95": 1200},
        "retries": {"mean_per_task": 0.2, "tasks_with_retry_pct": 10.0},
    }

    class FakeOrchRunMetrics:
        @staticmethod
        def aggregate_recent(limit=20):
            assert limit == 20  # default
            return fake_metrics

    monkeypatch.setattr("backend.tools.config_tool.SettingsRepository", FakeSettingsRepo)
    # Patch the lazy import: import inside execute() looks up
    # backend.data.orch_run_metrics module then accesses OrchRunMetrics attr.
    import backend.data.orch_run_metrics as metrics_mod

    monkeypatch.setattr(metrics_mod, "OrchRunMetrics", FakeOrchRunMetrics)

    res = tool.execute()
    assert res.success is True, res.error
    assert res.content["configuration"]["temperature"] == 0.7
    assert res.content["recent_metrics"]["window"]["run_count"] == 5
    assert "诊断摘要" in res.output
    assert "成功率" in res.output


def test_diagnose_tool_rejects_invalid_window_runs():
    DiagnoseSageConfigTool, _ = _install_diagnose_imports()
    tool = DiagnoseSageConfigTool()

    # 非整数
    res = tool.execute(window_runs=3.5)
    assert res.success is False
    assert "正整数" in res.error

    # 越界（太大）
    res2 = tool.execute(window_runs=500)
    assert res2.success is False
    assert "1 到 200" in res2.error

    # 越界（太小）
    res3 = tool.execute(window_runs=0)
    assert res3.success is False
    assert "1 到 200" in res3.error

    # bool 不接受（bool 是 int 子类）
    res4 = tool.execute(window_runs=True)
    assert res4.success is False


def test_diagnose_tool_config_read_failure_returns_error(monkeypatch):
    DiagnoseSageConfigTool, _ = _install_diagnose_imports()
    tool = DiagnoseSageConfigTool()

    class BoomRepo:
        def get_json(self, key):
            raise RuntimeError("db locked")

    monkeypatch.setattr("backend.tools.config_tool.SettingsRepository", BoomRepo)

    res = tool.execute()
    assert res.success is False
    assert "读取配置失败" in res.error


def test_build_diagnosis_summary_empty_metrics():
    _, _build_diagnosis_summary = _install_diagnose_imports()
    summary = _build_diagnosis_summary({}, _empty_metrics())
    assert "诊断摘要" in summary
    assert "近期无 run 记录" in summary


def test_build_diagnosis_summary_with_data():
    _, _build_diagnosis_summary = _install_diagnose_imports()
    metrics = {
        "window": {"from": "2026-10-20", "to": "2026-10-24", "run_count": 10},
        "completion": {"success": 7, "failed": 2, "cancelled": 1, "other": 0},
        "failure_kind": {"max_iterations_exceeded": 1, "timeout": 1},
        "tokens": {"mean_per_task": 2000, "total": 20000, "task_count_with_tokens": 10},
        "latency_ms": {"mean": 800, "p50": 700, "p95": 3000},
        "retries": {"mean_per_task": 0.5, "tasks_with_retry_pct": 25.0},
    }
    summary = _build_diagnosis_summary({}, metrics)
    assert "10 次 run" in summary
    assert "成功率: 70%" in summary
    assert "max_iterations_exceeded=1" in summary
    assert "平均 0.50/任务" in summary
    assert "平均 800ms" in summary
    assert "2000/任务" in summary
