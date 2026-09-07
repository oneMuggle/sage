"""用用户提供的 RP Hub 内容做 E2E 验证。

模拟用户场景：用户给 LLM 一段网页内容，LLM 用 office_create 写入 Word。
我们直接走 markdown → generate_docx 路径，验证：
- 标题正确
- h2 / h3 标题层级正确
- bullet 列表渲染为 List Bullet
- emoji 原样保留
- 默认字体 = 宋体
"""
from __future__ import annotations

import zipfile
from pathlib import Path

from docx import Document

from backend.office.markdown_to_paragraphs import parse_markdown_to_paragraphs
from backend.office.models import (
    OfficeWordGenerateRequest,
    WordParagraphSpec,
)
from backend.office.word import DEFAULT_EA_FONT, generate_docx

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


def test_e2e_rp_hub_markdown_to_paragraphs_parses_correctly() -> None:
    """markdown 解析器对用户内容产出正确段落结构。"""
    paras = parse_markdown_to_paragraphs(USER_RP_HUB_MD)
    headings = [p["text"] for p in paras if p["heading"]]
    bullets = [p["text"] for p in paras if p["style"] == "bullet"]

    assert "RP Hub 网页内容整理" in headings
    assert "1. 聊天与角色卡管理" in headings
    assert "2. 多模型配置" in headings

    assert "角色卡搜索、添加、删除、批量选择" in bullets
    assert "角色卡工坊（创作专属角色卡）" in bullets
    assert "识图模型：独立配置用于图像识别" in bullets


def test_e2e_rp_hub_emoji_preserved_in_paragraphs() -> None:
    """emoji 原样保留不被转义。"""
    paras = parse_markdown_to_paragraphs(USER_RP_HUB_MD)
    all_text = "\n".join(p["text"] for p in paras)
    assert "📌" in all_text
    assert "🎯" in all_text
    assert "📝" in all_text
    assert "✅" in all_text


def test_e2e_rp_hub_generate_docx_renders_correctly(tmp_path: Path) -> None:
    """完整链路：markdown → generate_docx → docx 内容。"""
    paras = parse_markdown_to_paragraphs(USER_RP_HUB_MD)
    req = OfficeWordGenerateRequest(
        workspace_path=str(tmp_path),
        filename="RP Hub 网页内容整理",
        title="RP Hub 网页内容整理",
        paragraphs=[WordParagraphSpec(**p) for p in paras],
    )
    output_path = generate_docx(req)

    assert output_path.exists()
    doc = Document(str(output_path))

    # 标题存在
    assert "RP Hub 网页内容整理" in [p.text for p in doc.paragraphs]

    # h2 标题存在
    pstyles = {p.text: p.style.name for p in doc.paragraphs if p.text}
    assert pstyles.get("1. 聊天与角色卡管理") == "Heading 2"
    assert pstyles.get("2. 多模型配置") == "Heading 2"

    # bullet 渲染为 List Bullet
    list_bullet_count = sum(
        1 for p in doc.paragraphs
        if p.style.name == "List Bullet" and "角色卡" in p.text
    )
    assert list_bullet_count >= 2

    # emoji 写入文件后仍存在
    all_text = "\n".join(p.text for p in doc.paragraphs)
    assert "📌" in all_text
    assert "✅" in all_text


def test_e2e_rp_hub_default_font_set(tmp_path: Path) -> None:
    """生成的 docx 默认字体 = 宋体。"""
    paras = parse_markdown_to_paragraphs(USER_RP_HUB_MD)
    req = OfficeWordGenerateRequest(
        workspace_path=str(tmp_path),
        filename="RP Hub",
        title="RP Hub",
        paragraphs=[WordParagraphSpec(**p) for p in paras],
    )
    output_path = generate_docx(req)
    with zipfile.ZipFile(output_path) as zf:
        styles_xml = zf.read("word/styles.xml").decode("utf-8")
    assert f'w:eastAsia="{DEFAULT_EA_FONT}"' in styles_xml
