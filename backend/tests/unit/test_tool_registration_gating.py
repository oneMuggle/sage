"""网络模式对工具注册的门禁（Task 6）。

注册期决策而非执行期报错：LLM 看到工具就会试，返回"该模式不可用"只是多烧一轮
迭代。参照 registry.get_schemas_for_llm 对 requires_tool_context 的处理方式。
"""

import pytest

from backend.domain.network_policy import NetworkMode, NetworkPolicy
from backend.tools import ToolRegistry, register_all_tools
from backend.tools.agent_tool import SUBAGENT_TOOL_WHITELIST, build_readonly_tool_registry

pytestmark = [pytest.mark.unit]

_OUTBOUND = ("web_search", "web_fetch", "http_download")


def _names(policy):
    registry = ToolRegistry()
    register_all_tools(registry, network_policy=policy)
    return set(registry.list_names())


def test_online_registers_all_outbound_tools():
    names = _names(NetworkPolicy(mode=NetworkMode.ONLINE))
    for tool in _OUTBOUND:
        assert tool in names


def test_intranet_hides_web_search_but_keeps_fetch_and_download():
    names = _names(
        NetworkPolicy(mode=NetworkMode.INTRANET, allowed_hosts=("*.example.internal",))
    )
    assert "web_search" not in names
    assert "web_fetch" in names
    assert "http_download" in names


def test_offline_hides_all_outbound_tools():
    names = _names(NetworkPolicy(mode=NetworkMode.OFFLINE))
    for tool in _OUTBOUND:
        assert tool not in names


def test_non_outbound_tools_survive_every_mode():
    """门禁只影响出网工具，本地工具在任何模式下都在。"""
    for mode in (NetworkMode.ONLINE, NetworkMode.INTRANET, NetworkMode.OFFLINE):
        names = _names(NetworkPolicy(mode=mode))
        for tool in ("read_file", "write_file", "bash", "calculator", "memory_search"):
            assert tool in names, f"{tool} 在 {mode.value} 模式下消失了"


def test_gating_applies_to_subagent_registry():
    """子代理路径同样过门禁 —— 否则 agent 工具能绕过网络模式。"""
    registry = build_readonly_tool_registry(
        network_policy=NetworkPolicy(mode=NetworkMode.OFFLINE)
    )
    names = set(registry.list_names())
    assert "web_search" not in names
    assert "web_fetch" not in names
    assert "read_file" in names


def test_subagent_intranet_keeps_fetch():
    registry = build_readonly_tool_registry(
        network_policy=NetworkPolicy(
            mode=NetworkMode.INTRANET, allowed_hosts=("*.example.internal",)
        )
    )
    names = set(registry.list_names())
    assert "web_search" not in names
    assert "web_fetch" in names


def test_http_download_is_in_subagent_whitelist():
    assert "http_download" in SUBAGENT_TOOL_WHITELIST


def test_default_none_policy_reads_settings(monkeypatch):
    """network_policy=None 时从 settings 读 —— 生产路径不显式传参。"""
    calls = []

    def _fake_load():
        calls.append(1)
        return NetworkPolicy(mode=NetworkMode.OFFLINE)

    monkeypatch.setattr("backend.tools.load_network_policy", _fake_load)
    registry = ToolRegistry()
    register_all_tools(registry)

    assert calls, "register_all_tools 未读取网络策略"
    assert "web_search" not in registry.list_names()
