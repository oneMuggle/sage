"""Wiki 系统集成测试 (2026-09-25)

项目类型分类系统 - Phase 9.5.5
测试 Wiki 模板、API 文档生成、文献聚合、会议纪要提取的协同工作。
"""

from __future__ import annotations

from pathlib import Path

from backend.wiki.api_doc_generator import generate_wiki_api_docs
from backend.wiki.literature_aggregator import generate_literature_review
from backend.wiki.meetings_extractor import generate_meetings_index
from backend.wiki.wiki_templates import (
    create_wiki_structure,
)


class TestWikiTemplatesIntegration:
    """Wiki 模板集成测试"""

    def test_coding_project_creates_api_docs_dir(self, tmp_path: Path) -> None:
        """Coding 项目创建 API 文档目录"""
        from unittest.mock import MagicMock

        ensure_mock = MagicMock()
        write_mock = MagicMock()

        create_wiki_structure(
            project_path=tmp_path,
            project_type="coding",
            ensure_dir_fn=ensure_mock,
            write_file_fn=write_mock,
        )

        created_dirs = [str(call.args[1]) for call in ensure_mock.call_args_list]
        assert any("wiki/api-docs" in d for d in created_dirs)

    def test_research_project_creates_literature_dir(self, tmp_path: Path) -> None:
        """Research 项目创建文献目录"""
        from unittest.mock import MagicMock

        ensure_mock = MagicMock()
        write_mock = MagicMock()

        create_wiki_structure(
            project_path=tmp_path,
            project_type="research",
            ensure_dir_fn=ensure_mock,
            write_file_fn=write_mock,
        )

        created_dirs = [str(call.args[1]) for call in ensure_mock.call_args_list]
        assert any("wiki/literature" in d for d in created_dirs)

    def test_business_project_creates_meetings_dir(self, tmp_path: Path) -> None:
        """Business 项目创建会议目录"""
        from unittest.mock import MagicMock

        ensure_mock = MagicMock()
        write_mock = MagicMock()

        create_wiki_structure(
            project_path=tmp_path,
            project_type="business",
            ensure_dir_fn=ensure_mock,
            write_file_fn=write_mock,
        )

        created_dirs = [str(call.args[1]) for call in ensure_mock.call_args_list]
        assert any("wiki/meetings" in d for d in created_dirs)


class TestApiDocGeneratorIntegration:
    """API 文档生成集成测试"""

    def test_generates_docs_for_coding_project(self, tmp_path: Path) -> None:
        """为 Coding 项目生成 API 文档"""
        # 创建 Python 源文件
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "main.py").write_text(
            '"""Main module."""\n\n'
            "def main() -> None:\n"
            '    """Entry point."""\n'
            "    pass\n",
            encoding="utf-8",
        )
        (src_dir / "utils.py").write_text(
            '"""Utility functions."""\n\n'
            "def format_output(data: dict) -> str:\n"
            '    """Format data for display."""\n'
            "    return str(data)\n",
            encoding="utf-8",
        )

        files = generate_wiki_api_docs(tmp_path)

        assert len(files) >= 3  # index + 2 modules
        index_content = (tmp_path / "wiki" / "api-docs" / "index.md").read_text(
            encoding="utf-8"
        )
        assert "API 文档索引" in index_content
        assert "main" in index_content.lower()
        assert "utils" in index_content.lower()


class TestLiteratureAggregatorIntegration:
    """文献聚合集成测试"""

    def test_generates_review_for_research_project(self, tmp_path: Path) -> None:
        """为 Research 项目生成文献综述"""
        # 创建文献目录和文件
        lit_dir = tmp_path / "wiki" / "literature"
        lit_dir.mkdir(parents=True)
        (lit_dir / "transformer.md").write_text(
            "---\n"
            "title: Attention Is All You Need\n"
            "authors: [Vaswani et al.]\n"
            "year: 2017\n"
            "tags: [transformer, nlp]\n"
            "---\n\n"
            "# Attention Is All You Need\n\n"
            "The transformer architecture...",
            encoding="utf-8",
        )
        (lit_dir / "bert.md").write_text(
            "---\n"
            "title: BERT\n"
            "authors: [Devlin et al.]\n"
            "year: 2019\n"
            "tags: [pretraining, nlp]\n"
            "---\n\n"
            "# BERT\n\n"
            "Bidirectional encoder representations...",
            encoding="utf-8",
        )

        result = generate_literature_review(tmp_path)

        assert result is not None
        content = result.read_text(encoding="utf-8")
        assert "# 文献综述索引" in content
        assert "共 2 篇文献" in content
        assert "Attention Is All You Need" in content
        assert "BERT" in content
        assert "2019 年" in content
        assert "2017 年" in content


class TestMeetingsExtractorIntegration:
    """会议纪要提取集成测试"""

    def test_generates_index_for_business_project(self, tmp_path: Path) -> None:
        """为 Business 项目生成会议索引"""
        # 创建会议目录和文件
        meetings_dir = tmp_path / "wiki" / "meetings"
        meetings_dir.mkdir(parents=True)
        (meetings_dir / "2024-01-15-sprint-review.md").write_text(
            "---\n"
            "title: Sprint Review\n"
            "date: 2024-01-15\n"
            "attendees: [Alice, Bob, Charlie]\n"
            "---\n\n"
            "# Sprint Review\n\n"
            "## 决议\n"
            "- 发布 v2.0\n"
            "- 更新文档\n\n"
            "## Action Items\n"
            "- Alice 负责部署\n",
            encoding="utf-8",
        )
        (meetings_dir / "2024-02-01-planning.md").write_text(
            "---\n"
            "title: Q1 Planning\n"
            "date: 2024-02-01\n"
            "attendees: [Alice, David]\n"
            "---\n\n"
            "# Q1 Planning\n\n"
            "## 决议\n"
            "- 启动新项目\n",
            encoding="utf-8",
        )

        result = generate_meetings_index(tmp_path)

        assert result is not None
        content = result.read_text(encoding="utf-8")
        assert "# 会议纪要索引" in content
        assert "共 2 次会议记录" in content
        assert "Sprint Review" in content
        assert "Q1 Planning" in content
        assert "发布 v2.0" in content
        assert "启动新项目" in content


class TestEndToEndWorkflow:
    """端到端工作流测试"""

    def test_coding_project_full_workflow(self, tmp_path: Path) -> None:
        """Coding 项目完整工作流：模板创建 → API 文档生成"""
        # Step 1: 创建 Wiki 结构
        from unittest.mock import MagicMock

        ensure_mock = MagicMock()
        write_mock = MagicMock()

        create_wiki_structure(
            project_path=tmp_path,
            project_type="coding",
            ensure_dir_fn=ensure_mock,
            write_file_fn=write_mock,
        )

        # Step 2: 添加 Python 源文件
        (tmp_path / "app.py").write_text(
            '"""Application module."""\n\n'
            "def run() -> None:\n"
            '    """Run the application."""\n'
            "    pass\n",
            encoding="utf-8",
        )

        # Step 3: 生成 API 文档
        files = generate_wiki_api_docs(tmp_path)

        assert len(files) >= 2
        index_file = tmp_path / "wiki" / "api-docs" / "index.md"
        assert index_file.exists()
        content = index_file.read_text(encoding="utf-8")
        assert "app" in content.lower()

    def test_research_project_full_workflow(self, tmp_path: Path) -> None:
        """Research 项目完整工作流：模板创建 → 文献聚合"""
        # Step 1: 创建 Wiki 结构（模拟目录已存在）
        lit_dir = tmp_path / "wiki" / "literature"
        lit_dir.mkdir(parents=True)

        # Step 2: 添加文献
        (lit_dir / "paper.md").write_text(
            "---\ntitle: Test Paper\nyear: 2023\n---\n# Test Paper\nContent",
            encoding="utf-8",
        )

        # Step 3: 生成文献综述
        result = generate_literature_review(tmp_path)

        assert result is not None
        content = result.read_text(encoding="utf-8")
        assert "Test Paper" in content

    def test_business_project_full_workflow(self, tmp_path: Path) -> None:
        """Business 项目完整工作流：模板创建 → 会议索引"""
        # Step 1: 创建 Wiki 结构（模拟目录已存在）
        meetings_dir = tmp_path / "wiki" / "meetings"
        meetings_dir.mkdir(parents=True)

        # Step 2: 添加会议记录
        (meetings_dir / "2024-03-01.md").write_text(
            "---\ntitle: March Meeting\ndate: 2024-03-01\n---\n"
            "# March Meeting\n\n## 决议\n- Decision made",
            encoding="utf-8",
        )

        # Step 3: 生成会议索引
        result = generate_meetings_index(tmp_path)

        assert result is not None
        content = result.read_text(encoding="utf-8")
        assert "March Meeting" in content
