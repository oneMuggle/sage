"""Tests for SkillMdImporter — single-process file importer for SKILL.md.

Mirrors test_skill_md_loader.py style: monkeypatch env, use tmp_path, no real fs.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import List, Optional
from unittest import mock

import pytest

from backend.skills.registry import SkillRegistry
from backend.skills.skill_md.importer import SkillMdImporter, parse_file_from_bytes


def _make_skill_md(name: str, description: str = "Test skill") -> bytes:
    """Generate a valid SKILL.md file content."""
    return textwrap.dedent(f"""\
        ---
        name: {name}
        description: {description}
        ---
        Body of {name}.
    """).encode("utf-8")


def _make_named_upload(name: str, content: bytes, filename: Optional[str] = None):
    """Mock UploadFile-like object with .filename and async .read()."""
    upload = mock.AsyncMock()
    upload.filename = filename or f"{name}.md"
    upload.read = mock.AsyncMock(side_effect=[content, b""])
    return upload


@pytest.fixture()
def registry() -> SkillRegistry:
    return SkillRegistry()


@pytest.fixture()
def builtin_names(registry: SkillRegistry) -> List[str]:
    """Register a few builtins to test conflict behavior."""
    for n in ("coder", "search", "writer"):
        from backend.skills.base import BaseSkill, SkillResult, SkillSchema

        skill = mock.Mock(spec=BaseSkill)
        skill.name = n
        skill.schema = SkillSchema(
            name=n, description=f"builtin {n}", triggers=[], parameters={}, examples=[]
        )
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


async def test_import_files_rejects_symlinked_skill_directory(
    registry: SkillRegistry, skills_dir: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (skills_dir / "evil").symlink_to(outside, target_is_directory=True)

    result = await SkillMdImporter(registry, skills_dir=skills_dir).import_files(
        [_make_named_upload("evil", _make_skill_md("evil"))]
    )

    assert result["imported"] == []
    assert result["skipped"][0]["reason"] == "write_failed"
    assert not (outside / "SKILL.md").exists()


async def test_import_files_rejects_symlinked_root(
    registry: SkillRegistry, tmp_path: Path
) -> None:
    real_root = tmp_path / "real-root"
    real_root.mkdir()
    linked_root = tmp_path / "skills"
    linked_root.symlink_to(real_root, target_is_directory=True)

    result = await SkillMdImporter(registry, skills_dir=linked_root).import_files(
        [_make_named_upload("evil", _make_skill_md("evil"))]
    )

    assert result["imported"] == []
    assert result["skipped"][0]["reason"] == "write_failed"
    assert not (real_root / "evil" / "SKILL.md").exists()


async def test_import_files_rejects_symlinked_skill_file(
    registry: SkillRegistry, skills_dir: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text("original", encoding="utf-8")
    (skills_dir / "evil").mkdir()
    (skills_dir / "evil" / "SKILL.md").symlink_to(outside)

    result = await SkillMdImporter(registry, skills_dir=skills_dir).import_files(
        [_make_named_upload("evil", _make_skill_md("evil"))]
    )

    assert result["imported"] == []
    assert result["skipped"][0]["reason"] == "write_failed"
    assert outside.read_text(encoding="utf-8") == "original"


async def test_import_files_refreshes_bin_gating_between_batch_items(
    registry: SkillRegistry, skills_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Batch imports do not reuse a stale bin snapshot from the first item."""
    monkeypatch.setattr(
        "backend.skills.skill_md.gating.shutil.which",
        lambda name: "/usr/bin/git" if name == "git" else None,
    )
    first = textwrap.dedent("""\
        ---
        name: needs-git
        description: Needs git
        requires:
          bins: [git]
        ---
        Body
    """).encode("utf-8")
    second = textwrap.dedent("""\
        ---
        name: needs-missing
        description: Needs missing tool
        requires:
          bins: [missing-tool]
        ---
        Body
    """).encode("utf-8")

    result = await SkillMdImporter(registry, skills_dir=skills_dir).import_files(
        [
            _make_named_upload("needs-git", first),
            _make_named_upload("needs-missing", second),
        ]
    )

    assert [item["name"] for item in result["imported"]] == ["needs-git"]
    assert result["skipped"][0]["reason"] == "hot_reload_failed"
    assert not registry.exists("needs-missing")
    assert not (skills_dir / "needs-missing" / "SKILL.md").exists()




async def test_import_files_rolls_back_when_hash_fails_after_hot_reload(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    """A hash failure must leave no registry entry, file, or loader state."""
    content = _make_skill_md("hash-failure")
    importer = SkillMdImporter(registry, skills_dir=skills_dir)

    with mock.patch(
        "backend.skills.skill_md.loader.SkillMdHotLoader._compute_hash",
        side_effect=OSError("simulated hash failure"),
    ):
        result = await importer.import_files(
            [_make_named_upload("hash-failure", content)]
        )

    assert result == {
        "imported": [],
        "skipped": [{"name": "hash-failure", "reason": "hot_reload_failed"}],
    }
    assert not registry.exists("hash-failure")
    assert not (skills_dir / "hash-failure" / "SKILL.md").exists()
    assert importer._batch_loader is not None
    assert importer._batch_loader._loaded_paths == {}
    assert importer._batch_loader._file_hashes == {}


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


async def test_import_files_applies_bin_gating_from_uploaded_frontmatter(
    registry: SkillRegistry, skills_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Imported skills use declared bins for gating rather than an empty snapshot."""
    monkeypatch.setattr(
        "backend.skills.skill_md.gating.shutil.which",
        lambda name: "/usr/bin/git" if name == "git" else None,
    )
    content = textwrap.dedent("""\
        ---
        name: needs-git
        description: Needs git
        requires:
          bins: [git]
        ---
        Body
    """).encode("utf-8")

    result = await SkillMdImporter(registry, skills_dir=skills_dir).import_files(
        [_make_named_upload("needs-git", content)]
    )

    assert result["imported"] == [{"name": "needs-git", "path": "."}]
    assert registry.exists("needs-git")


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
    registry: SkillRegistry, skills_dir: Path, builtin_names: List[str]
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
    # Name schema validation is centralized in frontmatter.parse, then classified
    # at the importer boundary for backwards-compatible API semantics.
    assert result["skipped"][0]["reason"] == "invalid_name"


async def test_import_files_redacts_absolute_upload_filename(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    """Skipped import names never echo an absolute multipart filename."""
    result = await SkillMdImporter(registry, skills_dir=skills_dir).import_files(
        [_make_named_upload("/home/user/private/broken.md", b"not frontmatter")]
    )

    assert result["skipped"] == [{"name": "broken.md", "reason": "parse_error"}]
    assert "/home/user/private" not in str(result)


async def test_import_files_redacts_invalid_frontmatter_name(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    """Invalid YAML names are replaced by the safe upload basename."""
    content = b"---\nname: /home/user/private\ndescription: invalid\n---\nbody"
    result = await SkillMdImporter(registry, skills_dir=skills_dir).import_files(
        [_make_named_upload("submitted.md", content)]
    )

    assert result["skipped"] == [{"name": "submitted.md", "reason": "invalid_name"}]
    assert "/home/user/private" not in str(result)


@pytest.mark.parametrize(
    "filename",
    [
        "/home/user/private/broken.md",
        r"C:\\Users\\private\\broken.md",
        "bad\x00name\nwith\tcontrols\u202e.md",
    ],
)
async def test_import_files_redacts_posix_windows_and_control_filenames(
    registry: SkillRegistry, skills_dir: Path, filename: str
) -> None:
    """All skipped-name paths use only the client filename basename."""
    result = await SkillMdImporter(registry, skills_dir=skills_dir).import_files(
        [_make_named_upload("broken", b"not frontmatter", filename=filename)]
    )

    skipped_name = result["skipped"][0]["name"]
    assert result["skipped"][0]["reason"] == "parse_error"
    assert "/" not in skipped_name
    assert "\\\\" not in skipped_name
    assert all(
        not (ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F)
        for char in skipped_name
    )
    assert not any(
        ord(char) in {0x061C, 0x200E, 0x200F, *range(0x202A, 0x202F), *range(0x2066, 0x206A)}
        for char in skipped_name
    )
    assert filename not in str(result)


async def test_import_files_redacts_read_failure_filename(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    upload = mock.AsyncMock()
    upload.filename = r"C:\\Users\\private\\read-failed.md"
    upload.read = mock.AsyncMock(side_effect=OSError("read failed"))

    result = await SkillMdImporter(registry, skills_dir=skills_dir).import_files([upload])

    assert result["skipped"] == [{"name": "read-failed.md", "reason": "read_failed"}]
    assert "Users" not in str(result)


async def test_import_files_redacts_oversized_filename(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    upload = mock.AsyncMock()
    upload.filename = "/home/user/private/too-large.md"
    upload.read = mock.AsyncMock(return_value=b"x" * (1024 * 1024 + 1))

    result = await SkillMdImporter(registry, skills_dir=skills_dir).import_files([upload])

    assert result["skipped"][0]["name"] == "too-large.md"
    assert result["skipped"][0]["reason"].startswith("file_too_large")
    assert "/home/user/private" not in str(result)


# ===== test_import_files_skips_parse_error =====


async def test_import_files_skips_parse_error(registry: SkillRegistry, skills_dir: Path) -> None:
    """frontmatter without required 'name' → skip with parse_error reason."""
    bad_content = b"---\ndescription: no name here\n---\nbody"
    files = [_make_named_upload("broken", bad_content)]
    importer = SkillMdImporter(registry, skills_dir=skills_dir)
    result = await importer.import_files(files)

    assert result["imported"] == []
    skip = result["skipped"][0]
    assert skip["name"] == "broken"
    assert skip["reason"] == "parse_error"


@pytest.mark.parametrize("name_field", ["''", "null", "42", "Bad Name"])
async def test_import_files_classifies_bom_invalid_name(
    registry: SkillRegistry, skills_dir: Path, name_field: str
) -> None:
    """A parser-stripped BOM must not hide an explicitly invalid name."""
    content = f"﻿---\nname: {name_field}\ndescription: invalid name\n---\nbody".encode()

    result = await SkillMdImporter(registry, skills_dir=skills_dir).import_files(
        [_make_named_upload("broken", content)]
    )

    assert result["skipped"] == [{"name": "broken", "reason": "invalid_name"}]


async def test_import_files_classifies_trailing_name_newline_as_invalid_name(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    """An explicitly quoted newline name is rejected before any directory write."""
    content = b'---\nname: "good\\n"\ndescription: invalid name\n---\nbody\n'

    result = await SkillMdImporter(registry, skills_dir=skills_dir).import_files(
        [_make_named_upload("broken", content)]
    )

    assert result["imported"] == []
    assert result["skipped"] == [{"name": "broken", "reason": "invalid_name"}]
    assert not (skills_dir / "good\n").exists()
    assert list(skills_dir.iterdir()) == []


async def test_import_files_classifies_trailing_space_closing_fence_as_parse_error(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    """The classifier must use the parser's strict closing-fence semantics."""
    content = b"---\nname: Bad Name\ndescription: invalid name\n---   \nbody"

    result = await SkillMdImporter(registry, skills_dir=skills_dir).import_files(
        [_make_named_upload("broken", content)]
    )

    assert result["skipped"] == [{"name": "broken", "reason": "parse_error"}]


# ===== test_import_files_aggregates_skipped_in_result =====


async def test_import_files_aggregates_skipped_in_result(
    registry: SkillRegistry, skills_dir: Path, builtin_names: List[str]
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

    # Patch the low-level writer used by the importer.
    with mock.patch(
        "backend.skills.skill_md.importer.write_skill_file",
        side_effect=PermissionError("denied"),
    ):
        result = await importer.import_files(files)

    assert result["imported"] == []
    assert result["skipped"][0]["reason"] == "write_failed"


async def test_import_files_cleans_partial_write_after_writer_error(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    """A writer that creates a file before failing must not leave a ghost skill."""
    content = _make_skill_md("partial")
    target = skills_dir / "partial" / "SKILL.md"

    def write_then_fail(root: Path, name: str, payload: bytes, *, overwrite: bool) -> Path:
        del overwrite
        destination = root / name
        destination.mkdir()
        (destination / "SKILL.md").write_bytes(payload)
        raise OSError("simulated disk failure")

    importer = SkillMdImporter(registry, skills_dir=skills_dir)
    with mock.patch(
        "backend.skills.skill_md.importer.write_skill_file", side_effect=write_then_fail
    ):
        result = await importer.import_files([_make_named_upload("partial", content)])

    assert result["skipped"] == [{"name": "partial", "reason": "write_failed"}]
    assert not target.exists()




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
    assert result["imported"][0]["path"] == "."


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


async def test_import_files_rejects_batches_over_file_count_limit(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    from backend.skills.skill_md.importer import MAX_IMPORT_FILES

    files = [_make_named_upload(f"skill-{i}", _make_skill_md(f"skill-{i}")) for i in range(MAX_IMPORT_FILES + 1)]
    result = await SkillMdImporter(registry, skills_dir=skills_dir).import_files(files)

    assert result["imported"] == []
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["reason"].startswith("batch_too_many_files")


async def test_import_files_rejects_batches_over_total_size_limit(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    from backend.skills.skill_md import importer as importer_module

    original_limit = importer_module.MAX_IMPORT_TOTAL_SIZE_BYTES
    importer_module.MAX_IMPORT_TOTAL_SIZE_BYTES = len(_make_skill_md("one"))
    try:
        files = [
            _make_named_upload("one", _make_skill_md("one")),
            _make_named_upload("two", _make_skill_md("two")),
        ]
        result = await SkillMdImporter(registry, skills_dir=skills_dir).import_files(files)
    finally:
        importer_module.MAX_IMPORT_TOTAL_SIZE_BYTES = original_limit

    assert len(result["imported"]) == 1
    assert result["skipped"][0]["reason"].startswith("batch_too_large")


async def test_import_files_rejects_oversized_files_after_bounded_reads(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    """The importer reads in bounded chunks and probes only one byte past the cap."""
    from backend.skills.skill_md.importer import MAX_FILE_SIZE_BYTES

    chunk_size = 64 * 1024
    chunks = [b"x" * chunk_size] * (MAX_FILE_SIZE_BYTES // chunk_size)
    upload = mock.AsyncMock()
    upload.filename = "huge.md"
    upload.read = mock.AsyncMock(side_effect=[*chunks, b"x"])

    result = await SkillMdImporter(registry, skills_dir=skills_dir).import_files([upload])

    assert result["imported"] == []
    assert result["skipped"][0]["reason"].startswith("file_too_large")
    assert upload.read.call_count == len(chunks) + 1
    assert all(call.args[0] <= chunk_size for call in upload.read.call_args_list)
    assert upload.read.call_args_list[-1].args == (1,)
    assert not (skills_dir / "huge" / "SKILL.md").exists()


async def test_import_files_reads_upload_in_chunks(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    """UploadFile-like readers receive a maximum read size instead of an unbounded read."""
    content = _make_skill_md("chunked")
    upload = mock.AsyncMock()
    upload.filename = "chunked.md"
    upload.read = mock.AsyncMock(side_effect=[content, b""])

    result = await SkillMdImporter(registry, skills_dir=skills_dir).import_files([upload])

    assert len(result["imported"]) == 1
    assert upload.read.call_args_list[0].args[0] <= 64 * 1024


def test_parse_file_from_bytes_requires_fenced_frontmatter_semantics() -> None:
    """The importer follows frontmatter.parse's closing-fence line semantics."""
    content = b"---\nname: tight\ndescription: tight\n---Body starts immediately"
    with pytest.raises(ValueError, match="unclosed frontmatter"):
        parse_file_from_bytes(content)


def test_parse_file_from_bytes_rejects_invalid_utf8() -> None:
    with pytest.raises(ValueError, match="invalid UTF-8"):
        parse_file_from_bytes(b"---\xff")


def test_parse_file_from_bytes_rejects_missing_frontmatter() -> None:
    with pytest.raises(ValueError, match="missing frontmatter"):
        parse_file_from_bytes(b"plain markdown")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("description", "x" * 1025),
        ("compatibility", "x" * 501),
        ("compatibility", "[linux]"),
        ("allowed-tools", "[read]"),
        ("always", "not-a-bool"),
        ("command-dispatch", "invalid"),
        ("os", "linux"),
        ("requires", "git"),
    ],
)
async def test_import_files_skips_schema_errors(
    registry: SkillRegistry,
    skills_dir: Path,
    field: str,
    value: str,
) -> None:
    content = textwrap.dedent(
        f"""\
        ---
        name: schema-error
        description: Valid description
        {field}: {value}
        ---
        body
        """
    ).encode("utf-8")
    result = await SkillMdImporter(registry, skills_dir=skills_dir).import_files(
        [_make_named_upload("schema-error", content)]
    )
    assert result["imported"] == []
    assert result["skipped"] == [{"name": "schema-error", "reason": "parse_error"}]


async def test_import_files_accepts_bom_crlf_and_v2_fields(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    content = (
        "﻿---\r\n"
        "name: v2-import\r\n"
        "description: Use this skill for v2 imports\r\n"
        "when_to_use: Use this for v2 imports\r\n"
        "requires:\r\n"
        "  bins: [git]\r\n"
        "os: [linux]\r\n"
        "always: true\r\n"
        "command-dispatch: tool\r\n"
        "license: MIT\r\n"
        "compatibility: Linux\r\n"
        "allowed-tools: read write\r\n"
        "---\r\n"
        "body\r\n"
    ).encode()
    result = await SkillMdImporter(registry, skills_dir=skills_dir).import_files(
        [_make_named_upload("v2-import", content)]
    )
    assert [item["name"] for item in result["imported"]] == ["v2-import"]
    skill = registry.get("v2-import")
    assert skill is not None
    assert skill._doc.when_to_use == "Use this for v2 imports"
    assert skill._doc.requires.bins == ["git"]
    assert skill._doc.os == ["linux"]
    assert skill._doc.always is True
    assert skill._doc.dispatch.command_dispatch == "tool"
    assert skill._doc.compatibility == "Linux"
    assert skill._doc.allowed_tools == ("read", "write")


# ===== test_import_files_handles_body_with_horizontal_rule =====


async def test_import_files_handles_body_with_horizontal_rule(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    """Body containing --- (markdown HR) must not be parsed as closing delimiter."""
    content = (
        b"---\n"
        b"name: with-hr\n"
        b"description: body has hr\n"
        b"---\n"
        b"# Section\n"
        b"\n"
        b"---\n"  # this is a markdown horizontal rule in the body
        b"more body\n"
    )
    files = [_make_named_upload("with-hr", content)]
    importer = SkillMdImporter(registry, skills_dir=skills_dir)
    result = await importer.import_files(files)

    assert len(result["imported"]) == 1
    assert result["imported"][0]["name"] == "with-hr"
    written = skills_dir / "with-hr" / "SKILL.md"
    assert b"# Section" in written.read_bytes()
    assert b"more body" in written.read_bytes()


# ===== test_import_files_uses_one_loader_for_batch =====


async def test_import_files_uses_one_loader_for_batch(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    """All files in one batch share a single SkillMdHotLoader instance."""
    files = [_make_named_upload(f"skill-{i}", _make_skill_md(f"skill-{i}")) for i in range(3)]
    importer = SkillMdImporter(registry, skills_dir=skills_dir)
    await importer.import_files(files)

    # After batch, exactly one loader should have been constructed
    assert importer._batch_loader is not None
    # All 3 skills loaded via the same loader
    assert len(importer._batch_loader._loaded_paths) == 3
