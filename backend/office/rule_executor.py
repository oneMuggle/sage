# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""Rule execution engine for the Office rules workspace (P3).

Independent of ``word_audit`` (which consumes ``WordRulePack``). Blocks come
from the read-only document profile; regex rules are deterministic, AI rules
are batched into one LLM call per 40 blocks. The engine is read-only.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

from backend.office.doc_profile import read_doc_profile
from backend.office.errors import OfficeParseError
from backend.office.rule_models import AuditFinding, AuditResult, Rule

_MAX_FINDINGS = 200
_AI_BATCH_SIZE = 40
_AI_MAX_CHARS = 8000


@dataclass
class DocumentBlock:
    index: int
    kind: str
    text: str
    label: str


def _classify_style(style: str) -> str:
    lowered = style.lower()
    if lowered.startswith("heading") or style.startswith("标题"):
        return "heading"
    if "caption" in lowered or style.startswith("题注"):
        return "caption"
    return "body"


def extract_blocks(
    file_path: Path, *, workspace_path: Optional[str] = None
) -> List[DocumentBlock]:
    """Flatten a .docx profile into scannable blocks (empty text skipped)."""
    profile = read_doc_profile(Path(file_path), workspace_path=workspace_path)
    paragraphs = profile.get("paragraphs") or []
    blocks: List[DocumentBlock] = []
    for paragraph in paragraphs:
        text = str(paragraph.get("text") or "")
        if not text.strip():
            continue
        index = int(paragraph.get("index", len(blocks)))
        blocks.append(
            DocumentBlock(
                index=index,
                kind=_classify_style(str(paragraph.get("style") or "")),
                text=text,
                label=f"第 {index + 1} 段",
            )
        )
    table_offset = len(paragraphs)
    for table_index, table in enumerate(profile.get("tables") or []):
        text = " ".join(
            str(cell.get("text") or "") for cell in (table.get("cells") or [])
        ).strip()
        if not text:
            continue
        blocks.append(
            DocumentBlock(
                index=table_offset + table_index,
                kind="table",
                text=text,
                label=f"表格 {table_index + 1}",
            )
        )
    return blocks


def select_blocks(blocks: List[DocumentBlock], scope: str) -> List[DocumentBlock]:
    if scope == "full":
        return list(blocks)
    return [block for block in blocks if block.kind == scope]


def _run_regex_rule(rule: Rule, blocks: List[DocumentBlock]) -> List[AuditFinding]:
    if not rule.pattern:
        raise OfficeParseError(f"正则规则缺少 pattern：{rule.name}")
    try:
        compiled = re.compile(rule.pattern)
    except re.error as exc:
        raise OfficeParseError(f"规则「{rule.name}」的正则表达式无效: {exc}") from exc
    findings: List[AuditFinding] = []
    for block in select_blocks(blocks, rule.scope):
        if compiled.search(block.text):
            findings.append(
                AuditFinding(
                    rule_id=rule.id,
                    rule_name=rule.name,
                    severity=rule.severity,
                    message=rule.description or f"命中规则「{rule.name}」",
                    location=block.label,
                    suggestion=rule.description or "请按规则调整该段落",
                )
            )
    return findings


def _build_ai_prompt(rules: List[Rule], blocks: List[DocumentBlock]) -> str:
    lines = [
        "你是一个文档审校引擎。请检查下列文档片段是否违反规则，只返回 JSON 数组。",
        "规则：",
    ]
    for rule in rules:
        detail = rule.ai_prompt or rule.description or rule.name
        lines.append(f"- {rule.id} | {rule.name} | {detail}")
    lines.append("文档片段：")
    used = 0
    for block in blocks:
        line = f"[{block.index}] {block.text}"
        if used + len(line) > _AI_MAX_CHARS:
            break
        lines.append(line)
        used += len(line)
    lines.append(
        '返回格式：[{"rule_id":"...","block_index":0,"message":"...","suggestion":"..."}]；'
        "没有问题时返回 []。"
    )
    return "\n".join(lines)


def _parse_ai_findings(
    raw: str, rules: List[Rule], blocks: List[DocumentBlock]
) -> List[AuditFinding]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end <= start:
        raise OfficeParseError("LLM 审校结果不是 JSON 数组")
    try:
        items = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise OfficeParseError(f"LLM 审校结果解析失败: {exc}") from exc
    if not isinstance(items, list):
        raise OfficeParseError("LLM 审校结果不是 JSON 数组")
    by_rule = {rule.id: rule for rule in rules}
    by_index = {block.index: block for block in blocks}
    findings: List[AuditFinding] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        rule = by_rule.get(str(item.get("rule_id")))
        block = by_index.get(item.get("block_index"))
        if rule is None or block is None:
            continue
        findings.append(
            AuditFinding(
                rule_id=rule.id,
                rule_name=rule.name,
                severity=rule.severity,
                message=str(item.get("message") or rule.name)[:500],
                location=block.label,
                suggestion=str(item.get("suggestion") or rule.description)[:500],
            )
        )
    return findings


async def _run_ai_rules(
    rules: List[Rule], blocks: List[DocumentBlock], llm_client: Any
) -> List[AuditFinding]:
    if llm_client is None:
        raise OfficeParseError("AI 规则需要 LLM 客户端")
    findings: List[AuditFinding] = []
    for start in range(0, len(blocks), _AI_BATCH_SIZE):
        batch = blocks[start : start + _AI_BATCH_SIZE]
        prompt = _build_ai_prompt(rules, batch)
        raw = await llm_client.complete(prompt)
        findings.extend(_parse_ai_findings(raw, rules, batch))
    return findings


async def run_audit(
    rules: List[Rule],
    file_path: Path,
    *,
    workspace_path: Optional[str] = None,
    llm_client: Any = None,
) -> AuditResult:
    """Audit a .docx against enabled rules; read-only."""
    enabled = [rule for rule in rules if rule.enabled]
    blocks = extract_blocks(file_path, workspace_path=workspace_path)
    findings: List[AuditFinding] = []
    for rule in enabled:
        if rule.check_mode != "regex":
            continue
        findings.extend(_run_regex_rule(rule, blocks))
        if len(findings) >= _MAX_FINDINGS:
            break
    ai_rules = [rule for rule in enabled if rule.check_mode == "ai"]
    if ai_rules and len(findings) < _MAX_FINDINGS and blocks:
        findings.extend(await _run_ai_rules(ai_rules, blocks, llm_client))
    findings = findings[:_MAX_FINDINGS]
    return AuditResult(
        findings=findings,
        error_count=sum(1 for item in findings if item.severity == "error"),
        warning_count=sum(1 for item in findings if item.severity == "warning"),
        info_count=sum(1 for item in findings if item.severity == "info"),
    )
