"""M1.1 ``sage_self_status`` 工具：一次性聚合 8 维自透明信息。

背景（2026-11-04 分析 ② 版本 / 实际模型 / 权限模式 / MCP / 插件 / 用量 / 健康）：
此前这些信息散落在 7 个模块，agent 要调 6-7 次工具才能拼出完整画面。
``sage_self_status`` 把它们聚合成一次返回，对应 Claude Code 的 ``/status``。

设计约束：

- 聚合函数（``gather_self_status``）放在 ``backend.services.self_status``，
  不依赖工具框架 —— 便于单元测试与 REST 路由复用；
- 工具层（``SageSelfStatusTool``）只是薄包装，返回 ``ToolResult``；
- 任一维度失败 → 该维度置 ``{"error": "..."}``，其他维度不受影响（fail-open
  但 fail 可见，不整次工具失败）；
- 工具本身 ``RiskClass.READ``，不进 ``SELF_MODIFY_TOOLS``（只读操作）。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.services import self_status as ss_module
from backend.services.self_status import gather_self_status
from backend.tools.permissions import ToolCapability, classify_tool
from backend.tools.self_status_tool import SageSelfStatusTool

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# 能力分级 —— READ（不进 SELF_MODIFY_TOOLS，READ_ONLY 模式也放行）
# ---------------------------------------------------------------------------


def test_self_status_tools_registered_as_read():
    for name in ("sage_self_status", "sage_doctor", "sage_usage"):
        assert classify_tool(name) is ToolCapability.READ, (
            f"自透明只读工具 {name} 应为 READ（不进 SELF_MODIFY_TOOLS）"
        )


# ---------------------------------------------------------------------------
# 聚合函数 —— 每个维度独立，单个维度失败不污染其他维度
# ---------------------------------------------------------------------------


def test_gather_version_reads_package_json():
    """版本读 package.json；读取失败回退 'unknown'，不抛异常。"""
    with patch.object(ss_module, "_read_package_json_version", return_value="0.4.9-alpha.76"):
        data = gather_self_status()
    assert data["version"] == "0.4.9-alpha.76"


def test_gather_version_fallback_on_error():
    with patch.object(ss_module, "_read_package_json_version", side_effect=OSError("missing")):
        data = gather_self_status()
    assert data["version"] == "unknown"


def test_gather_permission_mode_returns_string():
    """权限模式来自 settings 表；读不到默认 WORKSPACE_WRITE。"""
    with patch.object(ss_module, "load_enforcer_from_settings") as mock_load:
        enforcer = MagicMock()
        enforcer.mode.value = "workspace_write"
        mock_load.return_value = enforcer
        data = gather_self_status()
    assert data["permission_mode"] == "workspace_write"


def test_gather_permission_mode_fallback():
    """settings 表读不到时默认 'workspace_write'（fail-open）。"""
    with patch.object(ss_module, "load_enforcer_from_settings", side_effect=OSError("db fail")):
        data = gather_self_status()
    assert data["permission_mode"] == "workspace_write"


def test_gather_effective_model_uses_llm_factory():
    """实际生效模型走 load_llm_config_for_chat() 解析（返回 LLMConfig 兼容 **dict**）。"""
    # 用真实 dict 而不是 MagicMock —— load_llm_config_for_chat 返回 dict，
    # MagicMock 会掩盖 getattr 在 dict 上永远返回 None 的 bug。
    fake_config = {
        "model": "gpt-4o",
        "provider": "custom",
        "api_key": "sk-***",
        "base_url": "https://api.example.com/v1",
        "endpoint_id": "ep-123",
        "temperature": 0.3,
    }
    with patch.object(ss_module, "load_llm_config_for_chat", return_value=fake_config):
        data = gather_self_status()
    assert data["effective_model"]["model"] == "gpt-4o"
    assert data["effective_model"]["provider"] == "custom"
    assert data["effective_model"]["endpoint_id"] == "ep-123"


def test_gather_effective_model_empty_config_is_error():
    """LLM 配置为空 dict / None（无可用端点）→ 有效 error 字段而不是抛异常。"""
    with patch.object(ss_module, "load_llm_config_for_chat", return_value=None):
        data = gather_self_status()
    assert "error" in data["effective_model"]


def test_gather_effective_model_fallback_on_error():
    """LLM 配置加载失败时返回带 error 字段的占位 dict，其他维度不受影响。"""
    with patch.object(ss_module, "load_llm_config_for_chat", side_effect=RuntimeError("no endpoints")):
        data = gather_self_status()
    assert "error" in data["effective_model"]
    assert "version" in data  # 其他维度仍然正常返回


def test_gather_mcp_list_returns_list_of_entries():
    """MCP 清单读 mcp pool 单例的 status_report()。

    用真实 dataclass 而不是 MagicMock —— ServerStatusEntry.since 是 float
    （time.time 纪元秒），MagicMock 会让任何属性访问都成功，掩盖
    datetime.fromtimestamp(float).isoformat() 的真实调用路径。
    """
    from backend.mcp.pool import McpStatusReport, ServerStatusEntry

    entry = ServerStatusEntry(
        name="drawio",
        state="ready",
        tool_count=3,
        last_error=None,
        since=1700000000.0,  # 真实 float 纪元秒
        required=False,
    )
    report = McpStatusReport(generated_at=1700000000.0, servers=(entry,))
    with patch.object(ss_module, "get_mcp_pool") as mock_pool:
        mock_pool.return_value.status_report.return_value = report
        data = gather_self_status()
    assert len(data["mcp"]) == 1
    assert data["mcp"][0]["name"] == "drawio"
    assert data["mcp"][0]["state"] == "ready"
    assert data["mcp"][0]["tool_count"] == 3
    # since 被转成 ISO-8601 字符串（UTC）
    since_str = data["mcp"][0]["since"]
    assert isinstance(since_str, str) and since_str.endswith("+00:00") or "T" in since_str


def test_gather_mcp_list_fallback():
    """MCP pool 不可用时返回空列表（不抛异常）。"""
    with patch.object(ss_module, "get_mcp_pool", side_effect=RuntimeError("no pool")):
        data = gather_self_status()
    assert data["mcp"] == [] or isinstance(data["mcp"], dict) and "error" in data["mcp"]


def test_gather_plugin_list_returns_records():
    """插件清单读 PluginLifecycleManager.list_plugins()。"""
    fake_record = MagicMock()
    fake_record.name = "my_plugin"
    fake_record.version = "1.0.0"
    fake_record.status = "enabled"
    with patch.object(ss_module, "get_plugin_lifecycle_manager") as mock_lcm:
        mock_lcm.return_value.list_plugins.return_value = [fake_record]
        data = gather_self_status()
    assert len(data["plugins"]) == 1
    assert data["plugins"][0]["name"] == "my_plugin"
    assert data["plugins"][0]["status"] == "enabled"


def test_gather_plugin_list_fallback():
    """插件系统不可用时返回空列表。"""
    with patch.object(
        ss_module, "get_plugin_lifecycle_manager", side_effect=RuntimeError("no db")
    ):
        data = gather_self_status()
    assert data["plugins"] == [] or isinstance(data["plugins"], dict) and "error" in data["plugins"]


def test_gather_usage_summary_returns_today():
    """今日用量来自 usage_tracker.summary_with_range()，且 estimated_cost_usd=None 不崩。"""
    fake_summary = {
        "today": {
            "requests": 12,
            "prompt_tokens": 50000,
            "completion_tokens": 10000,
            "estimated_cost_usd": None,  # 模型定价未知 —— 不应 :.4f TypeError
        }
    }
    with patch.object(ss_module, "get_usage_summary", return_value=fake_summary):
        data = gather_self_status()
    assert data["usage"]["today"]["requests"] == 12


def test_gather_usage_summary_fallback():
    with patch.object(ss_module, "get_usage_summary", side_effect=RuntimeError("tracker fail")):
        data = gather_self_status()
    assert isinstance(data["usage"], dict)
    assert "error" in data["usage"] or data["usage"] == {}


def test_gather_health_db_ok():
    """_gather_health 走 get_database().get_connection().execute('SELECT 1')。

    不能用 MagicMock 替代 get_database：Database 类本身没有 execute()，
    真实路径必须经 _LockedConnection.execute 内部持有 _SQLITE_LOCK。
    """
    mock_conn = MagicMock()
    mock_conn.execute.return_value = (1,)
    mock_db = MagicMock()
    mock_db.get_connection.return_value = mock_conn
    # _gather_health 内部 `from backend.data.database import get_database`
    # —— 必须 patch 该模块上的名字才能生效。
    with patch("backend.data.database.get_database", return_value=mock_db):
        data = ss_module._gather_health()
    assert data["backend_ok"] is True
    assert data["db_ok"] is True
    mock_conn.execute.assert_called_once_with("SELECT 1")


def test_gather_health_db_failure():
    """DB execute 抛异常时 db_ok=False 但 backend_ok 仍 True（后端进程还活着）。"""
    mock_conn = MagicMock()
    mock_conn.execute.side_effect = RuntimeError("locked")
    mock_db = MagicMock()
    mock_db.get_connection.return_value = mock_conn
    with patch("backend.data.database.get_database", return_value=mock_db):
        data = ss_module._gather_health()
    assert data["backend_ok"] is True
    assert data["db_ok"] is False


def test_build_summary_cost_none_path():
    """_build_summary 在 estimated_cost_usd=None 时输出 '未知' 而不是 '$0.0000'。"""
    from backend.tools.self_status_tool import SageSelfStatusTool

    data = {
        "version": "0.4.9",
        "effective_model": {"model": "gpt-4o", "provider": "openai", "endpoint_id": "ep-1"},
        "permission_mode": "workspace_write",
        "mcp": [],
        "plugins": [],
        "usage": {"today": {"requests": 1, "prompt_tokens": 10, "completion_tokens": 2,
                            "estimated_cost_usd": None}},
        "health": {"backend_ok": True, "db_ok": True},
        "context": {},
    }
    lines = SageSelfStatusTool._build_summary(data)
    joined = "\n".join(lines)
    assert "未知" in joined
    assert "$0.0000" not in joined


def test_sage_usage_unresolved_session_is_failure():
    """scope=session 且无 session_id → success=False（不是空结果）。"""
    from backend.tools.sage_usage_tool import SageUsageTool

    tool = SageUsageTool()
    # current_tool_context() 在测试环境默认返回 None → session_id 解析失败
    with patch("backend.tools.sage_usage_tool.usage_tracker", create=True) as _mock_tracker:
        # 直接走 _session_scope 的 no-session-id 路径（不走 tracker）
        data, _text = tool._session_scope(session_id=None)
    assert "error" in data


# ---------------------------------------------------------------------------
# 工具包装层 —— execute() 返回 ToolResult 且 success=True
# ---------------------------------------------------------------------------


def test_self_status_tool_returns_tool_result():
    tool = SageSelfStatusTool()
    with patch.object(ss_module, "gather_self_status") as mock_gather:
        mock_gather.return_value = {
            "version": "0.4.9",
            "effective_model": {"model": "gpt-4o"},
            "permission_mode": "workspace_write",
            "mcp": [],
            "plugins": [],
            "usage": {},
            "health": {"backend_ok": True},
            "context": {},
        }
        result = tool.execute()
    assert result.success is True
    assert result.content["version"] == "0.4.9"
    assert "gpt-4o" in result.output


def test_self_status_tool_handles_partial_failure():
    """即使部分维度失败，整次调用仍 success=True（其他维度已返回）。"""
    tool = SageSelfStatusTool()
    with patch.object(ss_module, "gather_self_status") as mock_gather:
        mock_gather.return_value = {
            "version": "unknown",
            "effective_model": {"error": "no endpoints configured"},
            "permission_mode": "workspace_write",
            "mcp": [],
            "plugins": [],
            "usage": {},
            "health": {"backend_ok": True},
            "context": {},
        }
        result = tool.execute()
    assert result.success is True
    assert "error" in result.content["effective_model"]


# ---------------------------------------------------------------------------
# 版本号读取 —— 单一真相源
# ---------------------------------------------------------------------------


def test_read_package_json_version_returns_string():
    """真实读取 package.json 返回有效版本字符串。"""
    version = ss_module._read_package_json_version()
    assert isinstance(version, str)
    # 不强制版本号格式（可能 alpha / beta / stable），但非空非 'unknown'
    assert version
    assert version != "unknown"
