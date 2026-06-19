"""M2 测试: 门控评估器。

覆盖:
- GatingContext 构造（from_env / 手动构造）
- evaluate_gating 纯函数（bins/env/os/always 全部组合）
- GatingResult 返回值（allowed/reasons/always_override）
"""

from __future__ import annotations

import pytest

from backend.skills.skill_md.gating import (
    GatingContext,
    build_gating_context,
    evaluate_gating,
)
from backend.skills.skill_md.skill import RequiresSpec, SkillMdDocument

pytestmark = pytest.mark.unit


# =====================================================================
# GatingContext 构造
# =====================================================================


def test_gating_context_from_env_auto_platform():
    """from_env() 自动检测平台（linux）。"""
    ctx = GatingContext.from_env()
    assert ctx.platform in ("macos", "linux", "windows")
    assert isinstance(ctx.available_bins, frozenset)
    assert isinstance(ctx.available_env, frozenset)
    assert isinstance(ctx.available_config, frozenset)


def test_gating_context_from_env_explicit_platform():
    """from_env() 可显式指定平台。"""
    ctx = GatingContext.from_env(platform="macos")
    assert ctx.platform == "macos"


def test_gating_context_from_env_with_bin_whitelist():
    """from_env() 探测白名单二进制。"""
    # git 通常在大多数系统上都可用
    ctx = GatingContext.from_env(bin_whitelist=["git", "nonexistent-binary-xyz"])
    assert "git" in ctx.available_bins
    assert "nonexistent-binary-xyz" not in ctx.available_bins


def test_build_gating_context_alias():
    """build_gating_context() 是 from_env() 的别名。"""
    ctx = build_gating_context(platform="linux")
    assert ctx.platform == "linux"


# =====================================================================
# evaluate_gating - 基础场景
# =====================================================================


def test_evaluate_empty_requires_allowed():
    """空 requires + 空 os → allowed=True。"""
    doc = SkillMdDocument(name="test", description="test")
    ctx = GatingContext(
        platform="linux",
        available_bins=frozenset(),
        available_env=frozenset(),
        available_config=frozenset(),
    )
    result = evaluate_gating(doc, ctx)
    assert result.allowed is True
    assert result.reasons == ()
    assert result.always_override is False


def test_evaluate_requires_bins_present():
    """requires.bins 全部存在 → allowed=True。"""
    doc = SkillMdDocument(
        name="test",
        description="test",
        requires=RequiresSpec(bins=["git", "docker"]),
    )
    ctx = GatingContext(
        platform="linux",
        available_bins=frozenset(["git", "docker"]),
        available_env=frozenset(),
        available_config=frozenset(),
    )
    result = evaluate_gating(doc, ctx)
    assert result.allowed is True


def test_evaluate_requires_bins_missing():
    """requires.bins 部分缺失 → allowed=False + reasons。"""
    doc = SkillMdDocument(
        name="test",
        description="test",
        requires=RequiresSpec(bins=["git", "docker"]),
    )
    ctx = GatingContext(
        platform="linux",
        available_bins=frozenset(["git"]),  # docker 缺失
        available_env=frozenset(),
        available_config=frozenset(),
    )
    result = evaluate_gating(doc, ctx)
    assert result.allowed is False
    assert "missing bin: docker" in result.reasons


def test_evaluate_requires_env_present():
    """requires.env 全部存在 → allowed=True。"""
    doc = SkillMdDocument(
        name="test",
        description="test",
        requires=RequiresSpec(env=["API_KEY"]),
    )
    ctx = GatingContext(
        platform="linux",
        available_bins=frozenset(),
        available_env=frozenset(["API_KEY"]),
        available_config=frozenset(),
    )
    result = evaluate_gating(doc, ctx)
    assert result.allowed is True


def test_evaluate_requires_env_missing():
    """requires.env 部分缺失 → allowed=False + reasons。"""
    doc = SkillMdDocument(
        name="test",
        description="test",
        requires=RequiresSpec(env=["API_KEY", "SECRET"]),
    )
    ctx = GatingContext(
        platform="linux",
        available_bins=frozenset(),
        available_env=frozenset(["API_KEY"]),  # SECRET 缺失
        available_config=frozenset(),
    )
    result = evaluate_gating(doc, ctx)
    assert result.allowed is False
    assert "missing env: SECRET" in result.reasons


# =====================================================================
# evaluate_gating - 平台过滤
# =====================================================================


def test_evaluate_os_match():
    """os 包含当前平台 → allowed=True。"""
    doc = SkillMdDocument(name="test", description="test", os=["macos", "linux"])
    ctx = GatingContext(
        platform="linux",
        available_bins=frozenset(),
        available_env=frozenset(),
        available_config=frozenset(),
    )
    result = evaluate_gating(doc, ctx)
    assert result.allowed is True


def test_evaluate_os_mismatch():
    """os 不包含当前平台 → allowed=False + reasons。"""
    doc = SkillMdDocument(name="test", description="test", os=["macos"])
    ctx = GatingContext(
        platform="linux",
        available_bins=frozenset(),
        available_env=frozenset(),
        available_config=frozenset(),
    )
    result = evaluate_gating(doc, ctx)
    assert result.allowed is False
    assert "platform mismatch" in result.reasons[0]


def test_evaluate_os_empty():
    """os 为空 → 不过滤平台，allowed=True。"""
    doc = SkillMdDocument(name="test", description="test", os=[])
    ctx = GatingContext(
        platform="linux",
        available_bins=frozenset(),
        available_env=frozenset(),
        available_config=frozenset(),
    )
    result = evaluate_gating(doc, ctx)
    assert result.allowed is True


# =====================================================================
# evaluate_gating - always 覆盖
# =====================================================================


def test_evaluate_always_true_overrides_requires():
    """always=True 跳过 requires 检查，allowed=True + always_override=True。"""
    doc = SkillMdDocument(
        name="test",
        description="test",
        requires=RequiresSpec(bins=["nonexistent"]),
        always=True,
    )
    ctx = GatingContext(
        platform="linux",
        available_bins=frozenset(),
        available_env=frozenset(),
        available_config=frozenset(),
    )
    result = evaluate_gating(doc, ctx)
    assert result.allowed is True
    assert result.always_override is True


def test_evaluate_always_true_still_checks_os():
    """always=True 仍检查平台过滤。"""
    doc = SkillMdDocument(
        name="test",
        description="test",
        os=["macos"],
        always=True,
    )
    ctx = GatingContext(
        platform="linux",
        available_bins=frozenset(),
        available_env=frozenset(),
        available_config=frozenset(),
    )
    result = evaluate_gating(doc, ctx)
    assert result.allowed is False
    assert result.always_override is False
    assert "platform mismatch" in result.reasons[0]


# =====================================================================
# evaluate_gating - 多条件组合
# =====================================================================


def test_evaluate_multiple_failures():
    """多条件同时失败 → reasons 列出全部失败原因。"""
    doc = SkillMdDocument(
        name="test",
        description="test",
        requires=RequiresSpec(bins=["docker"], env=["SECRET"]),
        os=["macos"],
    )
    ctx = GatingContext(
        platform="linux",
        available_bins=frozenset(),
        available_env=frozenset(),
        available_config=frozenset(),
    )
    result = evaluate_gating(doc, ctx)
    assert result.allowed is False
    assert len(result.reasons) == 3
    assert any("platform" in r for r in result.reasons)
    assert any("docker" in r for r in result.reasons)
    assert any("SECRET" in r for r in result.reasons)


def test_evaluate_requires_config_missing():
    """requires.config 缺失 → allowed=False + reasons（v1 暂不支持 config）。"""
    doc = SkillMdDocument(
        name="test",
        description="test",
        requires=RequiresSpec(config=["feature.flag"]),
    )
    ctx = GatingContext(
        platform="linux",
        available_bins=frozenset(),
        available_env=frozenset(),
        available_config=frozenset(),  # v1 不支持 config
    )
    result = evaluate_gating(doc, ctx)
    assert result.allowed is False
    assert "missing config: feature.flag" in result.reasons


# =====================================================================
# evaluate_gating - 边界场景
# =====================================================================


def test_evaluate_always_false_with_empty_requires():
    """always=False + 空 requires → allowed=True。"""
    doc = SkillMdDocument(
        name="test",
        description="test",
        requires=RequiresSpec(),
        always=False,
    )
    ctx = GatingContext(
        platform="linux",
        available_bins=frozenset(),
        available_env=frozenset(),
        available_config=frozenset(),
    )
    result = evaluate_gating(doc, ctx)
    assert result.allowed is True
    assert result.always_override is False


def test_evaluate_all_conditions_met():
    """所有条件满足 → allowed=True。"""
    doc = SkillMdDocument(
        name="test",
        description="test",
        requires=RequiresSpec(bins=["git"], env=["API_KEY"]),
        os=["linux", "macos"],
    )
    ctx = GatingContext(
        platform="linux",
        available_bins=frozenset(["git"]),
        available_env=frozenset(["API_KEY"]),
        available_config=frozenset(),
    )
    result = evaluate_gating(doc, ctx)
    assert result.allowed is True
    assert result.reasons == ()
