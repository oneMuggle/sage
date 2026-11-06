"""P4 上下文级联继承单元测试 (设计 §8)。

覆盖:
- 链构造 (父 → 子顺序);
- 标记格式 (``<!-- SAGE-CONTEXT level=... project=... -->``);
- 预算强制 (最外层先截断);
- 每层保底;
- 跨层内容哈希去重;
- 无注册项目降级;
- 用户级 ``~/.sage/SAGE.md`` 包含;
- 合成叶子层 (workspace 比最深层注册项目更靠内)。

pytestmark 标记 unit; ``setup_test_db`` 是 autouse fixture (每个测试独立临时 DB)。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from backend.chat.project_context import CASCADE_HEADER, RENDER_HEADER
from backend.chat.project_context_cascade import (
    CascadeLayer,
    _apply_cascade_budget,
    _sanitize_marker_value,
    discover_project_context_cascade,
)
from backend.data.project_repo import ProjectRepository

pytestmark = [pytest.mark.unit]


# ── helpers ─────────────────────────────────────────────────────────────────


def _register(path: Path) -> None:
    """在 projects 表登记 tmp_path 下的目录 (setup_test_db 提供临时 DB)。"""
    ProjectRepository().register(str(path))


def _write_instruction(directory: Path, filename: str, content: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / filename
    target.write_text(content, encoding="utf-8")
    return target


# ── marker sanitization ─────────────────────────────────────────────────────


def test_sanitize_marker_value_strips_newlines_and_quotes():
    assert _sanitize_marker_value('a"b\nc') == "a b c"
    assert _sanitize_marker_value("") == "project"
    assert _sanitize_marker_value('   "x"   ') == "x"


# ── budget ──────────────────────────────────────────────────────────────────


def test_apply_budget_no_op_when_under_cap():
    layer = CascadeLayer(
        project_id="p", project_name="p", path="/p", is_root=True,
        entries=[], budget_cut=0,
    )
    # plain_content 是空 → 长度 0 ≤ CASCADE_TOTAL_CHAR_CAP → 不动
    _apply_cascade_budget([layer])
    assert layer.budget_cut == 0


def _layer_plain(layer: CascadeLayer) -> int:
    """Plain content 总长 (含 per-entry 头部开销)。"""
    return len(layer.plain_content())


def test_apply_budget_outermost_first_truncation():
    """超预算时, 从最外层开始削减; 内层在保底内不受影响。"""
    from backend.chat.project_context import ContextEntry

    outer = CascadeLayer(
        project_id="o", project_name="o", path="/o", is_root=True,
        entries=[ContextEntry(path="/o/SAGE.md", source="sage_md", content="x" * 5000)],
    )
    inner = CascadeLayer(
        project_id="i", project_name="i", path="/i",
        entries=[ContextEntry(path="/i/SAGE.md", source="sage_md", content="y" * 3000)],
    )
    outer_len = _layer_plain(outer)  # header 29 + content 5000
    inner_len = _layer_plain(inner)  # 3029
    total_cap, floor = 4000, 1500
    overshoot = (outer_len + inner_len) - total_cap
    # 第一轮: 外层可 cut outer_len-floor; 内层可 cut inner_len-floor
    outer_expected_cut = min(overshoot, outer_len - floor)
    remaining_overshoot = overshoot - outer_expected_cut
    inner_expected_cut = min(remaining_overshoot, inner_len - floor)

    _apply_cascade_budget([outer, inner], total_cap=total_cap, floor=floor)
    assert outer.budget_cut == outer_expected_cut
    assert inner.budget_cut == inner_expected_cut


def test_apply_budget_floor_protects_inner_when_outer_can_cover():
    """外层单独能覆盖 overshoot 时, 内层不被动。"""
    from backend.chat.project_context import ContextEntry

    outer = CascadeLayer(
        project_id="o", project_name="o", path="/o", is_root=True,
        entries=[ContextEntry(path="/o/SAGE.md", source="sage_md", content="x" * 6000)],
    )
    inner = CascadeLayer(
        project_id="i", project_name="i", path="/i",
        entries=[ContextEntry(path="/i/SAGE.md", source="sage_md", content="y" * 2000)],
    )
    # outer_len ≈ 6029, inner_len ≈ 2029, overshoot ≈ 3058
    # 外层可 cut outer_len-floor = 4029+ ≥ overshoot → 内层未动
    _apply_cascade_budget([outer, inner], total_cap=5000, floor=2000)
    overshoot = _layer_plain(outer) + _layer_plain(inner) - 5000
    assert outer.budget_cut == overshoot
    assert inner.budget_cut == 0


def test_apply_budget_second_pass_dips_below_floor():
    """当所有层都到保底仍超预算, 第二轮允许低于保底继续削。"""
    from backend.chat.project_context import ContextEntry

    layers = [
        CascadeLayer(
            project_id="a", project_name="a", path="/a", is_root=True,
            entries=[ContextEntry(path="/a/SAGE.md", source="sage_md", content="x" * 2000)],
        ),
        CascadeLayer(
            project_id="b", project_name="b", path="/b",
            entries=[ContextEntry(path="/b/SAGE.md", source="sage_md", content="y" * 2000)],
        ),
        CascadeLayer(
            project_id="c", project_name="c", path="/c",
            entries=[ContextEntry(path="/c/SAGE.md", source="sage_md", content="z" * 2000)],
        ),
    ]
    # 每层 plain_content = header 29 + 2000 = 2029. 总 6087, cap 3000, floor 1500
    # overshoot = 3087; 第一轮每层可 cut 529 (总 1587); 剩 1500
    # 第二轮 — 最外层全部削掉, 2029-529=1500 ≤ 1500, 预算消耗归零
    _apply_cascade_budget(layers, total_cap=3000, floor=1500)
    total_plain = sum(_layer_plain(layer) for layer in layers)
    assert total_plain > 3000
    # 最外层预算消耗最多; 总和消耗后总长 ≤ cap
    total_after = sum(_layer_plain(layer) - layer.budget_cut for layer in layers)
    assert total_after <= 3000
    # 最外层被削得比中间层多, 中间层被削得比最内层多
    assert layers[0].budget_cut >= layers[1].budget_cut >= layers[2].budget_cut
    # 第二轮确实启动了: 最外层 budget_cut > 第一轮保底消耗 (2029-1500=529)
    assert layers[0].budget_cut > 529


# ── layer rendering ─────────────────────────────────────────────────────────


def test_cascade_layer_marker_root_and_project():
    root_layer = CascadeLayer(
        project_id="r", project_name="Root Project", path="/r", is_root=True,
    )
    child_layer = CascadeLayer(
        project_id="c", project_name="Child Project", path="/c",
    )
    assert root_layer.marker() == '<!-- SAGE-CONTEXT level="root" project="Root Project" -->'
    assert child_layer.marker() == '<!-- SAGE-CONTEXT level="project" project="Child Project" -->'


def test_cascade_layer_content_with_budget_cut():
    from backend.chat.project_context import ContextEntry

    layer = CascadeLayer(
        project_id="p", project_name="p", path="/p",
        entries=[ContextEntry(path="/p/SAGE.md", source="sage_md", content="abcdefghij")],
        budget_cut=3,
    )
    # plain 长度 10, cut 3 → 留 7 字符 + 末尾 [截断]
    assert layer.content().endswith("[截断]")
    assert "abcdefg" in layer.content()


# ── end-to-end cascade ──────────────────────────────────────────────────────


def test_fallback_when_no_registered_projects(tmp_path):
    """路径上没有已登记项目 → 降级为 discover_project_context (向上发现)。"""
    sub = tmp_path / "sub"
    sub.mkdir()
    (tmp_path / "SAGE.md").write_text("root-sage", encoding="utf-8")
    (sub / "CLAUDE.md").write_text("sub-claude", encoding="utf-8")

    cascade = discover_project_context_cascade(sub)

    # 无注册项目 → fallback 非空, 沿用向上发现结果
    assert cascade.fallback is not None
    assert cascade.layers == []
    rendered = cascade.render()
    assert "root-sage" in rendered
    assert "sub-claude" in rendered
    assert CASCADE_HEADER not in rendered  # 没走级联路径


def test_chain_construction_parent_to_child(tmp_path):
    """登记父+子项目, 绑定子路径 → 级联链按父 → 子顺序, 两层标记齐全。"""
    parent = tmp_path / "parent"
    child = parent / "child"
    grandchild = child / "grandchild"
    parent.mkdir()
    child.mkdir()
    grandchild.mkdir()
    _write_instruction(parent, "SAGE.md", "parent rule")
    _write_instruction(child, "CLAUDE.md", "child rule")
    _register(parent)
    _register(child)

    cascade = discover_project_context_cascade(grandchild)

    assert cascade.fallback is None, "应当走级联路径而非降级"
    assert len(cascade.layers) == 2
    # 父层在前, is_root 为 True; 子层在后, is_root 为 False
    assert cascade.layers[0].project_name == parent.name
    assert cascade.layers[0].is_root is True
    assert cascade.layers[1].project_name == child.name
    assert cascade.layers[1].is_root is False
    # 渲染包含两个 marker
    rendered = cascade.render()
    assert f'level="root" project="{parent.name}"' in rendered
    assert f'level="project" project="{child.name}"' in rendered
    # 渲染包含两个文件的内容
    assert "parent rule" in rendered
    assert "child rule" in rendered


def test_synthetic_leaf_layer_when_workspace_deeper(tmp_path):
    """workspace 比最深层注册项目更靠内且自身有指令文件 → 补叶子层。"""
    parent = tmp_path / "parent"
    child = parent / "child"
    workspace = child / "workspace"
    parent.mkdir()
    child.mkdir()
    workspace.mkdir()
    _write_instruction(parent, "SAGE.md", "parent rule")
    _write_instruction(child, "SAGE.md", "child rule")
    _write_instruction(workspace, "CLAUDE.md", "workspace-only rule")
    _register(parent)
    _register(child)

    cascade = discover_project_context_cascade(workspace)

    assert cascade.fallback is None
    assert len(cascade.layers) == 3  # parent + child + synthetic workspace leaf
    assert cascade.layers[2].project_id == ""  # 叶子层没有真实 project_id
    assert cascade.layers[2].project_name == "workspace"
    assert cascade.layers[2].is_root is False
    assert "workspace-only rule" in cascade.render()


def test_no_synthetic_leaf_when_workspace_has_no_instructions(tmp_path):
    """workspace 比最深层靠内但没指令文件 → 不补叶子层。"""
    parent = tmp_path / "parent"
    workspace = parent / "workspace"
    parent.mkdir()
    workspace.mkdir()
    _write_instruction(parent, "SAGE.md", "parent rule")
    _register(parent)

    cascade = discover_project_context_cascade(workspace)

    assert len(cascade.layers) == 1
    assert cascade.layers[0].project_name == parent.name


def test_content_hash_dedupe_across_levels(tmp_path):
    """同一内容在两层都出现 → 只在外层收集一次 (祖先优先)。"""
    parent = tmp_path / "parent"
    child = parent / "child"
    parent.mkdir()
    child.mkdir()
    _write_instruction(parent, "SAGE.md", "identical content")
    _write_instruction(child, "CLAUDE.md", "identical content\n")  # strip 后相同
    _register(parent)
    _register(child)

    cascade = discover_project_context_cascade(child)

    all_contents = []
    for layer in cascade.layers:
        for entry in layer.entries:
            all_contents.append(entry.content)
    assert all_contents.count("identical content") == 1
    # 外层的 sage 先被发现 → source 是 sage_md
    assert cascade.layers[0].entries[0].source == "sage_md"


def test_user_level_sage_md_included_in_global_entries(tmp_path, monkeypatch):
    """~/.sage/SAGE.md 应出现在 global_entries 中, 且渲染在级联块前。"""
    fake_home = tmp_path / "fakehome"
    fake_home.mkdir()
    user_sage = fake_home / ".sage" / "SAGE.md"
    user_sage.parent.mkdir()
    user_sage.write_text("global-rule", encoding="utf-8")
    monkeypatch.setenv("HOME", str(fake_home))
    # Path.home() 缓存失效需 patch
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    project = tmp_path / "proj"
    project.mkdir()
    _write_instruction(project, "SAGE.md", "project-rule")
    _register(project)

    cascade = discover_project_context_cascade(project)

    assert cascade.fallback is None
    assert len(cascade.global_entries) == 1
    assert cascade.global_entries[0].content == "global-rule"
    assert cascade.global_entries[0].source == "user_sage_md"
    rendered = cascade.render()
    # RENDER_HEADER (用户级) 与 CASCADE_HEADER (项目级) 都应出现, 用户级在前
    assert rendered.index(RENDER_HEADER) < rendered.index(CASCADE_HEADER)
    assert "global-rule" in rendered
    assert "project-rule" in rendered


def test_budget_enforced_end_to_end(tmp_path):
    """超总预算 → 外层被截断; 内层保底保护。"""
    parent = tmp_path / "parent"
    child = parent / "child"
    parent.mkdir()
    child.mkdir()
    # 外层塞到 3000 字符; 内层塞到 2500 字符 (均小于 PER_FILE_CHAR_CAP)
    _write_instruction(parent, "SAGE.md", "P" * 3000)
    _write_instruction(child, "SAGE.md", "C" * 2500)
    _register(parent)
    _register(child)

    # 把总预算临时压到 4000 (小于 3000+2500=5500)
    with patch(
        "backend.chat.project_context_cascade.CASCADE_TOTAL_CHAR_CAP", 4000
    ):
        cascade = discover_project_context_cascade(child)

    # 外层被削减; 内层因保底 (CASCADE_PER_LAYER_FLOOR) 至少保留 2000
    outer_body = cascade.layers[0].content()
    inner_body = cascade.layers[1].content()
    assert len(outer_body) < 3000, "外层应被截断"
    # 内层内容至少 2000 (保底) 或完全保留 (如果外层削够了)
    # 实际: overshoot = 5500-4000 = 1500; 外层可 cut 3000-2000=1000 → overshoot 500
    #        内层可 cut 2500-2000=500 → overshoot 0
    # 外层剩 2000 + [截断]; 内层剩 2000 + [截断]
    assert len(inner_body) <= 2500
    assert len(inner_body) >= 2000 or "[截断]" in inner_body


def test_invalid_path_falls_back(tmp_path):
    """不存在的路径 → fallback (向上发现返回空)。"""
    cascade = discover_project_context_cascade(tmp_path / "nonexistent")
    # fallback 可能为空 ProjectContext (没有指令文件), 但永远不抛
    assert cascade.layers == []
    assert isinstance(cascade.render(), str)


def test_repository_exception_falls_back(tmp_path):
    """ProjectRepository 抛异常 → 优雅降级, 不抛。"""
    parent = tmp_path / "parent"
    parent.mkdir()
    _write_instruction(parent, "SAGE.md", "parent-rule")
    _register(parent)

    with patch(
        "backend.chat.project_context_cascade._registered_ancestor_projects",
        side_effect=RuntimeError("db offline"),
    ):
        cascade = discover_project_context_cascade(parent)

    assert cascade.fallback is not None
    assert "parent-rule" in cascade.render()
