"""
skip_workspace_binding 功能测试 — 验证用户选择"不绑定项目"时跳过工作区解析链。

2026-11-04 (fix/skip-workspace-binding): 用户在新会话页明确选择"不绑定项目"时，
前端传 skip_workspace_binding=True，后端跳过整个工作区解析链，不绑定任何工作区。
语义对齐主流 AI 应用 (Cursor / Cline / Windsurf) 的"显式选择 > 自动推断"原则。
"""

from unittest.mock import MagicMock, patch

import pytest

PREFIX = "/api/v1"


@pytest.mark.integration()
@pytest.mark.asyncio()
async def test_create_session_skip_workspace_binding_true(client):
    """skip_workspace_binding=True 时不绑定任何工作区。"""
    with patch("backend.api.legacy_session_routes.DefaultWorkspaceResolver") as mock_resolver:
        mock_resolver_instance = MagicMock()
        mock_resolver.return_value = mock_resolver_instance
        mock_resolver_instance.resolve_default_workspace.return_value = None

        resp = await client.post(
            f"{PREFIX}/sessions",
            json={"title": "不绑定项目", "skip_workspace_binding": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "不绑定项目"
        assert "id" in data
        # 工作区绑定应为 null
        assert data.get("workspace_binding") is None

        # 验证解析链未被调用
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
