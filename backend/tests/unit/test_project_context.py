"""
M6 项目上下文发现单元测试

覆盖向上发现顺序、sage 优先、去重、单文件/总量上限、render 格式、
缺失/非法路径不抛异常。
"""

from __future__ import annotations

import pytest

from backend.chat.project_context import (
    PER_FILE_CHAR_CAP,
    RENDER_HEADER,
    TOTAL_CHAR_CAP,
    discover_project_context,
)

pytestmark = pytest.mark.unit


def test_upward_discovery_order_and_sage_first(tmp_path):
    """祖先在前、workspace 在后; 同级 SAGE.md 先于 CLAUDE.md。"""
    (tmp_path / "SAGE.md").write_text("root-sage", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "CLAUDE.md").write_text("sub-claude", encoding="utf-8")
    (sub / "SAGE.md").write_text("sub-sage", encoding="utf-8")
    deep = sub / "deep"
    deep.mkdir()  # workspace 根本身无指令文件

    ctx = discover_project_context(deep)

    contents = [e.content for e in ctx.entries]
    assert contents == ["root-sage", "sub-sage", "sub-claude"]
    assert [e.source for e in ctx.entries] == ["sage_md", "sage_md", "claude_md"]
    assert ctx.entries[0].path.endswith("SAGE.md")


def test_identical_content_deduped_by_hash(tmp_path):
    (tmp_path / "SAGE.md").write_text("same content", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "CLAUDE.md").write_text("same content\n", encoding="utf-8")  # strip 后同内容

    ctx = discover_project_context(sub)
    assert len(ctx.entries) == 1
    assert ctx.entries[0].source == "sage_md"  # 祖先的 sage 先被发现


def test_per_file_cap_truncates_and_flags(tmp_path):
    big = "x" * (PER_FILE_CHAR_CAP + 1000)
    (tmp_path / "SAGE.md").write_text(big, encoding="utf-8")

    ctx = discover_project_context(tmp_path)
    assert len(ctx.entries) == 1
    assert len(ctx.entries[0].content) == PER_FILE_CHAR_CAP
    assert ctx.entries[0].truncated is True
    assert "[截断]" in ctx.render()


def test_total_cap_stops_injection(tmp_path):
    # 3 层嵌套目录各一个 6000 字符文件 = 18000 > 16000 上限
    # → 第 3 个被截断到剩余额度 (4000)
    level = tmp_path
    for name in ("a", "b", "c"):
        level = level / name
        level.mkdir()
        (level / "SAGE.md").write_text(name * 6000, encoding="utf-8")

    ctx = discover_project_context(level)
    total = sum(len(e.content) for e in ctx.entries)
    assert total == TOTAL_CHAR_CAP
    assert len(ctx.entries) == 3
    assert ctx.entries[-1].truncated is True
    assert len(ctx.entries[-1].content) == 4000


def test_render_format_contains_marker_and_paths(tmp_path):
    (tmp_path / "SAGE.md").write_text("指令内容", encoding="utf-8")

    ctx = discover_project_context(tmp_path)
    rendered = ctx.render()
    assert rendered.startswith(RENDER_HEADER)
    assert "SAGE.md" in rendered
    assert "[sage_md]" in rendered
    assert "指令内容" in rendered


def test_no_files_gives_empty_context(tmp_path):
    ctx = discover_project_context(tmp_path)
    # 注意: 祖先目录可能含真实 SAGE.md/CLAUDE.md — 用隔离深路径断言 render 非抛即可
    assert isinstance(ctx.render(), str)
    assert ctx.workspace_root == str(tmp_path.resolve())


def test_missing_and_invalid_roots_never_raise():
    ctx = discover_project_context("/nonexistent/path/definitely/not/here")
    assert ctx.entries == []
    assert ctx.render() == ""

    ctx2 = discover_project_context(None)  # 类型错误输入也不抛
    assert ctx2.entries == []
    assert ctx2.render() == ""


def test_symlink_escaping_workspace_is_refused(tmp_path):
    """审查加固: 符号链接指向工作区外的 SAGE.md (如 ~/.ssh/id_rsa) 不得注入。"""
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.md"
    secret.write_text("TOP SECRET KEY MATERIAL", encoding="utf-8")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "SAGE.md").symlink_to(secret)

    ctx = discover_project_context(workspace)

    assert ctx.entries == []
    assert "TOP SECRET" not in ctx.render()


def test_symlink_within_workspace_is_allowed(tmp_path):
    """工作区内互链 (SAGE.md → 同目录真实文件) 放行注入。"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    real = workspace / "real-notes.md"
    real.write_text("legit project notes", encoding="utf-8")
    (workspace / "SAGE.md").symlink_to(real)

    ctx = discover_project_context(workspace)

    assert len(ctx.entries) == 1
    assert ctx.entries[0].content == "legit project notes"
