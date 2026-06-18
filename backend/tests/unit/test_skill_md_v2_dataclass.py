# mypy: disable-error-code="no-untyped-def,attr-defined,func-returns-value"
"""M1 测试: SkillMdDocument v2 字段扩展。

覆盖:
- RequiresSpec / DispatchMode dataclass 默认值
- SkillMdDocument 新增 requires / os / always / dispatch / resources 字段
- frontmatter.parse() 解析 v2 字段的类型校验
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.skills.skill_md.skill import (
    DispatchMode,
    RequiresSpec,
    SkillMdDocument,
)
from backend.skills.skill_md.frontmatter import parse, SkillMdParseError

pytestmark = pytest.mark.unit


# =====================================================================
# RequiresSpec dataclass
# =====================================================================


def test_requires_spec_default_empty():
    """RequiresSpec 默认值: 所有字段为空列表。"""
    req = RequiresSpec()
    assert req.bins == []
    assert req.env == []
    assert req.config == []


def test_requires_spec_with_bins():
    """RequiresSpec 可携带 bins。"""
    req = RequiresSpec(bins=["git", "docker"])
    assert req.bins == ["git", "docker"]
    assert req.env == []


def test_requires_spec_frozen():
    """RequiresSpec 是不可变 dataclass。"""
    req = RequiresSpec(bins=["git"])
    with pytest.raises(AttributeError):
        req.bins = ["docker"]


# =====================================================================
# DispatchMode dataclass
# =====================================================================


def test_dispatch_mode_default():
    """DispatchMode 默认值: 全部关闭 / auto。"""
    dm = DispatchMode()
    assert dm.disable_model_invocation is False
    assert dm.user_invocable is False
    assert dm.user_invocable_name is None
    assert dm.command_dispatch == "auto"


def test_dispatch_mode_with_custom_values():
    """DispatchMode 可设置自定义值。"""
    dm = DispatchMode(
        disable_model_invocation=True,
        user_invocable=True,
        user_invocable_name="/review",
        command_dispatch="tool",
    )
    assert dm.disable_model_invocation is True
    assert dm.user_invocable is True
    assert dm.user_invocable_name == "/review"
    assert dm.command_dispatch == "tool"


def test_dispatch_mode_frozen():
    """DispatchMode 是不可变 dataclass。"""
    dm = DispatchMode()
    with pytest.raises(AttributeError):
        dm.command_dispatch = "prompt"


# =====================================================================
# SkillMdDocument v2 字段
# =====================================================================


def test_skill_md_document_v2_defaults():
    """SkillMdDocument v2 字段默认值等价于 v1 行为。"""
    doc = SkillMdDocument(name="test", description="test skill")
    assert doc.requires == RequiresSpec()
    assert doc.os == []
    assert doc.always is False
    assert doc.dispatch == DispatchMode()
    assert doc.resources is None


def test_skill_md_document_v2_with_requires():
    """SkillMdDocument 可携带 RequiresSpec。"""
    req = RequiresSpec(bins=["git"])
    doc = SkillMdDocument(
        name="test",
        description="test skill",
        requires=req,
    )
    assert doc.requires.bins == ["git"]


def test_skill_md_document_v2_with_os_filter():
    """SkillMdDocument 可携带平台过滤。"""
    doc = SkillMdDocument(
        name="test",
        description="test skill",
        os=["macos", "linux"],
    )
    assert doc.os == ["macos", "linux"]


def test_skill_md_document_v2_with_always():
    """SkillMdDocument 可设置 always=True。"""
    doc = SkillMdDocument(
        name="test",
        description="test skill",
        always=True,
    )
    assert doc.always is True


def test_skill_md_document_v2_with_dispatch():
    """SkillMdDocument 可携带 DispatchMode。"""
    dm = DispatchMode(user_invocable=True, command_dispatch="tool")
    doc = SkillMdDocument(
        name="test",
        description="test skill",
        dispatch=dm,
    )
    assert doc.dispatch.user_invocable is True
    assert doc.dispatch.command_dispatch == "tool"


# =====================================================================
# frontmatter.parse() v2 字段解析
# =====================================================================


def test_parse_v2_requires_bins():
    """frontmatter 含 requires.bins → 解析为 RequiresSpec。"""
    text = """---
name: test-skill
description: A test skill
requires:
  bins: [git, docker]
---
Body content
"""
    meta, body = parse(text)
    assert meta["requires"] == {"bins": ["git", "docker"]}


def test_parse_v2_requires_env():
    """frontmatter 含 requires.env → 解析为 RequiresSpec。"""
    text = """---
name: test-skill
description: A test skill
requires:
  env: [AWS_ACCESS_KEY, GITHUB_TOKEN]
---
Body content
"""
    meta, body = parse(text)
    assert meta["requires"] == {"env": ["AWS_ACCESS_KEY", "GITHUB_TOKEN"]}


def test_parse_v2_requires_config():
    """frontmatter 含 requires.config → 解析为 RequiresSpec。"""
    text = """---
name: test-skill
description: A test skill
requires:
  config: [feature.flag.enabled]
---
Body content
"""
    meta, body = parse(text)
    assert meta["requires"] == {"config": ["feature.flag.enabled"]}


def test_parse_v2_requires_invalid_type_raises():
    """requires 非 dict → SkillMdParseError。"""
    text = """---
name: test-skill
description: A test skill
requires: "git"
---
Body content
"""
    with pytest.raises(SkillMdParseError) as exc:
        parse(text)
    assert "requires" in str(exc.value).lower()


def test_parse_v2_os_valid():
    """os 合法平台名 → 解析成功。"""
    text = """---
name: test-skill
description: A test skill
os: [macos, linux, windows]
---
Body content
"""
    meta, body = parse(text)
    assert meta["os"] == ["macos", "linux", "windows"]


def test_parse_v2_os_invalid_raises():
    """os 含非法平台名 → SkillMdParseError。"""
    text = """---
name: test-skill
description: A test skill
os: [solaris]
---
Body content
"""
    with pytest.raises(SkillMdParseError) as exc:
        parse(text)
    assert "os" in str(exc.value).lower() or "platform" in str(exc.value).lower()


def test_parse_v2_always_true():
    """always=true → 解析为 bool True。"""
    text = """---
name: test-skill
description: A test skill
always: true
---
Body content
"""
    meta, body = parse(text)
    assert meta["always"] is True


def test_parse_v2_always_false():
    """always=false → 解析为 bool False。"""
    text = """---
name: test-skill
description: A test skill
always: false
---
Body content
"""
    meta, body = parse(text)
    assert meta["always"] is False


def test_parse_v2_always_invalid_type_raises():
    """always 非 bool → SkillMdParseError。"""
    text = """---
name: test-skill
description: A test skill
always: "yes"
---
Body content
"""
    with pytest.raises(SkillMdParseError) as exc:
        parse(text)
    assert "always" in str(exc.value).lower()


def test_parse_v2_dispatch_fields():
    """dispatch 相关字段 → 解析成功。"""
    text = """---
name: test-skill
description: A test skill
disable-model-invocation: true
user-invocable: true
command-dispatch: tool
---
Body content
"""
    meta, body = parse(text)
    assert meta["disable-model-invocation"] is True
    assert meta["user-invocable"] is True
    assert meta["command-dispatch"] == "tool"


def test_parse_v2_command_dispatch_invalid_raises():
    """command-dispatch 非法值 → SkillMdParseError。"""
    text = """---
name: test-skill
description: A test skill
command-dispatch: invalid
---
Body content
"""
    with pytest.raises(SkillMdParseError) as exc:
        parse(text)
    assert "command-dispatch" in str(exc.value).lower()


def test_parse_v2_unknown_fields_ignored():
    """未知字段 → 不报错，进 raw_frontmatter。"""
    text = """---
name: test-skill
description: A test skill
future-field: some-value
---
Body content
"""
    meta, body = parse(text)
    assert meta["future-field"] == "some-value"


def test_parse_v2_backward_compatible():
    """v1 SKILL.md（无 v2 字段）→ 解析成功，v2 字段使用默认值。"""
    text = """---
name: test-skill
description: A test skill
version: 1.0.0
---
Body content
"""
    meta, body = parse(text)
    assert "requires" not in meta
    assert "os" not in meta
    assert "always" not in meta
    assert "disable-model-invocation" not in meta