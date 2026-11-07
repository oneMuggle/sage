# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容
"""四层规则聚合读接口（M3，2026-11-07）。

写入接口（POST/PATCH/DELETE）、AI patch、导入导出在 M4/M5/M6 追加到本模块。
`layer + rule_id` 走请求体/查询参数而不进路径：`constraint:<uuid>` 自带冒号。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from backend.data.database import make_with_db_lock
from backend.data.project_repo import Project, ProjectRepository
from backend.services.rules_registry import RulesRegistry

logger = logging.getLogger(__name__)

router = APIRouter(tags=["rules"])


def with_db_lock(func):  # noqa: ANN001 — 与 playbook_routes 同一装饰器工厂
    return make_with_db_lock(globals())(func)


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _project_or_404(project_id: str) -> Project:
    project = ProjectRepository().get(project_id)
    if project is None:
        raise _error(404, "project_not_found", "项目不存在")
    if not Path(project.path).is_dir():
        raise _error(410, "project_path_missing", "项目目录不存在或已被移动")
    return project


@router.get("/projects/{project_id}/rules")
@with_db_lock
def list_project_rules(project_id: str) -> Dict[str, Any]:
    """四层规则聚合列表（只读）。"""
    project = _project_or_404(project_id)
    entries = RulesRegistry().list_rules(project)
    return {"rules": [entry.to_dict() for entry in entries]}


@router.get("/projects/{project_id}/rules/effective")
@with_db_lock
def effective_project_rules(project_id: str) -> Dict[str, Any]:
    """注入顺序 + 冲突提示。"""
    project = _project_or_404(project_id)
    return RulesRegistry().effective(project)
