"""PDF 解析质量信号与打分（纯函数；PyMuPDF 惰性导入）。

本地提取器给出的文本质量决定是否值得升级到 MinerU 深度解析：文本过少、
空白页占比过高、含表格/公式的版面，本地纯文本抽取大概率丢失结构。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

#: 文本中出现的数学符号或 LaTeX 命令 → 判定含公式
_FORMULA_RE = re.compile(r"[∑∫√≈≠≤≥∂∞±×÷]|\\(frac|sum|int|sqrt|alpha|beta|theta)")

#: 单页字符数低于该值视为"文本稀疏"
LOW_TEXT_PER_PAGE = 120.0
#: 空白页占比高于该值视为"扫描件/图片版"
HIGH_BLANK_RATIO = 0.5


@dataclass(frozen=True)
class QualitySignals:
    page_count: int
    text_per_page: float
    blank_page_ratio: float
    has_table: bool
    has_formula: bool


def score_quality(signals: QualitySignals) -> float:
    """0.0–1.0 质量分：逐项扣分，下限 0，保留 3 位小数。"""
    score = 1.0
    if signals.text_per_page < LOW_TEXT_PER_PAGE:
        score -= 0.35
    if signals.blank_page_ratio > HIGH_BLANK_RATIO:
        score -= 0.30
    if signals.has_table:
        score -= 0.25
    if signals.has_formula:
        score -= 0.20
    return round(max(0.0, score), 3)


def compute_pdf_signals(content: bytes) -> Optional[QualitySignals]:
    """从 PDF 字节计算质量信号；损坏/不可解析时返回 None（交给提取器报错）。"""
    from backend.core.lazy import load_module

    pymupdf = load_module("pymupdf", "pymupdf", globals())
    try:
        doc = pymupdf.open(stream=content, filetype="pdf")
    except Exception:  # noqa: BLE001 — 损坏 PDF 由本地提取器统一报错
        return None
    try:
        page_count = doc.page_count
        if page_count <= 0:
            return QualitySignals(0, 0.0, 1.0, False, False)
        texts = [page.get_text("text") for page in doc]
        total_chars = sum(len(text.strip()) for text in texts)
        blank_pages = sum(1 for text in texts if not text.strip())
        has_table = False
        for page in doc:
            try:
                if page.find_tables().tables:
                    has_table = True
                    break
            except Exception:  # noqa: BLE001 — 单页表格探测失败不影响整体
                continue
        has_formula = bool(_FORMULA_RE.search("\n".join(texts)))
        return QualitySignals(
            page_count=page_count,
            text_per_page=round(total_chars / page_count, 2),
            blank_page_ratio=round(blank_pages / page_count, 3),
            has_table=has_table,
            has_formula=has_formula,
        )
    finally:
        doc.close()
