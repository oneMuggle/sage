# ruff: noqa: UP006, UP007, UP035
"""R86 static plugin index tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from backend.plugins.index_catalog import (
    PluginIndex,
    PluginIndexEntry,
    PluginSignature,
    PluginSource,
    PluginSourceKind,
    build_plugin_index,
    load_plugin_index,
    search_plugin_index,
    validate_plugin_index,
    write_plugin_index,
)
from backend.plugins.scaffold import ScaffoldOptions, scaffold_plugin
from backend.plugins.scaffold_templates import PluginEcosystemError

GENERATED_AT = "2026-10-21T00:00:00Z"


def _plugin(tmp_path: Path, name: str = "acme-echo") -> Path:
    root = tmp_path / name
    scaffold_plugin(
        ScaffoldOptions(
            name=name,
            output_dir=root,
            author="Ada",
            description="Echo utilities for Sage.",
        )
    )
    return root


def _local_index(tmp_path: Path) -> PluginIndex:
    root = _plugin(tmp_path)
    return build_plugin_index(
        [root],
        base_dir=tmp_path,
        generated_at=GENERATED_AT,
    ).index


def test_build_write_load_and_local_validate_local_index(tmp_path: Path) -> None:
    index = _local_index(tmp_path)
    output = write_plugin_index(index, tmp_path / "index.json")

    loaded = load_plugin_index(output)
    validation = validate_plugin_index(output, check_local=True)

    assert loaded.generated_at == GENERATED_AT
    assert loaded.plugins[0].source.kind == PluginSourceKind.LOCAL
    assert loaded.plugins[0].source.path == "acme-echo"
    assert loaded.plugins[0].compatibility.sage == ">=0.4.0"
    assert loaded.plugins[0].compatibility.win7.value == "unknown"
    assert validation.ok, validation.to_dict()


def test_build_git_index_records_checkout_subdir(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    root = repo / "examples" / "acme-echo"
    scaffold_plugin(ScaffoldOptions(name="acme-echo", output_dir=root))

    index = build_plugin_index(
        [root],
        source_kind="git",
        source_url="https://example.com/plugins.git",
        source_ref="main",
        base_dir=repo,
        generated_at=GENERATED_AT,
    ).index

    entry = index.plugins[0]
    assert entry.source.kind == PluginSourceKind.GIT
    assert entry.source.subdir == "examples/acme-echo"
    assert validate_plugin_index(index, check_local=True, base_dir=repo).ok


def test_checked_in_index_matches_hello_tool_example() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    index_path = repo_root / "plugins" / "index.json"

    validation = validate_plugin_index(
        index_path,
        check_local=True,
        base_dir=repo_root,
    )

    assert validation.ok, validation.to_dict()
    assert validation.index is not None
    results = search_plugin_index(validation.index, "hello", capability_type="tool")
    assert [result["name"] for result in results] == ["hello-tool"]


def test_index_rejects_duplicates_and_manifest_identity_mismatch(
    tmp_path: Path,
) -> None:
    entry = _local_index(tmp_path).plugins[0]

    with pytest.raises(ValueError, match="duplicate plugin index entry"):
        PluginIndex(plugins=[entry, entry])

    payload: Dict[str, Any] = entry.to_dict()
    payload["name"] = "different"
    with pytest.raises(ValueError, match="must match its manifest"):
        PluginIndexEntry(**payload)


def test_archive_source_requires_https_and_sha256() -> None:
    with pytest.raises(ValueError, match="must be HTTPS"):
        PluginSource(
            kind=PluginSourceKind.ARCHIVE,
            url="http://example.com/plugin.zip",
            sha256="a" * 64,
        )

    with pytest.raises(ValueError, match="sha256"):
        PluginSource(
            kind=PluginSourceKind.ARCHIVE,
            url="https://example.com/plugin.zip",
            sha256="not-a-hash",
        )

    source = PluginSource(
        kind=PluginSourceKind.ARCHIVE,
        url="https://example.com/plugin.zip",
        sha256="b" * 64,
    )
    signature = PluginSignature(
        algorithm="minisign",
        url="https://example.com/plugin.zip.minisig",
        key_id="publisher-1",
    )
    assert source.sha256 == "b" * 64
    assert signature.key_id == "publisher-1"


def test_index_validation_rejects_sage_compatibility_below_manifest(
    tmp_path: Path,
) -> None:
    payload = _local_index(tmp_path).plugins[0].to_dict()
    payload["compatibility"]["sage"] = ">=0.3.0"
    entry = PluginIndexEntry(**payload)

    validation = validate_plugin_index(PluginIndex(plugins=[entry]))

    assert not validation.ok
    assert {issue.code for issue in validation.errors} == {
        "COMPATIBILITY_BELOW_MANIFEST"
    }


def test_local_index_validation_detects_manifest_drift(tmp_path: Path) -> None:
    root = _plugin(tmp_path)
    result = build_plugin_index(
        [root],
        base_dir=tmp_path,
        generated_at=GENERATED_AT,
    )
    output = write_plugin_index(result.index, tmp_path / "index.json")

    manifest_path = root / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["metadata"]["description"] = "Changed after indexing."
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    validation = validate_plugin_index(output, check_local=True)

    assert not validation.ok
    assert "INDEX_LOCAL_MANIFEST_DRIFT" in {
        issue.code for issue in validation.errors
    }


def test_search_filters_by_text_capability_and_permission(tmp_path: Path) -> None:
    payload = _local_index(tmp_path).plugins[0].to_dict()
    payload["manifest"]["capabilities"][0]["permissions"] = ["file:read"]
    entry = PluginIndexEntry(**payload)
    index = PluginIndex(plugins=[entry])

    assert search_plugin_index(index, "Ada echo")[0]["name"] == "acme-echo"
    assert search_plugin_index(index, capability_type="tool")
    assert search_plugin_index(index, capability_type="skill") == []
    assert search_plugin_index(index, permission="file:read")
    assert search_plugin_index(index, permission="network:write") == []

    with pytest.raises(PluginEcosystemError) as exc_info:
        search_plugin_index(index, capability_type="widget")
    assert exc_info.value.code == "UNKNOWN_CAPABILITY_TYPE"
