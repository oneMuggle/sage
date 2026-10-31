"""AI-assisted playbook authoring (2026-10-31).

Builds a playbook draft from a short questionnaire plus the project's existing
type/directory structure. LLM output is validated and normalized; when the LLM
is unavailable or returns invalid JSON, a deterministic draft is returned.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from backend.services.llm_json import parse_json
from backend.services.playbook_library import get_builtin, suggested_builtin
from backend.services.playbook_spec import (
    PlaybookValidationError,
    normalize_playbook,
)

logger = logging.getLogger(__name__)

MAX_ANSWER_TEXT = 4000


@dataclass
class AuthorResult:
    playbook: Dict[str, Any]
    rationale: str
    llm_available: bool
    source: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "playbook": self.playbook,
            "rationale": self.rationale,
            "llm_available": self.llm_available,
            "source": self.source,
        }


def _base_spec(project: Any) -> Dict[str, Any]:
    project_type = getattr(project, "project_type", None) or getattr(
        project, "detected_type", None
    )
    spec = suggested_builtin(project_type)
    if spec is None:
        spec = get_builtin("coding-project")
    if spec is None:
        spec = {
            "schema_version": "1.0",
            "id": "custom-project",
            "name": "项目规程",
            "description": "",
            "applies_to": {"project_types": [], "sub_types": []},
            "directory_layout": [],
            "stages": [
                {
                    "id": "stage-1",
                    "label": "实施",
                    "order": 1,
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
        }
    return copy.deepcopy(spec)


def _slug(value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]
    return "item-" + digest


def _apply_answers(spec: Dict[str, Any], answers: Dict[str, Any], project: Any) -> Dict[str, Any]:
    """Apply questionnaire answers deterministically to a base spec."""
    name = str(answers.get("name") or "").strip()
    if name:
        spec["name"] = name[:200]
    notes = str(answers.get("notes") or "").strip()[:MAX_ANSWER_TEXT]
    if notes:
        spec.setdefault("global_rules", []).append(
            {
                "content": notes,
                "category": "project",
                "priority": 5,
            }
        )

    directories = answers.get("directories")
    if isinstance(directories, list) and directories:
        spec["directory_layout"] = [
            {
                "path": str(item).strip(),
                "required": True,
                "purpose": "",
            }
            for item in directories
            if str(item).strip()
        ]

    stages = answers.get("stages")
    if isinstance(stages, list) and stages:
        built_stages: List[Dict[str, Any]] = []
        for index, stage in enumerate(stages, start=1):
            if not isinstance(stage, dict):
                continue
            label = str(stage.get("label") or stage.get("name") or "").strip()
            if not label:
                continue
            stage_id = str(stage.get("id") or "").strip() or _slug(label)
            artifacts: List[Dict[str, Any]] = []
            for deliverable in stage.get("deliverables") or stage.get("artifacts") or []:
                text = str(deliverable).strip()
                if not text:
                    continue
                artifact_id = _slug(text)
                artifacts.append(
                    {
                        "id": artifact_id,
                        "label": text,
                        "required": True,
                        "match": {"globs": [f"**/{text}*"], "min_count": 1},
                        "missing_action": {
                            "type": "create_doc_stub",
                            "payload": {"path": f"docs/{text}.md", "template": "generic_document"},
                        },
                    }
                )
            built_stages.append(
                {
                    "id": stage_id,
                    "label": label,
                    "order": int(stage.get("order") or index),
                    "objective": str(stage.get("objective") or ""),
                    "artifacts": artifacts,
                    "exit_criteria": [],
                    "rules": [],
                    "recommended_milestones": [],
                }
            )
        if built_stages:
            spec["stages"] = built_stages

    spec["id"] = str(
        answers.get("id")
        or f"custom-{_slug(str(getattr(project, 'id', '')))}"
    )[:128]
    spec["description"] = str(answers.get("description") or spec.get("description") or "")[:4000]
    spec.setdefault("meta", {})
    spec["meta"]["author"] = "Sage AI 定制"
    return spec


def _build_prompt(project: Any, base: Dict[str, Any], answers: Dict[str, Any]) -> str:
    compact_base = {
        "id": base.get("id"),
        "name": base.get("name"),
        "stages": [
            {
                "id": stage["id"],
                "label": stage.get("label"),
                "artifacts": [item.get("label") for item in stage.get("artifacts") or []],
            }
            for stage in base.get("stages") or []
        ],
        "directories": [item.get("path") for item in base.get("directory_layout") or []],
    }
    return f"""你是项目管理方法论专家。请为一个项目生成 Sage Playbook 规程。

## 项目
- 名称: {getattr(project, 'name', '')}
- 类型: {getattr(project, 'project_type', None) or getattr(project, 'detected_type', None) or '未分类'}
- 子类型: {getattr(project, 'project_sub_type', None) or '未指定'}
- 描述: {getattr(project, 'description', None) or '无'}

## 用户补充要求
{json.dumps(answers, ensure_ascii=False)[:MAX_ANSWER_TEXT]}

## 参考内置规程（可调整，不必照抄）
{json.dumps(compact_base, ensure_ascii=False)}

## 输出要求
只输出一个 JSON 对象，不要 Markdown 围栏：
{{"rationale": "一句话说明为什么这样设计", "playbook": {{
  "schema_version": "1.0",
  "id": "custom-xxx",
  "name": "规程名称",
  "description": "适用范围",
  "applies_to": {{"project_types": ["coding|research|business|personal"], "sub_types": []}},
  "directory_layout": [{{"path": "01_阶段", "required": true, "purpose": "用途"}}],
  "stages": [
    {{"id": "stage-id", "label": "阶段名", "order": 1, "objective": "目标",
      "artifacts": [{{"id": "artifact-id", "label": "文档名", "required": true,
        "match": {{"globs": ["**/文档名*"], "min_count": 1}}}}],
      "exit_criteria": [], "rules": [], "recommended_milestones": []}}
  ],
  "global_rules": [], "todos": [], "ai_guidance": {{}}, "meta": {{}}
}}}}

约束：
- 阶段 2-8 个，每个阶段 1-6 个产物；globs 使用项目根相对路径。
- 不要包含任何项目文件内容或敏感信息。
"""


async def build_author_preview(
    project: Any,
    answers: Optional[Dict[str, Any]] = None,
    *,
    use_llm: bool = True,
    llm_client: Any = None,
) -> AuthorResult:
    """Generate a playbook draft from a questionnaire.

    Args:
        project: project object with id/name/type/description.
        answers: optional questionnaire answers (name/notes/stages/directories).
        use_llm: False forces the deterministic draft.
        llm_client: optional injected client exposing ``async complete(prompt)``.

    Returns:
        AuthorResult; never raises for LLM failures.
    """
    answers = answers or {}
    base = _base_spec(project)
    deterministic = normalize_playbook(_apply_answers(copy.deepcopy(base), answers, project))

    client = llm_client
    if client is None and use_llm:
        try:
            from backend.orchestration.llm_factory import build_llm_client_from_settings

            client = build_llm_client_from_settings()
        except Exception:  # noqa: BLE001 — LLM is optional
            logger.warning("failed to build LLM client for playbook authoring", exc_info=True)
            client = None

    if client is None:
        return AuthorResult(
            playbook=deterministic,
            rationale="基于内置规程与你的回答生成的确定性草案",
            llm_available=False,
            source="deterministic",
        )

    try:
        raw = await client.complete(_build_prompt(project, base, answers))
        payload = parse_json(raw)
        if not isinstance(payload, dict):
            raise PlaybookValidationError("LLM 未返回 JSON 对象")
        candidate = payload.get("playbook") or payload
        spec = normalize_playbook(candidate)
        rationale = str(payload.get("rationale") or "AI 根据项目信息与你的要求生成").strip()
        return AuthorResult(
            playbook=spec,
            rationale=rationale,
            llm_available=True,
            source="llm",
        )
    except Exception:  # noqa: BLE001 — fall back to deterministic draft
        logger.warning("LLM playbook authoring failed, falling back", exc_info=True)
        return AuthorResult(
            playbook=deterministic,
            rationale="AI 生成失败，已回退为基于内置规程的确定性草案",
            llm_available=False,
            source="deterministic",
        )


__all__ = ["AuthorResult", "build_author_preview"]
