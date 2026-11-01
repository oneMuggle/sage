# 117 — Word 文档画像（M0a，只读）

> 日期：2026-10-31 · 分支：`feat/word-document-profile`
> 方案：`docs/plans/2026-10-31_word-document-intelligence.md`（M0）、`docs/plans/2026-10-31_word-document-profile-m0a.md`

## 1. 定位

补齐 DOCX 读取的“有损”缺口，为后续模板填充、规则审校、锚点定位提供**只读结构化画像**。
旧 `POST /api/v1/office/word/read` 契约不变；本功能新增 `POST /api/v1/office/word/profile`。

## 2. 能力

- **页面**：页面宽高（pt）、方向、页边距、页眉/页脚距离、页眉页脚文本、PAGE 域标记；
- **样式**：docDefaults → `w:style` basedOn 链 → 直接 run 格式；
  - 字体 ascii / eastAsia、字号（pt）、粗体/斜体/下划线、颜色；
- **段落**：样式、标题级别（Heading N）、对齐、左右/首行缩进、段前段后、行距/规则、
  keep-with-next、分页前、编号（numId/level/format/text）；
- **run**：文本 + 有效格式 + 段内字符区间；
- **表格**：原始 `w:tc` 网格位置、`gridSpan`、`vMerge`、单元格文本；
- **书签**：名称 + 起止锚点；
- **域**：`w:instrText` / `w:fldSimple` 指令；
- **锚点**：`part / paragraph_index / run_index / char_start / char_end / text_hash`，
  表格锚点附 `table_index / row / col`。

## 3. 代码结构

```
backend/office/style_resolver.py        # docDefaults/styles basedOn/direct rPr
backend/office/doc_profile.py           # sections/styles/paragraphs/runs/tables/bookmarks/fields
backend/office/doc_profile_models.py    # Pydantic 响应模型
backend/api/office_routes.py            # POST /word/profile
```

零新增依赖（python-docx 已有）。

## 4. 契约

请求与 `/word/read` 相同：

```json
{"workspace_path": "/ws", "file_path": "/ws/office/word/<id>/input.docx"}
```

响应核心形状：

```json
{
  "ok": true,
  "source_path": "office/word/<id>/input.docx",
  "summary": {"paragraphs": 12, "tables": 1, "sections": 1, "styles": 40, "bookmarks": 1, "fields": 2},
  "defaults": {"font_ascii": "Calibri", "size_pt": 11.0},
  "sections": [{"index": 0, "page_width_pt": 612.0, "page_height_pt": 792.0, "orientation": "portrait", "margin_top_pt": 72.0}],
  "paragraphs": [{
    "index": 0,
    "style": "BodyCustom",
    "text": "Hello",
    "level": 0,
    "alignment": "center",
    "indent_left_pt": 18.0,
    "line_spacing": 1.5,
    "runs": [{
      "index": 0,
      "text": "Hello",
      "font_ascii": "Times New Roman",
      "font_east_asia": "宋体",
      "size_pt": 14.0,
      "bold": true,
      "italic": true,
      "underline": true,
      "color": "112233",
      "anchor": {"paragraph_index": 0, "run_index": 0, "char_start": 0, "char_end": 5, "text_hash": "…"}
    }]
  }],
  "tables": [{"index": 0, "rows": 2, "cols": 2, "cells": [{"row": 0, "col": 0, "col_span": 2, "v_merge": null}]}],
  "bookmarks": [{"name": "mark", "anchor": {"paragraph_index": 2, "char_start": 0}, "end_anchor": {"paragraph_index": 2, "char_start": 10}}],
  "fields": [{"instr": " PAGE ", "anchor": {"paragraph_index": 3}}],
  "warnings": []
}
```

## 5. 限制

- 主题字体不展开：仅解析显式 `w:ascii/w:hAnsi/w:eastAsia`；检测到 `w:*Theme` 返回
  `theme_fonts_unresolved` warning；
- 表格 `vMerge` 只输出标记（`restart`/`continue`），暂不计算跨行 `row_span`；
- 表格单元格内不输出 run 级画像（单元格文本 + 表格锚点即可用于定位）；
- 内容控件、修订（track changes）、文本框/图形暂不输出（M0b/M1）；
- 只读，不写回 DOCX。

## 6. 测试

- `backend/tests/unit/office/test_doc_profile.py`（4）：页面/样式/run 格式/合并单元格/
  书签/PAGE 域/非 docx 拒绝；
- `backend/tests/integration/test_office_routes.py`：`/word/profile` 端点；
- ruff / py38 / architecture 门禁通过。
