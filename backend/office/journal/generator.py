"""结构化 fill 模式：把 JournalContent 写入 docx 模板。

实现思路：
- 复制 spec 模板到 <workspace>/office/journal/generated/<uuid>.docx；
- 用 python-docx 打开，按 spec.headings 顺序追加/替换章节；
- 原子 rename 到 output_filename；
- 调用 record_generation 登记 SQLite。

设计要点：
- PEP 604/585 全部禁用（X | None / list[int]）；
- output_filename 是用户输入，必须经 resolve_within 围栏验证不能逃出 generated/；
- 清空 body 时保留 <w:sectPr>（页面尺寸/边距信息）；
- 缓存未命中时从空白 Document 重建是防御性代码（正常流程 parse_journal_spec
  总会缓存模板，但直接调用 generator 而不走 parser 时也需要工作）。
"""
from __future__ import annotations

import shutil
import time
import uuid
from pathlib import Path
from typing import List, Tuple

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

from backend.office.journal.errors import (
    JournalContentShapeError,
    JournalGenerationError,
)
from backend.office.journal.models import (
    JournalContent,
    JournalGenerationRecord,
    JournalSpec,
)
from backend.office.journal.persistence import (
    _layout_paths,
    record_generation,
    save_spec,
)
from backend.office.path_safety import resolve_within


def _validate_content_shape(spec: JournalSpec, content: JournalContent) -> None:
    """校验 content 的必填字段（abstract / keywords）非空。

    与 JournalSpec.validate_content 逻辑对齐，但 generator 入口显式调用
    以保证 structured_fill 和 llm_generate 路径都经过校验。
    """
    if not content.abstract.strip():
        raise JournalContentShapeError("content.abstract 不能为空")
    kw = content.sections.get("keywords", "") or content.sections.get("关键词", "")
    if not kw.strip():
        raise JournalContentShapeError("content.sections['keywords'] 不能为空")


def _set_eastasia_font(style, eastasia: str) -> None:
    """在 style 的 rPr 中设置 w:eastAsia 字体属性。"""
    rPr = style._element.find(qn("w:rPr"))
    if rPr is None:
        rPr = OxmlElement("w:rPr")
        style._element.insert(0, rPr)
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.insert(0, rFonts)
    rFonts.set(qn("w:eastAsia"), eastasia)


def _apply_styles(doc: Document, spec: JournalSpec) -> None:
    """把 spec 的字体/字号/行距/边距强制应用到 doc.styles。"""
    normal = doc.styles["Normal"]
    normal.font.name = spec.font_body.ascii_family or spec.font_body.family
    normal.font.size = Pt(spec.body_pt)
    pf = normal.paragraph_format
    pf.line_spacing = spec.line_spacing
    # CJK eastAsia 字体
    if spec.font_body.eastasia:
        _set_eastasia_font(normal, spec.font_body.eastasia)
    # 边距
    if doc.sections:
        section = doc.sections[0]
        for attr in ("top_margin", "bottom_margin", "left_margin", "right_margin"):
            setattr(section, attr, Cm(spec.margins_cm))


def _make_paragraph(text: str, style_name: str = "Heading1") -> OxmlElement:
    """构造一个 w:p 元素，包含指定 style 和文本内容。"""
    p = OxmlElement("w:p")
    pPr = OxmlElement("w:pPr")
    pStyle = OxmlElement("w:pStyle")
    pStyle.set(qn("w:val"), style_name)
    pPr.append(pStyle)
    p.append(pPr)
    run = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = text
    run.append(t)
    p.append(run)
    return p


def _make_body_paragraph(text: str) -> OxmlElement:
    """构造一个无特殊 style 的正文 w:p 元素。"""
    p = OxmlElement("w:p")
    run = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = text
    run.append(t)
    p.append(run)
    return p


def _write_sections(
    doc: Document, spec: JournalSpec, content: JournalContent
) -> None:
    """按 spec.headings 顺序写入章节。先清空现有正文段落但保留 sectPr。"""
    body = doc._element.body

    # 保留 sectPr（页面尺寸/边距/分栏等），清空其余段落和表格。
    # python-docx 的 doc.sections 读取 body 最后一个 <w:sectPr> 子元素；
    # 如果一并删除会导致 sections 为空、_apply_styles 的边距设置失效。
    sect_pr = body.find(qn("w:sectPr"))
    for child in list(body):
        body.remove(child)
    if sect_pr is not None:
        body.append(sect_pr)

    # 收集要写入的 (heading_text, body_text) 序列
    sections_to_write: List[Tuple[str, str]] = []
    sections_to_write.append(("摘要", content.abstract))
    sections_to_write.append(
        (
            "关键词",
            content.sections.get("keywords", "")
            or content.sections.get("关键词", ""),
        )
    )
    for h in spec.headings:
        if h.keyword in {"摘要", "关键词"}:
            continue
        text = content.sections.get(h.keyword, "")
        if text:
            sections_to_write.append((h.keyword, text))
    if content.references:
        sections_to_write.append(("参考文献", "\n".join(content.references)))

    # 标题（Heading 1 for Title）
    body.append(_make_paragraph(content.title, "Heading1"))

    # 章节内容
    for heading_text, body_text in sections_to_write:
        body.append(_make_paragraph(heading_text, "Heading1"))
        body.append(_make_body_paragraph(body_text))


def generate_structured(
    spec: JournalSpec,
    content: JournalContent,
    workspace: Path,
    output_filename: str,
) -> JournalGenerationRecord:
    """结构化 fill 模式。

    1. 校验 content 形状；
    2. 复制缓存模板到临时文件；
    3. 应用样式 + 写入章节；
    4. 验证 output_filename 不逃逸 generated/ 目录；
    5. 原子 rename 到最终路径；
    6. 登记 SQLite。
    """
    _validate_content_shape(spec, content)
    layout = _layout_paths(workspace)

    # 先写临时名，成功后 os.replace 到最终 output_filename
    tmp_path = layout["generated"] / f".tmp-{uuid.uuid4().hex}.docx"

    # 复制 spec 模板到 tmp。
    # 防御性 fallback：缓存不存在时从空白 Document 重建。正常流程中
    # parse_journal_spec 总会缓存模板到 cache/<sha256>.docx，但直接调用
    # generator 而不走 parser 时也可能出现缓存缺失。
    src_template = (
        workspace / "office" / "journal" / "cache" / f"{spec.template_sha256}.docx"
    )
    if src_template.exists():
        shutil.copy2(src_template, tmp_path)
        doc = Document(str(tmp_path))
    else:
        doc = Document()

    _apply_styles(doc, spec)
    _write_sections(doc, spec, content)
    doc.save(str(tmp_path))

    # 构造最终路径并验证不会逃逸 generated/ 目录。
    # output_filename 是用户输入，可能含 "../../../etc/cron.d/evil" 等注入。
    final_path = layout["generated"] / output_filename
    resolve_within(layout["generated"], final_path)

    if final_path.exists():
        tmp_path.unlink(missing_ok=True)
        raise JournalGenerationError(f"output file exists: {output_filename}")
    tmp_path.replace(final_path)

    # 确保 spec 已注册到 SQLite（FK 约束：office_journal_generations.spec_id
    # REFERENCES office_journal_specs.spec_id）。save_spec 是幂等的（INSERT OR
    # REPLACE），重复调用不会出错。
    save_spec(workspace, spec)

    record = JournalGenerationRecord(
        gen_id=f"gen_{uuid.uuid4().hex[:12]}",
        spec_id=spec.spec_id,
        output_path=str(final_path),
        mode="structured_fill",
        created_at=time.time_ns() // 1_000_000,
        bytes_written=final_path.stat().st_size,
    )
    return record_generation(workspace, record)


import json as _json


async def generate_article(
    spec: JournalSpec,
    user_request: str,
    *,
    llm_proxy,
    workspace: Path,
    output_filename: str,
    max_rounds: int = 2,
) -> JournalGenerationRecord:
    """LLM 自纠生成模式。

    最多 max_rounds 轮，每轮用上轮 validator 反馈注入 prompt 修正。
    最终一轮通过 _validate_content_shape 后调用 generate_structured 生成 docx。

    行为约束：
    - output_filename 仅用于最终落盘文件名；轮间不落盘 docx，避免文件名冲突；
    - 所有轮 LLM 返回的 content 在最后一轮通过 generate_structured 的
      _validate_content_shape 校验（abstract + keywords 非空）；
    - 若所有 max_rounds 轮均未通过校验，最后一次 LLM 返回的 content 仍会
      交给 generate_structured；其 _validate_content_shape 失败将抛
      JournalContentShapeError（YAGNI：不内置多轮 fallback）。
    """
    system_prompt = (
        "你是一位资深中文论文作者，请根据以下期刊模板规范生成论文内容。\n"
        f"期刊规范（JournalSpec JSON）:\n{spec.model_dump_json(indent=2)}\n\n"
        "返回严格符合以下 JSON schema：\n"
        '{"title": str, "abstract": str, "sections": {keyword: str}, '
        '"references": [str], "citations": [str]}'
    )

    last_content: dict = {}
    for round_idx in range(max_rounds):
        user_prompt = (
            f"用户请求: {user_request}\n\n"
            f"请生成论文内容，必须严格匹配 spec 中的 {len(spec.headings)} 个章节: "
            f"{', '.join(h.keyword for h in spec.headings)}"
        )
        if round_idx > 0 and last_content:
            # 把上一轮的校验反馈注入 prompt
            try:
                content_model = JournalContent.model_validate(last_content)
                _validate_content_shape(spec, content_model)
            except Exception as exc:
                user_prompt += f"\n\n上一轮问题: {exc}\n请按规范修正。"
            else:
                # 形状 OK，退出循环
                break

        result = await llm_proxy.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        last_content = _json.loads(result) if isinstance(result, str) else dict(result)

    content = JournalContent.model_validate(last_content)
    inner_rec = generate_structured(spec, content, workspace, output_filename)
    # inner_rec.mode == "structured_fill"（generate_structured 硬编码）；
    # 覆写为 llm_generate 以反映实际生成路径。
    final_rec = JournalGenerationRecord(
        gen_id=inner_rec.gen_id,
        spec_id=inner_rec.spec_id,
        output_path=inner_rec.output_path,
        mode="llm_generate",
        created_at=inner_rec.created_at,
        llm_model=getattr(llm_proxy, 'model', None) or inner_rec.llm_model,
        bytes_written=inner_rec.bytes_written,
        extra=inner_rec.extra,
    )
    return record_generation(workspace, final_rec)


__all__ = ["generate_structured", "generate_article"]
