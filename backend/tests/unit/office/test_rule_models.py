from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.office.rule_models import (
    AuditFinding,
    AuditResult,
    Rule,
    RuleGroup,
    RulePack,
)


def _rule(**overrides: object) -> Rule:
    base = {
        "id": "rule-1",
        "name": "No passive voice",
        "type": "format",
        "severity": "warning",
        "scope": "body",
        "check_mode": "regex",
        "pattern": r"\bis\b.*\bbeen\b",
        "enabled": True,
        "group_id": "group-1",
    }
    base.update(overrides)
    return Rule(**base)


def test_rule_valid() -> None:
    rule = _rule()
    assert rule.check_mode == "regex"
    assert rule.description == ""


def test_rule_invalid_type() -> None:
    with pytest.raises(ValidationError):
        _rule(type="invalid_type")


def test_rule_invalid_check_mode() -> None:
    with pytest.raises(ValidationError):
        _rule(check_mode="llm")


def test_rule_group_with_rules() -> None:
    group = RuleGroup(
        id="group-1",
        name="Style",
        description="Style rules",
        rules=[_rule()],
        priority=10,
        builtin=False,
    )
    assert len(group.rules) == 1
    assert group.rules[0].group_id == "group-1"


def test_rule_pack_fields() -> None:
    pack = RulePack(
        name="团队规范",
        version="1.0.0",
        groups=[RuleGroup(id="g1", name="Style")],
        exported_at="2026-11-07T10:00:00Z",
        exported_by="tester",
    )
    assert pack.version == "1.0.0"
    assert pack.groups[0].builtin is False


def test_audit_result_defaults() -> None:
    finding = AuditFinding(
        rule_id="rule-1",
        rule_name="No passive",
        severity="warning",
        message="Passive voice detected",
        location="Paragraph 3",
        suggestion="Rewrite in active voice",
    )
    assert finding.severity == "warning"

    empty = AuditResult()
    assert empty.findings == []
    assert (empty.error_count, empty.warning_count, empty.info_count) == (0, 0, 0)
