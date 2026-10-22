# ruff: noqa: UP006, UP007, UP035
"""R81：三层 harness 配置与四预设的机制单测。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

import pytest

from backend.application.kernel.harness_config import (
    PRESET_NAMES,
    PRESETS,
    HarnessConfig,
    HarnessConfigError,
    clear_harness_cache,
    default_harness_config,
    load_harness_config,
    presets_view,
    project_harness_path,
    resolved_view,
    select_bundles,
    user_harness_path,
)

KNOWN = ("shell", "browser", "office_core", "ask_user", "design")


@pytest.fixture(autouse=True)
def _clear_cache() -> Iterator[None]:
    clear_harness_cache()
    yield
    clear_harness_cache()


def _write_config(root: Path, text: str) -> Path:
    path = root / ".sage" / "harness.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_missing_files_mean_standard_with_no_warnings(tmp_path: Path) -> None:
    config = load_harness_config(
        workspace=tmp_path / "workspace",
        user_home=tmp_path / "home",
        environ={},
        known_bundles=KNOWN,
    )

    assert config.preset == "standard"
    assert config.bundle_overrides == {}
    assert config.flags == {}
    assert config.sources == ("builtin",)
    assert config.warnings == ()
    assert select_bundles(KNOWN, config) == KNOWN


def test_preset_catalog_shape() -> None:
    assert PRESET_NAMES == ("standard", "focus", "headless", "dev")
    assert PRESETS["standard"].excluded_bundles == ()
    assert PRESETS["focus"].excluded_bundles == (
        "office_core",
        "office_pdf",
        "office_template",
        "office_analysis",
        "office_journal",
        "office_quality",
        "browser",
        "multimodal",
        "design",
    )
    assert PRESETS["headless"].excluded_bundles == ("ask_user",)
    assert PRESETS["dev"].flag_values == {"dev": True}

    view = presets_view()
    assert [item["name"] for item in view] == list(PRESET_NAMES)
    assert view[1]["flags"] == {"context": "compact"}


def test_select_bundles_preserves_order_and_applies_overrides() -> None:
    config = HarnessConfig(
        preset="focus",
        bundle_overrides={"office_core": True, "shell": False},
        flags=dict(PRESETS["focus"].flag_values),
    )

    assert select_bundles(KNOWN, config) == ("office_core", "ask_user")
    assert config.skipped_reason("shell") == "override"
    assert config.skipped_reason("browser") == "preset"
    assert config.skipped_reason("ask_user") is None


def test_user_layer_loads_yaml(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    path = _write_config(
        home,
        "preset: focus\n"
        "bundles:\n"
        "  office_core: true\n"
        "  shell: false\n"
        "flags:\n"
        "  custom: enabled\n",
    )

    config = load_harness_config(
        workspace=workspace,
        user_home=home,
        environ={},
        known_bundles=KNOWN,
    )

    assert config.preset == "focus"
    assert config.bundle_overrides == {"office_core": True, "shell": False}
    assert config.flags == {"context": "compact", "custom": "enabled"}
    assert config.sources == ("builtin", str(path))
    assert config.warnings == ()


def test_project_layer_overrides_user_layer(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    user_path = _write_config(home, "preset: focus\nbundles:\n  browser: true\n")
    project_path = _write_config(
        workspace,
        "preset: headless\nbundles:\n  browser: false\n  ask_user: true\n",
    )

    config = load_harness_config(
        workspace=workspace,
        user_home=home,
        environ={},
        known_bundles=KNOWN,
    )

    assert config.preset == "headless"
    assert config.bundle_overrides == {"browser": False, "ask_user": True}
    assert config.flags == {"interactive": False}
    assert config.sources == ("builtin", str(user_path), str(project_path))
    assert select_bundles(KNOWN, config) == (
        "shell",
        "office_core",
        "ask_user",
        "design",
    )


def test_environment_preset_overrides_project_file(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    _write_config(workspace, "preset: headless\nflags:\n  owner: project\n")

    config = load_harness_config(
        workspace=workspace,
        user_home=home,
        environ={"SAGE_HARNESS_PRESET": "focus"},
        known_bundles=KNOWN,
    )

    assert config.preset == "focus"
    assert config.flags == {"context": "compact", "owner": "project"}
    assert config.sources[-1] == "env:SAGE_HARNESS_PRESET"


def test_patch_is_the_highest_layer(tmp_path: Path) -> None:
    config = load_harness_config(
        workspace=tmp_path / "workspace",
        user_home=tmp_path / "home",
        environ={"SAGE_HARNESS_PRESET": "focus"},
        patch={
            "preset": "dev",
            "bundles": {"browser": False},
            "flags": {"context": "verbose"},
        },
        known_bundles=KNOWN,
    )

    assert config.preset == "dev"
    assert config.bundle_overrides == {"browser": False}
    assert config.flags == {"dev": True, "context": "verbose"}
    assert config.sources == ("builtin", "env:SAGE_HARNESS_PRESET", "patch")


def test_empty_yaml_file_is_a_valid_source(tmp_path: Path) -> None:
    home = tmp_path / "home"
    path = _write_config(home, "")

    config = load_harness_config(
        workspace=tmp_path / "workspace",
        user_home=home,
        environ={},
    )

    assert config.preset == "standard"
    assert config.sources == ("builtin", str(path))
    assert config.warnings == ()


def test_unknown_preset_is_ignored_without_strict(tmp_path: Path) -> None:
    config = load_harness_config(
        workspace=tmp_path / "workspace",
        user_home=tmp_path / "home",
        environ={},
        patch={"preset": "turbo"},
    )

    assert config.preset == "standard"
    assert len(config.warnings) == 1
    assert "turbo" in config.warnings[0]


def test_unknown_preset_raises_in_strict_mode(tmp_path: Path) -> None:
    with pytest.raises(HarnessConfigError):
        load_harness_config(
            workspace=tmp_path / "workspace",
            user_home=tmp_path / "home",
            environ={},
            patch={"preset": "turbo"},
            strict=True,
        )


def test_unknown_bundle_is_dropped_with_warning(tmp_path: Path) -> None:
    config = load_harness_config(
        workspace=tmp_path / "workspace",
        user_home=tmp_path / "home",
        environ={},
        patch={"bundles": {"mystery": False, "shell": False}},
        known_bundles=KNOWN,
    )

    assert config.bundle_overrides == {"shell": False}
    assert len(config.warnings) == 1
    assert "mystery" in config.warnings[0]


def test_unknown_top_level_key_and_non_bool_are_warnings(tmp_path: Path) -> None:
    config = load_harness_config(
        workspace=tmp_path / "workspace",
        user_home=tmp_path / "home",
        environ={},
        patch={"surprise": True, "bundles": {"shell": "false"}},
        known_bundles=KNOWN,
    )

    assert config.bundle_overrides == {}
    assert len(config.warnings) == 2


def test_malformed_yaml_fails_open_or_strict(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_config(home, "preset: [focus\n")

    config = load_harness_config(
        workspace=tmp_path / "workspace",
        user_home=home,
        environ={},
    )
    assert config.preset == "standard"
    assert len(config.warnings) == 1

    with pytest.raises(HarnessConfigError):
        load_harness_config(
            workspace=tmp_path / "workspace",
            user_home=home,
            environ={},
            strict=True,
        )


def test_non_mapping_yaml_fails_open(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_config(home, "- just\n- a\n- list\n")

    config = load_harness_config(
        workspace=tmp_path / "workspace",
        user_home=home,
        environ={},
    )

    assert config.preset == "standard"
    assert len(config.warnings) == 1


def test_same_file_is_not_applied_twice(tmp_path: Path) -> None:
    root = tmp_path / "same"
    path = _write_config(root, "preset: dev\nsurprise: true\n")

    config = load_harness_config(
        workspace=root,
        user_home=root,
        environ={},
    )

    assert config.sources.count(str(path)) == 1
    assert len(config.warnings) == 1


def test_paths_honor_environment_overrides(tmp_path: Path) -> None:
    home = tmp_path / "env-home"
    workspace = tmp_path / "env-workspace"
    environ = {
        "SAGE_HARNESS_HOME": str(home),
        "SAGE_WORKSPACE": str(workspace),
    }

    assert user_harness_path(environ=environ) == home / ".sage" / "harness.yaml"
    assert project_harness_path(environ=environ) == workspace / ".sage" / "harness.yaml"


def test_mtime_cache_returns_copies_and_can_be_cleared(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    path = _write_config(home, "preset: focus\n")
    stat = path.stat()

    first = load_harness_config(workspace=workspace, user_home=home, environ={})
    first.preset = "dev"
    first.bundle_overrides["shell"] = False

    path.write_text("preset: headless\n", encoding="utf-8")
    os.utime(str(path), ns=(stat.st_atime_ns, stat.st_mtime_ns))
    second = load_harness_config(workspace=workspace, user_home=home, environ={})

    assert second.preset == "focus"
    assert second.bundle_overrides == {}

    clear_harness_cache()
    third = load_harness_config(workspace=workspace, user_home=home, environ={})
    assert third.preset == "headless"


def test_default_config_is_a_fresh_standard() -> None:
    first = default_harness_config()
    second = default_harness_config()
    first.bundle_overrides["shell"] = False

    assert second.preset == "standard"
    assert second.bundle_overrides == {}


def test_resolved_view_explains_selection() -> None:
    config = HarnessConfig(
        preset="headless",
        bundle_overrides={"shell": False, "ask_user": True},
        flags={"interactive": False},
        sources=("builtin", "patch"),
        warnings=("sample",),
    )

    view = resolved_view(config, KNOWN)

    assert view["preset"] == "headless"
    assert view["bundles"]["selected"] == ["browser", "office_core", "ask_user", "design"]
    assert view["bundles"]["skipped"] == [{"name": "shell", "reason": "override"}]
    assert view["sources"] == ["builtin", "patch"]
    assert view["warnings"] == ["sample"]
