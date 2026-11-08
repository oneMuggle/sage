# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容
"""规则包传输层 —— 信封构造 / 解析 / 三种导出格式 / 导入 diff（M6，2026-11-07）。

与 ``sage.playbook`` 信封（规程包）同位并存，但格式名完全不同，避免误判。
本模块是纯转换 / 只读 IO 层：导出只读项目文件，导入只生成候选，不落盘。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from backend.data.project_repo import Project
from backend.services.playbook_library import build_export_envelope
from backend.services.rules_registry import (
    RuleEntry,
    global_rules_path,
    safe_read,
    triggers_overlap,
)

logger = logging.getLogger(__name__)

SAGE_RULES_FORMAT = "sage.rules"
SAGE_RULES_VERSION = 1
MAX_EXPORT_FILE_BYTES = 1_048_576  # 1 MiB

# 导出时按该顺序探测项目总纲文件；导入时只接受同一组文件名（防路径穿越）。
_DOC_FILENAMES: Tuple[str, ...] = ("SAGE.md", "CLAUDE.md", "AGENTS.md")
_IMPORTABLE_DOC_FILENAMES = frozenset(_DOC_FILENAMES)


@dataclass
class ImportCandidate:
    """导入预览的一条候选。"""

    id: str
    kind: str  # constraint | doc | global | playbook
    status: str  # new | duplicate | conflict
    content: str
    duplicate_of: Optional[str] = None
    layer: Optional[str] = None
    category: Optional[str] = None
    trigger_pattern: Optional[str] = None
    priority: int = 5
    enabled: bool = True
    filename: Optional[str] = None


class RulesImportValidationError(ValueError):
    """导入信封校验失败；``status_code`` 供路由映射为 HTTP 状态。"""

    def __init__(
        self,
        message: str,
        *,
        format: str = SAGE_RULES_FORMAT,
        status_code: int = 400,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.format = format
        self.status_code = status_code


def _normalize_for_dedupe(value: str) -> str:
    """去重：空白归一 + 大小写不敏感；不剥标点，避免误合。"""
    return " ".join(str(value).split()).casefold()


def _project_meta(project: Project) -> Dict[str, Any]:
    return {
        "name": getattr(project, "name", "") or "",
        "type": getattr(project, "project_type", "") or "",
    }


def _read_file_text(path: Path) -> str:
    """导出专用：与 registry 共享符号链接 / 1 MiB 防护；读不到返回空串。"""
    text = safe_read(path)
    return "" if text is None else text


def _constraint_payloads(entries: Iterable[RuleEntry]) -> List[Dict[str, Any]]:
    """仅用户可写的项目约束进入规则包；规程投影不重复导出（属于规程包）。"""
    payloads: List[Dict[str, Any]] = []
    for entry in entries:
        if entry.layer != "constraint" or entry.editable != "full":
            continue
        payloads.append(
            {
                "category": entry.category,
                "content": entry.content,
                "trigger_pattern": entry.trigger,
                "priority": entry.priority,
                "enabled": entry.enabled,
            }
        )
    return payloads


def _doc_payloads(project: Project) -> Dict[str, str]:
    """项目总纲（SAGE.md / CLAUDE.md / AGENTS.md）直接读文件正文（含防护）。"""
    project_path = Path(project.path)
    docs: Dict[str, str] = {}
    for filename in _DOC_FILENAMES:
        text = _read_file_text(project_path / filename)
        if text.strip():
            docs[filename] = text
    return docs


def build_rules_export_envelope(
    project: Project,
    entries: Iterable[RuleEntry],
    *,
    include_playbook: bool = False,
    playbook_spec: Optional[Dict[str, Any]] = None,
    include_global: bool = False,
    include_docs: bool = True,
    include_constraints: bool = True,
    app_version: str = "unknown",
) -> Dict[str, Any]:
    """构造 ``.sagerules.json`` 信封。

    - ``constraints``：仅用户可写的项目约束；``include_constraints=False`` 时清空。
    - ``project_docs``：项目总纲文件正文（按文件名）。
    - ``global_rules``：``~/.sage/SAGE.md`` 正文；默认不勾选，避免带走全局偏好。
    - ``playbook``：可选的 ``sage.playbook`` 子信封。
    """
    layers: Dict[str, Any] = {
        "constraints": _constraint_payloads(entries) if include_constraints else [],
        "project_docs": _doc_payloads(project) if include_docs else {},
        "global_rules": (
            _read_file_text(global_rules_path()) if include_global else ""
        ),
    }
    if include_playbook and playbook_spec is not None:
        layers["playbook"] = build_export_envelope(
            playbook_spec, include_scaffold=True, app_version=app_version
        )
    return {
        "format": SAGE_RULES_FORMAT,
        "version": SAGE_RULES_VERSION,
        "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),  # noqa: UP017 — py3.8 compat
        "project": _project_meta(project),
        "layers": layers,
    }


_LAYER_TITLES = {
    "constraint": "项目规则",
    "playbook": "规程规则",
    "global": "全局规则",
    "doc": "项目总纲",
}


def _md_section(title: str, body: str) -> str:
    return f"\n\n## {title}\n\n{body.rstrip()}"


def _layer_entries(entries: Iterable[RuleEntry]) -> Dict[str, List[RuleEntry]]:
    grouped: Dict[str, List[RuleEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.layer, []).append(entry)
    return grouped


def render_rules_markdown(
    project: Project,
    entries: Iterable[RuleEntry],
    *,
    global_rules_text: str = "",
    playbook_markdown: str = "",
) -> str:
    """单文件可读版（按层分节，用于 ``format=md``）。"""
    meta = _project_meta(project)
    lines = ["# 规则包：{}".format(meta.get("name") or project.id), ""]
    by_layer = _layer_entries(entries)
    for layer_key in ("constraint", "doc", "global", "playbook"):
        if layer_key == "global" and not global_rules_text.strip():
            continue
        if layer_key == "playbook" and not playbook_markdown.strip():
            continue
        lines.append(_md_section(_LAYER_TITLES[layer_key], ""))
        if layer_key == "global":
            lines.append(global_rules_text.rstrip())
        elif layer_key == "playbook":
            lines.append(playbook_markdown.rstrip())
        else:
            for entry in by_layer.get(layer_key) or []:
                trigger = f"（触发：`{entry.trigger}`）" if entry.trigger else ""
                lines.append(
                    "- **{}** {}{}".format(
                        entry.category or "general", entry.content, trigger
                    )
                )
    return "\n".join(lines).rstrip() + "\n"


# 仅这些层的 ``content`` 是一行一句的规则，可被 AGENTS.md 以 bullet 形式列出；
# ``global`` / ``playbook`` 走独立的整段附加，避免重复渲染。
_SUMMARIZABLE_LAYERS: Tuple[str, ...] = ("constraint", "doc")


def render_rules_agents_md(
    project: Project,
    entries: Iterable[RuleEntry],
    *,
    global_rules_text: str = "",
    playbook_agents_md: str = "",
) -> str:
    """AGENTS.md 风格纯规则正文 —— 给 Claude Code / Cursor 使用。"""
    meta = _project_meta(project)
    lines = [
        "# 项目管理约定：{}".format(meta.get("name") or meta.get("type") or "sage"),
        "",
    ]
    if meta.get("type"):
        lines.append("项目类型：{}。".format(meta["type"]))
        lines.append("")
    active = [
        entry
        for entry in entries
        if entry.enabled and entry.layer in _SUMMARIZABLE_LAYERS
    ]
    if active:
        lines.extend(["## 规则", ""])
        lines.extend(f"- {entry.content}" for entry in active)
        lines.append("")
    if global_rules_text.strip():
        lines.extend(["## 全局偏好", "", global_rules_text.strip(), ""])
    if playbook_agents_md.strip():
        lines.extend([playbook_agents_md.rstrip(), ""])
    lines.extend(
        [
            "## AI 协同约定",
            "",
            "- 修改文件前，先对照本项目的规则与目录要求。",
            "- 不要编造文献、数据或交付物；只引用项目中真实存在的文件。",
            "",
        ]
    )
    return "\n".join(lines)


def _measure_payload_bytes(payload: Any) -> int:
    """str/bytes 按原始字节测长；dict 按重新序列化后的 UTF-8 长度测长。"""
    if isinstance(payload, bytes):
        return len(payload)
    if isinstance(payload, str):
        return len(payload.encode("utf-8"))
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def _decode_payload(payload: Any) -> Dict[str, Any]:
    if isinstance(payload, (str, bytes)):  # noqa: UP038 — py3.8 不支持 `str | bytes` 运行时 isinstance
        try:
            payload = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RulesImportValidationError(
                f"规则包 JSON 解析失败：{exc}"
            ) from exc
    if not isinstance(payload, dict):
        raise RulesImportValidationError("规则包必须是对象")
    return payload


def _validate_layers(payload: Dict[str, Any]) -> Dict[str, Any]:
    if payload.get("format") != SAGE_RULES_FORMAT:
        raise RulesImportValidationError(
            f"不是 Sage 规则包（format 必须为 {SAGE_RULES_FORMAT}）"
        )
    try:
        version = int(payload.get("version") or 0)
    except (TypeError, ValueError):
        version = 0
    if version != SAGE_RULES_VERSION:
        raise RulesImportValidationError(
            f"规则包版本不兼容（期望 {SAGE_RULES_VERSION}）"
        )
    layers = payload.get("layers")
    if not isinstance(layers, dict):
        raise RulesImportValidationError("layers 字段缺失或不是对象")
    constraints = layers.get("constraints")
    if constraints is None:
        layers["constraints"] = []
    elif not isinstance(constraints, list):
        raise RulesImportValidationError("layers.constraints 必须是数组")
    docs = layers.get("project_docs")
    if docs is None:
        layers["project_docs"] = {}
    elif not isinstance(docs, dict):
        raise RulesImportValidationError("layers.project_docs 必须是对象")
    else:
        for key in docs:
            if str(key) not in _IMPORTABLE_DOC_FILENAMES:
                raise RulesImportValidationError(
                    "project_docs 仅允许 SAGE.md / CLAUDE.md / AGENTS.md"
                )
    layers.setdefault("global_rules", "")
    return layers


def parse_rules_import(payload: Any) -> Dict[str, Any]:
    """校验导入信封；返回可用的信封字典。"""
    if _measure_payload_bytes(payload) > MAX_EXPORT_FILE_BYTES:
        raise RulesImportValidationError(
            f"规则包超过 {MAX_EXPORT_FILE_BYTES} 字节上限"
        )
    parsed = _decode_payload(payload)
    layers = _validate_layers(parsed)
    return {**parsed, "layers": layers}


def _index_constraints(
    existing_rules: Iterable[RuleEntry],
) -> Dict[str, List[RuleEntry]]:
    """约束按归一化后的 category 分桶，便于同 category 内逐条扫描触发词重叠。"""
    constraints_by_cat: Dict[str, List[RuleEntry]] = {}
    for entry in existing_rules:
        if entry.layer != "constraint":
            continue
        cat = _normalize_for_dedupe(entry.category or "")
        constraints_by_cat.setdefault(cat, []).append(entry)
    return constraints_by_cat


def _constraint_status(
    category: str,
    content: str,
    trigger: Optional[str],
    constraints_by_cat: Dict[str, List[RuleEntry]],
) -> Tuple[str, Optional[str]]:
    """同 category + 触发重叠 → duplicate/conflict；无重叠 → new。"""
    norm_cat = _normalize_for_dedupe(category)
    norm_content = _normalize_for_dedupe(content)
    for entry in constraints_by_cat.get(norm_cat, []):
        if triggers_overlap(trigger, entry.trigger):
            if _normalize_for_dedupe(entry.content or "") == norm_content:
                return "duplicate", entry.id
            return "conflict", entry.id
    return "new", None


def _coerce_priority(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 5


def _diff_constraints(
    layers: Dict[str, Any],
    constraints_by_cat: Dict[str, List[RuleEntry]],
) -> List[ImportCandidate]:
    candidates: List[ImportCandidate] = []
    for index, item in enumerate(layers.get("constraints") or []):
        if not isinstance(item, dict):
            continue
        category = str(item.get("category") or "general").strip() or "general"
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        status, duplicate_of = _constraint_status(
            category, content, item.get("trigger_pattern"), constraints_by_cat
        )
        candidates.append(
            ImportCandidate(
                id=f"import-constraint-{index}",
                kind="constraint",
                status=status,
                content=content,
                duplicate_of=duplicate_of,
                layer="constraint",
                category=category,
                trigger_pattern=item.get("trigger_pattern"),
                priority=_coerce_priority(item.get("priority") or 5),
                enabled=bool(item.get("enabled", True)),
            )
        )
    return candidates


def _diff_docs(
    envelope_docs: Dict[str, str], project: Optional[Project]
) -> List[ImportCandidate]:
    """整文件读盘比对：避免按小节聚合时多节文件被错判为 conflict。

    ``project is None`` 时所有 doc 候选视为 ``new``（无现有项目可读）。
    """
    candidates: List[ImportCandidate] = []
    for filename, text in (envelope_docs or {}).items():
        name = str(filename)
        body = str(text)
        if not name.strip() or not body.strip():
            continue
        if project is None:
            status, duplicate_of = "new", None
        else:
            existing_text = safe_read(Path(project.path) / name)
            if not existing_text or not existing_text.strip():
                status, duplicate_of = "new", None
            elif _normalize_for_dedupe(existing_text) == _normalize_for_dedupe(body):
                status, duplicate_of = "duplicate", f"doc:{name}"
            else:
                status, duplicate_of = "conflict", f"doc:{name}"
        candidates.append(
            ImportCandidate(
                id=f"import-doc-{name}",
                kind="doc",
                status=status,
                content=body,
                duplicate_of=duplicate_of,
                layer="doc",
                filename=name,
            )
        )
    return candidates


def _diff_global(envelope_global_text: str) -> List[ImportCandidate]:
    """整文件读盘比对：避免多节全局规则被错判为 conflict。"""
    text = str(envelope_global_text or "").strip()
    if not text:
        return []
    existing_text = safe_read(global_rules_path())
    if not existing_text or not existing_text.strip():
        status, duplicate_of = "new", None
    elif _normalize_for_dedupe(existing_text) == _normalize_for_dedupe(text):
        status, duplicate_of = "duplicate", "global:SAGE.md"
    else:
        status, duplicate_of = "conflict", "global:SAGE.md"
    return [
        ImportCandidate(
            id="import-global-SAGE.md",
            kind="global",
            status=status,
            content=text,
            duplicate_of=duplicate_of,
            layer="global",
            filename="SAGE.md",
        )
    ]


def _diff_playbook(layers: Dict[str, Any]) -> List[ImportCandidate]:
    layer = layers.get("playbook")
    if not isinstance(layer, dict) or not isinstance(layer.get("playbook"), dict):
        return []
    spec = layer["playbook"]
    playbook_id = str(spec.get("id") or "unknown")
    return [
        ImportCandidate(
            id=f"import-playbook-{playbook_id}",
            kind="playbook",
            status="new",
            content=str(spec.get("name") or playbook_id),
            category="playbook",
        )
    ]


def diff_rules_import(
    envelope: Dict[str, Any],
    project: Optional[Project],
    existing_rules: Iterable[RuleEntry],
) -> List[ImportCandidate]:
    """预览导入：逐条与当前状态比对，标记 new / duplicate / conflict。"""
    layers = envelope.get("layers") or {}
    constraints_by_cat = _index_constraints(existing_rules)
    candidates: List[ImportCandidate] = []
    candidates.extend(_diff_constraints(layers, constraints_by_cat))
    candidates.extend(_diff_docs(layers.get("project_docs") or {}, project))
    candidates.extend(_diff_global(layers.get("global_rules") or ""))
    candidates.extend(_diff_playbook(layers))
    return candidates


__all__ = [
    "MAX_EXPORT_FILE_BYTES",
    "SAGE_RULES_FORMAT",
    "SAGE_RULES_VERSION",
    "ImportCandidate",
    "RulesImportValidationError",
    "build_rules_export_envelope",
    "diff_rules_import",
    "parse_rules_import",
    "render_rules_agents_md",
    "render_rules_markdown",
]
