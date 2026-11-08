# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容
"""M4（sage-guide）：specialist 权限上限单测。

覆盖：

1. profile=None / role 非 specialist → base mode 不变
2. global full_access + profile workspace_write → 实际降级为 workspace_write
3. global workspace_write + profile full_access → 维持 workspace_write（只降不升）
4. global read_only + profile workspace_write → 维持 read_only
5. profile permission_mode 不在合法集 → 不修改 base
6. 调用 force_mode 但不写回 settings（实例覆盖）
"""

from __future__ import annotations

import pytest

from backend.core.legacy.agent import _apply_specialist_cap
from backend.tools.bash_validation import validate_bash
from backend.tools.permissions import PermissionEnforcer, PermissionMode

pytestmark = pytest.mark.unit


def _make_enforcer(mode: PermissionMode) -> PermissionEnforcer:
    return PermissionEnforcer(
        mode=mode, rules=(), bash_validator=validate_bash
    )


class TestApplySpecialistCap:
    def test_no_profile_returns_base_unchanged(self):
        base = _make_enforcer(PermissionMode.FULL_ACCESS)
        out = _apply_specialist_cap(None, base)
        assert out is base
        assert out.mode is PermissionMode.FULL_ACCESS

    def test_non_specialist_role_returns_base_unchanged(self):
        base = _make_enforcer(PermissionMode.FULL_ACCESS)
        profile = {"id": "primary", "role": "coordinator", "permission_mode": "read_only"}
        out = _apply_specialist_cap(profile, base)
        assert out is base
        assert out.mode is PermissionMode.FULL_ACCESS

    def test_full_access_capped_to_workspace_write(self):
        base = _make_enforcer(PermissionMode.FULL_ACCESS)
        profile = {
            "id": "sage-guide",
            "role": "specialist",
            "permission_mode": "workspace_write",
        }
        out = _apply_specialist_cap(profile, base)
        assert out is base  # 就地修改
        assert out.mode is PermissionMode.WORKSPACE_WRITE

    def test_workspace_write_not_escalated_to_full_access(self):
        """只降不升：profile 声明更宽松的全权，但全局已经是更严的工作区写。"""
        base = _make_enforcer(PermissionMode.WORKSPACE_WRITE)
        profile = {
            "id": "sage-guide",
            "role": "specialist",
            "permission_mode": "full_access",
        }
        out = _apply_specialist_cap(profile, base)
        assert out.mode is PermissionMode.WORKSPACE_WRITE

    def test_read_only_not_escalated_by_profile(self):
        base = _make_enforcer(PermissionMode.READ_ONLY)
        profile = {
            "id": "sage-guide",
            "role": "specialist",
            "permission_mode": "workspace_write",
        }
        out = _apply_specialist_cap(profile, base)
        assert out.mode is PermissionMode.READ_ONLY

    def test_full_access_capped_to_prompt(self):
        base = _make_enforcer(PermissionMode.FULL_ACCESS)
        profile = {
            "id": "custom-specialist",
            "role": "specialist",
            "permission_mode": "prompt",
        }
        out = _apply_specialist_cap(profile, base)
        assert out.mode is PermissionMode.PROMPT

    def test_invalid_permission_mode_in_profile_is_noop(self):
        base = _make_enforcer(PermissionMode.FULL_ACCESS)
        profile = {
            "id": "weird",
            "role": "specialist",
            "permission_mode": "hacker",
        }
        out = _apply_specialist_cap(profile, base)
        assert out.mode is PermissionMode.FULL_ACCESS

    def test_missing_permission_mode_in_profile_is_noop(self):
        base = _make_enforcer(PermissionMode.FULL_ACCESS)
        profile = {"id": "weird", "role": "specialist"}
        out = _apply_specialist_cap(profile, base)
        assert out.mode is PermissionMode.FULL_ACCESS

    def test_does_not_write_settings(self, monkeypatch):
        """force_mode 是实例级覆盖，绝不回写 settings 仓库。"""
        written = []
        monkeypatch.setattr(
            "backend.data.settings_repo.SettingsRepository.set",
            lambda self, *a, **kw: written.append(a),
        )
        base = _make_enforcer(PermissionMode.FULL_ACCESS)
        profile = {
            "id": "sage-guide",
            "role": "specialist",
            "permission_mode": "workspace_write",
        }
        _apply_specialist_cap(profile, base)
        assert written == [], "specialist 权限上限不应写回 settings"
