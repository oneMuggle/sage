"""Phase 4 项目级钩子配置单元测试。

重点覆盖安全模型:
- 信任门禁 (未信任 → 不加载, fail-closed)
- 命令路径约束 (workspace 外绝对路径 / ``..`` 穿越 → 拒绝)
- 版本校验 / 内联 python handler 拒绝
- 合并语义 (project 在前, user 完整保留, 超限截断)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.hooks.config import HookConfig, HookConfigError
from backend.hooks.merger import merge_hooks
from backend.hooks.project_config import (
    PROJECT_CONFIG_REL_PATH,
    SUPPORTED_VERSION,
    TRUSTED_WORKSPACES_KEY,
    is_workspace_trusted,
    load_project_hooks,
    load_trusted_workspaces,
    trust_workspace,
    untrust_workspace,
    validate_project_hooks,
)

pytestmark = pytest.mark.unit


class _FakeRepo:
    """最小 settings 仓储替身 (内存 dict)。"""

    def __init__(self, initial=None):
        self._store = dict(initial or {})
        self.raise_on_get = False

    def get_json(self, key):
        if self.raise_on_get:
            raise RuntimeError("db down")
        return self._store.get(key)

    def set_json(self, key, value):
        self._store[key] = value


def _write_config(workspace: Path, hooks: list, version: int = SUPPORTED_VERSION) -> Path:
    """在 workspace 下写 .sage/hooks.json。"""
    config_dir = workspace / ".sage"
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / "hooks.json"
    path.write_text(json.dumps({"version": version, "hooks": hooks}), encoding="utf-8")
    return path


# ==================== 信任门禁 ====================


def test_untrusted_workspace_does_not_load(tmp_path):
    """未信任的工作区 → 配置存在也不加载 (fail-closed)。"""
    _write_config(tmp_path, [{"event": "pre_tool_use", "matcher": "bash", "command": "ruff"}])
    repo = _FakeRepo()

    hooks = load_project_hooks(str(tmp_path), repo)
    assert hooks == [], "untrusted workspace must not load project hooks"


def test_trusted_workspace_loads(tmp_path):
    _write_config(tmp_path, [{"event": "pre_tool_use", "matcher": "bash", "command": "ruff"}])
    repo = _FakeRepo()
    trust_workspace(repo, str(tmp_path))

    hooks = load_project_hooks(str(tmp_path), repo)
    assert len(hooks) == 1
    assert hooks[0].command == "ruff"


def test_trust_workspace_is_idempotent(tmp_path):
    repo = _FakeRepo()
    trust_workspace(repo, str(tmp_path))
    trust_workspace(repo, str(tmp_path))
    assert len(load_trusted_workspaces(repo)) == 1


def test_untrust_workspace_removes(tmp_path):
    repo = _FakeRepo()
    trust_workspace(repo, str(tmp_path))
    assert is_workspace_trusted(repo, str(tmp_path))
    untrust_workspace(repo, str(tmp_path))
    assert not is_workspace_trusted(repo, str(tmp_path))


def test_untrust_unknown_workspace_is_noop(tmp_path):
    repo = _FakeRepo()
    untrust_workspace(repo, str(tmp_path))  # 不抛异常
    assert load_trusted_workspaces(repo) == set()


def test_missing_config_returns_empty(tmp_path):
    repo = _FakeRepo()
    trust_workspace(repo, str(tmp_path))
    assert load_project_hooks(str(tmp_path), repo) == []


def test_no_workspace_returns_empty():
    assert load_project_hooks(None, _FakeRepo()) == []
    assert load_project_hooks("", _FakeRepo()) == []


def test_repo_error_is_fail_closed(tmp_path):
    """settings 读失败 → 视为未信任 (不加载), 而非放行。"""
    _write_config(tmp_path, [{"event": "pre_tool_use", "matcher": "bash", "command": "ruff"}])
    repo = _FakeRepo()
    repo.raise_on_get = True
    assert load_project_hooks(str(tmp_path), repo) == []


# ==================== 命令路径约束 ====================


def test_absolute_path_outside_workspace_rejected(tmp_path):
    outside = tmp_path.parent / "evil-script.sh"
    raw = {
        "version": 1,
        "hooks": [{"event": "pre_tool_use", "matcher": "bash", "command": str(outside)}],
    }
    with pytest.raises(HookConfigError, match="outside the workspace"):
        validate_project_hooks(raw, str(tmp_path))


def test_absolute_path_inside_workspace_allowed(tmp_path):
    inside = tmp_path / "scripts" / "check.sh"
    raw = {
        "version": 1,
        "hooks": [{"event": "pre_tool_use", "matcher": "bash", "command": str(inside)}],
    }
    hooks = validate_project_hooks(raw, str(tmp_path))
    assert len(hooks) == 1


def test_parent_traversal_rejected(tmp_path):
    raw = {
        "version": 1,
        "hooks": [
            {"event": "pre_tool_use", "matcher": "bash", "command": "../../bin/evil.sh"}
        ],
    }
    with pytest.raises(HookConfigError, match="outside the workspace"):
        validate_project_hooks(raw, str(tmp_path))


def test_relative_path_inside_workspace_allowed(tmp_path):
    raw = {
        "version": 1,
        "hooks": [{"event": "pre_tool_use", "matcher": "bash", "command": "scripts/check.sh"}],
    }
    hooks = validate_project_hooks(raw, str(tmp_path))
    assert len(hooks) == 1


def test_bare_command_name_allowed(tmp_path):
    """无路径分隔符的命令名经 PATH 解析, 放行。"""
    raw = {
        "version": 1,
        "hooks": [
            {"event": "pre_tool_use", "matcher": "bash", "command": "ruff check ."}
        ],
    }
    hooks = validate_project_hooks(raw, str(tmp_path))
    assert len(hooks) == 1


def test_path_in_option_value_rejected(tmp_path):
    """--config=/outside/path 形式的越界路径也要被拦。"""
    outside = tmp_path.parent / "outside.json"
    raw = {
        "version": 1,
        "hooks": [
            {
                "event": "pre_tool_use",
                "matcher": "bash",
                "command": f"mythical-tool --config={outside}",
            }
        ],
    }
    with pytest.raises(HookConfigError, match="outside the workspace"):
        validate_project_hooks(raw, str(tmp_path))


# ==================== 结构校验 ====================


def test_unsupported_version_rejected(tmp_path):
    raw = {"version": 99, "hooks": []}
    with pytest.raises(HookConfigError, match="version"):
        validate_project_hooks(raw, str(tmp_path))


def test_non_object_config_rejected(tmp_path):
    with pytest.raises(HookConfigError, match="JSON object"):
        validate_project_hooks([], str(tmp_path))


def test_hooks_must_be_list(tmp_path):
    with pytest.raises(HookConfigError, match="must be a list"):
        validate_project_hooks({"version": 1, "hooks": "nope"}, str(tmp_path))


def test_too_many_project_hooks_rejected(tmp_path):
    raw = {
        "version": 1,
        "hooks": [{"event": "pre_tool_use", "matcher": "bash", "command": "ruff"}] * 21,
    }
    with pytest.raises(HookConfigError, match="too many"):
        validate_project_hooks(raw, str(tmp_path))


def test_project_config_rejects_http_hook_type(tmp_path):
    """项目级不开放 HTTP hook —— 防止仓库借信任门禁外联任意地址。"""
    raw = {
        "version": 1,
        "hooks": [
            {
                "event": "pre_tool_use",
                "matcher": "bash",
                "hook_type": "http",
                "url": "https://hooks.example.test/check",
            }
        ],
    }
    with pytest.raises(HookConfigError, match="http"):
        validate_project_hooks(raw, str(tmp_path))


def test_inline_python_handler_rejected(tmp_path):
    """项目级不允许无人认领的 python handler (等于允许仓库加载任意模块)。"""
    raw = {
        "version": 1,
        "hooks": [
            {
                "event": "pre_tool_use",
                "matcher": "bash",
                "hook_type": "python",
                "handler": "evil.module.func",
            }
        ],
    }
    with pytest.raises(HookConfigError, match="builtin_id"):
        validate_project_hooks(raw, str(tmp_path))


def test_python_hook_with_builtin_id_allowed(tmp_path):
    raw = {
        "version": 1,
        "hooks": [
            {
                "event": "pre_tool_use",
                "matcher": "bash",
                "hook_type": "python",
                "handler": "backend.hooks.builtin_guards.security_guard",
                "builtin_id": "security_guard",
            }
        ],
    }
    hooks = validate_project_hooks(raw, str(tmp_path))
    assert len(hooks) == 1
    assert hooks[0].builtin_id == "security_guard"


def test_invalid_config_fails_whole_load_not_partial(tmp_path):
    """一条非法 → 整份配置不加载 (半加载的团队策略比不加载更危险)。"""
    _write_config(
        tmp_path,
        [
            {"event": "pre_tool_use", "matcher": "bash", "command": "ruff"},
            {"event": "bogus_event", "matcher": "bash", "command": "x"},
        ],
    )
    repo = _FakeRepo()
    trust_workspace(repo, str(tmp_path))
    assert load_project_hooks(str(tmp_path), repo) == []


# ==================== 合并语义 ====================


def _h(cmd: str, event: str = "pre_tool_use") -> HookConfig:
    return HookConfig(event=event, command=cmd)


def test_merge_project_first():
    project = [_h("project-check")]
    user = [_h("user-check")]
    merged = merge_hooks(project, user)
    assert [h.command for h in merged] == ["project-check", "user-check"]


def test_merge_user_hooks_fully_preserved():
    project = [_h("p1"), _h("p2")]
    user = [_h("u1"), _h("u2"), _h("u3")]
    merged = merge_hooks(project, user)
    assert len(merged) == 5
    assert {h.command for h in merged} >= {"u1", "u2", "u3"}


def test_merge_truncates_keeping_project_first():
    project = [_h(f"p{i}") for i in range(15)]
    user = [_h(f"u{i}") for i in range(15)]
    merged = merge_hooks(project, user, max_hooks=20)
    assert len(merged) == 20
    assert [h.command for h in merged[:15]] == [f"p{i}" for i in range(15)]


def test_merge_empty_inputs():
    assert merge_hooks([], []) == []
    assert [h.command for h in merge_hooks([], [_h("u")])] == ["u"]
    assert [h.command for h in merge_hooks([_h("p")], [])] == ["p"]


def test_merge_does_not_mutate_inputs():
    project = [_h("p")]
    user = [_h("u")]
    merge_hooks(project, user)
    assert len(project) == 1
    assert len(user) == 1


# ==================== 常量一致性 ====================


def test_trusted_workspaces_key_matches_settings_whitelist():
    """信任键必须在 preferences 白名单内, 否则读写会被 400 拒绝。"""
    from backend.data.settings_repo import SettingsRepository

    assert TRUSTED_WORKSPACES_KEY in SettingsRepository.KEYS


def test_project_config_path_constant():
    assert PROJECT_CONFIG_REL_PATH == ".sage/hooks.json"
