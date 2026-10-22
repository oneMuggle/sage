"""Tests for SkillMdImporter.import_directory —— 技能目录整体导入。

与 test_skill_md_importer.py 的单文件导入互补：这里 multipart 的 filename
携带**相对路径**（``SKILL.md`` / ``scripts/scan.py`` / ``assets/tpl.html``），
一次导入入口文件 + 附属资源。
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest import mock

import pytest

from backend.skills.registry import SkillRegistry
from backend.skills.skill_md.exceptions import SkillDirectoryImportError
from backend.skills.skill_md.importer import SkillMdImporter


def _make_skill_md(name: str, description: str = "Test skill") -> bytes:
    return textwrap.dedent(f"""\
        ---
        name: {name}
        description: {description}
        ---
        Body of {name}.
    """).encode("utf-8")


def _make_upload(filename: str, content: bytes):
    """Mock UploadFile-like object with .filename and async .read()."""
    upload = mock.AsyncMock()
    upload.filename = filename
    upload.read = mock.AsyncMock(side_effect=[content, b""])
    return upload


@pytest.fixture()
def registry() -> SkillRegistry:
    return SkillRegistry()


@pytest.fixture()
def skills_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "skills"
    d.mkdir()
    monkeypatch.setenv("SAGE_SKILLS_DIR", str(d))
    return d


# ===== 成功路径 =====


async def test_import_directory_writes_entry_and_resources(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    """入口文件 + 附属资源按相对路径落盘到技能目录下。"""
    files = [
        _make_upload("SKILL.md", _make_skill_md("dir-skill")),
        _make_upload("scripts/scan.py", b"print('hi')\n"),
        _make_upload("assets/tpl.html", b"<p>tpl</p>"),
    ]

    result = await SkillMdImporter(registry, skills_dir=skills_dir).import_directory(files)

    assert result["imported"] == [{"name": "dir-skill", "path": "."}]
    assert result["skipped"] == []
    skill_dir = skills_dir / "dir-skill"
    assert (skill_dir / "SKILL.md").is_file()
    assert (skill_dir / "scripts" / "scan.py").read_bytes() == b"print('hi')\n"
    assert (skill_dir / "assets" / "tpl.html").read_bytes() == b"<p>tpl</p>"


async def test_import_directory_registers_skill(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    """导入成功后技能进入 registry。"""
    await SkillMdImporter(registry, skills_dir=skills_dir).import_directory(
        [_make_upload("SKILL.md", _make_skill_md("registered"))]
    )

    assert registry.exists("registered")


async def test_import_directory_accepts_lowercase_entry_filename(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    """入口文件名大小写不敏感。"""
    result = await SkillMdImporter(registry, skills_dir=skills_dir).import_directory(
        [_make_upload("skill.md", _make_skill_md("lower-entry"))]
    )

    assert result["imported"] == [{"name": "lower-entry", "path": "."}]
    assert (skills_dir / "lower-entry" / "SKILL.md").is_file()


async def test_import_directory_supports_nested_resource_paths(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    """白名单目录下的多层子目录同样落盘。"""
    result = await SkillMdImporter(registry, skills_dir=skills_dir).import_directory(
        [
            _make_upload("SKILL.md", _make_skill_md("nested")),
            _make_upload("references/guide/intro.md", b"intro\n"),
        ]
    )

    assert result["imported"] == [{"name": "nested", "path": "."}]
    assert (skills_dir / "nested" / "references" / "guide" / "intro.md").is_file()


# ===== 入口文件缺失 / 不合法 =====


async def test_import_directory_requires_skill_md(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    """没有 SKILL.md → 整批拒绝。"""
    with pytest.raises(SkillDirectoryImportError) as excinfo:
        await SkillMdImporter(registry, skills_dir=skills_dir).import_directory(
            [_make_upload("scripts/scan.py", b"print('hi')\n")]
        )

    assert excinfo.value.error_type == "missing_skill_md"
    assert not list(skills_dir.iterdir())


async def test_import_directory_rejects_unparsable_entry(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    """SKILL.md 无法解析 → parse_error，不写盘。"""
    with pytest.raises(SkillDirectoryImportError) as excinfo:
        await SkillMdImporter(registry, skills_dir=skills_dir).import_directory(
            [_make_upload("SKILL.md", b"no frontmatter here")]
        )

    assert excinfo.value.error_type == "parse_error"
    assert not list(skills_dir.iterdir())


async def test_import_directory_rejects_invalid_entry_name(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    """SKILL.md 的 name 非法 → invalid_name，不写盘。"""
    with pytest.raises(SkillDirectoryImportError) as excinfo:
        await SkillMdImporter(registry, skills_dir=skills_dir).import_directory(
            [_make_upload("SKILL.md", b"---\nname: Bad Name\ndescription: x\n---\nbody")]
        )

    assert excinfo.value.error_type == "invalid_name"
    assert not list(skills_dir.iterdir())


async def test_import_directory_without_files_raises(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    """空文件列表 → no_files。"""
    with pytest.raises(SkillDirectoryImportError) as excinfo:
        await SkillMdImporter(registry, skills_dir=skills_dir).import_directory([])

    assert excinfo.value.error_type == "no_files"


# ===== 路径穿越 / 非法路径 =====


@pytest.mark.parametrize(
    "filename",
    [
        "../evil.md",
        "../../etc/passwd",
        "/absolute/evil.md",
        "C:\\Windows\\evil.md",
        "scripts\\evil.py",
        "./evil.md",
        "scripts//evil.py",
        "scripts/../../evil.py",
    ],
)
async def test_import_directory_rejects_unsafe_relative_paths(
    registry: SkillRegistry, skills_dir: Path, filename: str
) -> None:
    """非法相对路径被跳过（invalid_path），不影响合法入口导入。"""
    result = await SkillMdImporter(registry, skills_dir=skills_dir).import_directory(
        [
            _make_upload("SKILL.md", _make_skill_md("safe-skill")),
            _make_upload(filename, b"payload"),
        ]
    )

    assert result["imported"] == [{"name": "safe-skill", "path": "."}]
    invalid = [item for item in result["skipped"] if item["reason"] == "invalid_path"]
    assert len(invalid) == 1
    assert "/" not in invalid[0]["name"]
    assert "\\" not in invalid[0]["name"]
    assert not (skills_dir / "evil.md").exists()


async def test_import_directory_rejects_too_deep_relative_path(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    """超过深度上限的相对路径被拒绝。"""
    deep = "/".join(["a"] * 12) + "/x.py"

    result = await SkillMdImporter(registry, skills_dir=skills_dir).import_directory(
        [
            _make_upload("SKILL.md", _make_skill_md("deep-skill")),
            _make_upload(deep, b"payload"),
        ]
    )

    assert result["imported"] == [{"name": "deep-skill", "path": "."}]
    assert any(item["reason"] == "invalid_path" for item in result["skipped"])


async def test_import_directory_skips_files_outside_resource_whitelist(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    """非白名单目录的资源被忽略（加载器不会读它们）。"""
    result = await SkillMdImporter(registry, skills_dir=skills_dir).import_directory(
        [
            _make_upload("SKILL.md", _make_skill_md("whitelist")),
            _make_upload("docs/readme.md", b"docs"),
        ]
    )

    assert result["imported"] == [{"name": "whitelist", "path": "."}]
    assert {"name": "docs/readme.md", "reason": "resource_dir_not_allowed"} in result["skipped"]
    assert not (skills_dir / "whitelist" / "docs").exists()


async def test_import_directory_skips_hidden_paths(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    """隐藏路径段被拒绝。"""
    result = await SkillMdImporter(registry, skills_dir=skills_dir).import_directory(
        [
            _make_upload("SKILL.md", _make_skill_md("hidden-skill")),
            _make_upload("scripts/.secret.py", b"secret"),
        ]
    )

    assert result["imported"] == [{"name": "hidden-skill", "path": "."}]
    assert {"name": "scripts/.secret.py", "reason": "hidden_path_rejected"} in result["skipped"]
    assert not (skills_dir / "hidden-skill" / "scripts" / ".secret.py").exists()


async def test_import_directory_rejects_single_segment_resource_name(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    """单段资源名（``scripts``）与同名资源目录冲突 → 明确跳过，不写盘。

    旧行为：它会一路走到写盘才以 ``write_failed`` 落进 skipped —— 用户看不出
    真实原因是"名字与目录撞了"。
    """
    result = await SkillMdImporter(registry, skills_dir=skills_dir).import_directory(
        [
            _make_upload("SKILL.md", _make_skill_md("shallow")),
            _make_upload("scripts", b"i am a file"),
            _make_upload("scripts/scan.py", b"print('hi')\n"),
        ]
    )

    assert result["imported"] == [{"name": "shallow", "path": "."}]
    assert {"name": "scripts", "reason": "resource_path_too_shallow"} in result["skipped"]
    skill_dir = skills_dir / "shallow"
    assert (skill_dir / "scripts" / "scan.py").is_file()


@pytest.mark.parametrize(
    "filename",
    [
        "scripts/nul",
        "scripts/COM1.txt",
        "references/aux.md",
        "assets/LPT9.png",
    ],
)
async def test_import_directory_rejects_windows_reserved_device_names(
    registry: SkillRegistry, skills_dir: Path, filename: str
) -> None:
    """Windows 保留设备名在导入阶段被拒绝（Win7 安装包是受支持平台）。

    ``NUL`` / ``COM1`` 这类名字在 Windows 上带扩展名也无法创建普通文件，
    与其到写盘时失败，不如在路径解析阶段直接判掉。
    """
    result = await SkillMdImporter(registry, skills_dir=skills_dir).import_directory(
        [
            _make_upload("SKILL.md", _make_skill_md("reserved")),
            _make_upload(filename, b"payload"),
        ]
    )

    assert result["imported"] == [{"name": "reserved", "path": "."}]
    invalid = [item for item in result["skipped"] if item["reason"] == "invalid_path"]
    assert len(invalid) == 1
    assert not (skills_dir / "reserved" / "scripts" / "nul").exists()


async def test_import_directory_rejects_symlinked_resource_dir(
    registry: SkillRegistry, skills_dir: Path, tmp_path: Path
) -> None:
    """资源目录是 symlink → 拒绝写入，不落到 symlink 目标。"""
    outside = tmp_path / "outside"
    outside.mkdir()
    skill_dir = skills_dir / "sym-skill"
    skill_dir.mkdir()
    try:
        (skill_dir / "scripts").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("当前环境无 symlink 特权")

    result = await SkillMdImporter(registry, skills_dir=skills_dir).import_directory(
        [
            _make_upload("SKILL.md", _make_skill_md("sym-skill")),
            _make_upload("scripts/evil.py", b"payload"),
        ]
    )

    assert result["imported"] == [{"name": "sym-skill", "path": "."}]
    assert {"name": "scripts/evil.py", "reason": "write_failed"} in result["skipped"]
    assert not (outside / "evil.py").exists()


# ===== 冲突 / 幂等 =====


async def test_import_directory_skips_builtin_conflict(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    """builtin 技能名永远胜。"""
    from backend.skills.base import BaseSkill, SkillResult, SkillSchema

    skill = mock.Mock(spec=BaseSkill)
    skill.name = "coder"
    skill.schema = SkillSchema(
        name="coder", description="builtin", triggers=[], parameters={}, examples=[]
    )
    skill.execute = mock.Mock(return_value=SkillResult(success=True, content=""))
    registry.register(skill)

    result = await SkillMdImporter(registry, skills_dir=skills_dir).import_directory(
        [_make_upload("SKILL.md", _make_skill_md("coder"))]
    )

    assert result["imported"] == []
    assert result["skipped"] == [{"name": "coder", "reason": "builtin_conflict"}]


async def test_import_directory_skips_already_existing_skill(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    """磁盘已有同名 SKILL.md → already_exists，不覆盖。"""
    (skills_dir / "dup-skill").mkdir()
    (skills_dir / "dup-skill" / "SKILL.md").write_bytes(_make_skill_md("dup-skill"))

    result = await SkillMdImporter(registry, skills_dir=skills_dir).import_directory(
        [_make_upload("SKILL.md", _make_skill_md("dup-skill"))]
    )

    assert result["imported"] == []
    assert result["skipped"] == [{"name": "dup-skill", "reason": "already_exists"}]


async def test_import_directory_rolls_back_directory_on_hot_reload_failure(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    """hot reload 失败 → 整个技能目录（含附属资源）回滚。"""
    with mock.patch(
        "backend.skills.skill_md.loader.SkillMdHotLoader._compute_hash",
        side_effect=OSError("simulated hash failure"),
    ):
        result = await SkillMdImporter(registry, skills_dir=skills_dir).import_directory(
            [
                _make_upload("SKILL.md", _make_skill_md("rollback")),
                _make_upload("scripts/scan.py", b"print('hi')\n"),
            ]
        )

    assert result["imported"] == []
    assert {"name": "rollback", "reason": "hot_reload_failed"} in result["skipped"]
    assert not registry.exists("rollback")
    assert not (skills_dir / "rollback").exists()


# ===== 限额 =====


async def test_import_directory_rejects_batches_over_file_count_limit(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    from backend.skills.skill_md.importer import MAX_IMPORT_FILES

    files = [_make_upload(f"scripts/f{i}.py", b"x") for i in range(MAX_IMPORT_FILES + 1)]
    result = await SkillMdImporter(registry, skills_dir=skills_dir).import_directory(files)

    assert result["imported"] == []
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["reason"].startswith("batch_too_many_files")


async def test_import_directory_skips_oversized_file(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    """超过单文件 1MB 上限的资源被跳过，入口仍可导入。"""
    from backend.skills.skill_md.importer import MAX_FILE_SIZE_BYTES

    result = await SkillMdImporter(registry, skills_dir=skills_dir).import_directory(
        [
            _make_upload("SKILL.md", _make_skill_md("oversized")),
            _make_upload("scripts/big.py", b"x" * (MAX_FILE_SIZE_BYTES + 1)),
        ]
    )

    assert result["imported"] == [{"name": "oversized", "path": "."}]
    assert any(
        item["reason"].startswith("file_too_large") for item in result["skipped"]
    )
    assert not (skills_dir / "oversized" / "scripts" / "big.py").exists()


async def test_import_directory_skips_read_failure(
    registry: SkillRegistry, skills_dir: Path
) -> None:
    """读取失败的上传 → read_failed，入口仍可导入。"""
    broken = mock.AsyncMock()
    broken.filename = "scripts/broken.py"
    broken.read = mock.AsyncMock(side_effect=OSError("read failed"))

    result = await SkillMdImporter(registry, skills_dir=skills_dir).import_directory(
        [
            _make_upload("SKILL.md", _make_skill_md("read-fail")),
            broken,
        ]
    )

    assert result["imported"] == [{"name": "read-fail", "path": "."}]
    assert {"name": "scripts/broken.py", "reason": "read_failed"} in result["skipped"]
