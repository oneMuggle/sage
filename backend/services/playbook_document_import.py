"""Document-to-Playbook import service (2026-11-03).

Parses Word/PDF/Markdown documents and generates a Playbook spec using LLM.
Falls back to a deterministic template when LLM is unavailable.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from backend.services.llm_json import parse_json
from backend.services.playbook_spec import (
    PlaybookValidationError,
    normalize_playbook,
)

logger = logging.getLogger(__name__)

MAX_DOCUMENT_TEXT = 20000
MAX_FILENAME_LEN = 256


@dataclass
class DocumentImportResult:
    playbook: Dict[str, Any]
    source_doc: str
    rationale: str
    llm_available: bool
    source: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "playbook": self.playbook,
            "source_doc": self.source_doc,
            "rationale": self.rationale,
            "llm_available": self.llm_available,
            "source": self.source,
        }


def _slug(value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]
    return "item-" + digest


def _extract_stages_from_text(text: str) -> List[Dict[str, Any]]:
    stages: List[Dict[str, Any]] = []
    lines = text.split("\n")

    CN_NUMERALS = {
        "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
        "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    }

    stage_patterns = [
        re.compile(r"^#{1,3}\s*(\d+)[.)]\s*(.+)$"),
        re.compile(r"^(\d+)[.)]\s*(.+)$"),
        re.compile(r"^(?:第\s*)(\d+|[一二三四五六七八九十])\s*[阶段步].*?[：:]\s*(.+)$"),
        re.compile(r"^(?:第\s*)(\d+|[一二三四五六七八九十])\s*[：:]\s*(.+)$"),
        re.compile(r"^(?:Phase|Stage)\s*(\d+)[：:]\s*(.+)$", re.IGNORECASE),
    ]

    def _parse_num(raw: str) -> int:
        if raw.isdigit():
            return int(raw)
        return CN_NUMERALS.get(raw, 0)

    for line in lines:
        line = line.strip()
        if not line:
            continue
        for pattern in stage_patterns:
            match = pattern.match(line)
            if match:
                num = _parse_num(match.group(1))
                label = match.group(2).strip()
                if 1 <= num <= 20 and label:
                    stage_id = _slug(label)
                    stages.append({
                        "id": stage_id,
                        "label": label,
                        "order": num,
                        "objective": "",
                        "artifacts": [],
                        "exit_criteria": [],
                        "rules": [],
                        "recommended_milestones": [],
                    })
                break

    return stages[:8]


def _extract_artifacts_from_text(text: str) -> List[Dict[str, Any]]:
    artifacts: List[Dict[str, Any]] = []
    artifact_patterns = [
        re.compile(r"^[•\-\*]\s*(.+)$"),
        re.compile(r"^\d+[.)]\s*(.+)$"),
    ]

    lines = text.split("\n")
    in_artifact_section = False

    for line in lines:
        line = line.strip()
        if not line:
            continue

        lower = line.lower()
        if any(kw in lower for kw in ["产物", "交付物", "deliverable", "输出", "成果"]):
            in_artifact_section = True
            continue

        if in_artifact_section:
            for pattern in artifact_patterns:
                match = pattern.match(line)
                if match:
                    label = match.group(1).strip()
                    if label and len(label) < 100:
                        artifact_id = _slug(label)
                        artifacts.append({
                            "id": artifact_id,
                            "label": label,
                            "required": True,
                            "match": {"globs": [f"**/{label}*"], "min_count": 1},
                            "missing_action": {
                                "type": "create_doc_stub",
                                "payload": {"path": f"docs/{label}.md", "template": "generic_document"},
                            },
                        })
                    break

    return artifacts[:20]


def _extract_rules_from_text(text: str) -> List[Dict[str, Any]]:
    rules: List[Dict[str, Any]] = []
    rule_patterns = [
        re.compile(r"^[•\-\*]\s*(.+)$"),
        re.compile(r"^\d+[.)]\s*(.+)$"),
    ]

    lines = text.split("\n")
    in_rule_section = False

    for line in lines:
        line = line.strip()
        if not line:
            continue

        lower = line.lower()
        if any(kw in lower for kw in ["规则", "规范", "要求", "rule", "constraint"]):
            in_rule_section = True
            continue

        if in_rule_section:
            for pattern in rule_patterns:
                match = pattern.match(line)
                if match:
                    content = match.group(1).strip()
                    if content and len(content) < 500:
                        rule_id = _slug(content)
                        rules.append({
                            "id": rule_id,
                            "content": content,
                            "category": "project",
                            "priority": 5,
                        })
                    break

    return rules[:20]


def _build_deterministic_playbook(text: str, filename: str) -> Dict[str, Any]:
    stages = _extract_stages_from_text(text)
    artifacts = _extract_artifacts_from_text(text)
    rules = _extract_rules_from_text(text)

    if not stages:
        stages = [{
            "id": "stage-1",
            "label": "实施",
            "order": 1,
            "objective": "",
            "artifacts": artifacts[:10],
            "exit_criteria": [],
            "rules": [],
            "recommended_milestones": [],
        }]
    else:
        if artifacts:
            for stage in stages:
                if not stage["artifacts"]:
                    stage["artifacts"] = artifacts[:5]

    name = filename.rsplit(".", 1)[0] if "." in filename else filename
    name = name[:200]

    playbook = {
        "schema_version": "1.0",
        "id": f"doc-import-{_slug(filename)}",
        "name": name,
        "description": f"从文档 {filename} 导入的规程草案",
        "applies_to": {"project_types": [], "sub_types": []},
        "directory_layout": [],
        "stages": stages,
        "global_rules": rules,
        "todos": [],
        "ai_guidance": {},
        "meta": {"source": "document_import", "source_doc": filename[:MAX_FILENAME_LEN]},
    }

    return normalize_playbook(playbook)


def _build_prompt(text: str, filename: str) -> str:
    return f"""你是项目管理方法论专家。用户将提供一份规范文档，请从中提取 Playbook 规程。

## 文档信息
- 文件名: {filename[:MAX_FILENAME_LEN]}
- 内容预览:
{text[:MAX_DOCUMENT_TEXT]}

## 提取要求

1. **阶段**（stages）：识别项目生命周期的各个阶段
   - 每个阶段需要：id（英文 kebab-case）、label（中文名称）、order（顺序号）
   - 每个阶段的目标（objective，一句话）
   - 每个阶段的产物（artifacts）
     - 每个产物需要：id、label、globs（文件匹配模式）

2. **通用规则**（global_rules）：适用于整个项目的规则
   - 每条规则需要：id、content、category、priority

请只输出 JSON，格式如下：
{{"rationale": "一句话说明", "playbook": {{
  "schema_version": "1.0",
  "id": "doc-import-xxx",
  "name": "规程名称",
  "description": "适用范围",
  "applies_to": {{"project_types": [], "sub_types": []}},
  "directory_layout": [],
  "stages": [
    {{"id": "stage-id", "label": "阶段名", "order": 1, "objective": "目标",
      "artifacts": [{{"id": "artifact-id", "label": "文档名", "required": true,
        "match": {{"globs": ["**/文档名*"], "min_count": 1}}}}],
      "exit_criteria": [], "rules": [], "recommended_milestones": []}}
  ],
  "global_rules": [], "todos": [], "ai_guidance": {{}}, "meta": {{}}
}}}}

约束：
- 阶段 2-8 个，每个阶段 1-6 个产物
- 不要包含任何敏感信息
"""


async def import_playbook_from_document(
    file_path: Path,
    filename: str,
    *,
    use_llm: bool = True,
    llm_client: Any = None,
) -> DocumentImportResult:
    """Generate a Playbook spec from a document file."""
    from backend.wiki.file_parser import parse_document

    text = parse_document(file_path)
    if not text.strip():
        text = "(文档内容为空或无法解析)"

    deterministic = _build_deterministic_playbook(text, filename)

    client = llm_client
    if client is None and use_llm:
        try:
            from backend.orchestration.llm_factory import build_llm_client_from_settings
            client = build_llm_client_from_settings()
        except Exception:
            logger.warning("failed to build LLM client for document import", exc_info=True)
            client = None

    if client is None:
        return DocumentImportResult(
            playbook=deterministic,
            source_doc=filename[:MAX_FILENAME_LEN],
            rationale="基于文档结构分析生成的确定性草案",
            llm_available=False,
            source="deterministic",
        )

    try:
        raw = await client.complete(_build_prompt(text, filename))
        payload = parse_json(raw)
        if not isinstance(payload, dict):
            raise PlaybookValidationError("LLM 未返回 JSON 对象")
        candidate = payload.get("playbook") or payload
        spec = normalize_playbook(candidate)
        rationale = str(payload.get("rationale") or "AI 根据文档内容生成").strip()
        return DocumentImportResult(
            playbook=spec,
            source_doc=filename[:MAX_FILENAME_LEN],
            rationale=rationale,
            llm_available=True,
            source="llm",
        )
    except Exception:
        logger.warning("LLM document import failed, falling back", exc_info=True)
        return DocumentImportResult(
            playbook=deterministic,
            source_doc=filename[:MAX_FILENAME_LEN],
            rationale="AI 生成失败，已回退为基于文档结构的确定性草案",
            llm_available=False,
            source="deterministic",
        )


__all__ = ["DocumentImportResult", "import_playbook_from_document"]
