"""M4 测试: 资源索引。

覆盖 backend.skills.skill_md.resources:
- ResourceIndex dataclass
- build_resource_index: 扫描白名单子目录
- validate_resource_path: 路径遍历防御
- render_body_with_resources: 替换 body 中的 {baseDir}/... 引用
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.skills.skill_md.resources import (
    ALLOWED_RESOURCE_DIRS,
    ResourceIndex,
    build_resource_index,
    render_body_with_resources,
    validate_resource_path,
)
from backend.skills.skill_md.validation import SkillMdSecurityError

pytestmark = pytest.mark.unit


def _create_resource_files(base_dir: Path) -> None:
    """创建测试用的资源目录结构。"""
    # 白名单子目录
    (base_dir / "scripts").mkdir()
    (base_dir / "scripts" / "lint.py").write_text("# script\n", encoding="utf-8")
    (base_dir / "scripts" / "format.sh").write_text("#!/bin/bash\n", encoding="utf-8")

    (base_dir / "references").mkdir()
    (base_dir / "references" / "guide.md").write_text("# Guide\n", encoding="utf-8")

    (base_dir / "assets").mkdir()
    (base_dir / "assets" / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    (base_dir / "templates").mkdir()
    (base_dir / "templates" / "default.txt").write_text("default template\n", encoding="utf-8")

    # 创建非白名单子目录（应被忽略）
    (base_dir / "secret_data").mkdir()
    (base_dir / "secret_data" / "credentials.txt").write_text("secret\n", encoding="utf-8")

    (base_dir / "config").mkdir()
    (base_dir / "config" / "settings.yaml").write_text("key: value\n", encoding="utf-8")

    # 创建隐藏目录（应被跳过）
    (base_dir / ".hidden").mkdir()
    (base_dir / ".hidden" / "secret.py").write_text("# hidden\n", encoding="utf-8")

    # 创建白名单子目录中的隐藏文件（应被跳过）
    (base_dir / "scripts" / ".secret.py").write_text("# hidden script\n", encoding="utf-8")

    # 创建白名单子目录中的非 .py 文件（仅 scripts/ 接受 .py）
    (base_dir / "scripts" / "README.md").write_text("# readme\n", encoding="utf-8")
    (base_dir / "scripts" / "config.txt").write_text("config\n", encoding="utf-8")


# =====================================================================
# ResourceIndex dataclass
# =====================================================================


def test_resource_index_default_empty():
    """ResourceIndex 默认值: 所有字段为空元组。"""
    idx = ResourceIndex()
    assert idx.scripts == ()
    assert idx.references == ()
    assert idx.assets == ()
    assert idx.templates == ()


def test_resource_index_with_files(tmp_path):
    """ResourceIndex 可携带文件路径。"""
    script = tmp_path / "script.py"
    ref = tmp_path / "ref.md"
    idx = ResourceIndex(
        scripts=(script,),
        references=(ref,),
    )
    assert idx.scripts == (script,)
    assert idx.references == (ref,)


# =====================================================================
# ALLOWED_RESOURCE_DIRS 常量
# =====================================================================


def test_allowed_resource_dirs():
    """白名单子目录: scripts, references, assets, templates。"""
    assert frozenset({"scripts", "references", "assets", "templates"}) == ALLOWED_RESOURCE_DIRS


# =====================================================================
# build_resource_index - 扫描
# =====================================================================


def test_build_resource_index_empty_dir(tmp_path):
    """空目录 → ResourceIndex 全空。"""
    idx = build_resource_index(tmp_path)
    assert idx.scripts == ()
    assert idx.references == ()
    assert idx.assets == ()
    assert idx.templates == ()


def test_build_resource_index_scans_whitelist_dirs(tmp_path):
    """build_resource_index 扫描白名单子目录。"""
    _create_resource_files(tmp_path)
    idx = build_resource_index(tmp_path)

    # scripts/*.py 应被索引（仅 .py 文件，format.sh 被忽略）
    assert len(idx.scripts) == 1
    script_names = {p.name for p in idx.scripts}
    assert script_names == {"lint.py"}

    # references/** 应被索引
    assert len(idx.references) == 1
    assert idx.references[0].name == "guide.md"

    # assets/** 应被索引
    assert len(idx.assets) == 1
    assert idx.assets[0].name == "logo.png"

    # templates/** 应被索引
    assert len(idx.templates) == 1
    assert idx.templates[0].name == "default.txt"


def test_build_resource_index_ignores_non_whitelist_dirs(tmp_path):
    """非白名单子目录 (secret_data, config) 应被忽略。"""
    _create_resource_files(tmp_path)
    idx = build_resource_index(tmp_path)
    # 所有资源都应该在白名单子目录中
    all_resources = idx.scripts + idx.references + idx.assets + idx.templates
    for resource in all_resources:
        relative = resource.relative_to(tmp_path)
        assert relative.parts[0] in ALLOWED_RESOURCE_DIRS


def test_build_resource_index_ignores_hidden_dirs(tmp_path):
    """隐藏目录 (.hidden) 应被跳过。"""
    _create_resource_files(tmp_path)
    idx = build_resource_index(tmp_path)
    all_resources = idx.scripts + idx.references + idx.assets + idx.templates
    for resource in all_resources:
        relative = resource.relative_to(tmp_path)
        assert not any(part.startswith(".") for part in relative.parts)


def test_build_resource_index_ignores_hidden_files_in_whitelist_dirs(tmp_path):
    """白名单子目录中的隐藏文件应被跳过。"""
    _create_resource_files(tmp_path)
    idx = build_resource_index(tmp_path)
    for script in idx.scripts:
        assert not script.name.startswith(".")


def test_build_resource_index_scripts_only_accepts_py_files(tmp_path):
    """scripts/ 目录只接受 .py 文件，其他扩展名被忽略。"""
    _create_resource_files(tmp_path)
    idx = build_resource_index(tmp_path)
    for script in idx.scripts:
        # 注意: format.sh 也是"脚本"，但 v1 简化: 只接受 .py
        # 实际上 plan 说只接受 .py，所以 format.sh 应该被忽略
        assert script.suffix == ".py"


def test_build_resource_index_references_accepts_all_files(tmp_path):
    """references/ 目录接受所有文件类型。"""
    _create_resource_files(tmp_path)
    (tmp_path / "references" / "data.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "references" / "config.yaml").write_text("k: v\n", encoding="utf-8")
    idx = build_resource_index(tmp_path)
    ref_names = {p.name for p in idx.references}
    assert "guide.md" in ref_names
    assert "data.json" in ref_names
    assert "config.yaml" in ref_names


def test_build_resource_index_nonexistent_dir(tmp_path):
    """base_dir 不存在 → 返回空 ResourceIndex（不抛异常）。"""
    nonexistent = tmp_path / "nonexistent"
    idx = build_resource_index(nonexistent)
    assert idx.scripts == ()
    assert idx.references == ()


# =====================================================================
# validate_resource_path - 路径遍历防御
# =====================================================================


def test_validate_resource_path_in_base_dir(tmp_path):
    """路径在 base_dir 内 → 返回 resolve 后的路径。"""
    base = tmp_path / "skills"
    base.mkdir()
    target = base / "scripts" / "lint.py"
    target.parent.mkdir()
    target.write_text("# script\n", encoding="utf-8")

    resolved = validate_resource_path(target, base_dir=base)
    assert resolved == target.resolve()


def test_validate_resource_path_rejects_traversal(tmp_path):
    """路径用 ../ 跳出 base_dir → 抛 SkillMdSecurityError。"""
    base = tmp_path / "skills"
    base.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("secret\n", encoding="utf-8")

    # 构造一个通过 ../ 跳出 base_dir 的路径
    evil_path = base / ".." / "secret.txt"

    with pytest.raises(SkillMdSecurityError):
        validate_resource_path(evil_path, base_dir=base)


def test_validate_resource_path_rejects_absolute_escape(tmp_path):
    """绝对路径跳出 base_dir → 抛 SkillMdSecurityError。"""
    base = tmp_path / "skills"
    base.mkdir()
    # /etc/passwd 在 base_dir 之外
    with pytest.raises(SkillMdSecurityError):
        validate_resource_path(Path("/etc/passwd"), base_dir=base)


def test_validate_resource_path_rejects_symlink_escape(tmp_path):
    """symlink 指到 base_dir 之外 → 抛 SkillMdSecurityError。"""
    base = tmp_path / "skills"
    base.mkdir()
    escape = tmp_path / "secret.txt"
    escape.write_text("secret\n", encoding="utf-8")

    link = base / "sneaky_link.py"
    link.symlink_to(escape)

    with pytest.raises(SkillMdSecurityError):
        validate_resource_path(link, base_dir=base)


def test_validate_resource_path_accepts_file_in_nested_subdir(tmp_path):
    """base_dir 下的嵌套子目录中的文件应该被接受。"""
    base = tmp_path / "skills"
    base.mkdir()
    nested = base / "scripts" / "subdir"
    nested.mkdir(parents=True)
    target = nested / "deep.py"
    target.write_text("# deep\n", encoding="utf-8")

    resolved = validate_resource_path(target, base_dir=base)
    assert resolved == target.resolve()


# =====================================================================
# render_body_with_resources - body 占位符替换
# =====================================================================


def test_render_body_with_resources_replaces_base_dir(tmp_path):
    """body 中的 {baseDir} 占位符应被替换为绝对路径。"""
    _create_resource_files(tmp_path)
    idx = build_resource_index(tmp_path)
    body = "Reference the script at {baseDir}/scripts/lint.py"
    rendered = render_body_with_resources(body, base_dir=tmp_path, index=idx)
    expected = f"Reference the script at {tmp_path}/scripts/lint.py"
    assert rendered == expected


def test_render_body_with_resources_replaces_multiple_references(tmp_path):
    """body 中的多个 {baseDir} 引用应全部被替换。"""
    _create_resource_files(tmp_path)
    idx = build_resource_index(tmp_path)
    body = (
        "Script: {baseDir}/scripts/lint.py\n"
        "Guide: {baseDir}/references/guide.md\n"
        "Asset: {baseDir}/assets/logo.png"
    )
    rendered = render_body_with_resources(body, base_dir=tmp_path, index=idx)
    expected = (
        f"Script: {tmp_path}/scripts/lint.py\n"
        f"Guide: {tmp_path}/references/guide.md\n"
        f"Asset: {tmp_path}/assets/logo.png"
    )
    assert rendered == expected


def test_render_body_with_resources_preserves_other_text(tmp_path):
    """body 中非 {baseDir} 的内容应原样保留。"""
    _create_resource_files(tmp_path)
    idx = build_resource_index(tmp_path)
    body = (
        "# Skill\n\n"
        "Use the script at {baseDir}/scripts/lint.py for code review.\n\n"
        "See also {baseDir}/references/guide.md for details.\n"
    )
    rendered = render_body_with_resources(body, base_dir=tmp_path, index=idx)
    # 非占位符内容应原样保留
    assert "# Skill\n\n" in rendered
    assert "Use the script at" in rendered
    assert "for code review.\n\n" in rendered
    assert "See also" in rendered
    assert "for details.\n" in rendered
    # 占位符应被替换
    assert "{baseDir}" not in rendered
    assert f"{tmp_path}/scripts/lint.py" in rendered
    assert f"{tmp_path}/references/guide.md" in rendered


def test_render_body_with_resources_no_references(tmp_path):
    """body 中没有 {baseDir} 引用 → 原样返回。"""
    body = "# Plain markdown\n\nNo references here.\n"
    rendered = render_body_with_resources(body, base_dir=tmp_path, index=ResourceIndex())
    assert rendered == body


def test_render_body_with_resources_handles_repeated_references(tmp_path):
    """body 中同一个 {baseDir} 引用出现多次应全部被替换。"""
    _create_resource_files(tmp_path)
    idx = build_resource_index(tmp_path)
    body = (
        "First: {baseDir}/scripts/lint.py\n"
        "Second: {baseDir}/scripts/lint.py\n"
        "Third: {baseDir}/scripts/lint.py"
    )
    rendered = render_body_with_resources(body, base_dir=tmp_path, index=idx)
    expected = (
        f"First: {tmp_path}/scripts/lint.py\n"
        f"Second: {tmp_path}/scripts/lint.py\n"
        f"Third: {tmp_path}/scripts/lint.py"
    )
    assert rendered == expected


def test_render_body_with_resources_path_validation(tmp_path):
    """render_body_with_resources 应校验 {baseDir} 路径不逃逸。"""
    _create_resource_files(tmp_path)
    idx = build_resource_index(tmp_path)
    # 模拟一个恶意 body，引用 base_dir 之外的路径
    evil_body = "Evil: {baseDir}/../secret.txt"

    # 这应该被检测到并抛异常（或替换失败）
    # 由于 {baseDir} 在 base_dir 内，但 /../ 会逃逸
    with pytest.raises(SkillMdSecurityError):
        render_body_with_resources(evil_body, base_dir=tmp_path, index=idx)
