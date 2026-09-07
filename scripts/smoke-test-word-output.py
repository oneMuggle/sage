#!/usr/bin/env python3
"""Task 8 手测脚本 — 模拟 LLM 传 markdown 走 office_create 路径生成 Word。

生成路径：
  1. 直接调 _normalize_content 模拟 LLM 字符串输入（测 4 层兜底）
  2. 用 _normalize_content 返回的 dict 构造 OfficeWordGenerateRequest
  3. 调 generate_docx 生成 .docx
  4. 报告输出路径让用户用 Word/LibreOffice 打开

测试三个 bug 是否全部修好：
  ① 内容显示不全 → 走 JSON 字符串路径，验证 LLM 传 JSON 也能全量渲染
  ② 没有格式 → 走 markdown 路径，验证 # ## - 都正确解析
  ③ 字体是 ＭＳ ゴシック → 验证默认 宋体
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

# 直接 import 生产代码走真实路径
from backend.office.markdown_to_paragraphs import parse_markdown_to_paragraphs
from backend.office.models import (
    OfficeDocType,
    OfficeWordGenerateRequest,
    WordParagraphSpec,
)
from backend.office.word import DEFAULT_ASCII_FONT, DEFAULT_EA_FONT, generate_docx
from backend.tools.office_create_tool import OfficeCreateTool

# ── 用户提供的 RP Hub 内容（同 T7 E2E） ──
USER_RP_HUB_MD = """# RP Hub 网页内容整理

📌 网页概况
RP Hub 是一个基于 AI 的角色扮演（RP）聊天 Web 应用。

🎯 主要功能模块

## 1. 聊天与角色卡管理

- 角色卡搜索、添加、删除、批量选择
- 角色卡工坊（创作专属角色卡）

## 2. 多模型配置

- 聊天模型三槽位：质量 / 均衡 / 快速
- 识图模型：独立配置用于图像识别

📝 小结
✅ 多模型槽位 + 独立识图模型
✅ 内置 AI 生图
"""


def test_case(name: str, content, output_path: Path) -> Path:
    """模拟 LLM 调用 office_create 的完整路径。"""
    print(f"\n{'='*60}")
    print(f"[{name}]")
    print(f"  Input type: {type(content).__name__}")
    print(f"  Input (first 100 chars): {str(content)[:100]!r}")

    # 1) _normalize_content 4 层兜底
    normalized = OfficeCreateTool._normalize_content(
        OfficeDocType.WORD, "rp-hub-output.docx", content
    )
    if normalized is None:
        raise AssertionError(f"{name}: _normalize_content returned None")
    print(f"  Normalized: {list(normalized.keys())}")
    if "paragraphs" in normalized:
        print(f"    - paragraphs count: {len(normalized['paragraphs'])}")
        styles = set()
        for p in normalized["paragraphs"]:
            styles.add(
                (p.get("heading") or "-", p.get("style") or "-")
            )
        print(f"    - style combinations: {styles}")

    # 2) 构造 OfficeWordGenerateRequest
    req = OfficeWordGenerateRequest(
        workspace_path=str(output_path.parent),
        filename=output_path.stem,
        title=normalized.get("title", "Test"),
        paragraphs=[WordParagraphSpec(**p) for p in normalized["paragraphs"]],
    )

    # 3) 生成
    generated = generate_docx(req, output_dir=str(output_path.parent))
    print(f"  Generated: {generated}")
    print(f"  File size: {generated.stat().st_size} bytes")

    # 4) 静态检查 docx 内容
    from docx import Document

    doc = Document(str(generated))
    styles_in_doc = [
        (p.text[:40], p.style.name)
        for p in doc.paragraphs
        if p.text.strip()
    ]
    print(f"  Paragraphs in docx ({len(styles_in_doc)} non-empty):")
    for text, style in styles_in_doc[:10]:
        print(f"    [{style}] {text!r}")
    if len(styles_in_doc) > 10:
        print(f"    ... ({len(styles_in_doc) - 10} more)")

    # 5) 静态检查 styles.xml 默认字体
    with zipfile.ZipFile(generated) as zf:
        styles_xml = zf.read("word/styles.xml").decode("utf-8")
    font_found = DEFAULT_EA_FONT in styles_xml
    print(f"  Default font check: eastAsia='{DEFAULT_EA_FONT}' in styles.xml -> {font_found}")
    if not font_found:
        print(f"  WARNING: {DEFAULT_EA_FONT} NOT in styles.xml")
        print(f"  ASCII default: {DEFAULT_ASCII_FONT}")

    return generated


def main() -> int:
    out_dir = Path.home() / "sage-smoke-test"
    out_dir.mkdir(exist_ok=True)

    print(f"Smoke test output dir: {out_dir}")

    # Case A: markdown（bug ② 主要路径）
    case_a = test_case(
        "Case A — markdown (bug ②: 没有格式)",
        USER_RP_HUB_MD,
        out_dir / "A-markdown-rp-hub.docx",
    )

    # Case B: JSON string（bug ① 主要路径）
    json_str = (
        '{"title": "RP Hub JSON 测试", '
        '"paragraphs": [{"text": "这是 JSON 传入的段落", "heading": "h2"}, '
        '{"text": "Bullet 1", "style": "bullet"}, '
        '{"text": "Bullet 2", "style": "bullet"}, '
        '{"text": "结尾段落，🎯 emoji 也应保留"}]}'
    )
    case_b = test_case(
        "Case B — JSON string (bug ①: 内容显示不全)",
        json_str,
        out_dir / "B-json-string.docx",
    )

    # Case C: 纯字符串（旧路径，验证向后兼容）
    case_c = test_case(
        "Case C — 纯字符串 (旧路径，向后兼容)",
        "今天天气真好，心情舒畅。",
        out_dir / "C-plain-string.docx",
    )

    # Case D: 自定义字体
    print("\n" + "=" * 60)
    print("[Case D — 自定义字体 (微软雅黑)]")
    # 直接构造 req 测 font_family 透传
    paras = parse_markdown_to_paragraphs(USER_RP_HUB_MD)
    req = OfficeWordGenerateRequest(
        workspace_path=str(out_dir),
        filename="D-custom-font-yahei",
        title="自定义字体测试",
        paragraphs=[WordParagraphSpec(**p) for p in paras],
        font_family="微软雅黑",
    )
    case_d = generate_docx(req, output_dir=str(out_dir))
    with zipfile.ZipFile(case_d) as zf:
        styles_xml = zf.read("word/styles.xml").decode("utf-8")
    has_yahei = "微软雅黑" in styles_xml
    print(f"  Custom font check: '微软雅黑' in styles.xml -> {has_yahei}")
    print(f"  Generated: {case_d}")

    print("\n" + "=" * 60)
    print("All generated files:")
    for f in sorted(out_dir.glob("*.docx")):
        print(f"  - {f}")
    print("\nOpen the above files with Word / LibreOffice / WPS and check:")
    print("  * Chinese text renders as 宋体 (default) / 微软雅黑 (Case D)")
    print("  * Bullet lists render as bullet-style paragraphs")
    print("  * h1/h2 have heading styles applied")
    print("  * Emoji characters like  📌🎯✅ display correctly")
    print("  * Bugs ①/②/③ are actually fixed")

    return 0


if __name__ == "__main__":
    sys.exit(main())
