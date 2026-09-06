"""Wiki Lint API 集成测试。

测试 GET /lint 端点,使用 monkeypatch 绕过项目授权。
"""
from pathlib import Path

import pytest

from backend.api import wiki_routes
from backend.api.wiki_routes import lint


@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    """创建临时 Wiki 项目。"""
    project = tmp_path / "wiki-project"
    project.mkdir()
    (project / "wiki").mkdir()
    return project


@pytest.fixture(autouse=True)
def _patch_auth(monkeypatch, project_root: Path):
    """绕过项目授权。"""
    monkeypatch.setattr(
        wiki_routes,
        "authorize_registered_project",
        lambda _: project_root,
    )


class TestLintEndpoint:
    """测试 GET /lint。"""

    async def test_empty_project_reports_structure_errors(
        self, project_root: Path
    ) -> None:
        """空项目应报告缺失的必需目录和文件。"""
        result = await lint(project_path=str(project_root))

        assert "total" in result
        assert "by_severity" in result
        assert "issues" in result
        # wiki/entities, wiki/concepts, wiki/sources, wiki/queries 都缺 → 4 errors
        # wiki/schema.md 缺 → 1 more error; 合计 5
        assert result["by_severity"]["error"] == 5
        assert result["total"] == 5

    async def test_well_formed_project_returns_clean(
        self, project_root: Path
    ) -> None:
        """每个非豁免页面都被其他页面引用时,应无 lint 问题。"""
        wiki = project_root / "wiki"
        (wiki / "entities").mkdir()
        (wiki / "concepts").mkdir()
        (wiki / "sources").mkdir()
        (wiki / "queries").mkdir()
        (wiki / "schema.md").write_text(
            "---\ntitle: Schema\n---\n", encoding="utf-8"
        )
        (wiki / "overview.md").write_text(
            "---\ntitle: Overview\n---\n", encoding="utf-8"
        )
        (wiki / "entities" / "a.md").write_text(
            "---\ntitle: A\n---\nSee [[b]]", encoding="utf-8"
        )
        (wiki / "entities" / "b.md").write_text(
            "---\ntitle: B\n---\nSee [[a]] and [[c]]", encoding="utf-8"
        )
        (wiki / "concepts" / "c.md").write_text(
            "---\ntitle: C\n---\nSee [[a]]", encoding="utf-8"
        )

        result = await lint(project_path=str(project_root))

        assert result["total"] == 0
        assert result["by_severity"] == {"error": 0, "warning": 0, "info": 0}

    async def test_broken_wikilink_reported_as_warning(
        self, project_root: Path
    ) -> None:
        """断链应产生 warning 级别的 wikilink_broken 问题。"""
        wiki = project_root / "wiki"
        (wiki / "entities").mkdir()
        (wiki / "entities" / "a.md").write_text(
            "---\ntitle: A\n---\nSee [[missing-page]] for details.",
            encoding="utf-8",
        )

        result = await lint(project_path=str(project_root))

        broken = [
            i for i in result["issues"] if i["type"] == "wikilink_broken"
        ]
        assert len(broken) == 1
        assert broken[0]["severity"] == "warning"
        assert broken[0]["broken_target"] == "missing-page"
        assert broken[0]["page"] == "wiki/entities/a.md"

    async def test_missing_frontmatter_reported(
        self, project_root: Path
    ) -> None:
        """缺少 frontmatter 的页面应产生 warning。"""
        wiki = project_root / "wiki"
        (wiki / "entities").mkdir()
        (wiki / "entities" / "a.md").write_text(
            "No frontmatter here", encoding="utf-8"
        )

        result = await lint(project_path=str(project_root))

        fm_issues = [
            i for i in result["issues"]
            if i["type"] == "frontmatter_missing"
        ]
        assert len(fm_issues) == 1
        assert fm_issues[0]["severity"] == "warning"

    async def test_orphan_page_reported_as_info(
        self, project_root: Path
    ) -> None:
        """未被引用的页面应产生 info 级别的 orphan 问题。"""
        wiki = project_root / "wiki"
        (wiki / "entities").mkdir()
        (wiki / "entities" / "lonely.md").write_text(
            "---\ntitle: Lonely\n---\nNo one references me.",
            encoding="utf-8",
        )

        result = await lint(project_path=str(project_root))

        orphans = [i for i in result["issues"] if i["type"] == "orphan"]
        assert any(o["page"] == "wiki/entities/lonely.md" for o in orphans)
        assert all(o["severity"] == "info" for o in orphans)

    async def test_result_shape(self, project_root: Path) -> None:
        """返回的 dict 应包含完整结构字段。"""
        result = await lint(project_path=str(project_root))

        assert isinstance(result["total"], int)
        assert set(result["by_severity"].keys()) == {"error", "warning", "info"}
        assert isinstance(result["issues"], list)
        for issue in result["issues"]:
            assert "type" in issue
            assert "severity" in issue
            assert "page" in issue
            assert "detail" in issue
