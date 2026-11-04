"""Unit tests for per-item playbook diff (2026-11-01)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from backend.services.playbook_diff import diff_playbooks
from backend.services.playbook_library import get_builtin


def _spec() -> Dict[str, Any]:
    spec = get_builtin("cn-research-grant")
    assert spec is not None
    return deepcopy(spec)


def _proposal(spec: Dict[str, Any]) -> Dict[str, Any]:
    return next(stage for stage in spec["stages"] if stage["id"] == "proposal")


def test_identical_specs_have_no_changes() -> None:
    spec = _spec()
    diff = diff_playbooks(spec, deepcopy(spec))
    assert diff["stages_added"] == []
    assert diff["stages_removed"] == []
    assert diff["stages_changed"] == []
    assert diff["directories_added"] == []
    assert diff["directories_removed"] == []
    assert diff["directories_changed"] == []
    assert diff["name_changed"] is False
    assert diff["description_changed"] is False
    assert diff["global_rules_added"] == []
    assert diff["global_rules_removed"] == []
    assert diff["stage_details"] == {}


def test_stage_items_are_diffed_individually() -> None:
    old = _spec()
    new = deepcopy(old)
    proposal = _proposal(new)
    proposal["artifacts"][0]["match"]["globs"] = ["**/开题报告*.md"]
    removed = proposal["artifacts"].pop(1)
    proposal["artifacts"].append(
        {
            "id": "data_management_plan",
            "label": "数据管理计划",
            "required": False,
            "match": {"globs": ["**/DMP*.md"]},
        }
    )
    proposal["rules"].append({"content": "新增规则：数据脱敏"})
    proposal["recommended_milestones"].append(
        {"title": "完成伦理审批", "due_offset_days": 30}
    )
    proposal["exit_criteria"].append(
        {"id": "dmp_ready", "label": "数据管理计划完成", "type": "manual"}
    )

    diff = diff_playbooks(old, new)
    assert diff["stages_changed"] == ["proposal"]
    details = diff["stage_details"]["proposal"]

    changed_ids = {item["id"]: item for item in details["artifacts_changed"]}
    assert "match" in changed_ids["proposal_report"]["fields"]
    assert {item["id"] for item in details["artifacts_added"]} == {"data_management_plan"}
    assert [item["id"] for item in details["artifacts_removed"]] == [removed["id"]]
    assert details["rules_added"] == ["新增规则：数据脱敏"]
    assert details["milestones_added"] == ["完成伦理审批"]
    assert [item["id"] for item in details["criteria_added"]] == ["dmp_ready"]
    assert details["has_changes"] is True


def test_criteria_changes_are_reported_by_field() -> None:
    old = _spec()
    new = deepcopy(old)
    proposal = _proposal(new)
    proposal["exit_criteria"][0]["label"] = "开题报告已通过评审"
    proposal["exit_criteria"][0]["artifact_id"] = "proposal_report"

    details = diff_playbooks(old, new)["stage_details"]["proposal"]
    changed = {item["id"]: item for item in details["criteria_changed"]}
    criterion_id = proposal["exit_criteria"][0]["id"]
    assert "label" in changed[criterion_id]["fields"]


def test_directory_global_rule_and_metadata_changes() -> None:
    old = _spec()
    new = deepcopy(old)
    new["name"] = "自定义科研规程"
    new["directory_layout"].append(
        {"path": "05_附录", "required": False, "purpose": "附录材料"}
    )
    new["directory_layout"][0]["purpose"] = "开题与立项材料"
    new["global_rules"].append({"content": "所有文件命名包含日期"})

    diff = diff_playbooks(old, new)
    assert diff["name_changed"] is True
    assert diff["description_changed"] is False
    assert diff["directories_added"] == ["05_附录"]
    assert diff["directories_changed"] == ["01_开题"]
    assert diff["global_rules_added"] == ["所有文件命名包含日期"]
    assert diff["stage_details"] == {}


def test_stage_added_and_removed() -> None:
    old = _spec()
    new = deepcopy(old)
    removed = new["stages"].pop()
    new["stages"].append(
        {
            "id": "archive",
            "label": "归档",
            "order": 4,
            "objective": "长期归档",
            "artifacts": [],
            "exit_criteria": [],
            "rules": [],
            "recommended_milestones": [],
        }
    )

    diff = diff_playbooks(old, new)
    assert diff["stages_added"] == ["archive"]
    assert diff["stages_removed"] == [removed["id"]]
    assert diff["stages_changed"] == []
