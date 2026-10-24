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
