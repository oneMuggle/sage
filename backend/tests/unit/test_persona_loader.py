# mypy: disable-error-code="no-untyped-def,attr-defined"
"""PersonaLoader 单测（A5 — Persona 声明式 Markdown manifest）。

覆盖 backend.adapters.out.skill.persona_loader:
- parse_manifest: 正常路径 / 必填字段 / 非法值 / frontmatter 畸形 / BOM
- 内置 personas（ops / coder / researcher）全量解析回归
- discover_persona_dirs: env var / ~/.sage/personas 优先级
- PersonaLoader: 目录扫描 / 冲突优先级 / 热加载（新增 / 变更 / 删除 / id 迁移）
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import pytest

_IS_WINDOWS = sys.platform == "win32"

from backend.adapters.out.skill.persona_loader import (
    PersonaLoader,
    PersonaManifestError,
    builtin_personas_dir,
    discover_persona_dirs,
    load_manifest_file,
    parse_manifest,
)

pytestmark = pytest.mark.unit


# =====================================================================
# helpers
# =====================================================================


def _manifest_text(
    *,
    persona_id: str = "alpha",
    name: str = "Alpha Persona",
    extra: str = "",
    body: str = "You are the Alpha persona.\n",
) -> str:
    """构造一份合法的 persona manifest 文本。"""
    return (
        f"---\n"
        f"id: {persona_id}\n"
        f"name: {name}\n"
        f"{extra}"
        f"---\n"
        f"{body}"
    )


def _write_persona(
    parent: Path,
    stem: str,
    *,
    persona_id: Optional[str] = None,
    extra: str = "",
    body: str = "You are a test persona.\n",
) -> Path:
    """在 parent/<stem>.md 写一份 manifest，返回路径。"""
    parent.mkdir(parents=True, exist_ok=True)
    fm_id = f"id: {persona_id}\n" if persona_id else ""
    path = parent / f"{stem}.md"
    path.write_text(
        f"---\n{fm_id}name: {stem} persona\n{extra}---\n{body}",
        encoding="utf-8",
    )
    return path


# =====================================================================
# parse_manifest — 正常路径
# =====================================================================


def test_parse_full_manifest_extracts_all_fields():
    text = _manifest_text(
        extra=(
            "icon: wrench\n"
            "tagline: one-liner\n"
            "description: longer description\n"
            "tools: [terminal, read_file, write_file]\n"
            "connectors: true\n"
            "recommended_models: [claude-sonnet-4-5, gpt-4-1]\n"
            "default_mode: prompt\n"
        ),
        body="You are the Ops persona.\n\nBe careful.\n",
    )
    manifest = parse_manifest(text, source="mem://test")

    assert manifest.id == "alpha"
    assert manifest.name == "Alpha Persona"
    assert manifest.icon == "wrench"
    assert manifest.tagline == "one-liner"
    assert manifest.description == "longer description"
    assert manifest.tools == ("terminal", "read_file", "write_file")
    assert manifest.connectors is True
    assert manifest.recommended_models == ("claude-sonnet-4-5", "gpt-4-1")
    assert manifest.default_mode == "prompt"
    assert manifest.system_prompt == "You are the Ops persona.\n\nBe careful."
    assert manifest.source == "mem://test"
    assert manifest.builtin is False


def test_parse_minimal_manifest_applies_defaults():
    manifest = parse_manifest(_manifest_text())

    assert manifest.id == "alpha"
    assert manifest.icon == ""
    assert manifest.tools == ()
    assert manifest.connectors is False
    assert manifest.recommended_models == ()
    # 缺省模式对齐全局默认（settings 默认 workspace_write）
    assert manifest.default_mode == "workspace_write"


def test_parse_derives_id_from_fallback_filename():
    text = "---\nname: No Id Persona\n---\nBody.\n"
    manifest = parse_manifest(text, fallback_id="My Persona")

    assert manifest.id == "my-persona"


def test_parse_tools_accepts_comma_separated_string():
    text = _manifest_text(extra="tools: terminal, read_file ,write_file\n")
    manifest = parse_manifest(text)

    assert manifest.tools == ("terminal", "read_file", "write_file")


def test_parse_mode_is_case_insensitive():
    text = _manifest_text(extra="default_mode: FULL_ACCESS\n")
    manifest = parse_manifest(text)

    assert manifest.default_mode == "full_access"


def test_parse_strips_utf8_bom():
    text = "\ufeff" + _manifest_text()
    manifest = parse_manifest(text)

    assert manifest.id == "alpha"


def test_parse_builtin_flag_propagates():
    manifest = parse_manifest(_manifest_text(), builtin=True)

    assert manifest.builtin is True


def test_parse_empty_optional_values_stay_empty_not_null():
    # `icon:` 后为空 → YAML None；必须兜底为空串，不能变成字面量 "null"
    text = _manifest_text(extra="icon:\ntagline:\ndescription:\n")
    manifest = parse_manifest(text)

    assert manifest.icon == ""
    assert manifest.tagline == ""
    assert manifest.description == ""


def test_parse_blank_default_mode_falls_back_to_default():
    text = _manifest_text(extra="default_mode:\n")
    manifest = parse_manifest(text)

    assert manifest.default_mode == "workspace_write"


# =====================================================================
# parse_manifest — 失败路径
# =====================================================================


def test_parse_rejects_missing_frontmatter():
    with pytest.raises(PersonaManifestError, match="frontmatter"):
        parse_manifest("Just a body, no fence.\n")


def test_parse_rejects_unterminated_frontmatter():
    with pytest.raises(PersonaManifestError, match="unterminated"):
        parse_manifest("---\nid: alpha\nname: Alpha\n")


def test_parse_rejects_invalid_yaml():
    with pytest.raises(PersonaManifestError, match="invalid YAML"):
        parse_manifest("---\nid: [unclosed\n---\nBody.\n")


def test_parse_rejects_non_mapping_frontmatter():
    with pytest.raises(PersonaManifestError, match="mapping"):
        parse_manifest("---\n- a\n- b\n---\nBody.\n")


@pytest.mark.parametrize(
    "bad_id",
    ["Alpha", "../evil", "a/b", "-leading-dash", "", "x" * 65],
    ids=["uppercase", "traversal", "slash", "leading-dash", "empty-ish", "too-long"],
)
def test_parse_rejects_invalid_explicit_id(bad_id):
    # 空字符串 id 会走 fallback 派生路径，这里用 fallback=None 保证报错
    text = f"---\nid: '{bad_id}'\nname: Bad\n---\nBody.\n"
    with pytest.raises(PersonaManifestError):
        parse_manifest(text)


def test_parse_rejects_missing_id_without_fallback():
    with pytest.raises(PersonaManifestError, match="needs an `id`"):
        parse_manifest("---\nname: No Id\n---\nBody.\n")


def test_parse_rejects_missing_name():
    with pytest.raises(PersonaManifestError, match="name"):
        parse_manifest("---\nid: alpha\n---\nBody.\n")


def test_parse_rejects_blank_name():
    with pytest.raises(PersonaManifestError, match="name"):
        parse_manifest("---\nid: alpha\nname: '   '\n---\nBody.\n")


def test_parse_rejects_empty_body():
    with pytest.raises(PersonaManifestError, match="no body"):
        parse_manifest("---\nid: alpha\nname: Alpha\n---\n   \n")


def test_parse_rejects_unknown_default_mode():
    text = _manifest_text(extra="default_mode: turbo\n")
    with pytest.raises(PersonaManifestError, match="default_mode"):
        parse_manifest(text)


def test_parse_rejects_non_bool_connectors():
    text = _manifest_text(extra="connectors: [github]\n")
    with pytest.raises(PersonaManifestError, match="connectors"):
        parse_manifest(text)


def test_parse_rejects_wrong_type_tools():
    text = _manifest_text(extra="tools: 3\n")
    with pytest.raises(PersonaManifestError, match="tools"):
        parse_manifest(text)


def test_parse_rejects_non_string_tools_items():
    text = _manifest_text(extra="tools: [1, 2]\n")
    with pytest.raises(PersonaManifestError, match="strings"):
        parse_manifest(text)


# =====================================================================
# 内置 personas 回归（ops / coder / researcher）
# =====================================================================


def test_builtin_personas_all_parse_cleanly():
    personas_dir = builtin_personas_dir()
    manifests = {
        md.stem: load_manifest_file(md, builtin=True)
        for md in sorted(personas_dir.glob("*.md"))
    }

    assert set(manifests) == {"ops", "coder", "researcher"}
    for manifest in manifests.values():
        assert manifest.builtin is True
        assert manifest.system_prompt
        assert manifest.tools  # 每个内置 persona 都声明了工具
        assert manifest.default_mode in {
            "read_only",
            "workspace_write",
            "prompt",
            "full_access",
        }


def test_builtin_ops_manifest_declares_ops_capabilities():
    manifest = load_manifest_file(builtin_personas_dir() / "ops.md", builtin=True)

    assert manifest.id == "ops"
    assert "terminal" in manifest.tools
    assert manifest.connectors is True
    assert manifest.recommended_models


# =====================================================================
# discover_persona_dirs
# =====================================================================


def test_discover_dirs_respects_env_var(tmp_path, monkeypatch):
    env_dir = tmp_path / "env-personas"
    env_dir.mkdir()
    monkeypatch.setenv("SAGE_PERSONAS_DIR", str(env_dir))
    monkeypatch.setenv("HOME", str(tmp_path))  # ~/.sage/personas 不存在

    result = discover_persona_dirs()

    assert result == [env_dir]


def test_discover_dirs_includes_home_sage_personas(tmp_path, monkeypatch):
    home_personas = tmp_path / ".sage" / "personas"
    home_personas.mkdir(parents=True)
    monkeypatch.setenv("SAGE_PERSONAS_DIR", "")
    monkeypatch.setenv("HOME", str(tmp_path))

    result = discover_persona_dirs()

    assert home_personas in result


def test_discover_dirs_empty_when_nothing_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("SAGE_PERSONAS_DIR", "")
    monkeypatch.setenv("HOME", str(tmp_path))

    assert discover_persona_dirs() == []


# =====================================================================
# PersonaLoader — 扫描
# =====================================================================


def test_scan_loads_manifests_from_dirs(tmp_path):
    _write_persona(tmp_path, "alpha")
    _write_persona(tmp_path, "beta", persona_id="beta")
    loader = PersonaLoader(dirs=[tmp_path], include_builtin=False)

    result = loader.scan_and_load()

    assert result.added == 2
    assert result.skipped == 0
    assert set(loader.ids()) == {"alpha", "beta"}
    assert loader.get("alpha").name == "alpha persona"


def test_scan_skips_hidden_and_non_md_files(tmp_path):
    _write_persona(tmp_path, "visible")
    (tmp_path / ".hidden.md").write_text(_manifest_text(persona_id="hidden"), encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not a manifest", encoding="utf-8")
    loader = PersonaLoader(dirs=[tmp_path], include_builtin=False)

    loader.scan_and_load()

    assert loader.ids() == ["visible"]


def test_scan_skips_invalid_manifest_but_loads_others(tmp_path):
    _write_persona(tmp_path, "good")
    (tmp_path / "bad.md").write_text("no frontmatter here\n", encoding="utf-8")
    loader = PersonaLoader(dirs=[tmp_path], include_builtin=False)

    result = loader.scan_and_load()

    assert result.added == 1
    assert result.skipped == 1
    assert loader.ids() == ["good"]


def test_scan_skips_non_utf8_manifest_but_loads_others(tmp_path):
    # UTF-16/二进制内容伪装成 .md：不能炸掉整轮扫描
    _write_persona(tmp_path, "good")
    (tmp_path / "binary.md").write_bytes(b"\xff\xfe-\x00-\x00-\x00garbage")
    loader = PersonaLoader(dirs=[tmp_path], include_builtin=False)

    result = loader.scan_and_load()

    assert result.added == 1
    assert result.skipped == 1
    assert loader.ids() == ["good"]


@pytest.mark.skipif(_IS_WINDOWS, reason="POSIX permission bits only")
def test_scan_skips_unreadable_manifest_but_loads_others(tmp_path):
    _write_persona(tmp_path, "good")
    locked = _write_persona(tmp_path, "locked")
    locked.chmod(0)
    loader = PersonaLoader(dirs=[tmp_path], include_builtin=False)
    try:
        result = loader.scan_and_load()
    finally:
        locked.chmod(0o644)  # 恢复权限，保证 tmp_path 清理不被卡住

    assert result.added == 1
    assert result.skipped == 1
    assert loader.ids() == ["good"]


@pytest.mark.skipif(_IS_WINDOWS, reason="POSIX permission bits only")
def test_rescan_removes_persona_whose_file_became_unreadable(tmp_path):
    path = _write_persona(tmp_path, "alpha")
    loader = PersonaLoader(dirs=[tmp_path], include_builtin=False)
    loader.scan_and_load()

    path.chmod(0)
    try:
        result = loader.scan_and_load()
    finally:
        path.chmod(0o644)

    assert result.removed == 1
    assert loader.get("alpha") is None


def test_scan_id_collision_first_directory_wins(tmp_path):
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    _write_persona(dir_a, "dup", persona_id="dup", body="From dir A.\n")
    _write_persona(dir_b, "dup", persona_id="dup", body="From dir B.\n")
    loader = PersonaLoader(dirs=[dir_a, dir_b], include_builtin=False)

    result = loader.scan_and_load()

    assert result.added == 1
    assert result.skipped == 1
    assert loader.get("dup").system_prompt == "From dir A."


def test_scan_builtin_wins_over_user_dir(tmp_path):
    # 用户目录试图覆盖内置 ops —— builtin 永远先扫描，用户版 skip
    _write_persona(tmp_path, "ops", persona_id="ops", body="User override.\n")
    loader = PersonaLoader(dirs=[tmp_path], include_builtin=True)

    loader.scan_and_load()

    ops = loader.get("ops")
    assert ops.builtin is True
    assert ops.system_prompt != "User override."


def test_scan_missing_dir_is_noop(tmp_path):
    loader = PersonaLoader(dirs=[tmp_path / "does-not-exist"], include_builtin=False)

    result = loader.scan_and_load()

    assert result.added == 0
    assert loader.ids() == []


def test_default_loader_loads_builtin_personas(tmp_path):
    # dirs=[] → 无用户目录，仅 builtin
    loader = PersonaLoader(dirs=[])

    loader.scan_and_load()

    assert set(loader.ids()) == {"ops", "coder", "researcher"}


# =====================================================================
# PersonaLoader — 热加载
# =====================================================================


def test_hot_reload_detects_content_change(tmp_path):
    path = _write_persona(tmp_path, "alpha", body="Old prompt.\n")
    loader = PersonaLoader(dirs=[tmp_path], include_builtin=False)
    loader.scan_and_load()

    path.write_text(
        _manifest_text(body="New prompt.\n"),
        encoding="utf-8",
    )
    result = loader.hot_reload()

    assert result.updated == 1
    assert result.added == 0
    assert loader.get("alpha").system_prompt == "New prompt."


def test_rescan_detects_new_file(tmp_path):
    _write_persona(tmp_path, "alpha")
    loader = PersonaLoader(dirs=[tmp_path], include_builtin=False)
    loader.scan_and_load()

    _write_persona(tmp_path, "beta", persona_id="beta")
    result = loader.scan_and_load()

    assert result.added == 1
    assert set(loader.ids()) == {"alpha", "beta"}


def test_rescan_detects_removed_file(tmp_path):
    path = _write_persona(tmp_path, "alpha")
    loader = PersonaLoader(dirs=[tmp_path], include_builtin=False)
    loader.scan_and_load()

    path.unlink()
    result = loader.scan_and_load()

    assert result.removed == 1
    assert loader.get("alpha") is None
    assert loader.ids() == []


def test_rescan_handles_id_change_as_remove_plus_add(tmp_path):
    path = _write_persona(tmp_path, "alpha", persona_id="alpha")
    loader = PersonaLoader(dirs=[tmp_path], include_builtin=False)
    loader.scan_and_load()

    # 同一文件把 id 从 alpha 改成 beta
    path.write_text(
        "---\nid: beta\nname: renamed\n---\nRenamed body.\n",
        encoding="utf-8",
    )
    result = loader.scan_and_load()

    assert result.removed == 1
    assert result.added == 1
    assert loader.get("alpha") is None
    assert loader.get("beta").name == "renamed"


def test_check_for_updates_lists_changed_ids(tmp_path):
    path = _write_persona(tmp_path, "alpha")
    _write_persona(tmp_path, "beta", persona_id="beta")
    loader = PersonaLoader(dirs=[tmp_path], include_builtin=False)
    loader.scan_and_load()
    assert loader.check_for_updates() == []

    path.write_text(_manifest_text(body="Changed.\n"), encoding="utf-8")

    assert loader.check_for_updates() == ["alpha"]


def test_check_for_updates_lists_deleted_ids(tmp_path):
    path = _write_persona(tmp_path, "alpha")
    loader = PersonaLoader(dirs=[tmp_path], include_builtin=False)
    loader.scan_and_load()

    path.unlink()

    assert loader.check_for_updates() == ["alpha"]


@pytest.mark.skipif(_IS_WINDOWS, reason="POSIX permission bits only")
def test_check_for_updates_flags_unreadable_as_stale(tmp_path):
    path = _write_persona(tmp_path, "alpha")
    loader = PersonaLoader(dirs=[tmp_path], include_builtin=False)
    loader.scan_and_load()

    path.chmod(0)
    try:
        assert loader.check_for_updates() == ["alpha"]
    finally:
        path.chmod(0o644)


def test_unchanged_rescan_reports_zero_events(tmp_path):
    _write_persona(tmp_path, "alpha")
    loader = PersonaLoader(dirs=[tmp_path], include_builtin=False)
    loader.scan_and_load()

    result = loader.scan_and_load()

    assert result.added == 0
    assert result.updated == 0
    assert result.removed == 0
    assert result.skipped == 0


# =====================================================================
# PersonaLoader — 查询
# =====================================================================


def test_get_unknown_id_returns_none(tmp_path):
    loader = PersonaLoader(dirs=[tmp_path], include_builtin=False)
    loader.scan_and_load()

    assert loader.get("nope") is None


def test_list_all_returns_manifests(tmp_path):
    _write_persona(tmp_path, "alpha")
    loader = PersonaLoader(dirs=[tmp_path], include_builtin=False)
    loader.scan_and_load()

    all_personas = loader.list_all()

    assert len(all_personas) == 1
    assert all_personas[0].id == "alpha"


def test_get_stats_reports_loader_state(tmp_path):
    _write_persona(tmp_path, "alpha")
    loader = PersonaLoader(dirs=[tmp_path], include_builtin=False)
    loader.scan_and_load()

    stats = loader.get_stats()

    assert stats["loaded_personas"] == 1
    assert stats["watched_files"] == 1
    assert stats["persona_dirs"] == [str(tmp_path)]
    assert stats["ids"] == ["alpha"]
