"""Wiki 模板系统单元测试 (2026-09-25)

项目类型分类系统 - Phase 9.5.1
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from backend.wiki.wiki_templates import (
    TEMPLATES,
    create_wiki_structure,
    get_directories,
    get_pages,
    get_template,
)


class TestGetTemplate:
    """get_template 测试"""

    def test_returns_coding_template(self) -> None:
        t = get_template("coding")
        assert t.project_type == "coding"
        assert "wiki/api-docs" in t.directories

    def test_returns_research_template(self) -> None:
        t = get_template("research")
        assert t.project_type == "research"
        assert "wiki/literature" in t.directories

    def test_returns_business_template(self) -> None:
        t = get_template("business")
        assert t.project_type == "business"
        assert "wiki/meetings" in t.directories

    def test_returns_personal_template(self) -> None:
        t = get_template("personal")
        assert t.project_type == "personal"
        assert "wiki/inbox" in t.directories

    def test_unknown_type_falls_back_to_coding(self) -> None:
        t = get_template("unknown")
        assert t.project_type == "coding"

    def test_none_type_falls_back_to_coding(self) -> None:
        t = get_template(None)
        assert t.project_type == "coding"


class TestGetDirectories:
    """get_directories 测试"""

    def test_includes_common_directories(self) -> None:
        dirs = get_directories("coding")
        assert "raw/sources" in dirs
        assert "raw/assets" in dirs
        assert ".llm-wiki" in dirs

    def test_includes_type_specific_directories(self) -> None:
        dirs = get_directories("coding")
        assert "wiki/api-docs" in dirs
        assert "wiki/architecture" in dirs

    def test_research_has_literature(self) -> None:
        dirs = get_directories("research")
        assert "wiki/literature" in dirs
        assert "wiki/experiments" in dirs


class TestGetPages:
    """get_pages 测试"""

    def test_returns_three_pages_per_type(self) -> None:
        for ptype in TEMPLATES:
            pages = get_pages(ptype)
            assert len(pages) == 3

    def test_replaces_project_name_variable(self) -> None:
        pages = get_pages("coding", "My Project")
        overview = next(p for p in pages if "overview" in p.relative_path)
        assert "My Project" in overview.content
        assert "{project_name}" not in overview.content

    def test_default_project_name(self) -> None:
        pages = get_pages("coding")
        overview = next(p for p in pages if "overview" in p.relative_path)
        assert "Project" in overview.content


class TestCreateWikiStructure:
    """create_wiki_structure 集成测试"""

    def test_creates_directories_and_pages(self, tmp_path: Path) -> None:
        ensure_mock = MagicMock()
        write_mock = MagicMock()

        create_wiki_structure(
            project_path=tmp_path,
            project_type="coding",
            project_name="TestProject",
            ensure_dir_fn=ensure_mock,
            write_file_fn=write_mock,
        )

        # 验证目录创建
        assert ensure_mock.call_count >= 8  # 3 common + 5 coding-specific
        created_dirs = [str(call.args[1]).replace("\\", "/") for call in ensure_mock.call_args_list]
        assert any("raw/sources" in d for d in created_dirs)
        assert any("wiki/api-docs" in d for d in created_dirs)

        # 验证页面写入
        assert write_mock.call_count == 3  # schema, overview, index
        written_files = [str(call.args[1]) for call in write_mock.call_args_list]
        assert any("schema.md" in f for f in written_files)
        assert any("overview.md" in f for f in written_files)
        assert any("index.md" in f for f in written_files)

    def test_all_types_create_valid_structure(self, tmp_path: Path) -> None:
        for ptype in TEMPLATES:
            ensure_mock = MagicMock()
            write_mock = MagicMock()

            create_wiki_structure(
                project_path=tmp_path,
                project_type=ptype,
                ensure_dir_fn=ensure_mock,
                write_file_fn=write_mock,
            )

            assert ensure_mock.call_count >= 3  # at least common dirs
            assert write_mock.call_count == 3  # always 3 pages
