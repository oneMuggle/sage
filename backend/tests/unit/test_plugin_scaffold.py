# ruff: noqa: UP006, UP007, UP035
"""R86 plugin scaffold, static validation, and dev smoke tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Set

import pytest

from backend.plugins.scaffold import (
    ScaffoldOptions,
    list_templates,
    run_plugin_dev,
    scaffold_plugin,
    validate_plugin_package,
)
from backend.plugins.scaffold_templates import PluginEcosystemError


def _codes(validation: object) -> Set[str]:
    return {issue.code for issue in validation.issues}  # type: ignore[attr-defined]


def _scaffold(
    tmp_path: Path,
    *,
    template: str = "tool",
    name: str = "acme-echo",
) -> Path:
    root = tmp_path / name
    result = scaffold_plugin(
        ScaffoldOptions(
            name=name,
            output_dir=root,
            template=template,
            author="Ada",
        )
    )
    return result.root


def _rewrite_manifest(root: Path, payload: dict) -> None:
    (root / "plugin.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def test_template_catalog_marks_only_tool_as_supported() -> None:
    templates = {item["name"]: item for item in list_templates()}

    assert list(templates) == ["tool", "hook", "mcp", "skill"]
    assert templates["tool"]["maturity"] == "supported"
    assert templates["hook"]["maturity"] == "preview"
    assert templates["mcp"]["capability_type"] == "mcp_server"
    assert templates["skill"]["capability_type"] == "skill"


def test_tool_scaffold_is_complete_and_strictly_valid(tmp_path: Path) -> None:
    root = _scaffold(tmp_path)

    for relative in [
        "plugin.json",
        "README.md",
        "handlers.py",
        "examples/request.json",
        "tests/test_plugin.py",
        ".github/workflows/plugin-ci.yml",
        ".gitignore",
    ]:
        assert (root / relative).is_file(), relative

    manifest = json.loads((root / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "acme-echo"
    assert manifest["capabilities"][0]["entry_point"] == "handlers:run"
    assert manifest["python_version"] == ">=3.8"

    validation = validate_plugin_package(root, strict=True)
    assert validation.ok
    assert validation.issues == ()
    assert validation.permissions == []


def test_scaffold_refuses_overwrite_but_force_preserves_extra_files(
    tmp_path: Path,
) -> None:
    root = _scaffold(tmp_path)
    readme = root / "README.md"
    readme.write_text("local edits\n", encoding="utf-8")
    extra = root / "extra.txt"
    extra.write_text("keep me\n", encoding="utf-8")

    with pytest.raises(PluginEcosystemError) as exc_info:
        scaffold_plugin(ScaffoldOptions(name="acme-echo", output_dir=root))
    assert exc_info.value.code == "PLUGIN_OUTPUT_EXISTS"
    assert readme.read_text(encoding="utf-8") == "local edits\n"

    scaffold_plugin(
        ScaffoldOptions(name="acme-echo", output_dir=root, force=True)
    )
    assert "local edits" not in readme.read_text(encoding="utf-8")
    assert extra.read_text(encoding="utf-8") == "keep me\n"


@pytest.mark.parametrize("template", ["hook", "mcp", "skill"])
def test_preview_templates_validate_with_runtime_warning(
    tmp_path: Path,
    template: str,
) -> None:
    root = _scaffold(tmp_path, template=template, name=f"acme-{template}")
    validation = validate_plugin_package(root)
    strict = validate_plugin_package(root, strict=True)

    assert validation.ok
    assert not strict.ok
    assert "RUNTIME_PREVIEW_ONLY" in _codes(validation)
    assert validation.manifest is not None
    entry_point = validation.manifest.capabilities[0].entry_point
    assert entry_point
    if template in {"mcp", "skill"}:
        assert (root / entry_point).is_file()


def test_validation_reports_missing_entry_and_permission_shape(
    tmp_path: Path,
) -> None:
    root = _scaffold(tmp_path)
    manifest = json.loads((root / "plugin.json").read_text(encoding="utf-8"))
    manifest["capabilities"][0]["entry_point"] = "missing_handlers:run"
    manifest["capabilities"][0]["permissions"] = ["FileRead", "custom:read"]
    _rewrite_manifest(root, manifest)

    validation = validate_plugin_package(root)

    assert not validation.ok
    assert "ENTRY_POINT_MODULE_NOT_FOUND" in _codes(validation)
    assert "INVALID_PERMISSION" in _codes(validation)
    assert "UNKNOWN_PERMISSION_SCOPE" in _codes(validation)


def test_validation_rejects_skill_entry_outside_plugin_root(tmp_path: Path) -> None:
    root = _scaffold(tmp_path, template="skill", name="acme-skill")
    manifest = json.loads((root / "plugin.json").read_text(encoding="utf-8"))
    manifest["capabilities"][0]["entry_point"] = "../outside/SKILL.md"
    _rewrite_manifest(root, manifest)

    validation = validate_plugin_package(root)

    assert not validation.ok
    assert "SKILL_ENTRY_OUTSIDE_ROOT" in _codes(validation)


def test_dev_smoke_runs_scaffolded_tool_out_of_process(tmp_path: Path) -> None:
    root = _scaffold(tmp_path)

    result = run_plugin_dev(
        root,
        arguments={"name": "Ada"},
        config={"greeting": "Hi"},
    )

    assert result.result == {
        "message": "Hi, Ada!",
        "plugin": "acme-echo",
        "template": "tool",
    }
    assert result.runtime["state"] == "active"
    assert result.runtime["running"] is True
    assert result.record["status"] == "enabled"


def test_checked_in_hello_tool_example_is_strictly_valid() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    root = repo_root / "examples" / "plugins" / "hello-tool"

    validation = validate_plugin_package(root, strict=True)

    assert validation.ok, validation.to_dict()
    assert validation.manifest is not None
    assert validation.manifest.name == "hello-tool"
