# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""Rule execution engine for the Office rules workspace (P3).

Independent of ``word_audit`` (which consumes ``WordRulePack``). Blocks come
from read-only document readers: .docx paragraphs + tables, .xlsx sheet names
+ non-empty rows, .pptx slide titles / text / tables. Regex rules are
deterministic, AI rules are batched into one LLM call per 40 blocks. The
engine is read-only.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

from backend.office.doc_profile import read_doc_profile
from backend.office.errors import OfficeLLMError, OfficeParseError
from backend.office.rule_models import AuditFinding, AuditResult, Rule

_MAX_FINDINGS = 200
_AI_BATCH_SIZE = 40
_AI_MAX_CHARS = 8000
# Cap the blocks fed to the LLM: beyond this the prompt either truncates or
# exceeds model context, and the audit quality collapses. Caller gets a
# deterministic (regex-only) result instead of a half-baked AI one.
_MAX_AI_BLOCKS = 400

# M6f：规则审校是只读的快速检查。xlsx 按行、pptx 按页展平；病理文件里的
# 巨型表格/演示文稿会让正则与 LLM prompt 失去意义，因此在展平层直接截断。
_MAX_XLSX_SHEETS = 100
_MAX_XLSX_ROWS_PER_SHEET = 500
_MAX_XLSX_ROW_CELLS = 50
_MAX_CELL_CHARS = 500
_MAX_BLOCK_CHARS = 2000
_MAX_PPT_SLIDES = 200
_MAX_PPT_TABLE_CELLS = 200


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


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _extract_docx_blocks(path: Path, *, workspace_path: Optional[str]) -> List[DocumentBlock]:
    """Flatten a .docx profile into scannable blocks (empty text skipped)."""
    profile = read_doc_profile(path, workspace_path=workspace_path)
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
        text = " ".join(str(cell.get("text") or "") for cell in (table.get("cells") or [])).strip()
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


def _extract_xlsx_blocks(path: Path) -> List[DocumentBlock]:
    """工作表名 → heading；每行非空数据 → table（label 带工作表名与行号）。"""
    from backend.core.lazy import load_attr
    from backend.office.excel import _cell_value_to_str

    load_workbook = load_attr("openpyxl", "load_workbook", globals())
    try:
        workbook = load_workbook(str(path), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 — openpyxl 抛错类型多样
        raise OfficeParseError(f"无法解析 Excel 文档：{exc}", file_path=path) from exc

    blocks: List[DocumentBlock] = []
    try:
        for sheet_index, sheet in enumerate(workbook.worksheets):
            if sheet_index >= _MAX_XLSX_SHEETS:
                break
            title = str(sheet.title or "").strip() or f"工作表{sheet_index + 1}"
            blocks.append(
                DocumentBlock(
                    index=len(blocks),
                    kind="heading",
                    text=title,
                    label=f"工作表「{title}」",
                )
            )
            emitted = 0
            for row_index, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                if emitted >= _MAX_XLSX_ROWS_PER_SHEET:
                    break
                cells = [
                    _truncate(_cell_value_to_str(value).strip(), _MAX_CELL_CHARS)
                    for value in row[:_MAX_XLSX_ROW_CELLS]
                ]
                text = " | ".join(cell for cell in cells if cell)
                if not text:
                    continue
                blocks.append(
                    DocumentBlock(
                        index=len(blocks),
                        kind="table",
                        text=_truncate(text, _MAX_BLOCK_CHARS),
                        label=f"工作表「{title}」第 {row_index} 行",
                    )
                )
                emitted += 1
    except Exception as exc:  # noqa: BLE001 — 迭代期损坏同样归一为解析失败
        raise OfficeParseError(f"无法解析 Excel 文档：{exc}", file_path=path) from exc
    finally:
        with contextlib.suppress(Exception):
            workbook.close()
    return blocks


def _extract_slide_tables(slide: Any) -> List[str]:
    """每张表展平为 ' | ' 连接的单元格文本（全空表跳过）。"""
    tables: List[str] = []
    for shape in slide.shapes:
        if not getattr(shape, "has_table", False):
            continue
        cells: List[str] = []
        for row in shape.table.rows:
            if len(cells) >= _MAX_PPT_TABLE_CELLS:
                break
            cells.extend(str(cell.text).strip() for cell in row.cells)
        text = " | ".join(cell for cell in cells[:_MAX_PPT_TABLE_CELLS] if cell)
        if text:
            tables.append(_truncate(text, _MAX_BLOCK_CHARS))
    return tables


def _slide_placeholder_title(slide: Any) -> str:
    """只认标题占位符；普通文本框一律算正文（审校范围以版式占位符为准）。"""
    try:
        placeholder = slide.shapes.title
    except (AttributeError, KeyError):
        return ""
    if placeholder is None or not getattr(placeholder, "has_text_frame", False):
        return ""
    return placeholder.text_frame.text.strip()


def _extract_pptx_blocks(path: Path) -> List[DocumentBlock]:
    """标题占位符 → heading、正文 → body、表格 → table（label 带幻灯片序号）。"""
    from backend.core.lazy import load_attr
    from backend.office.ppt import _extract_text_blocks

    Presentation = load_attr("pptx", "Presentation", globals())
    try:
        presentation = Presentation(str(path))
        slide_iter = list(presentation.slides)[:_MAX_PPT_SLIDES]
    except Exception as exc:  # noqa: BLE001 — python-pptx 抛错类型多样
        raise OfficeParseError(f"无法解析 PPT 文档：{exc}", file_path=path) from exc

    blocks: List[DocumentBlock] = []
    try:
        for slide_index, slide in enumerate(slide_iter):
            slide_no = slide_index + 1
            title = _slide_placeholder_title(slide)
            if title:
                blocks.append(
                    DocumentBlock(
                        index=len(blocks),
                        kind="heading",
                        text=title,
                        label=f"幻灯片 {slide_no} 标题",
                    )
                )
            body = "\n".join(_extract_text_blocks(slide)).strip()
            if body:
                blocks.append(
                    DocumentBlock(
                        index=len(blocks),
                        kind="body",
                        text=_truncate(body, _MAX_BLOCK_CHARS),
                        label=f"幻灯片 {slide_no} 正文",
                    )
                )
            for table_no, table_text in enumerate(_extract_slide_tables(slide), start=1):
                blocks.append(
                    DocumentBlock(
                        index=len(blocks),
                        kind="table",
                        text=table_text,
                        label=f"幻灯片 {slide_no} 表格 {table_no}",
                    )
                )
    except Exception as exc:  # noqa: BLE001 — 迭代期损坏同样归一为解析失败
        raise OfficeParseError(f"无法解析 PPT 文档：{exc}", file_path=path) from exc
    return blocks


def extract_blocks(file_path: Path, *, workspace_path: Optional[str] = None) -> List[DocumentBlock]:
    """Flatten a supported document into scannable blocks (empty text skipped)."""
    path = Path(file_path)
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return _extract_docx_blocks(path, workspace_path=workspace_path)
    if suffix == ".xlsx":
        return _extract_xlsx_blocks(path)
    if suffix == ".pptx":
        return _extract_pptx_blocks(path)
    raise OfficeParseError("规则审校仅支持 .docx / .xlsx / .pptx 文档", file_path=path)


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
        raw_index = item.get("block_index")
        block = by_index.get(raw_index) if isinstance(raw_index, int) else None
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
        if len(findings) >= _MAX_FINDINGS:
            break
        batch = blocks[start : start + _AI_BATCH_SIZE]
        prompt = _build_ai_prompt(rules, batch)
        try:
            raw = await llm_client.complete(prompt)
        except Exception as exc:  # noqa: BLE001 — re-raised as OfficeLLMError below
            raise OfficeLLMError("LLM 调用失败，请稍后重试") from exc
        findings.extend(_parse_ai_findings(raw, rules, batch))
    return findings


def _run_regex_rules(
    rules: List[Rule], blocks: List[DocumentBlock]
) -> List[AuditFinding]:
    """Hoisted regex sweep — CPU-bound, safe to run in an executor."""
    findings: List[AuditFinding] = []
    for rule in rules:
        if rule.check_mode != "regex":
            continue
        findings.extend(_run_regex_rule(rule, blocks))
        if len(findings) >= _MAX_FINDINGS:
            break
    return findings


async def run_audit(
    rules: List[Rule],
    file_path: Path,
    *,
    workspace_path: Optional[str] = None,
    llm_client: Any = None,
) -> AuditResult:
    """Audit a .docx/.xlsx/.pptx against enabled rules; read-only."""
    enabled = list({r.id: r for r in rules if r.enabled}.values())
    blocks = extract_blocks(file_path, workspace_path=workspace_path)
    regex_rules = [rule for rule in enabled if rule.check_mode == "regex"]
    loop = asyncio.get_running_loop()
    findings: List[AuditFinding] = await loop.run_in_executor(
        None, _run_regex_rules, regex_rules, blocks
    )
    ai_rules = [rule for rule in enabled if rule.check_mode == "ai"]
    if ai_rules and len(findings) < _MAX_FINDINGS and blocks:
        capped = blocks[:_MAX_AI_BLOCKS]
        findings.extend(await _run_ai_rules(ai_rules, capped, llm_client))
    findings = findings[:_MAX_FINDINGS]
    return AuditResult(
        findings=findings,
        error_count=sum(1 for item in findings if item.severity == "error"),
        warning_count=sum(1 for item in findings if item.severity == "warning"),
        info_count=sum(1 for item in findings if item.severity == "info"),
    )
