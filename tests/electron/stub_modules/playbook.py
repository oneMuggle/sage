"""Playbook stub routes for Electron E2E (2026-11-01).

Serves just enough of the project + playbook surface for the governance page
to render a bound playbook and exercise the classification batch-move flow.

Routes:
- GET  /api/v1/projects
- GET  /api/v1/projects/{pid}/playbook
- POST /api/v1/projects/{pid}/playbook/actions/apply
- GET  /api/v1/projects/{pid}/milestones
- GET  /api/v1/projects/{pid}/workspace-overview
- GET  /api/v1/projects/{pid}/git-status
- GET  /api/v1/memory/project-profile

``ctx.state["playbook_actions"]`` records every applied action list so specs
can assert what the UI sent.
"""
from __future__ import annotations

from .common import send_json

PROJECT_ID = "p1"
NOW_MS = 1793500000000


def register_playbook_routes(registry: dict) -> None:
    registry[("GET", r"^/api/v1/projects$")] = _list_projects
    registry[("GET", r"^/api/v1/projects/(?P<pid>[^/]+)/playbook$")] = _current
    registry[
        ("POST", r"^/api/v1/projects/(?P<pid>[^/]+)/playbook/actions/apply$")
    ] = _apply_actions
    registry[("GET", r"^/api/v1/projects/(?P<pid>[^/]+)/milestones$")] = _milestones
    registry[
        ("GET", r"^/api/v1/projects/(?P<pid>[^/]+)/workspace-overview$")
    ] = _workspace_overview
    registry[("GET", r"^/api/v1/projects/(?P<pid>[^/]+)/git-status$")] = _git_status
    registry[("GET", r"^/api/v1/memory/project-profile$")] = _project_profile
    registry[("GET", r"^/api/v1/__stub/playbook-actions$")] = _debug_actions


def _list_projects(ctx, body, **_):
    send_json(
        ctx,
        200,
        {
            "projects": [
                {
                    "id": PROJECT_ID,
                    "path": "/tmp/sage-playbook-e2e",
                    "name": "E2E 科研项目",
                    "created_at": 1,
                    "last_opened_at": 1,
                    "description": "",
                    "session_count": 0,
                    "last_session_id": None,
                    "allowed_paths": [],
                    "project_type": "research",
                    "project_stage": "proposal",
                    "vcs_mode": "builtin",
                    "detected_type": "research",
                }
            ]
        },
    )


def _audit(undo: bool = False) -> dict:
    classification = [
        {
            "from": "开题报告.md",
            "to": "01_开题/开题报告.md",
            "artifact_id": "proposal_report",
            "label": "开题报告",
            "stage_id": "proposal",
            "reason": "开题报告应位于 01_开题/",
        }
    ]
    unclassified = [
        {
            "path": "论文初稿.docx",
            "suggested_to": "03_成果/论文初稿.docx",
            "confidence": 0.83,
            "reason": "文件名包含「论文」",
        }
    ]
    if undo:
        classification = []
        unclassified = []
    return {
        "playbook": {"id": "cn-research-grant", "name": "科研课题"},
        "current_stage": "proposal",
        "detected_stage": {"id": "proposal", "confidence": 0.9, "evidence": []},
        "stages": [
            {
                "id": "proposal",
                "label": "开题",
                "order": 1,
                "objective": "明确研究问题",
                "progress": 50,
                "required_total": 2,
                "required_done": 1,
                "remaining": [
                    {
                        "id": "literature_matrix",
                        "label": "文献对比矩阵",
                        "missing_action": None,
                    }
                ],
                "artifacts": [],
                "exit_criteria": [
                    {
                        "id": "literature_matrix_ready",
                        "label": "文献对比矩阵已建立",
                        "type": "manual",
                        "status": "pending",
                    }
                ],
            }
        ],
        "classification_suggestions": classification,
        "unclassified_files": unclassified,
        "undo_available": {"at": NOW_MS, "count": 2} if undo else None,
        "overall": {"required_total": 2, "required_done": 1, "progress": 50},
        "scanned_at": NOW_MS,
    }


def _current(ctx, body, **_):
    send_json(
        ctx,
        200,
        {
            "bound": True,
            "playbook": {
                "schema_version": "1.0",
                "id": "cn-research-grant",
                "name": "科研课题（开题 · 实施 · 结题）",
                "description": "E2E 规程",
                "applies_to": {"project_types": ["research"], "sub_types": []},
                "directory_layout": [
                    {"path": "01_开题", "required": True, "purpose": "开题材料"}
                ],
                "stages": [
                    {
                        "id": "proposal",
                        "label": "开题",
                        "order": 1,
                        "objective": "明确研究问题",
                        "artifacts": [],
                        "exit_criteria": [],
                        "rules": [],
                        "recommended_milestones": [],
                    }
                ],
                "global_rules": [],
                "todos": [],
                "ai_guidance": {},
                "meta": {},
            },
            "source": "builtin:cn-research-grant",
            "version": 1,
            "state": {"current_stage": "proposal"},
            "audit": _audit(),
        },
    )


def _apply_actions(ctx, body, **_):
    actions = body.get("actions") or []
    if ctx.state is not None:
        ctx.state.setdefault("playbook_actions", []).append(actions)
    action_types = [item.get("type") for item in actions if isinstance(item, dict)]
    undo = "undo_last_batch_move" in action_types
    batch = "batch_move" in action_types
    send_json(
        ctx,
        200,
        {
            "applied": [item for item in action_types if item],
            "skipped": [],
            "errors": [],
            "checkpoint_created": True,
            "audit": _audit(undo=batch and not undo),
        },
    )


def _milestones(ctx, body, **_):
    send_json(ctx, 200, {"milestones": []})


def _workspace_overview(ctx, body, **_):
    send_json(
        ctx,
        200,
        {
            "project_id": PROJECT_ID,
            "has_sage_md": False,
            "has_hooks_json": False,
            "checkpoint_count": 0,
            "latest_checkpoint_at": None,
            "recent_checkpoints": [],
            "coding_indicators": [],
            "office_deliverables": [],
            "research_artifacts": [],
            "directory_summary": [],
        },
    )


def _git_status(ctx, body, **_):
    send_json(
        ctx,
        200,
        {
            "is_repo": False,
            "modified_files": [],
            "staged_files": [],
            "untracked_files": [],
            "recent_commits": [],
        },
    )


def _project_profile(ctx, body, **_):
    send_json(
        ctx,
        200,
        {
            "project_key": "/tmp/sage-playbook-e2e",
            "items": [],
            "categories": [],
            "snapshot": "",
        },
    )


def _debug_actions(ctx, body, **_):
    send_json(
        ctx,
        200,
        {"actions": (ctx.state or {}).get("playbook_actions", [])},
    )
