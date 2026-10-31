"""Built-in playbook library, export envelopes and markdown rendering (2026-10-31).

The built-in playbooks live as JSON files under ``playbook_builtin/`` so they can
be reviewed and diffed like code. Everything here is standard-library only.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.services.playbook_spec import (
    PlaybookValidationError,
    normalize_playbook,
    spec_hash,
)

_BUILTIN_DIR = Path(__file__).parent / "playbook_builtin"
_CACHE: Optional[Dict[str, Dict[str, Any]]] = None

#: Markdown skeletons used by ``create_doc_stub`` actions. The content is
#: deliberately generic: it never includes a user's project material.
DOC_STUB_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "research_proposal": {
        "title": "开题报告",
        "sections": [
            "一、研究背景与意义",
            "二、研究问题与科学假设",
            "三、国内外研究现状（文献综述矩阵）",
            "四、研究内容与技术路线",
            "五、预期成果与创新点",
            "六、研究计划与进度安排",
            "七、参考文献",
        ],
    },
    "experiment_log": {
        "title": "实验记录",
        "sections": [
            "一、实验目的",
            "二、实验环境与配置（随机种子 / 超参数）",
            "三、实验步骤",
            "四、原始结果（均值 ± 标准差）",
            "五、误差分析与结论",
        ],
    },
    "final_report": {
        "title": "结题报告",
        "sections": [
            "一、项目概况与任务书要求",
            "二、研究内容完成情况",
            "三、主要成果与创新点",
            "四、经费使用与决算说明",
            "五、存在问题与后续计划",
            "六、附件清单",
        ],
    },
    "architecture_decision": {
        "title": "架构决策记录（ADR）",
        "sections": [
            "一、背景与问题",
            "二、候选方案",
            "三、决策与理由",
            "四、影响与权衡",
            "五、后续行动",
        ],
    },
    "test_report": {
        "title": "测试报告",
        "sections": [
            "一、测试范围",
            "二、测试环境",
            "三、用例与覆盖",
            "四、缺陷统计",
            "五、结论与发布建议",
        ],
    },
    "release_notes": {
        "title": "发布说明",
        "sections": [
            "一、版本信息",
            "二、新增功能",
            "三、修复与改进",
            "四、升级注意事项",
            "五、已知问题",
        ],
    },
    "generic_document": {
        "title": "文档",
        "sections": ["一、背景", "二、正文", "三、结论", "四、附录"],
    },
}


def _load_builtin() -> Dict[str, Dict[str, Any]]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    items: Dict[str, Dict[str, Any]] = {}
    if _BUILTIN_DIR.is_dir():
        for path in sorted(_BUILTIN_DIR.glob("*.json")):
            with path.open("r", encoding="utf-8") as handle:
                spec = normalize_playbook(json.load(handle))
            items[spec["id"]] = spec
    _CACHE = items
    return items


def list_builtin() -> List[Dict[str, Any]]:
    """Return lightweight summaries for the built-in playbook picker."""
    return [
        {
            "id": spec["id"],
            "name": spec["name"],
            "description": spec.get("description", ""),
            "project_types": list(spec["applies_to"]["project_types"]),
            "sub_types": list(spec["applies_to"]["sub_types"]),
            "stage_count": len(spec["stages"]),
            "directories": [item["path"] for item in spec["directory_layout"]],
        }
        for spec in _load_builtin().values()
    ]


def get_builtin(playbook_id: str) -> Optional[Dict[str, Any]]:
    """Return a copy of a built-in playbook, or None when unknown."""
    spec = _load_builtin().get(str(playbook_id))
    return None if spec is None else json.loads(json.dumps(spec, ensure_ascii=False))


def suggested_builtin(project_type: Optional[str]) -> Optional[Dict[str, Any]]:
    """Pick the first built-in playbook whose ``applies_to`` matches the type."""
    wanted = str(project_type or "").strip().lower()
    if not wanted:
        return None
    for spec in _load_builtin().values():
        if wanted in spec["applies_to"]["project_types"]:
            return json.loads(json.dumps(spec, ensure_ascii=False))
    return None


def render_markdown_handbook(spec: Dict[str, Any]) -> str:
    """Render a human-readable, printable handbook for sharing."""
    lines: List[str] = ["# {}".format(spec["name"]), ""]
    if spec.get("description"):
        lines.extend([spec["description"], ""])
    lines.extend(["## 目录结构", ""])
    if spec.get("directory_layout"):
        for item in spec["directory_layout"]:
            mark = "必需" if item.get("required", True) else "可选"
            purpose = item.get("purpose") or ""
            lines.append("- `{}/`（{}）{}".format(item["path"], mark, purpose))
    else:
        lines.append("- （无固定目录要求）")
    lines.extend(["", "## 阶段与交付物", ""])
    for stage in sorted(spec["stages"], key=lambda item: item["order"]):
        lines.append("### {}. {}".format(stage["order"], stage["label"]))
        if stage.get("objective"):
            lines.append(stage["objective"])
        lines.append("")
        for artifact in stage["artifacts"]:
            mark = "必需" if artifact.get("required", True) else "可选"
            globs = ", ".join(f"`{item}`" for item in artifact["match"]["globs"])
            lines.append("- [ ] {}（{}）：{}".format(artifact["label"], mark, globs))
        for criterion in stage.get("exit_criteria") or []:
            label = criterion.get("label") or criterion.get("id")
            if label:
                lines.append(f"- [ ] 退出条件：{label}")
        lines.append("")

    rules = list(spec.get("global_rules") or [])
    for stage in spec["stages"]:
        for rule in stage.get("rules") or []:
            if rule.get("content"):
                rules.append(rule)
    if rules:
        lines.extend(["## 规则", ""])
        for rule in rules:
            content = rule.get("content") or rule.get("template_key") or ""
            if content:
                lines.append(f"- {content}")
        lines.append("")

    milestones = []
    for stage in spec["stages"]:
        for milestone in stage.get("recommended_milestones") or []:
            if milestone.get("title"):
                milestones.append("- [ ] {}（{}）".format(milestone["title"], stage["label"]))
    if milestones:
        lines.extend(["## 推荐里程碑", ""] + milestones + [""])

    if spec.get("todos"):
        lines.extend(["## 建议待办", ""])
        for todo in spec["todos"]:
            if todo.get("title"):
                lines.append("- [ ] {}".format(todo["title"]))
        lines.append("")

    meta = spec.get("meta") or {}
    lines.extend(
        [
            "---",
            "",
            "> 作者：{} · 许可证：{} · 导出自 Sage".format(meta.get("author") or "未知", meta.get("license") or "未声明"),
            "",
        ]
    )
    return "\n".join(lines)


def build_export_envelope(
    spec: Dict[str, Any],
    *,
    include_scaffold: bool = True,
    app_version: str = "unknown",
) -> Dict[str, Any]:
    """Build the portable ``.sageplaybook.json`` envelope.

    Only the methodology and optional empty scaffold are exported; project
    contents are never included.
    """
    normalized = normalize_playbook(spec)
    scaffold: Dict[str, Any] = {"include": bool(include_scaffold), "directories": [], "documents": []}
    if include_scaffold:
        scaffold["directories"] = [
            item["path"] for item in normalized["directory_layout"] if item.get("required", True)
        ]
        for stage in normalized["stages"]:
            for artifact in stage["artifacts"]:
                action = artifact.get("missing_action") or {}
                if action.get("type") in {"create_doc_stub", "open_doc"}:
                    payload = dict(action.get("payload") or {})
                    if payload:
                        scaffold["documents"].append(payload)
    return {
        "format": "sage.playbook",
        "schema_version": normalized["schema_version"],
        "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),  # noqa: UP017 — py3.8 compat
        "exporter": {"app": "Sage", "version": str(app_version)},
        "playbook": normalized,
        "scaffold": scaffold,
        "integrity": {"sha256": spec_hash(normalized)},
    }


def _safe_relative_path(value: Any, field: str) -> str:
    raw = str(value if value is not None else "").strip().replace("\\", "/")
    if raw.startswith("/") or raw.startswith("~"):
        raise PlaybookValidationError(f"非法相对路径: {raw!r}")
    parts = [part for part in raw.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise PlaybookValidationError(f"非法相对路径: {raw!r}")
    return "/".join(parts)


def render_agents_markdown(spec: Dict[str, Any]) -> str:
    """Render an AGENTS.md / CLAUDE.md compatible snippet for other AI tools."""
    lines: List[str] = [f"# 项目管理约定：{spec['name']}", ""]
    if spec.get("description"):
        lines.extend([spec["description"], ""])
    lines.extend(["## 目录约定", ""])
    for item in spec.get("directory_layout") or []:
        mark = "必需" if item.get("required", True) else "可选"
        purpose = item.get("purpose") or ""
        lines.append(f"- `{item['path']}/`（{mark}）{purpose}")
    lines.extend(["", "## 阶段与交付物", ""])
    for stage in sorted(spec.get("stages") or [], key=lambda item: item["order"]):
        lines.append(f"### {stage['order']}. {stage['label']}")
        if stage.get("objective"):
            lines.append(stage["objective"])
        lines.append("")
        for artifact in stage.get("artifacts") or []:
            mark = "必需" if artifact.get("required", True) else "可选"
            globs = ", ".join(f"`{item}`" for item in artifact["match"]["globs"])
            lines.append(f"- {artifact['label']}（{mark}）：{globs}")
        for criterion in stage.get("exit_criteria") or []:
            label = criterion.get("label") or criterion.get("id")
            if label:
                lines.append(f"- 退出条件：{label}")
        lines.append("")
    rules = list(spec.get("global_rules") or [])
    for stage in spec.get("stages") or []:
        rules.extend(stage.get("rules") or [])
    if rules:
        lines.extend(["## 规则", ""])
        for rule in rules:
            content = rule.get("content")
            if content:
                lines.append(f"- {content}")
        lines.append("")
    lines.extend(
        [
            "## AI 协同约定",
            "",
            "- 修改或新增文件前，先对照本规程的目录与交付物要求。",
            "- 缺失的必需要素应先补齐，再推进阶段；阶段变更需用户确认。",
            "- 不要编造文献、数据或交付物；只引用项目中真实存在的文件。",
            "",
        ]
    )
    return "\n".join(lines)


def validate_import_envelope(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validate an imported envelope and return ``{playbook, scaffold}``.

    Raises:
        PlaybookValidationError: for non-Sage files, incompatible specs, or
            unsafe scaffold paths.
    """
    if not isinstance(payload, dict) or payload.get("format") != "sage.playbook":
        raise PlaybookValidationError("不是 Sage 规程文件")
    spec = normalize_playbook(payload.get("playbook") or {})
    integrity = payload.get("integrity")
    if isinstance(integrity, dict) and integrity.get("sha256"):
        expected = str(integrity.get("sha256"))
        actual = spec_hash(spec)
        if expected != actual:
            raise PlaybookValidationError("规程文件校验失败：integrity.sha256 不匹配")
    raw_scaffold = payload.get("scaffold") or {}
    if not isinstance(raw_scaffold, dict):
        raise PlaybookValidationError("scaffold 必须是对象")
    scaffold: Dict[str, Any] = {
        "include": bool(raw_scaffold.get("include", False)),
        "directories": [],
        "documents": [],
    }
    for item in raw_scaffold.get("directories") or []:
        scaffold["directories"].append(_safe_relative_path(item, "scaffold.directories"))
    for item in raw_scaffold.get("documents") or []:
        if not isinstance(item, dict):
            raise PlaybookValidationError("scaffold.documents 必须是对象数组")
        document = dict(item)
        document["path"] = _safe_relative_path(item.get("path"), "scaffold.documents.path")
        scaffold["documents"].append(document)
    return {"playbook": spec, "scaffold": scaffold}


def render_doc_stub(template_id: Optional[str], *, title: Optional[str] = None) -> str:
    """Render a markdown stub for ``create_doc_stub`` actions."""
    template = DOC_STUB_TEMPLATES.get(str(template_id or "")) or DOC_STUB_TEMPLATES["generic_document"]
    heading = title or template["title"]
    lines = [f"# {heading}", ""]
    for section in template["sections"]:
        lines.extend([f"## {section}", "", "（待填写）", ""])
    return "\n".join(lines)


__all__ = [
    "DOC_STUB_TEMPLATES",
    "build_export_envelope",
    "get_builtin",
    "list_builtin",
    "render_agents_markdown",
    "render_doc_stub",
    "render_markdown_handbook",
    "suggested_builtin",
    "validate_import_envelope",
]
