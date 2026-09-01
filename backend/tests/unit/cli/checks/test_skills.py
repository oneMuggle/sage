"""Tests for the stdlib-only SkillsCheck and skills lint CLI."""
from __future__ import annotations

import ast
import importlib
from pathlib import Path

from backend.cli.checks import skills
from backend.cli.doctor import Severity
from backend.cli.skills import main


def _write_skill(root: Path, directory: str, name: str = "") -> None:
    skill_dir = root / directory
    skill_dir.mkdir(parents=True)
    actual_name = name or directory
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {actual_name}\ndescription: Use this skill for tests\n---\n\n# Body\n",
        encoding="utf-8",
    )


def test_no_skill_directory_is_info(monkeypatch, tmp_path):
    monkeypatch.setenv("SAGE_SKILLS_DIR", str(tmp_path / "missing"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    result = skills.SkillsCheck().run()
    assert result.severity == Severity.INFO
    assert "未配置" in result.message


def test_bad_frontmatter_is_warning(tmp_path):
    root = tmp_path / "skills"
    skill_dir = root / "broken"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: broken\n", encoding="utf-8")
    messages = skills.lint_skill_files([root])
    assert messages
    assert "closing" in messages[0]


def test_duplicate_name_across_roots_reports_first_root_as_winner(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_skill(first, "one", name="shared")
    _write_skill(second, "two", name="shared")
    messages = skills.lint_skill_files([first, second])
    assert any("duplicate skill 'shared'" in message for message in messages)
    assert str(first / "one" / "SKILL.md") in "\n".join(messages)


def test_skills_module_does_not_import_runtime_skills():
    module = importlib.import_module("backend.cli.checks.skills")
    source = Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    imported_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert all(
        module_name != "backend.skills" and not module_name.startswith("backend.skills.")
        for module_name in imported_modules
        if module_name is not None
    )
    assert all(
        name != "backend.skills" and not name.startswith("backend.skills.")
        for name in imported_names
    )


def test_lint_cli_returns_nonzero_for_bad_skill(tmp_path, capsys):
    root = tmp_path / "skills"
    _write_skill(root, "valid")
    (root / "bad").mkdir()
    (root / "bad" / "SKILL.md").write_text("not frontmatter", encoding="utf-8")
    assert main(["lint", str(root)]) == 1
    assert "bad" in capsys.readouterr().out


def test_lint_cli_returns_zero_for_empty_roots(capsys, tmp_path):
    assert main(["lint", str(tmp_path / "missing")]) == 0
    assert "未配置" in capsys.readouterr().out
