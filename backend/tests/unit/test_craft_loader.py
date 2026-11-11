"""Tests for CraftRuleRegistry and craft rule parsing."""
from __future__ import annotations

from pathlib import Path

from backend.design.craft_loader import CraftRuleRegistry, _parse_craft_md

_RULE_TEMPLATE = """---
id: {rule_id}
name: {name}
description: {description}
applies_to: {applies_to}
priority: {priority}
---

# {name}

Body of the {rule_id} rule.
"""


def _write_rule(
    craft_dir: Path,
    rule_id: str,
    *,
    name: str = "Rule",
    applies_to: str = "both",
    priority: int = 1,
    description: str = "A rule",
) -> Path:
    craft_dir.mkdir(parents=True, exist_ok=True)
    path = craft_dir / f"{rule_id}.md"
    path.write_text(
        _RULE_TEMPLATE.format(
            rule_id=rule_id,
            name=name,
            description=description,
            applies_to=applies_to,
            priority=priority,
        ),
        encoding="utf-8",
    )
    return path


def test_parse_craft_md_extracts_frontmatter():
    text = _RULE_TEMPLATE.format(
        rule_id="demo-rule",
        name="Demo Rule",
        description="Demo description",
        applies_to="deck",
        priority=2,
    )
    rule = _parse_craft_md(text, fallback_id="fallback")

    assert rule.id == "demo-rule"
    assert rule.name == "Demo Rule"
    assert rule.description == "Demo description"
    assert rule.applies_to == "deck"
    assert rule.priority == 2
    assert "Body of the demo-rule rule." in rule.content
    assert "---" not in rule.content


def test_parse_craft_md_without_frontmatter_uses_fallback():
    rule = _parse_craft_md("# No frontmatter here", fallback_id="bare")

    assert rule.id == "bare"
    assert rule.applies_to == "both"
    assert rule.priority == 99
    assert rule.content == "# No frontmatter here"


def test_parse_craft_md_malformed_priority_falls_back_to_99():
    text = _RULE_TEMPLATE.format(
        rule_id="bad-priority",
        name="Bad Priority",
        description="x",
        applies_to="both",
        priority="high",
    )
    rule = _parse_craft_md(text, fallback_id="fallback")

    assert rule.priority == 99


def test_parse_craft_md_accepts_quoted_priority():
    text = _RULE_TEMPLATE.format(
        rule_id="quoted",
        name="Quoted",
        description="x",
        applies_to="both",
        priority='"2"',
    )
    rule = _parse_craft_md(text, fallback_id="fallback")

    assert rule.priority == 2


def test_parse_craft_md_strips_duplicate_h1():
    text = _RULE_TEMPLATE.format(
        rule_id="dup-h1",
        name="Dup H1",
        description="x",
        applies_to="both",
        priority=1,
    )
    rule = _parse_craft_md(text, fallback_id="fallback")

    assert not rule.content.lstrip().startswith("#")
    assert "Body of the dup-h1 rule." in rule.content


def test_parse_craft_md_empty_frontmatter():
    rule = _parse_craft_md("---\n---\nBody text here", fallback_id="empty")

    assert rule.id == "empty"
    assert "Body text here" in rule.content
    assert "---" not in rule.content


def test_registry_skips_unreadable_file(tmp_path):
    craft_dir = tmp_path / "craft"
    _write_rule(craft_dir, "good", priority=1)
    (craft_dir / "binary.md").write_bytes(b"\xff\xfe\x00broken")

    registry = CraftRuleRegistry(tmp_path)

    assert [r.id for r in registry.list_rules()] == ["good"]


def test_registry_dedupes_by_rule_id(tmp_path):
    craft_dir = tmp_path / "craft"
    _write_rule(craft_dir, "a", name="First", priority=0)
    # The frontmatter id wins over the filename stem.
    (craft_dir / "b.md").write_text(
        _RULE_TEMPLATE.format(
            rule_id="a",
            name="Second",
            description="dup",
            applies_to="both",
            priority=1,
        ),
        encoding="utf-8",
    )

    registry = CraftRuleRegistry(tmp_path)
    rules = registry.list_rules()

    assert len(rules) == 1
    assert rules[0].id == "a"


def test_registry_lists_rules_sorted_by_priority(tmp_path):
    craft_dir = tmp_path / "craft"
    _write_rule(craft_dir, "late", priority=9)
    _write_rule(craft_dir, "early", priority=0)
    _write_rule(craft_dir, "middle", priority=3)

    registry = CraftRuleRegistry(tmp_path)
    rules = registry.list_rules()

    assert [r.id for r in rules] == ["early", "middle", "late"]


def test_registry_missing_craft_dir_returns_empty(tmp_path):
    registry = CraftRuleRegistry(tmp_path)

    assert registry.list_rules() == []


def test_rules_for_kind_filters_by_applies_to(tmp_path):
    craft_dir = tmp_path / "craft"
    _write_rule(craft_dir, "universal", applies_to="both", priority=0)
    _write_rule(craft_dir, "deck-only", applies_to="deck", priority=1)
    _write_rule(craft_dir, "proto-only", applies_to="prototype", priority=2)

    registry = CraftRuleRegistry(tmp_path)

    deck_ids = [r.id for r in registry.rules_for_kind("deck")]
    proto_ids = [r.id for r in registry.rules_for_kind("prototype")]

    assert deck_ids == ["universal", "deck-only"]
    assert proto_ids == ["universal", "proto-only"]


def test_registry_caches_parsed_rules(tmp_path):
    craft_dir = tmp_path / "craft"
    _write_rule(craft_dir, "cached")

    registry = CraftRuleRegistry(tmp_path)
    first = registry.list_rules()[0]

    # Mutate the file on disk; cache should keep returning the parsed copy.
    (craft_dir / "cached.md").write_text(
        _RULE_TEMPLATE.format(
            rule_id="cached",
            name="Changed",
            description="changed",
            applies_to="both",
            priority=1,
        ),
        encoding="utf-8",
    )
    second = registry.list_rules()[0]

    assert first.name == second.name == "Rule"
