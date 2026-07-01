"""Tests for SkillMdImporter — single-process file importer for SKILL.md.

Mirrors test_skill_md_loader.py style: monkeypatch env, use tmp_path, no real fs.
"""
from __future__ import annotations

import textwrap
from pathlib import Path
from unittest import mock

import pytest

from backend.skills.registry import SkillRegistry
from backend.skills.skill_md.importer import SkillMdImporter


def _make_skill_md(name: str, description: str = "Test skill") -> bytes:
    """Generate a valid SKILL.md file content."""
    return textwrap.dedent(f"""\
        ---
        name: {name}
        description: {description}
        ---
        Body of {name}.
    """).encode("utf-8")


def _make_named_upload(name: str, content: bytes, filename: str | None = None):
    """Mock UploadFile-like object with .filename and async .read()."""
    upload = mock.AsyncMock()
    upload.filename = filename or f"{name}.md"
    upload.read = mock.AsyncMock(return_value=content)
    return upload


@pytest.fixture()
def registry() -> SkillRegistry:
    return SkillRegistry()


@pytest.fixture()
def builtin_names(registry: SkillRegistry) -> list[str]:
    """Register a few builtins to test conflict behavior."""
    for n in ("coder", "search", "writer"):
        from backend.skills.base import BaseSkill, SkillResult, SkillSchema

        skill = mock.Mock(spec=BaseSkill)
        skill.name = n
        skill.schema = SkillSchema(name=n, description=f"builtin {n}", triggers=[], parameters={}, examples=[])
        skill.execute = mock.Mock(return_value=SkillResult(success=True, content=""))
        registry.register(skill)
    return ["coder", "search", "writer"]


@pytest.fixture()
def skills_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point SAGE_SKILLS_DIR to a fresh tmp dir for each test."""
    d = tmp_path / "skills"
    d.mkdir()
    monkeypatch.setenv("SAGE_SKILLS_DIR", str(d))
    return d


# ===== test_import_files_writes_skill_md_to_correct_path =====


async def test_import_files_writes_skill_md_to_correct_path(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    files = [_make_named_upload("code-review", _make_skill_md("code-review"))]
    importer = SkillMdImporter(registry, skills_dir=skills_dir)
    result = await importer.import_files(files)

    assert len(result["imported"]) == 1
    assert result["imported"][0]["name"] == "code-review"
    written = skills_dir / "code-review" / "SKILL.md"
    assert written.is_file()
    assert b"Body of code-review" in written.read_bytes()


# ===== test_import_files_creates_skill_dir_if_missing =====


async def test_import_files_creates_skill_dir_if_missing(
    registry: SkillRegistry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If skills_dir doesn't exist, mkdir it (not 500)."""
    d = tmp_path / "new_skills"
    assert not d.exists()
    monkeypatch.setenv("SAGE_SKILLS_DIR", str(d))
    files = [_make_named_upload("code-review", _make_skill_md("code-review"))]
    importer = SkillMdImporter(registry, skills_dir=d)
    result = await importer.import_files(files)

    assert d.is_dir()
    assert len(result["imported"]) == 1


# ===== test_import_files_skips_builtin_name_collision =====


async def test_import_files_skips_builtin_name_collision(
    registry: SkillRegistry, skills_dir: Path, builtin_names: list[str]
) -> None:
    files = [_make_named_upload("coder", _make_skill_md("coder"))]
    importer = SkillMdImporter(registry, skills_dir=skills_dir)
    result = await importer.import_files(files)

    assert result["imported"] == []
    assert len(result["skipped"]) == 1
    assert result["skipped"][0] == {"name": "coder", "reason": "builtin_conflict"}
    # builtin stays registered, SKILL.md not registered
    assert registry.exists("coder")


# ===== test_import_files_skips_existing_skill_md =====


async def test_import_files_skips_existing_skill_md(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    """If a SKILL.md with same name already on disk, skip + report."""
    (skills_dir / "code-review").mkdir()
    (skills_dir / "code-review" / "SKILL.md").write_bytes(_make_skill_md("code-review"))

    files = [_make_named_upload("code-review", _make_skill_md("code-review"))]
    importer = SkillMdImporter(registry, skills_dir=skills_dir)
    result = await importer.import_files(files)

    assert result["imported"] == []
    assert result["skipped"][0]["reason"] == "already_exists"


# ===== test_import_files_skips_invalid_name =====


@pytest.mark.parametrize("bad_name", ["BadName", "with space", "../etc/passwd", "x" * 65])
async def test_import_files_skips_invalid_name(
    registry: SkillRegistry, skills_dir: Path, bad_name: str
) -> None:
    files = [_make_named_upload(bad_name, _make_skill_md(bad_name))]
    importer = SkillMdImporter(registry, skills_dir=skills_dir)
    result = await importer.import_files(files)

    assert result["imported"] == []
    assert result["skipped"][0]["reason"] == "invalid_name"


# ===== test_import_files_skips_parse_error =====


async def test_import_files_skips_parse_error(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    """frontmatter without required 'name' → skip with parse_error reason."""
    bad_content = b"---\ndescription: no name here\n---\nbody"
    files = [_make_named_upload("broken", bad_content)]
    importer = SkillMdImporter(registry, skills_dir=skills_dir)
    result = await importer.import_files(files)

    assert result["imported"] == []
    skip = result["skipped"][0]
    assert skip["name"] == "broken"
    assert skip["reason"].startswith("parse_error:")


# ===== test_import_files_aggregates_skipped_in_result =====


async def test_import_files_aggregates_skipped_in_result(
    registry: SkillRegistry, skills_dir: Path, builtin_names: list[str]
) -> None:
    """Mix of valid + builtin_conflict + invalid → all reported."""
    files = [
        _make_named_upload("good", _make_skill_md("good")),
        _make_named_upload("coder", _make_skill_md("coder")),  # builtin
        _make_named_upload("Bad-Name", _make_skill_md("Bad-Name")),  # invalid
    ]
    importer = SkillMdImporter(registry, skills_dir=skills_dir)
    result = await importer.import_files(files)

    assert len(result["imported"]) == 1
    assert result["imported"][0]["name"] == "good"
    assert len(result["skipped"]) == 2
    skip_reasons = {s["name"]: s["reason"] for s in result["skipped"]}
    assert skip_reasons["coder"] == "builtin_conflict"
    assert skip_reasons["Bad-Name"] == "invalid_name"


# ===== test_import_files_hot_reloads_after_write =====


async def test_import_files_hot_reloads_after_write(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    """After write, the new skill appears in the registry."""
    files = [_make_named_upload("code-review", _make_skill_md("code-review"))]
    importer = SkillMdImporter(registry, skills_dir=skills_dir)
    await importer.import_files(files)

    assert registry.exists("code-review")
    skill = registry.get("code-review")
    assert skill is not None
    assert skill.name == "code-review"


# ===== test_import_files_handles_write_permission_error =====


async def test_import_files_handles_write_permission_error(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    """If write fails (mock PermissionError), skip + write_failed reason."""
    files = [_make_named_upload("code-review", _make_skill_md("code-review"))]
    importer = SkillMdImporter(registry, skills_dir=skills_dir)

    # Patch Path.write_bytes to raise PermissionError
    with mock.patch.object(Path, "write_bytes", side_effect=PermissionError("denied")):
        result = await importer.import_files(files)

    assert result["imported"] == []
    assert result["skipped"][0]["reason"].startswith("write_failed:")


# ===== test_import_files_resolves_sage_skills_dir_first =====


async def test_import_files_resolves_sage_skills_dir_first(
    registry: SkillRegistry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SAGE_SKILLS_DIR is preferred over ~/.sage/skills."""
    sage_dir = tmp_path / "sage_env"
    sage_dir.mkdir()
    monkeypatch.setenv("SAGE_SKILLS_DIR", str(sage_dir))

    # Mock home to a different tmp dir to ensure ~/.sage/skills is NOT used
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    files = [_make_named_upload("code-review", _make_skill_md("code-review"))]
    importer = SkillMdImporter(registry)  # No explicit skills_dir
    await importer.import_files(files)

    assert (sage_dir / "code-review" / "SKILL.md").is_file()
    assert not (fake_home / ".sage" / "skills").exists()


# ===== test_import_files_falls_back_to_dot_sage_skills =====


async def test_import_files_falls_back_to_dot_sage_skills(
    registry: SkillRegistry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If SAGE_SKILLS_DIR unset/invalid, fall back to ~/.sage/skills (auto-mkdir)."""
    monkeypatch.setenv("SAGE_SKILLS_DIR", "")
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    files = [_make_named_upload("code-review", _make_skill_md("code-review"))]
    importer = SkillMdImporter(registry)
    result = await importer.import_files(files)

    expected = fake_home / ".sage" / "skills" / "code-review" / "SKILL.md"
    assert expected.is_file()
    assert result["imported"][0]["path"] == str(expected)


# ===== test_import_files_returns_empty_when_no_files =====


async def test_import_files_returns_empty_when_no_files(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    importer = SkillMdImporter(registry, skills_dir=skills_dir)
    result = await importer.import_files([])
    assert result == {"imported": [], "skipped": []}


# ===== test_import_files_rejects_oversized_files =====


async def test_import_files_rejects_oversized_files(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    """Files > 1MB are skipped (DoS defense)."""
    huge = b"---\nname: huge\ndescription: huge\n---\n" + b"x" * (1024 * 1024 + 1)
    files = [_make_named_upload("huge", huge)]
    importer = SkillMdImporter(registry, skills_dir=skills_dir)
    result = await importer.import_files(files)

    assert result["imported"] == []
    assert result["skipped"][0]["reason"].startswith("file_too_large")
