"""Unit tests for playbook spec normalization and built-in library (2026-10-31)."""

from __future__ import annotations

import pytest

from backend.services.playbook_library import (
    build_export_envelope,
    get_builtin,
    list_builtin,
    render_markdown_handbook,
    validate_import_envelope,
)
from backend.services.playbook_spec import (
    PlaybookValidationError,
    normalize_playbook,
    spec_hash,
)


def minimal_playbook(**overrides):
    spec = {
        "schema_version": "1.0",
        "id": "demo",
        "name": "示例规程",
        "applies_to": {"project_types": ["research"], "sub_types": []},
        "directory_layout": [
            {"path": "01_开题", "required": True, "purpose": "开题材料"}
        ],
        "stages": [
            {
                "id": "proposal",
                "label": "开题",
                "order": 1,
                "artifacts": [
                    {
                        "id": "proposal_report",
                        "label": "开题报告",
                        "required": True,
                        "match": {"globs": ["**/开题报告*.md"]},
                    }
                ],
                "exit_criteria": [],
                "rules": [],
                "recommended_milestones": [],
            }
        ],
        "global_rules": [],
        "todos": [],
        "ai_guidance": {},
        "meta": {"author": "t", "license": "CC-BY-4.0", "created_at": "2026-10-31"},
    }
    spec.update(overrides)
    return spec


def test_normalize_fills_defaults_and_rejects_unknown_version():
    spec = normalize_playbook(minimal_playbook())
    assert spec["stages"][0]["artifacts"][0]["match"]["min_count"] == 1
    with pytest.raises(PlaybookValidationError):
        normalize_playbook(minimal_playbook(schema_version="9.0"))


def test_normalize_rejects_path_traversal_and_absolute_paths():
    bad = minimal_playbook(
        directory_layout=[{"path": "../escape", "required": True}]
    )
    with pytest.raises(PlaybookValidationError):
        normalize_playbook(bad)

    bad = minimal_playbook(
        directory_layout=[{"path": "/abs/path", "required": True}]
    )
    with pytest.raises(PlaybookValidationError):
        normalize_playbook(bad)


def test_spec_hash_is_stable_and_order_independent():
    a = normalize_playbook(minimal_playbook())
    b = dict(reversed(list(a.items())))
    assert spec_hash(a) == spec_hash(normalize_playbook(b))


def test_builtin_library_has_research_and_coding():
    ids = {item["id"] for item in list_builtin()}
    assert {"cn-research-grant", "coding-project"} <= ids
    assert get_builtin("cn-research-grant")["stages"][0]["id"] == "proposal"


def test_markdown_and_export_envelope_round_trip():
    spec = get_builtin("cn-research-grant")
    md = render_markdown_handbook(spec)
    assert "开题" in md and "实施" in md
    envelope = build_export_envelope(spec, include_scaffold=True, app_version="0.6.0")
    parsed = validate_import_envelope(envelope)
    assert parsed["playbook"]["id"] == spec["id"]
    assert parsed["scaffold"]["directories"]
