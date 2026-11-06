"""workspace_scanner 单元测试（P2 of 2026-11-05 设计）。

覆盖：项目识别（模板声明 / 上下文文件）、容器目录保留、默认排除、
.sageignore、符号链接记录、深度与条目上限、缓存、序列化、
DB 同步（只增不删）与 parent_id 派生。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.services.project_template import ProjectTemplate, TemplateDirectory
from backend.services.workspace_scanner import (
    DISCOVERY_CONTEXT_FILE,
    DISCOVERY_MANUAL,
    DISCOVERY_TEMPLATE,
    ScannedNode,
    SymlinkRecord,
    WorkspaceScanner,
    contains_context_file,
    invalidate_scan_cache,
    is_ignored,
    load_ignore_patterns,
    scan_project,
    sync_projects_from_tree,
)


@pytest.fixture(autouse=True)
def _clear_scan_cache():
    """每个用例前后清空模块级扫描缓存，避免 tmp 路径复用导致串味。"""
    invalidate_scan_cache()
    yield
    invalidate_scan_cache()


def _mkdirs(root: Path, *rels: str) -> None:
    for rel in rels:
        (root / rel).mkdir(parents=True, exist_ok=True)


def _touch(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────
# 基础扫描
# ─────────────────────────────────────────────────────────────────────


class TestScanBasics:
    def test_root_node(self, tmp_path):
        tree = WorkspaceScanner().scan(tmp_path)
        assert tree.root.role == "root"
        assert tree.root.discovery_source == DISCOVERY_MANUAL
        assert tree.root.rel_path == ""
        assert tree.root.path == str(tmp_path.resolve())
        assert tree.root.children == []

    def test_missing_root_raises(self, tmp_path):
        with pytest.raises(ValueError, match="not a directory"):
            WorkspaceScanner().scan(tmp_path / "nope")

    def test_plain_dirs_not_in_tree(self, tmp_path):
        _mkdirs(tmp_path, "a/b/c")
        tree = WorkspaceScanner().scan(tmp_path)
        assert tree.root.children == []

    def test_context_file_makes_project(self, tmp_path):
        _mkdirs(tmp_path, "alpha")
        _touch(tmp_path / "alpha" / "SAGE.md")
        tree = WorkspaceScanner().scan(tmp_path)

        assert len(tree.root.children) == 1
        node = tree.root.children[0]
        assert node.name == "alpha"
        assert node.role == "project"
        assert node.discovery_source == DISCOVERY_CONTEXT_FILE
        assert node.rel_path == "alpha"

    @pytest.mark.parametrize("ctx_name", ["CLAUDE.md", "AGENTS.md"])
    def test_other_context_files(self, tmp_path, ctx_name):
        _touch(tmp_path / "beta" / ctx_name)
        tree = WorkspaceScanner().scan(tmp_path)
        assert [n.name for n in tree.root.children] == ["beta"]

    def test_contains_context_file(self, tmp_path):
        _mkdirs(tmp_path, "x", "y")
        assert contains_context_file(tmp_path / "x") is False
        _touch(tmp_path / "y" / "SAGE.md")
        assert contains_context_file(tmp_path / "y") is True

    def test_template_role_project(self, tmp_path):
        _mkdirs(tmp_path, "mesh")
        tpl = ProjectTemplate(
            name="T",
            directories=[TemplateDirectory(path="mesh", desc="网格", role="project")],
        )
        tree = WorkspaceScanner().scan(tmp_path, tpl)

        node = tree.root.children[0]
        assert node.name == "mesh"
        assert node.role == "project"
        assert node.discovery_source == DISCOVERY_TEMPLATE

    def test_template_folder_role_not_project(self, tmp_path):
        _mkdirs(tmp_path, "docs")
        tpl = ProjectTemplate(
            name="T",
            directories=[TemplateDirectory(path="docs", role="folder")],
        )
        tree = WorkspaceScanner().scan(tmp_path, tpl)
        assert tree.root.children == []

    def test_template_nested_project_path(self, tmp_path):
        _mkdirs(tmp_path, "cases/sub")
        tpl = ProjectTemplate(
            name="T",
            directories=[TemplateDirectory(path="cases/sub", role="project")],
        )
        tree = WorkspaceScanner().scan(tmp_path, tpl)

        container = tree.root.children[0]
        assert container.name == "cases"
        assert container.role == "folder"
        assert container.children[0].name == "sub"
        assert container.children[0].role == "project"

    def test_container_folder_kept_for_descendant_project(self, tmp_path):
        _touch(tmp_path / "outer" / "inner" / "SAGE.md")
        tree = WorkspaceScanner().scan(tmp_path)

        outer = tree.root.children[0]
        assert outer.name == "outer"
        assert outer.role == "folder"
        assert outer.discovery_source is None
        assert outer.children[0].name == "inner"
        assert outer.children[0].role == "project"

    def test_nested_projects(self, tmp_path):
        _touch(tmp_path / "proj1" / "SAGE.md")
        _touch(tmp_path / "proj1" / "sub" / "CLAUDE.md")
        tree = WorkspaceScanner().scan(tmp_path)

        proj1 = tree.root.children[0]
        assert proj1.role == "project"
        assert [c.name for c in proj1.children] == ["sub"]
        assert proj1.children[0].role == "project"


# ─────────────────────────────────────────────────────────────────────
# 排除规则
# ─────────────────────────────────────────────────────────────────────


class TestExcludes:
    @pytest.mark.parametrize("excluded", ["node_modules", "__pycache__", "build", ".git"])
    def test_default_excludes(self, tmp_path, excluded):
        _touch(tmp_path / excluded / "SAGE.md")
        tree = WorkspaceScanner().scan(tmp_path)
        assert tree.root.children == []

    def test_custom_excludes(self, tmp_path):
        _touch(tmp_path / "skipme" / "SAGE.md")
        tree = WorkspaceScanner(excludes={"skipme"}).scan(tmp_path)
        assert tree.root.children == []

    def test_sageignore_applied(self, tmp_path):
        (tmp_path / ".sageignore").write_text("ignored/\n*.log\n", encoding="utf-8")
        _touch(tmp_path / "ignored" / "SAGE.md")
        _touch(tmp_path / "kept" / "SAGE.md")
        tree = WorkspaceScanner().scan(tmp_path)
        assert [n.name for n in tree.root.children] == ["kept"]


class TestIgnorePatterns:
    def test_load_missing(self, tmp_path):
        assert load_ignore_patterns(tmp_path) == []

    def test_load_strips_comments_and_blanks(self, tmp_path):
        (tmp_path / ".sageignore").write_text(
            "# comment\n\nfoo/\n  !bar/\n", encoding="utf-8"
        )
        assert load_ignore_patterns(tmp_path) == ["foo/", "!bar/"]

    def test_basename_pattern(self):
        assert is_ignored("a/b/cache", "cache", ["cache"]) is True
        assert is_ignored("a/b/cache", "cache", ["other"]) is False

    def test_anchored_pattern(self):
        assert is_ignored("top", "top", ["/top"]) is True
        assert is_ignored("a/top", "top", ["/top"]) is False

    def test_double_star(self):
        assert is_ignored("a/b/c/tmp", "tmp", ["a/**/tmp"]) is True
        assert is_ignored("x/y", "y", ["**/y"]) is True

    def test_negation_last_match_wins(self):
        patterns = ["*.log", "!keep.log"]
        assert is_ignored("keep.log", "keep.log", patterns) is False
        assert is_ignored("drop.log", "drop.log", patterns) is True


# ─────────────────────────────────────────────────────────────────────
# 符号链接 / 深度 / 条目上限
# ─────────────────────────────────────────────────────────────────────


class TestSymlinksAndLimits:
    def test_symlink_recorded_not_recursed(self, tmp_path):
        _touch(tmp_path / "real" / "SAGE.md")
        os.symlink(tmp_path / "real", tmp_path / "link")

        tree = WorkspaceScanner().scan(tmp_path)

        names = [n.name for n in tree.root.children]
        assert "real" in names
        assert "link" not in names

        link_rec = next(s for s in tree.symlinks if s.name == "link")
        assert link_rec.rel_path == "link"
        assert link_rec.target_path == os.path.realpath(tmp_path / "real")

    def test_symlink_loop_terminates(self, tmp_path):
        _touch(tmp_path / "proj" / "SAGE.md")
        os.symlink(tmp_path, tmp_path / "loop")

        tree = WorkspaceScanner().scan(tmp_path)
        assert any(s.name == "loop" for s in tree.symlinks)
        assert [n.name for n in tree.root.children] == ["proj"]

    def test_max_depth(self, tmp_path):
        _touch(tmp_path / "a" / "b" / "SAGE.md")
        _touch(tmp_path / "a" / "b" / "c" / "SAGE.md")

        tree = WorkspaceScanner(max_depth=2).scan(tmp_path)
        a = tree.root.children[0]
        b = a.children[0]
        assert b.name == "b"
        assert b.children == []  # c 在深度 3，被截断

    def test_max_entries_truncated(self, tmp_path):
        for i in range(5):
            _touch(tmp_path / f"p{i}" / "SAGE.md")

        tree = WorkspaceScanner(max_entries_per_dir=3).scan(tmp_path)
        assert tree.truncated_paths == ["."]
        # 排序后只处理前 3 个
        assert [n.name for n in tree.root.children] == ["p0", "p1", "p2"]

    def test_unreadable_dir_skipped(self, tmp_path, monkeypatch):
        _mkdirs(tmp_path, "locked")
        real_scandir = os.scandir

        def fake_scandir(path):
            if Path(path).name == "locked":
                raise PermissionError("denied")
            return real_scandir(path)

        monkeypatch.setattr(
            "backend.services.workspace_scanner.os.scandir", fake_scandir
        )
        tree = WorkspaceScanner().scan(tmp_path)
        assert tree.root.children == []


# ─────────────────────────────────────────────────────────────────────
# 缓存
# ─────────────────────────────────────────────────────────────────────


class TestScanCache:
    def test_scan_project_caches(self, tmp_path):
        _touch(tmp_path / "p" / "SAGE.md")
        first = scan_project(tmp_path)
        second = scan_project(tmp_path)
        assert first is second

    def test_force_rescans(self, tmp_path):
        first = scan_project(tmp_path)
        _touch(tmp_path / "later" / "SAGE.md")
        second = scan_project(tmp_path, force=True)
        assert second is not first
        assert [n.name for n in second.root.children] == ["later"]

    def test_invalidate_single(self, tmp_path):
        first = scan_project(tmp_path)
        invalidate_scan_cache(tmp_path)
        assert scan_project(tmp_path) is not first

    def test_invalidate_all(self, tmp_path):
        scan_project(tmp_path)
        invalidate_scan_cache()
        assert scan_project(tmp_path) is not None


# ─────────────────────────────────────────────────────────────────────
# 序列化
# ─────────────────────────────────────────────────────────────────────


class TestSerialization:
    def test_to_dict(self, tmp_path):
        _touch(tmp_path / "p" / "SAGE.md")
        os.symlink(tmp_path / "p", tmp_path / "link")
        tree = WorkspaceScanner().scan(tmp_path)
        data = tree.to_dict()

        assert data["root"]["role"] == "root"
        assert data["root"]["children"][0]["name"] == "p"
        assert data["symlinks"][0]["kind"] == "symlink"
        assert "truncated" in data
        assert isinstance(data["scanned_at"], float)

    def test_iter_projects(self, tmp_path):
        _touch(tmp_path / "outer" / "inner" / "SAGE.md")
        tree = WorkspaceScanner().scan(tmp_path)
        rel_paths = [n.rel_path for n in tree.iter_projects()]
        assert rel_paths == ["", "outer/inner"]

    def test_scanned_node_is_project(self):
        assert ScannedNode("", "", "", role="root").is_project is True
        assert ScannedNode("", "", "", role="project").is_project is True
        assert ScannedNode("", "", "", role="folder").is_project is False

    def test_symlink_record_to_dict(self):
        rec = SymlinkRecord(rel_path="a/b", name="b", target_path="/tmp/x")
        assert rec.to_dict() == {
            "rel_path": "a/b",
            "name": "b",
            "target_path": "/tmp/x",
            "kind": "symlink",
        }


# ─────────────────────────────────────────────────────────────────────
# 与数据库同步（只增不删 + parent_id 派生）
# ─────────────────────────────────────────────────────────────────────


class TestSyncProjects:
    def _register_root(self, tmp_path):
        from backend.data.project_repo import ProjectRepository

        root_dir = tmp_path / "root-proj"
        root_dir.mkdir()
        return ProjectRepository().register(str(root_dir))

    def test_new_subprojects_registered(self, tmp_path):
        from backend.data.project_repo import ProjectRepository

        root = self._register_root(tmp_path)
        _touch(Path(root.path) / "alpha" / "SAGE.md")
        tree = WorkspaceScanner().scan(Path(root.path))

        repo = ProjectRepository()
        created = sync_projects_from_tree(root.id, tree)

        assert len(created) == 1
        sub = repo.get_project_for_workspace(str((Path(root.path) / "alpha").resolve()))
        assert sub is not None
        assert sub.parent_id == root.id
        assert sub.discovery_source == DISCOVERY_CONTEXT_FILE

    def test_nested_parent_id(self, tmp_path):
        from backend.data.project_repo import ProjectRepository

        root = self._register_root(tmp_path)
        _touch(Path(root.path) / "outer" / "inner" / "SAGE.md")
        tree = WorkspaceScanner().scan(Path(root.path))

        repo = ProjectRepository()
        sync_projects_from_tree(root.id, tree)

        inner = repo.get_project_for_workspace(
            str((Path(root.path) / "outer" / "inner").resolve())
        )
        assert inner is not None
        assert inner.parent_id == root.id  # 容器目录不产生项目行

    def test_existing_project_not_duplicated(self, tmp_path):
        from backend.data.project_repo import ProjectRepository

        root = self._register_root(tmp_path)
        repo = ProjectRepository()
        alpha_dir = Path(root.path) / "alpha"
        alpha_dir.mkdir()
        (alpha_dir / "SAGE.md").write_text("x", encoding="utf-8")
        existing = repo.register(str(alpha_dir))

        tree = WorkspaceScanner().scan(Path(root.path))
        created = sync_projects_from_tree(root.id, tree)

        assert created == []
        refreshed = repo.get(existing.id)
        assert refreshed is not None
        assert refreshed.parent_id == root.id

    def test_missing_root_returns_empty(self, tmp_path):
        _mkdirs(tmp_path, "x")
        tree = WorkspaceScanner().scan(tmp_path)
        assert sync_projects_from_tree("nonexistent-id", tree) == []

    def test_vanished_dir_not_deleted(self, tmp_path):
        import shutil

        from backend.data.project_repo import ProjectRepository

        root = self._register_root(tmp_path)
        repo = ProjectRepository()
        alpha_dir = Path(root.path) / "alpha"
        alpha_dir.mkdir()
        (alpha_dir / "SAGE.md").write_text("x", encoding="utf-8")
        tree = WorkspaceScanner().scan(Path(root.path))
        sync_projects_from_tree(root.id, tree)

        sub_path = str(alpha_dir.resolve())
        assert repo.get_project_for_workspace(sub_path) is not None

        # 磁盘删除后重扫：项目行必须保留（只增不删）
        shutil.rmtree(alpha_dir)
        tree2 = WorkspaceScanner().scan(Path(root.path))
        sync_projects_from_tree(root.id, tree2)
        assert repo.get_project_for_workspace(sub_path) is not None
