"""Wiki Review API 集成测试。

测试 GET /review 端点,使用 monkeypatch 绕过项目授权。
"""
from pathlib import Path

import pytest

from backend.api import wiki_routes
from backend.api.wiki_routes import review


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """创建临时 Wiki 项目。"""
    project = tmp_path / "wiki-project"
    project.mkdir()
    (project / "wiki").mkdir()
    return project


@pytest.fixture(autouse=True)
def patch_auth(monkeypatch, project_root: Path):
    """绕过项目授权。"""
    monkeypatch.setattr(
        wiki_routes,
        "authorize_registered_project",
        lambda _: project_root,
    )


class TestReviewEndpoint:
    """测试 GET /review。"""

    async def test_empty_project_returns_clean(self, project_root: Path) -> None:
        """空项目（无 wiki 文件）应无任何 review 项。"""
        result = await review(project_path=str(project_root))

        assert "total" in result
        assert "by_type" in result
        assert "items" in result
        # 空 wiki 目录没有 .md 文件 → 各 detector 都返回 []
        assert result["total"] == 0
        assert result["items"] == []

    async def test_well_formed_project_is_clean(self, project_root: Path) -> None:
        """互相引用、标题独特、日期一致的 wiki 应无 review 项。"""
        wiki = project_root / "wiki"
        (wiki / "a.md").write_text(
            "---\ntitle: Alpha\ncreated: 2026-01-01\nupdated: 2026-09-06\n---\n"
            + ("Long body content. " * 20)
            + "\nSee [[b]]",
            encoding="utf-8",
        )
        (wiki / "b.md").write_text(
            "---\ntitle: Beta\ncreated: 2026-01-01\nupdated: 2026-09-06\n---\n"
            + ("Long body content. " * 20)
            + "\nSee [[a]]",
            encoding="utf-8",
        )

        result = await review(project_path=str(project_root))

        assert result["total"] == 0
        assert all(v == 0 for v in result["by_type"].values())

    async def test_missing_page_reported(self, project_root: Path) -> None:
        """断链指向的不存在页应产生 missing-page 项。"""
        wiki = project_root / "wiki"
        (wiki / "a.md").write_text(
            "---\ntitle: A\n---\nSee [[nonexistent-page]] for details.",
            encoding="utf-8",
        )

        result = await review(project_path=str(project_root))

        missing = [
            i for i in result["items"] if i["type"] == "missing-page"
        ]
        assert len(missing) == 1
        assert "nonexistent-page" in missing[0]["title"]
        assert missing[0]["affected_pages"] == ["wiki/a.md"]
        assert missing[0]["confidence"] == 1.0

    async def test_duplicate_reported(self, project_root: Path) -> None:
        """标题高度重叠的页对应产生 duplicate 项。"""
        wiki = project_root / "wiki"
        (wiki / "a.md").write_text(
            "---\ntitle: Deep Transformer Model Architecture\n---\nbody",
            encoding="utf-8",
        )
        (wiki / "b.md").write_text(
            "---\ntitle: Deep Transformer Model Implementation\n---\nbody",
            encoding="utf-8",
        )

        result = await review(project_path=str(project_root))

        dups = [i for i in result["items"] if i["type"] == "duplicate"]
        assert len(dups) == 1
        assert "Transformer" in dups[0]["title"]
        assert dups[0]["confidence"] >= 0.5

    async def test_contradiction_reported(self, project_root: Path) -> None:
        """created > updated 应产生 contradiction 项。"""
        wiki = project_root / "wiki"
        (wiki / "a.md").write_text(
            "---\ntitle: A\ncreated: 2026-09-06\nupdated: 2026-01-01\n---\nbody",
            encoding="utf-8",
        )

        result = await review(project_path=str(project_root))

        contra = [i for i in result["items"] if i["type"] == "contradiction"]
        assert len(contra) == 1
        assert "日期矛盾" in contra[0]["title"]

    async def test_suggestion_short_page_reported(
        self, project_root: Path
    ) -> None:
        """短页应产生 suggestion 项。"""
        wiki = project_root / "wiki"
        (wiki / "a.md").write_text(
            "---\ntitle: A\n---\nshort body",
            encoding="utf-8",
        )

        result = await review(project_path=str(project_root))

        suggs = [
            i for i in result["items"]
            if i["type"] == "suggestion" and i["detail"] == "short_page"
        ]
        assert len(suggs) == 1
        assert suggs[0]["confidence"] == 0.6

    async def test_confirm_orphan_reported(self, project_root: Path) -> None:
        """无入链的页应产生 confirm 项。"""
        wiki = project_root / "wiki"
        (wiki / "lonely.md").write_text(
            "---\ntitle: Lonely\n---\nNobody references me",
            encoding="utf-8",
        )

        result = await review(project_path=str(project_root))

        confirms = [
            i for i in result["items"] if i["type"] == "confirm"
        ]
        assert any(c["affected_pages"] == ["wiki/lonely.md"] for c in confirms)

    async def test_result_shape(self, project_root: Path) -> None:
        """返回的 dict 应包含完整结构字段。"""
        result = await review(project_path=str(project_root))

        assert isinstance(result["total"], int)
        assert set(result["by_type"].keys()) == {
            "duplicate",
            "contradiction",
            "missing-page",
            "confirm",
            "suggestion",
        }
        assert isinstance(result["items"], list)
        for item in result["items"]:
            assert "id" in item
            assert "type" in item
            assert "title" in item
            assert "description" in item
            assert "affected_pages" in item
            assert "confidence" in item
            assert item["id"].startswith("rv-")
