"""Native Word revisions (M4b): tracked replacements + review comments.

Changes are written as ``w:del`` + ``w:ins`` inside the document body so
Word/WPS review panes can accept or reject them. Every change targets the
first paragraph containing the exact ``find`` text (body or table cell).
The source file is never modified unless ``overwrite=True``.
"""

from __future__ import annotations

import re
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from .edit import _apply_docx_add_comment, _docx_locate_paragraph_with_text
from .errors import OfficeFileNotFoundError, OfficeParseError, OfficePathError
from .path_safety import resolve_within
from .word_rulepack_models import (
    WordAuditIssue,
    WordRevisionChange,
    WordRevisionResult,
    WordRulePack,
)

_SAVE_RETRY_DELAYS = (0.0, 0.1, 0.25, 0.5, 1.0)


def _check_output_name(name: str) -> str:
    value = (name or "").strip()
    if not value:
        raise OfficeParseError("output_filename 不能为空")
    if Path(value).is_absolute() or "/" in value or "\\" in value:
        raise OfficeParseError("output_filename 不能包含路径分隔符")
    if value in (".", ".."):
        raise OfficeParseError("output_filename 非法")
    if not value.lower().endswith(".docx"):
        raise OfficeParseError("output_filename 必须以 .docx 结尾")
    return value


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.name


def _convert_date(sample: str, expected_label: str) -> Optional[str]:
    numbers = re.findall(r"\d+", sample or "")
    if len(numbers) < 3:
        return None
    year, month, day = int(numbers[0]), int(numbers[1]), int(numbers[2])
    label = str(expected_label or "").split(",")[0].strip()
    if label == "YYYY年M月D日":
        return f"{year}年{month}月{day}日"
    if label == "YYYY-MM-DD":
        return f"{year}-{month:02d}-{day:02d}"
    if label == "YYYY/M/D":
        return f"{year}/{month}/{day}"
    if label == "YYYY.M.D":
        return f"{year}.{month}.{day}"
    return None


def build_revision_plan(
    issues: List[WordAuditIssue], pack: WordRulePack
) -> List[Dict[str, Any]]:
    """Derive tracked-replacement candidates from fixable audit issues."""
    rules = {rule.id: rule for rule in pack.rules}
    plan: List[Dict[str, Any]] = []
    seen: set = set()
    for issue in issues:
        rule = rules.get(issue.rule_id)
        if rule is None or not rule.fixable or not issue.fixable:
            continue
        if rule.kind == "content.terminology":
            if not issue.expected or not issue.actual:
                continue
            for variant in str(issue.actual).split(","):
                target = variant.strip()
                key = (target, issue.expected)
                if not target or key in seen:
                    continue
                plan.append(
                    {
                        "rule_id": issue.rule_id,
                        "find": target,
                        "replace": issue.expected,
                        "comment": issue.message,
                    }
                )
                seen.add(key)
        elif rule.kind == "content.date_format":
            if not issue.actual or not issue.expected:
                continue
            replacement = _convert_date(str(issue.actual), str(issue.expected))
            key = (str(issue.actual), replacement)
            if not replacement or replacement == issue.actual or key in seen:
                continue
            plan.append(
                {
                    "rule_id": issue.rule_id,
                    "find": str(issue.actual),
                    "replace": replacement,
                    "comment": issue.message,
                }
            )
            seen.add(key)
    return plan


def _run_text(run: Any) -> str:
    return "".join(text.text or "" for text in run.findall(qn("w:t")))


def _set_run_text(run: Any, text: str) -> None:
    texts = run.findall(qn("w:t"))
    if not texts:
        element = OxmlElement("w:t")
        run.append(element)
        texts = [element]
    texts[0].text = text
    texts[0].set(qn("xml:space"), "preserve")
    for extra in texts[1:]:
        run.remove(extra)


def _new_run(source: Any, text: str, *, deleted: bool = False) -> Any:
    run = OxmlElement("w:r")
    rpr = source.find(qn("w:rPr"))
    if rpr is not None:
        run.append(deepcopy(rpr))
    if deleted:
        element = OxmlElement("w:delText")
        element.set(qn("xml:space"), "preserve")
        element.text = text
        run.append(element)
        return run
    lines = str(text).split("\n")
    for index, line in enumerate(lines):
        if index:
            run.append(OxmlElement("w:br"))
        element = OxmlElement("w:t")
        element.set(qn("xml:space"), "preserve")
        element.text = line
        run.append(element)
    return run


def _split_run(run: Any, text: str, index: int) -> None:
    if index <= 0 or index >= len(text):
        return
    suffix = _new_run(run, text[index:])
    run.addnext(suffix)
    _set_run_text(run, text[:index])


def _split_at(paragraph_el: Any, offset: int) -> None:
    position = 0
    for run in paragraph_el.findall(qn("w:r")):
        text = _run_text(run)
        end = position + len(text)
        if position < offset < end:
            _split_run(run, text, offset - position)
            return
        position = end


def _next_revision_id(document: Any) -> int:
    next_id = 900001
    for element in document.element.body.iter():
        if element.tag in (qn("w:ins"), qn("w:del")):
            try:
                next_id = max(next_id, int(element.get(qn("w:id")) or 0) + 1)
            except ValueError:
                continue
    return next_id


def _tracked_replace(
    paragraph: Any,
    find: str,
    replace: str,
    author: str,
    date: str,
    revision_id: int,
) -> bool:
    paragraph_el = paragraph._p
    runs = paragraph_el.findall(qn("w:r"))
    text = "".join(_run_text(run) for run in runs)
    start = text.find(find)
    if start < 0:
        return False
    end = start + len(find)
    _split_at(paragraph_el, start)
    _split_at(paragraph_el, end)

    affected: List[Tuple[Any, str]] = []
    position = 0
    for run in paragraph_el.findall(qn("w:r")):
        run_text = _run_text(run)
        run_start, run_end = position, position + len(run_text)
        position = run_end
        if run_end <= start or run_start >= end:
            continue
        affected.append((run, run_text))
    if not affected:
        return False

    deleted = OxmlElement("w:del")
    deleted.set(qn("w:id"), str(revision_id))
    deleted.set(qn("w:author"), author)
    deleted.set(qn("w:date"), date)
    for run, run_text in affected:
        deleted.append(_new_run(run, run_text, deleted=True))

    inserted = OxmlElement("w:ins")
    inserted.set(qn("w:id"), str(revision_id + 1))
    inserted.set(qn("w:author"), author)
    inserted.set(qn("w:date"), date)
    inserted.append(_new_run(affected[0][0], replace))

    first_run = affected[0][0]
    first_run.addprevious(deleted)
    first_run.addprevious(inserted)
    for run, _text in affected:
        paragraph_el.remove(run)
    return True


def _add_review_comment(
    document: Any,
    find: str,
    comment: str,
    author: str,
    warnings: List[Dict[str, str]],
) -> None:
    try:
        result = _apply_docx_add_comment(
            document,
            {"find": find, "comment": comment, "author": author},
            "add_comment",
        )
        if not result.get("ok"):
            raise OfficeParseError("批注写入未完成")
    except Exception as exc:  # noqa: BLE001 — comments must not block revisions
        warnings.append(
            {
                "code": "comment_failed",
                "message": f"批注添加失败（{find[:40]}）: {str(exc)[:200]}",
            }
        )


def _save_and_replace(document: Any, temporary: Path, target: Path) -> None:
    try:
        document.save(str(temporary))
        last_exc: Optional[Exception] = None
        for delay in _SAVE_RETRY_DELAYS:
            if delay:
                time.sleep(delay)
            try:
                temporary.replace(target)
                return
            except PermissionError as exc:
                last_exc = exc
        if last_exc is not None:
            raise OfficeParseError(f"原子替换失败: {last_exc}") from last_exc
    finally:
        try:
            if temporary.exists():
                temporary.unlink()
        except OSError:
            pass


def apply_word_revisions(
    file_path: Path,
    changes: List[Dict[str, Any]],
    output_filename: Optional[str] = None,
    *,
    overwrite: bool = False,
    author: str = "Sage",
    workspace_path: Optional[str] = None,
    rule_pack_id: str = "",
    add_comments: bool = True,
) -> WordRevisionResult:
    """Write tracked changes/comments into a new (or overwritten) .docx."""
    path = Path(file_path)
    if not path.exists():
        raise OfficeFileNotFoundError(path)
    if not path.is_file():
        raise OfficeParseError("DOCX 路径不是文件")
    if path.suffix.lower() != ".docx":
        raise OfficeParseError("仅支持 .docx 修订写入")
    if not changes:
        raise OfficeParseError("没有可应用的修订")
    if overwrite and output_filename:
        raise OfficeParseError("overwrite=true 时不能指定 output_filename")
    root = Path(workspace_path).resolve() if workspace_path else path.parent.resolve()
    if not root.is_dir():
        raise OfficeParseError("工作区目录不存在")
    try:
        document = Document(str(path))
    except Exception as exc:  # noqa: BLE001 — map all parse failures
        raise OfficeParseError(f"Failed to parse DOCX: {exc}") from exc

    warnings: List[Dict[str, str]] = []
    results: List[WordRevisionChange] = []
    applied = 0
    revision_id = _next_revision_id(document)
    date = datetime.now(timezone.utc).isoformat(timespec="seconds")  # noqa: UP017 — py38
    seen: set = set()
    for raw in changes:
        find = str(raw.get("find") or "")
        replace = str(raw.get("replace") or "")
        comment = str(raw.get("comment") or "")
        rule_id = raw.get("rule_id")
        key = (find, replace)
        if not find:
            results.append(
                WordRevisionChange(
                    rule_id=rule_id,
                    find=find or "(empty)",
                    replace=replace,
                    comment=comment,
                    applied=False,
                    reason="find 为空",
                )
            )
            continue
        if key in seen:
            results.append(
                WordRevisionChange(
                    rule_id=rule_id,
                    find=find,
                    replace=replace,
                    comment=comment,
                    applied=False,
                    reason="重复修订",
                )
            )
            continue
        seen.add(key)
        paragraph = _docx_locate_paragraph_with_text(document, find)
        if paragraph is None:
            results.append(
                WordRevisionChange(
                    rule_id=rule_id,
                    find=find,
                    replace=replace,
                    comment=comment,
                    applied=False,
                    reason="未找到目标文本",
                )
            )
            continue
        if add_comments and comment:
            _add_review_comment(document, find, comment, author, warnings)
        ok = _tracked_replace(paragraph, find, replace, author, date, revision_id)
        if ok:
            revision_id += 2
            applied += 1
        results.append(
            WordRevisionChange(
                rule_id=rule_id,
                find=find,
                replace=replace,
                comment=comment,
                applied=ok,
                reason="" if ok else "目标跨非普通文本或无法拆分",
            )
        )

    overwritten = False
    if overwrite:
        target = path
        if applied:
            temporary = path.with_name(path.name + ".m4b-tmp")
            _save_and_replace(document, temporary, target)
            overwritten = True
    else:
        name = _check_output_name(output_filename or f"{path.stem}-revised.docx")
        try:
            target = resolve_within(root, path.parent / name)
        except OfficePathError as exc:
            raise OfficeParseError("输出路径不在工作区内") from exc
        if target == path:
            raise OfficeParseError("输出文件不能覆盖源文件；如需覆盖请使用 overwrite=true")
        if target.exists():
            raise OfficeParseError("输出文件已存在，拒绝覆盖")
        try:
            document.save(str(target))
        except OSError as exc:
            raise OfficeParseError(f"写入修订文件失败: {exc}") from exc

    return WordRevisionResult(
        ok=applied > 0,
        source_path=_rel(path, root),
        output_path=_rel(target, root),
        overwritten=overwritten,
        rule_pack_id=rule_pack_id,
        planned=len(changes),
        applied=applied,
        skipped=len(changes) - applied,
        changes=results,
        remaining=None,
        warnings=warnings,
    )


__all__ = ["apply_word_revisions", "build_revision_plan"]
