"""Word 格式自动修复（Round 12）—— lint → repair → 复检闭环。

与 :func:`backend.office.word_lint.lint_docx` 配对：Linter 查出违规，
本模块对**可机械修复**的违规执行确定性修复：

- 样式/页面组（page/body/headings/title/header/footer）→ 直接复用
  :func:`backend.office.word_layout.apply_format_spec`（对已加载文档
  再应用一次即是修复，幂等）；
- 编号组（numbering/sequence）→ 按文档内 Heading 1-5 出现顺序重算
  "N/N.M/N.M.K/N.M.K.J/N.M.K.J.I" 前缀（剥离旧前缀再写入；参考文献节
  标题跳过，与生成器/Linter 行为对偶）；
- 题注组（caption/sequence）→ 图/表题注按出现顺序重排编号；
- 语义组（citation/coverage）→ **不可自动修**（需要人工判断缺的是
  哪条引用），保留在复检结果中。

安全语义：
- 默认写**新文件** ``<stem>-repaired.docx``，绝不覆盖原文件；
  ``overwrite=True`` 时经临时名 + ``os.replace`` 原子替换原文件；
- 修复后自动复检（lint），remaining 携带未消除的违规；
- 纯本地操作，零网络。
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Optional

from docx import Document
from docx.oxml.ns import qn

from .errors import OfficeParseError
from .models import WordFormatSpec, WordRepairResult
from .word_layout import apply_format_spec
from .word_lint import (
    _FIGURE_CAPTION_RE,
    _HEADING_PREFIX_RE,
    _TABLE_CAPTION_RE,
    lint_docx,
)

#: 样式/页面组 rule_id 前缀（可由 apply_format_spec 幂等修复）
_STYLE_RULE_PREFIXES = ("page/", "body/", "headings/", "title/", "header/", "footer/")

# Round 20 起 lint/生成已覆盖 h1-h5，修复端保持同一级别集合
_HEADING_STYLES = {
    "Heading 1": 1,
    "Heading 2": 2,
    "Heading 3": 3,
    "Heading 4": 4,
    "Heading 5": 5,
}


def _renumber_headings(doc: Document, bib_heading: str) -> None:
    """按出现顺序重排正文标题的多级编号前缀（剥离旧前缀再写入）。

    标题文本经 ``para.text`` 重写（run 合并为单 run）——标题格式来自
    样式定义，重写不损失外观。
    """
    counters = [0] * len(_HEADING_STYLES)
    for para in doc.paragraphs:
        style_name = para.style.name if para.style is not None else ""
        level = _HEADING_STYLES.get(style_name)
        if level is None:
            continue
        if para.text.strip() == bib_heading:
            continue
        counters[level - 1] += 1
        for idx in range(level, len(counters)):
            counters[idx] = 0
        prefix = ".".join(str(counters[i]) for i in range(level))
        stripped = _HEADING_PREFIX_RE.sub("", para.text)
        para.text = f"{prefix} {stripped}"


def _rewrite_seq_caption_number(para, new_number: int) -> None:
    """仅改 SEQ 题注段的缓存编号 run（Round 48 缺陷修复）。

    ``para.text = ...`` 整体重写会摧毁 R42 引入的 SEQ 域与书签（交叉
    引用/图表目录收录随之失效）——这里定位 separate 与 end 之间的纯
    数字缓存 run，只改它的文本，域结构原样保留。
    """
    from docx.oxml.ns import qn

    state = "outside"
    for run in para.runs:
        for fld in run._r.findall(qn("w:fldChar")):
            fld_type = fld.get(qn("w:fldCharType"))
            if fld_type == "begin":
                state = "in_instr"
            elif fld_type == "separate" and state == "in_instr":
                state = "in_cache"
            elif fld_type == "end":
                state = "outside"
        if state == "in_cache" and run.text.strip().isdigit():
            run.text = str(new_number)
            return


def _renumber_captions(doc: Document) -> None:
    """图/表题注按出现顺序重排编号（保留 "图N　" 之外的文本）。

    携带 SEQ 域的题注段（Round 42）只改缓存编号 run，不整体重写。
    """
    for label, regex in (("图", _FIGURE_CAPTION_RE), ("表", _TABLE_CAPTION_RE)):
        seq = 0
        for para in doc.paragraphs:
            if regex.match(para.text):
                seq += 1
                has_seq = any(
                    "SEQ" in (el.text or "")
                    for el in para._p.findall(".//" + qn("w:instrText"))
                )
                if has_seq:
                    _rewrite_seq_caption_number(para, seq)
                else:
                    para.text = re.sub(
                        rf"^{label}\d+", f"{label}{seq}", para.text, count=1
                    )


def _collect_seq_captions(doc: Document, label: str) -> list:
    """按文档顺序收集指定 label 的题注条目 [(编号, 文本)]。

    与 lint 同款域缓存跳过——目录/图目录缓存行不当作题注。
    """
    from .word_lint import _iter_paragraphs_outside_fields

    regex = _FIGURE_CAPTION_RE if label == "图" else _TABLE_CAPTION_RE
    entries = []
    for para in _iter_paragraphs_outside_fields(doc):
        match = regex.match(para.text)
        if match is not None:
            entries.append((int(match.group(1)), regex.match(para.text).string[match.end():].strip()))
    return entries


def _insert_tof_before_body(doc, index_spec, label: str, entries: list) -> None:
    """在文档前部插入 TOF 域（目录域之后；无目录则首段之前）。

    insert_paragraph_before 逐段前插：按期望顺序依次插入即落在锚点前。
    """
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt

    from .word_layout import _fld_char

    anchor = doc.paragraphs[0] if doc.paragraphs else None
    if anchor is None:
        return

    def _new_para(text: str = "", bold: bool = False, size: Optional[object] = None):
        para = anchor.insert_paragraph_before(text)
        if bold and para.runs:
            para.runs[0].bold = True
        if size is not None and para.runs:
            para.runs[0].font.size = size
        return para

    title = _new_para(str(index_spec.heading_text), bold=True, size=Pt(16))
    _ = title
    begin_para = anchor.insert_paragraph_before()
    _fld_char(begin_para, "begin")
    instr_el = OxmlElement("w:instrText")
    instr_el.set(qn("xml:space"), "preserve")
    instr_el.text = rf" TOC \h \z \c {label!r} ".replace("'", '"')
    begin_para._p.append(instr_el)
    _fld_char(begin_para, "separate")
    if entries:
        for number, text in entries:
            anchor.insert_paragraph_before(f"{label}{number}　{text}")
    else:
        anchor.insert_paragraph_before(str(index_spec.placeholder_text))
    end_para = anchor.insert_paragraph_before()
    _fld_char(end_para, "end")


def repair_docx(path: Path, spec: WordFormatSpec, *, overwrite: bool = False) -> WordRepairResult:
    """对照 FormatSpec 自动修复 .docx 的可机械修复违规，修复后复检。

    默认写新文件 ``<stem>-repaired.docx``；``overwrite=True`` 时经
    临时名 + ``os.replace`` 原子替换原文件。解析失败抛
    :class:`OfficeParseError`（调用方映射 422）。
    """
    try:
        doc = Document(str(path))
    except Exception as exc:
        raise OfficeParseError(f"无法解析 docx: {exc}") from exc

    before = lint_docx(path, spec)
    repaired: set = set()

    # 样式/页面组：apply_format_spec 幂等修复
    style_issues = [
        i for i in before.issues if i.rule_id.startswith(_STYLE_RULE_PREFIXES)
    ]
    if style_issues:
        apply_format_spec(doc, spec)
        repaired.update(i.rule_id for i in style_issues)

    # 编号组
    bib_heading = (
        spec.bibliography.heading_text if spec.bibliography is not None else "参考文献"
    )
    if spec.numbering and any(i.rule_id == "numbering/sequence" for i in before.issues):
        _renumber_headings(doc, bib_heading)
        repaired.add("numbering/sequence")

    # 题注组
    if any(i.rule_id == "caption/sequence" for i in before.issues):
        _renumber_captions(doc)
        repaired.add("caption/sequence")

    # Round 48：图/表目录域在位修复——从文档自身 SEQ 题注构建条目，
    # 在目录域之后（无目录则文档首段之前）插入 TOF 域。
    index_fixes = {
        "figure_index/presence": ("图", spec.figure_index),
        "table_index/presence": ("表", spec.table_index),
    }
    for rule_id, (label, index_spec) in index_fixes.items():
        if index_spec is None or not any(
            i.rule_id == rule_id for i in before.issues
        ):
            continue
        from .models import WordIndexSpec

        entries = _collect_seq_captions(doc, label)
        _insert_tof_before_body(
            doc, index_spec if index_spec is not None else WordIndexSpec(), label, entries
        )
        repaired.add(rule_id)

    # 保存：默认新文件；overwrite 走临时名 + os.replace 原子替换
    # （Windows Defender 会短暂锁住新落盘文件，与 edit.py 同款退避重试）
    if overwrite:
        target = path
        tmp = path.with_name(path.name + ".repair-tmp")
        doc.save(str(tmp))
        last_exc: Optional[Exception] = None
        for delay in (0.0, 0.1, 0.25, 0.5, 1.0):
            if delay:
                time.sleep(delay)
            try:
                tmp.replace(target)
                last_exc = None
                break
            except PermissionError as exc:
                last_exc = exc
        if last_exc is not None:
            raise last_exc
    else:
        target = path.with_name(path.stem + "-repaired.docx")
        doc.save(str(target))

    remaining = lint_docx(target, spec)
    return WordRepairResult(
        ok=remaining.ok,
        repaired_rules=sorted(repaired),
        output_path=str(target),
        overwrite=overwrite,
        remaining=remaining,
    )
