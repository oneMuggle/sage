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


def _renumber_captions(doc: Document) -> None:
    """图/表题注按出现顺序重排编号（保留 "图N　" 之外的文本）。"""
    for label, regex in (("图", _FIGURE_CAPTION_RE), ("表", _TABLE_CAPTION_RE)):
        seq = 0
        for para in doc.paragraphs:
            if regex.match(para.text):
                seq += 1
                para.text = re.sub(rf"^{label}\d+", f"{label}{seq}", para.text, count=1)


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
