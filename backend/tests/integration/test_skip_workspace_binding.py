"""
skip_workspace_binding 功能测试 — 验证用户选择"默认工作区"时绑定到 ~/Sage/。

2026-11-20 (feat/default-workspace): 用户在新会话页选择"默认工作区（~/Sage/）"时，
前端传 skip_workspace_binding=True，后端调 resolve_to_default()，
将会话绑定到 ~/Sage/（source="default"），所有工具正常工作。
旧行为（skip=true → workspace_binding=None）已废弃。
"""

from unittest.mock import MagicMock, patch

import pytest

PREFIX = "/api/v1"


@pytest.mark.integration()
@pytest.mark.asyncio()
async def test_create_session_skip_workspace_binding_true(client):
    """skip_workspace_binding=True 时绑定到默认工作区 ~/Sage/。"""
    with patch("backend.api.legacy_session_routes.DefaultWorkspaceResolver") as mock_resolver:
        mock_resolver_instance = MagicMock()
        mock_resolver.return_value = mock_resolver_instance
        # 模拟 resolve_to_default() 返回 ~/Sage/
        mock_resolution = MagicMock()
        mock_resolution.path = "/home/user/Sage"
        mock_resolution.source.value = "default"
        mock_resolution.is_fallback = False
        mock_resolver_instance.resolve_to_default.return_value = mock_resolution

        with patch("backend.api.legacy_session_routes.bind_session_workspace"):
            resp = await client.post(
                f"{PREFIX}/sessions",
                json={"title": "默认工作区", "skip_workspace_binding": True},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["title"] == "默认工作区"
            assert "id" in data
            # 工作区绑定应为默认工作区
            binding = data.get("workspace_binding")
            assert binding is not None
            assert binding["path"] == "/home/user/Sage"
            assert binding["source"] == "default"

            # 验证调用了 resolve_to_default() 而非 resolve_default_workspace()
            mock_resolver_instance.resolve_to_default.assert_called_once()
            mock_resolver_instance.resolve_default_workspace.assert_not_called()


@pytest.mark.integration()
@pytest.mark.asyncio()
async def test_create_session_skip_workspace_binding_false(client):
    """skip_workspace_binding=False（默认）时正常走解析链。"""
    with patch("backend.api.legacy_session_routes.DefaultWorkspaceResolver") as mock_resolver:
        mock_resolver_instance = MagicMock()
        mock_resolver.return_value = mock_resolver_instance
        # 模拟解析到 scratch 工作区
        mock_resolution = MagicMock()
        mock_resolution.path = "/tmp/scratch"
        mock_resolution.source.value = "scratch"
        mock_resolution.is_fallback = True
        mock_resolver_instance.resolve_default_workspace.return_value = mock_resolution

        with patch("backend.api.legacy_session_routes.bind_session_workspace"):
            resp = await client.post(
                f"{PREFIX}/sessions",
                json={"title": "默认绑定", "skip_workspace_binding": False},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["title"] == "默认绑定"
            # 验证解析链被调用
            mock_resolver_instance.resolve_default_workspace.assert_called_once()


@pytest.mark.integration()
@pytest.mark.asyncio()
async def test_create_session_default_calls_resolver(client):
    """不传 skip_workspace_binding 时默认走解析链（向后兼容）。"""
    with patch("backend.api.legacy_session_routes.DefaultWorkspaceResolver") as mock_resolver:
        mock_resolver_instance = MagicMock()
        mock_resolver.return_value = mock_resolver_instance
        mock_resolution = MagicMock()
        mock_resolution.path = "/tmp/scratch"
        mock_resolution.source.value = "scratch"
        mock_resolution.is_fallback = True
        mock_resolver_instance.resolve_default_workspace.return_value = mock_resolution

        with patch("backend.api.legacy_session_routes.bind_session_workspace"):
            resp = await client.post(
                f"{PREFIX}/sessions",
                json={"title": "默认行为"},
            )
            assert resp.status_code == 200
            # 验证解析链被调用
            mock_resolver_instance.resolve_default_workspace.assert_called_once()
