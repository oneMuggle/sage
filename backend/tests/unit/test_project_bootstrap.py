"""Unit tests for AI project bootstrap preview/apply (2026-10-29)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.data import database as database_module
from backend.data.database import Database
from backend.data.project_constraint_repo import ProjectConstraintRepository
from backend.data.project_milestone_repo import ProjectMilestoneRepository
from backend.data.project_repo import ProjectRepository
from backend.services import project_bootstrap
from backend.services.project_analysis_agent import AnalysisReport, SuggestedRule
from backend.services.project_rule_generator import RuleDraft, RuleGenerationResult


@pytest.fixture()
def db(monkeypatch: pytest.MonkeyPatch) -> Database:
    test_db = Database(":memory:")
    test_db.init_db()
    monkeypatch.setattr(database_module, "_db", test_db)
    return test_db


@pytest.fixture()
def project(db: Database, tmp_path: Path):
    root = tmp_path / "demo-project"
    root.mkdir()
    (root / "main.py").write_text("print('hi')", encoding="utf-8")
    return ProjectRepository().register(str(root), project_type="coding")


class FakeAgent:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def analyze(self, profile, *, allow_llm: bool = True) -> AnalysisReport:
        return AnalysisReport(
            level1_type="coding",
            sub_type="python_backend",
            confidence=0.9,
            tech_stack=["python"],
            architecture_summary="demo architecture",
            suggested_rules=[
                SuggestedRule(
                    template_key="python_default",
                    label="Python 规范",
                    reason="检测到 .py 文件",
                    confidence=0.9,
                    category="coding_style",
                    content="Use black for formatting",
                    trigger_pattern="always",
                    priority=8,
                )
            ],
            governance_recommendations=["补充 CI"],
            stage_recommendation="development",
            sage_md_draft="# Demo SAGE",
            docs_refs=[],
            llm_available=allow_llm,
        )


class FakeGenerator:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def generate(self, _profile, _report, existing_contents=None) -> RuleGenerationResult:
        return RuleGenerationResult(
            rules=[
                RuleDraft(
                    category="coding_style",
                    content="Use ruff for linting",
                    trigger_pattern="always",
                    priority=7,
                    source="template",
                    template_key="python_default",
                    reason="检测到 Python 项目",
                )
            ],
            milestones=[{"title": "AI 里程碑", "description": "AI 生成"}],
            llm_available=True,
        )


@pytest.mark.asyncio()
async def test_preview_returns_deterministic_suggestions(
    project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(project_bootstrap, "ProjectAnalysisAgent", FakeAgent)
    monkeypatch.setattr(project_bootstrap, "git_available", lambda: True)

    result = await project_bootstrap.build_bootstrap_preview(project, use_llm=False)

    suggestions = result["suggestions"]
    assert suggestions["sage_md"]["content"] == "# Demo SAGE"
    assert suggestions["rules"][0]["content"] == "Use black for formatting"
    assert suggestions["milestones"]
    assert suggestions["git_init"]["recommended"] is True
    assert result["scan"]["git"]["is_repo"] is False
    assert result["llm_available"] is False


@pytest.mark.asyncio()
async def test_preview_skips_git_when_git_missing(
    project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(project_bootstrap, "ProjectAnalysisAgent", FakeAgent)
    monkeypatch.setattr(project_bootstrap, "git_available", lambda: False)

    result = await project_bootstrap.build_bootstrap_preview(project, use_llm=False)

    assert result["suggestions"]["git_init"]["recommended"] is False
    assert result["suggestions"]["git_init"]["blockers"] == ["git_not_available"]


@pytest.mark.asyncio()
async def test_preview_uses_generated_custom_rules(
    project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(project_bootstrap, "ProjectAnalysisAgent", FakeAgent)
    monkeypatch.setattr(project_bootstrap, "ProjectRuleGenerator", FakeGenerator)
    monkeypatch.setattr(project_bootstrap, "git_available", lambda: True)

    result = await project_bootstrap.build_bootstrap_preview(project, use_llm=True)

    assert result["suggestions"]["rules"][0]["content"] == "Use ruff for linting"
    assert any(item["title"] == "AI 里程碑" for item in result["suggestions"]["milestones"])
    assert result["llm_available"] is True


def test_apply_writes_sage_md_rules_and_milestones(
    project, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []
    monkeypatch.setattr(project_bootstrap, "git_available", lambda: True)
    monkeypatch.setattr(
        project_bootstrap,
        "init_project_git",
        lambda path: calls.append(path)
        or {"initialized": True, "already_repo": False, "git_available": True, "error": None},
    )

    result = project_bootstrap.apply_bootstrap(
        project,
        {
            "metadata": {"description": "demo", "project_sub_type": "python_backend"},
            "sage_md": True,
            "sage_md_content": "# Demo SAGE",
            "rules": [
                {
                    "category": "coding_style",
                    "content": "Use black for formatting",
                    "priority": 8,
                }
            ],
            "milestones": [{"title": "MVP", "description": "first"}],
            "git_init": True,
        },
    )

    root = Path(project.path)
    assert (root / "SAGE.md").read_text(encoding="utf-8") == "# Demo SAGE"
    constraints = ProjectConstraintRepository().list_by_project(project.id)
    assert [item.content for item in constraints] == ["Use black for formatting"]
    milestones = ProjectMilestoneRepository().list_by_project(project.id)
    assert [item.title for item in milestones] == ["MVP"]
    assert calls == [project.path]

    updated = ProjectRepository().get(project.id)
    assert updated is not None
    assert updated.description == "demo"
    assert updated.project_sub_type == "python_backend"
    assert updated.vcs_mode == "git"
    state = json.loads(updated.bootstrap_state or "{}")
    assert "sage_md" in state["applied"]
    assert "git_init" in state["applied"]
    assert result["errors"] == []


def test_apply_does_not_overwrite_existing_sage_md(
    project, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(project.path)
    (root / "SAGE.md").write_text("# Existing", encoding="utf-8")

    result = project_bootstrap.apply_bootstrap(
        project,
        {"sage_md": True, "sage_md_content": "# New"},
    )

    assert (root / "SAGE.md").read_text(encoding="utf-8") == "# Existing"
    assert "sage_md" in result["skipped"]


def test_apply_dedupes_existing_rule_content(project) -> None:
    ProjectConstraintRepository().create(
        project_id=project.id,
        category="coding_style",
        content="Use black for formatting",
    )

    result = project_bootstrap.apply_bootstrap(
        project,
        {
            "rules": [
                {
                    "category": "coding_style",
                    "content": "  Use   black for formatting ",
                    "priority": 8,
                }
            ]
        },
    )

    constraints = ProjectConstraintRepository().list_by_project(project.id)
    assert len(constraints) == 1
    assert "rule" in result["skipped"]


def test_apply_git_init_is_opt_in(project, monkeypatch: pytest.MonkeyPatch) -> None:
    called = []
    monkeypatch.setattr(project_bootstrap, "git_available", lambda: True)
    monkeypatch.setattr(
        project_bootstrap,
        "init_project_git",
        lambda path: called.append(path) or {"initialized": True, "error": None},
    )

    project_bootstrap.apply_bootstrap(project, {})

    assert called == []


def test_apply_git_unavailable_records_error(
    project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(project_bootstrap, "git_available", lambda: False)

    result = project_bootstrap.apply_bootstrap(project, {"git_init": True})

    assert result["errors"] == [{"item": "git_init", "message": "本机未检测到 Git，已跳过"}]
