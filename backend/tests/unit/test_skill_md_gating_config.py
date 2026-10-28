"""requires.config 门控实现 (缺口 #11)。

- config 键在 settings 白名单里且有值 -> 放行
- config 键在白名单里但没值 -> "missing config: <key>"
- config 键不在白名单里 -> "unknown config key: <key> (not in settings whitelist)"
- 没有 settings_repo (无 DB 环境) -> available_config 为空, 保守跳过
- 单键读取失败不阻断整体快照
"""

from __future__ import annotations

import os

import pytest

from backend.skills.skill_md.gating import (
    GatingContext,
    build_gating_context,
    evaluate_gating,
)
from backend.skills.skill_md.skill import RequiresSpec, SkillMdDocument

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(os.name == "nt", reason="skill gating 读取依赖 POSIX O_NOFOLLOW"),
]


class _FakeSettingsRepo:
    """最小 settings 仓储替身 -- 只暴露 gating 需要的 get() 接口。"""

    def __init__(self, values):
        # type: (dict) -> None
        self._values = dict(values)

    def get(self, key):
        return self._values.get(key)


def _doc_with_config(*config_keys):
    return SkillMdDocument(
        name="cfg-skill",
        description="需要配置的技能",
        requires=RequiresSpec(config=list(config_keys)),
    )


def test_config_key_present_allows_skill():
    repo = _FakeSettingsRepo({"permission_mode": "ask"})
    ctx = build_gating_context(platform="linux", settings_repo=repo)

    result = evaluate_gating(_doc_with_config("permission_mode"), ctx)

    assert result.allowed is True
    assert result.reasons == ()


def test_config_key_known_but_absent_reports_missing():
    repo = _FakeSettingsRepo({})
    ctx = build_gating_context(platform="linux", settings_repo=repo)

    result = evaluate_gating(_doc_with_config("permission_mode"), ctx)

    assert result.allowed is False
    assert "missing config: permission_mode" in result.reasons


def test_config_key_not_in_whitelist_reports_unknown():
    repo = _FakeSettingsRepo({})
    ctx = build_gating_context(platform="linux", settings_repo=repo)

    result = evaluate_gating(_doc_with_config("not.a.real.setting"), ctx)

    assert result.allowed is False
    assert (
        "unknown config key: not.a.real.setting (not in settings whitelist)"
        in result.reasons
    )


def test_empty_config_value_counts_as_missing():
    repo = _FakeSettingsRepo({"permission_mode": ""})
    ctx = build_gating_context(platform="linux", settings_repo=repo)

    result = evaluate_gating(_doc_with_config("permission_mode"), ctx)

    assert result.allowed is False
    assert "missing config: permission_mode" in result.reasons


def test_without_settings_repo_config_is_never_available():
    ctx = build_gating_context(platform="linux")

    assert ctx.available_config == frozenset()
    result = evaluate_gating(_doc_with_config("permission_mode"), ctx)
    assert result.allowed is False
    assert "missing config: permission_mode" in result.reasons


def test_known_config_snapshot_lists_settings_whitelist():
    ctx = build_gating_context(platform="linux")

    assert "permission_mode" in ctx.known_config
    assert "not.a.real.setting" not in ctx.known_config


def test_manually_built_context_keeps_missing_config_reason():
    """旧调用点 (显式构造 GatingContext) 行为不变 -- 保持 "missing config"。"""
    ctx = GatingContext(
        platform="linux",
        available_bins=frozenset(),
        available_env=frozenset(),
        available_config=frozenset(),
    )

    result = evaluate_gating(_doc_with_config("feature.flag"), ctx)

    assert result.allowed is False
    assert "missing config: feature.flag" in result.reasons


def test_settings_read_failure_degrades_to_missing_not_crash():
    class _BrokenRepo:
        def get(self, key):
            raise RuntimeError("db down")

    ctx = build_gating_context(platform="linux", settings_repo=_BrokenRepo())

    assert ctx.available_config == frozenset()
    result = evaluate_gating(_doc_with_config("permission_mode"), ctx)
    assert result.allowed is False
