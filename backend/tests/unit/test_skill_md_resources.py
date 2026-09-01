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

from backend.skills.skill_md import resources as resources_module
from backend.skills.skill_md.resources import (
    ALLOWED_RESOURCE_DIRS,
    ResourceIndex,
    build_resource_index,
    render_body_with_resources,
    validate_resource_path,
)
from backend.skills.skill_md.validation import SkillMdSecurityError

pytestmark = pytest.mark.unit


def _patch_os_name(monkeypatch, name: str) -> None:
    """Patch only resources' platform view without mutating process-wide os.name."""
    original_os = resources_module.os

    class OsProxy:
        def __getattr__(self, attribute):
            return getattr(original_os, attribute)

    proxy = OsProxy()
    proxy.name = name
    monkeypatch.setattr(resources_module, "os", proxy)


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


def test_build_resource_index_fails_closed_without_verified_platform_support(tmp_path, monkeypatch):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "safe.py").write_text("pass", encoding="utf-8")
    monkeypatch.setattr(resources_module, "_resource_index_platform_supported", lambda: False)

    assert build_resource_index(tmp_path) == ResourceIndex()


def test_build_resource_index_windows_metadata_only_normal_resource(tmp_path, monkeypatch):
    """Synthetic Windows branch indexes regular resources after metadata checks."""
    base = tmp_path / "skill"
    scripts = base / "scripts"
    scripts.mkdir(parents=True)
    target = scripts / "check.py"
    target.write_text("pass\n", encoding="utf-8")
    _patch_os_name(monkeypatch, "nt")
    monkeypatch.setattr(resources_module, "_is_reparse_point", lambda path: False)

    index = build_resource_index(base)

    assert index.scripts == (target,)


def test_build_resource_index_windows_does_not_recurse_into_reparse_directory(
    tmp_path, monkeypatch
):
    """Known reparse directories are skipped before their descendants are enumerated."""
    base = tmp_path / "skill"
    scripts = base / "scripts"
    scripts.mkdir(parents=True)
    reparse_dir = scripts / "junction"
    reparse_dir.mkdir()
    descendant = reparse_dir / "should-not-be-seen.py"
    descendant.write_text("secret\n", encoding="utf-8")
    safe = scripts / "safe.py"
    safe.write_text("pass\n", encoding="utf-8")
    _patch_os_name(monkeypatch, "nt")
    monkeypatch.setattr(
        resources_module,
        "_is_reparse_point",
        lambda path: Path(path) == reparse_dir,
    )

    index = build_resource_index(base)

    assert index.scripts == (safe,)


def test_build_resource_index_windows_lstat_error_skips_branch(
    tmp_path, monkeypatch
):
    """A metadata failure prevents enumeration of that directory branch."""
    base = tmp_path / "skill"
    scripts = base / "scripts"
    scripts.mkdir(parents=True)
    broken_dir = scripts / "broken"
    broken_dir.mkdir()
    (broken_dir / "should-not-be-seen.py").write_text("secret\n", encoding="utf-8")
    safe = scripts / "safe.py"
    safe.write_text("pass\n", encoding="utf-8")
    _patch_os_name(monkeypatch, "nt")

    def fail_for_broken(path):
        if Path(path) == broken_dir:
            raise OSError("lstat unavailable")
        return False

    monkeypatch.setattr(resources_module, "_is_reparse_point", fail_for_broken)

    index = build_resource_index(base)

    assert index.scripts == (safe,)


@pytest.mark.parametrize("metadata_result", [True, OSError("metadata unavailable")])
def test_build_resource_index_windows_skips_reparse_or_metadata_error(
    tmp_path, monkeypatch, metadata_result
):
    """Synthetic Windows metadata failures and reparse points fail closed."""
    base = tmp_path / "skill"
    scripts = base / "scripts"
    scripts.mkdir(parents=True)
    target = scripts / "unsafe.py"
    target.write_text("secret\n", encoding="utf-8")
    _patch_os_name(monkeypatch, "nt")

    def fake_is_reparse_point(path):
        if Path(path) == target:
            if isinstance(metadata_result, OSError):
                raise metadata_result
            return metadata_result
        return False

    monkeypatch.setattr(resources_module, "_is_reparse_point", fake_is_reparse_point)

    assert build_resource_index(base).scripts == ()


def test_build_resource_index_non_posix_non_windows_returns_empty(tmp_path, monkeypatch):
    """Unsupported platforms remain fail-closed."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "check.py").write_text("pass\n", encoding="utf-8")
    _patch_os_name(monkeypatch, "java")

    assert build_resource_index(tmp_path) == ResourceIndex()


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




def test_relative_base_dir_index_renders_indexed_resource_without_absolute_path(
    tmp_path, monkeypatch
):
    """Relative roots use one canonical path across indexing and authorization."""
    base = tmp_path / "skill"
    (base / "references").mkdir(parents=True)
    (base / "references" / "guide.md").write_text("guide", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    index = build_resource_index(Path("skill"))

    assert index.references == (base.resolve() / "references" / "guide.md",)
    rendered = render_body_with_resources(
        "See {baseDir}/references/guide.md", Path("skill"), index
    )
    assert rendered == "See references/guide.md"
    assert str(base.resolve()) not in rendered


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


def test_build_resource_index_skips_symlink_escape(tmp_path):
    """白名单目录中的越界符号链接不应进入资源索引。"""
    base = tmp_path / "skill"
    base.mkdir()
    scripts = base / "scripts"
    scripts.mkdir()
    outside = tmp_path / "secret.py"
    outside.write_text("print('secret')\n", encoding="utf-8")
    link = scripts / "linked.py"
    link.symlink_to(outside)

    index = build_resource_index(base)

    assert index.scripts == ()


def test_build_resource_index_skips_symlink_inside_base(tmp_path):
    """即使 symlink 目标仍在 base_dir 内，也不纳入资源索引。"""
    base = tmp_path / "skill"
    base.mkdir()
    scripts = base / "scripts"
    scripts.mkdir()
    target = scripts / "real.py"
    target.write_text("print('real')\n", encoding="utf-8")
    link = scripts / "linked.py"
    link.symlink_to(target)

    index = build_resource_index(base)

    assert index.scripts == (target,)


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
    """body 中的资源引用应替换为安全逻辑相对路径。"""
    _create_resource_files(tmp_path)
    idx = build_resource_index(tmp_path)
    body = "Reference the script at {baseDir}/scripts/lint.py"
    rendered = render_body_with_resources(body, base_dir=tmp_path, index=idx)
    assert rendered == "Reference the script at scripts/lint.py"
    assert str(tmp_path) not in rendered


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
        "Script: scripts/lint.py\n"
        "Guide: references/guide.md\n"
        "Asset: assets/logo.png"
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
    assert "scripts/lint.py" in rendered
    assert "references/guide.md" in rendered
    assert str(tmp_path) not in rendered


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
        "First: scripts/lint.py\n"
        "Second: scripts/lint.py\n"
        "Third: scripts/lint.py"
    )
    assert rendered == expected


def test_render_body_with_resources_rejects_unindexed_resource(tmp_path):
    (tmp_path / "references").mkdir()
    (tmp_path / "references" / "guide.md").write_text("guide", encoding="utf-8")
    with pytest.raises(SkillMdSecurityError):
        render_body_with_resources(
            "{baseDir}/references/guide.md", tmp_path, ResourceIndex()
        )


@pytest.mark.parametrize("punctuation", [".", ",", ")", "]", ":", "!"])
def test_render_body_with_resources_preserves_trailing_path_punctuation(
    tmp_path, punctuation
):
    references = tmp_path / "references"
    references.mkdir()
    guide = references / "guide.md"
    guide.write_text("guide", encoding="utf-8")
    index = ResourceIndex(references=(guide,))

    body = f"See {{baseDir}}/references/guide.md{punctuation}"
    assert render_body_with_resources(body, tmp_path, index) == (
        f"See references/guide.md{punctuation}"
    )


def test_render_body_with_resources_rejects_traversal_with_trailing_punctuation(
    tmp_path,
):
    references = tmp_path / "references"
    references.mkdir()
    guide = references / "guide.md"
    guide.write_text("guide", encoding="utf-8")
    index = ResourceIndex(references=(guide,))

    with pytest.raises(SkillMdSecurityError):
        render_body_with_resources(
            "{baseDir}/references/guide.md/../secret.", tmp_path, index
        )


def test_render_body_with_resources_rejects_directory_and_nul(tmp_path):
    (tmp_path / "references").mkdir()
    idx = ResourceIndex(references=(tmp_path / "references",))
    with pytest.raises(SkillMdSecurityError):
        render_body_with_resources("{baseDir}/references", tmp_path, idx)
    with pytest.raises(SkillMdSecurityError):
        render_body_with_resources("{baseDir}/references/\x00x", tmp_path, idx)


def test_render_body_with_resources_rejects_symlink_even_if_indexed(tmp_path):
    (tmp_path / "references").mkdir()
    outside = tmp_path.parent / "secret-resource.txt"
    outside.write_text("secret", encoding="utf-8")
    link = tmp_path / "references" / "link.txt"
    link.symlink_to(outside)
    idx = ResourceIndex(references=(link,))
    with pytest.raises(SkillMdSecurityError):
        render_body_with_resources("{baseDir}/references/link.txt", tmp_path, idx)


def test_render_body_with_resources_replaces_root_safely(tmp_path):
    rendered = render_body_with_resources("root={baseDir}", tmp_path, ResourceIndex())
    assert rendered == "root=."
    assert str(tmp_path) not in rendered


def test_render_body_with_resources_rejects_forged_index_entries(tmp_path):
    """Rendering must re-check hand-built indexes against resource policy."""
    references = tmp_path / "references"
    references.mkdir()
    (references / "guide.md").write_text("guide", encoding="utf-8")
    secret_dir = tmp_path / "secret"
    secret_dir.mkdir()
    secret = secret_dir / "credentials.txt"
    secret.write_text("secret", encoding="utf-8")
    hidden = references / ".hidden.md"
    hidden.write_text("hidden", encoding="utf-8")
    script_sh = tmp_path / "scripts"
    script_sh.mkdir()
    shell_script = script_sh / "run.sh"
    shell_script.write_text("#!/bin/sh", encoding="utf-8")

    forged_indexes = (
        ResourceIndex(references=(secret,)),
        ResourceIndex(references=(hidden,)),
        ResourceIndex(scripts=(shell_script,)),
    )
    for index in forged_indexes:
        with pytest.raises(SkillMdSecurityError):
            render_body_with_resources(
                "{baseDir}/references/guide.md", tmp_path, index
            )


@pytest.mark.parametrize(
    "body",
    ["{baseDir}..", "{baseDir}../secret", r"{baseDir}..\\secret", "{baseDir}./secret"],
)
def test_render_body_with_resources_rejects_root_dot_path_combinations(tmp_path, body):
    """A root token followed by path-like dots cannot become a traversal."""
    with pytest.raises(SkillMdSecurityError):
        render_body_with_resources(body, tmp_path, ResourceIndex())


def test_render_body_with_resources_rejects_backslash_references(tmp_path):
    """反斜杠资源引用必须进入拒绝逻辑，不能降级为根目录引用。"""
    for body in (
        r"Reference: {baseDir}\references\secret.txt",
        r"Traversal: {baseDir}\..\..\secret",
    ):
        with pytest.raises(SkillMdSecurityError):
            render_body_with_resources(body, tmp_path, ResourceIndex())


def test_render_body_with_resources_rejects_nul_after_placeholder(tmp_path):
    """占位符后的 NUL 必须拒绝，不能残留控制字符或伪路径。"""
    with pytest.raises(SkillMdSecurityError):
        render_body_with_resources(
            "Reference: {baseDir}\x00/secret", tmp_path, ResourceIndex()
        )


def test_render_body_with_resources_rejects_adjacent_root_placeholders(tmp_path):
    """相邻根占位符必须拒绝，避免渲染成歧义路径。"""
    with pytest.raises(SkillMdSecurityError):
        render_body_with_resources("Reference: {baseDir}{baseDir}", tmp_path, ResourceIndex())


@pytest.mark.parametrize("invalid_suffix", ["x", "_x", "\\x", "\x00x", "\x1fx"])
def test_render_body_with_resources_rejects_non_boundary_suffix(
    tmp_path, invalid_suffix
):
    """占位符紧邻路径/标识符或控制字符时必须拒绝。"""
    with pytest.raises(SkillMdSecurityError):
        render_body_with_resources(
            f"Reference: {{baseDir}}{invalid_suffix}", tmp_path, ResourceIndex()
        )


@pytest.mark.parametrize("punctuation", [".", ":", "!", "*", "'", '"', "—"])
def test_render_body_with_resources_allows_prose_punctuation_after_root(
    tmp_path, punctuation
):
    """根占位符后可跟 Markdown/Unicode 标点，不应误判为伪路径。"""
    body = f"Reference: {{baseDir}}{punctuation}"
    assert render_body_with_resources(body, tmp_path, ResourceIndex()) == f"Reference: .{punctuation}"


def test_render_body_with_resources_path_validation(tmp_path):
    """render_body_with_resources 应校验 {baseDir} 路径不逃逸。"""
    _create_resource_files(tmp_path)
    idx = build_resource_index(tmp_path)
    evil_body = "Evil: {baseDir}/../secret.txt"

    with pytest.raises(SkillMdSecurityError):
        render_body_with_resources(evil_body, base_dir=tmp_path, index=idx)
