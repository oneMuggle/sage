"""SageAgent 把 policy 透传给 register_all_tools（P0-3 scratch 注入点）。"""

from unittest.mock import patch

from backend.domain.tool_policy import ToolPolicy


def test_sageagent_forwards_policy_to_register_all_tools():
    from backend.core.legacy.agent import SageAgent

    with patch("backend.core.legacy.agent.register_all_tools") as mock_reg:
        SageAgent(bare=False, policy=ToolPolicy(workspace_root="/tmp/scratch"))

    assert mock_reg.call_count == 1
    _, kwargs = mock_reg.call_args
    assert kwargs.get("policy") is not None
    assert kwargs["policy"].workspace_root == "/tmp/scratch"
