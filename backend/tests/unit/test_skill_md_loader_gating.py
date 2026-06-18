"""M3 测试: Loader 集成门控。

覆盖:
- SkillMdHotLoader 接受 gating_ctx 参数
- scan_and_load 内部对每个 skill 调用 evaluate_gating
- 门控失败的 skill 被 skip，记入 skipped_count
- always=True 的 skill 跳过门控检查
- 集成测试验证：2 个 skill，1 个 requires 不满足 → 只加载另一个
- 确保 v1 行为不变（gating_ctx=None 时全部加载）
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.skills.registry import SkillRegistry
from backend.skills.skill_md.gating import GatingContext
from backend.skills.skill_md.loader import SkillMdHotLoader

pytestmark = pytest.mark.unit


def _write_skill_md(tmp_path: Path, name: str, content: str) -> Path:
    """在 tmp_path/<name>/SKILL.md 写一个 SKILL.md。"""
    skill_dir = tmp_path / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / "SKILL.md"
    path.write_text(content, encoding="utf-8")
    return path


# =====================================================================
# 基础门控集成
# =====================================================================


def test_loader_without_gating_ctx_loads_all(tmp_path):
    """gating_ctx=None (v1 行为) → 全部加载，无门控。"""
    registry = SkillRegistry()
    loader = SkillMdHotLoader(registry, dirs=[tmp_path], gating_ctx=None)

    _write_skill_md(
        tmp_path,
        "skill-a",
        """---
name: skill-a
description: Test skill A
requires:
  bins: [nonexistent-binary-xyz]
---
Body A
""",
    )

    loaded, skipped = loader.scan_and_load()
    assert loaded == 1
    assert skipped == 0
    assert registry.exists("skill-a")


def test_loader_with_gating_ctx_skips_unmet_requires(tmp_path):
    """gating_ctx 存在 + requires.bins 不满足 → skip。"""
    registry = SkillRegistry()
    ctx = GatingContext(
        platform="linux",
        available_bins=frozenset(),  # 没有任何二进制
        available_env=frozenset(),
        available_config=frozenset(),
    )
    loader = SkillMdHotLoader(registry, dirs=[tmp_path], gating_ctx=ctx)

    _write_skill_md(
        tmp_path,
        "skill-a",
        """---
name: skill-a
description: Test skill A
requires:
  bins: [nonexistent-binary-xyz]
---
Body A
""",
    )

    loaded, skipped = loader.scan_and_load()
    assert loaded == 0
    assert skipped == 1
    assert not registry.exists("skill-a")


def test_loader_with_gating_ctx_loads_met_requires(tmp_path):
    """gating_ctx 存在 + requires.bins 满足 → 加载。"""
    registry = SkillRegistry()
    ctx = GatingContext(
        platform="linux",
        available_bins=frozenset(["git"]),  # git 可用
        available_env=frozenset(),
        available_config=frozenset(),
    )
    loader = SkillMdHotLoader(registry, dirs=[tmp_path], gating_ctx=ctx)

    _write_skill_md(
        tmp_path,
        "skill-a",
        """---
name: skill-a
description: Test skill A
requires:
  bins: [git]
---
Body A
""",
    )

    loaded, skipped = loader.scan_and_load()
    assert loaded == 1
    assert skipped == 0
    assert registry.exists("skill-a")


def test_loader_multiple_skills_partial_gating(tmp_path):
    """2 个 skill，1 个 requires 不满足 → 只加载另一个。"""
    registry = SkillRegistry()
    ctx = GatingContext(
        platform="linux",
        available_bins=frozenset(["git"]),  # git 可用，docker 不可用
        available_env=frozenset(),
        available_config=frozenset(),
    )
    loader = SkillMdHotLoader(registry, dirs=[tmp_path], gating_ctx=ctx)

    _write_skill_md(
        tmp_path,
        "skill-a",
        """---
name: skill-a
description: Test skill A (requires git)
requires:
  bins: [git]
---
Body A
""",
    )

    _write_skill_md(
        tmp_path,
        "skill-b",
        """---
name: skill-b
description: Test skill B (requires docker)
requires:
  bins: [docker]
---
Body B
""",
    )

    loaded, skipped = loader.scan_and_load()
    assert loaded == 1
    assert skipped == 1
    assert registry.exists("skill-a")
    assert not registry.exists("skill-b")


# =====================================================================
# always=True 覆盖门控
# =====================================================================


def test_loader_always_true_skips_gating(tmp_path):
    """always=True → 跳过门控，即使 requires 不满足也加载。"""
    registry = SkillRegistry()
    ctx = GatingContext(
        platform="linux",
        available_bins=frozenset(),  # 没有任何二进制
        available_env=frozenset(),
        available_config=frozenset(),
    )
    loader = SkillMdHotLoader(registry, dirs=[tmp_path], gating_ctx=ctx)

    _write_skill_md(
        tmp_path,
        "skill-a",
        """---
name: skill-a
description: Test skill A
requires:
  bins: [nonexistent-binary-xyz]
always: true
---
Body A
""",
    )

    loaded, skipped = loader.scan_and_load()
    assert loaded == 1
    assert skipped == 0
    assert registry.exists("skill-a")


def test_loader_always_true_still_checks_os(tmp_path):
    """always=True 仍检查平台过滤。"""
    registry = SkillRegistry()
    ctx = GatingContext(
        platform="linux",
        available_bins=frozenset(),
        available_env=frozenset(),
        available_config=frozenset(),
    )
    loader = SkillMdHotLoader(registry, dirs=[tmp_path], gating_ctx=ctx)

    _write_skill_md(
        tmp_path,
        "skill-a",
        """---
name: skill-a
description: Test skill A
os: [macos]
always: true
---
Body A
""",
    )

    loaded, skipped = loader.scan_and_load()
    assert loaded == 0
    assert skipped == 1
    assert not registry.exists("skill-a")


# =====================================================================
# 平台过滤
# =====================================================================


def test_loader_os_filter_match(tmp_path):
    """os 包含当前平台 → 加载。"""
    registry = SkillRegistry()
    ctx = GatingContext(
        platform="linux",
        available_bins=frozenset(),
        available_env=frozenset(),
        available_config=frozenset(),
    )
    loader = SkillMdHotLoader(registry, dirs=[tmp_path], gating_ctx=ctx)

    _write_skill_md(
        tmp_path,
        "skill-a",
        """---
name: skill-a
description: Test skill A
os: [linux, macos]
---
Body A
""",
    )

    loaded, skipped = loader.scan_and_load()
    assert loaded == 1
    assert skipped == 0
    assert registry.exists("skill-a")


def test_loader_os_filter_mismatch(tmp_path):
    """os 不包含当前平台 → skip。"""
    registry = SkillRegistry()
    ctx = GatingContext(
        platform="linux",
        available_bins=frozenset(),
        available_env=frozenset(),
        available_config=frozenset(),
    )
    loader = SkillMdHotLoader(registry, dirs=[tmp_path], gating_ctx=ctx)

    _write_skill_md(
        tmp_path,
        "skill-a",
        """---
name: skill-a
description: Test skill A
os: [macos, windows]
---
Body A
""",
    )

    loaded, skipped = loader.scan_and_load()
    assert loaded == 0
    assert skipped == 1
    assert not registry.exists("skill-a")


# =====================================================================
# 环境变量门控
# =====================================================================


def test_loader_requires_env_missing(tmp_path):
    """requires.env 缺失 → skip。"""
    registry = SkillRegistry()
    ctx = GatingContext(
        platform="linux",
        available_bins=frozenset(),
        available_env=frozenset(),  # 没有任何环境变量
        available_config=frozenset(),
    )
    loader = SkillMdHotLoader(registry, dirs=[tmp_path], gating_ctx=ctx)

    _write_skill_md(
        tmp_path,
        "skill-a",
        """---
name: skill-a
description: Test skill A
requires:
  env: [SOME_SECRET_KEY]
---
Body A
""",
    )

    loaded, skipped = loader.scan_and_load()
    assert loaded == 0
    assert skipped == 1
    assert not registry.exists("skill-a")


def test_loader_requires_env_present(tmp_path):
    """requires.env 存在 → 加载。"""
    registry = SkillRegistry()
    ctx = GatingContext(
        platform="linux",
        available_bins=frozenset(),
        available_env=frozenset(["SOME_SECRET_KEY"]),
        available_config=frozenset(),
    )
    loader = SkillMdHotLoader(registry, dirs=[tmp_path], gating_ctx=ctx)

    _write_skill_md(
        tmp_path,
        "skill-a",
        """---
name: skill-a
description: Test skill A
requires:
  env: [SOME_SECRET_KEY]
---
Body A
""",
    )

    loaded, skipped = loader.scan_and_load()
    assert loaded == 1
    assert skipped == 0
    assert registry.exists("skill-a")


# =====================================================================
# 多条件组合
# =====================================================================


def test_loader_multiple_conditions_all_met(tmp_path):
    """所有条件满足 → 加载。"""
    registry = SkillRegistry()
    ctx = GatingContext(
        platform="linux",
        available_bins=frozenset(["git"]),
        available_env=frozenset(["API_KEY"]),
        available_config=frozenset(),
    )
    loader = SkillMdHotLoader(registry, dirs=[tmp_path], gating_ctx=ctx)

    _write_skill_md(
        tmp_path,
        "skill-a",
        """---
name: skill-a
description: Test skill A
os: [linux, macos]
requires:
  bins: [git]
  env: [API_KEY]
---
Body A
""",
    )

    loaded, skipped = loader.scan_and_load()
    assert loaded == 1
    assert skipped == 0
    assert registry.exists("skill-a")


def test_loader_multiple_conditions_one_missing(tmp_path):
    """多个条件中一个不满足 → skip。"""
    registry = SkillRegistry()
    ctx = GatingContext(
        platform="linux",
        available_bins=frozenset(["git"]),
        available_env=frozenset(),  # API_KEY 缺失
        available_config=frozenset(),
    )
    loader = SkillMdHotLoader(registry, dirs=[tmp_path], gating_ctx=ctx)

    _write_skill_md(
        tmp_path,
        "skill-a",
        """---
name: skill-a
description: Test skill A
os: [linux]
requires:
  bins: [git]
  env: [API_KEY]
---
Body A
""",
    )

    loaded, skipped = loader.scan_and_load()
    assert loaded == 0
    assert skipped == 1
    assert not registry.exists("skill-a")
