from __future__ import annotations

from typing import Any

from backend.office.rule_conflicts import detect_conflicts
from backend.office.rule_models import Rule


def _rule(**overrides: Any) -> Rule:
    payload = {
        "id": "rule-1",
        "name": "规则一",
        "type": "terminology",
        "severity": "warning",
        "scope": "body",
        "check_mode": "regex",
        "pattern": "待定",
        "group_id": "group-1",
    }
    payload.update(overrides)
    return Rule(**payload)


def test_identical_regex_is_error() -> None:
    conflicts = detect_conflicts([_rule(id="r1", pattern="待定"), _rule(id="r2", pattern=" 待定 ")])
    assert len(conflicts) == 1
    assert conflicts[0].rule_ids == ["r1", "r2"]
    assert conflicts[0].severity == "error"


def test_substring_regex_is_warning() -> None:
    conflicts = detect_conflicts(
        [_rule(id="r1", pattern="待定"), _rule(id="r2", pattern="待定|暂缺")]
    )
    assert len(conflicts) == 1
    assert conflicts[0].severity == "warning"


def test_similar_ai_prompts_conflict() -> None:
    prompt = "检查正文是否使用了口语化表达"
    conflicts = detect_conflicts(
        [
            _rule(id="r1", check_mode="ai", pattern=None, ai_prompt=prompt),
            _rule(id="r2", check_mode="ai", pattern=None, ai_prompt=prompt + "，如口语词"),
        ]
    )
    assert len(conflicts) == 1
    assert conflicts[0].rule_ids == ["r1", "r2"]
    assert conflicts[0].severity == "warning"


def test_different_scope_or_mode_never_conflicts() -> None:
    rules = [
        _rule(id="r1", scope="body", pattern="待定"),
        _rule(id="r2", scope="heading", pattern="待定"),
        _rule(id="r3", scope="body", check_mode="ai", pattern=None, ai_prompt="待定"),
        _rule(id="r4", scope="body", pattern="待定", enabled=False),
    ]
    assert detect_conflicts(rules) == []


def test_distinct_rules_do_not_conflict() -> None:
    rules = [
        _rule(id="r1", pattern="待定"),
        _rule(id="r2", pattern="TODO"),
        _rule(id="r3", check_mode="ai", pattern=None, ai_prompt="检查错别字"),
        _rule(id="r4", check_mode="ai", pattern=None, ai_prompt="检查标点符号是否规范"),
    ]
    assert detect_conflicts(rules) == []
