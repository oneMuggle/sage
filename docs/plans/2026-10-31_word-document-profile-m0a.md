# Word 文档画像 M0a（只读）实施计划

> 日期：2026-10-31 · 分支：`feat/word-document-profile`
> 基线：`origin/main` = `73501c97f`
> 前置：`docs/plans/2026-10-31_word-document-intelligence.md` 的 M0
> 范围：只读 DocumentProfile；不改现有 `read_docx` 契约、不写回、不做内容控件/修订。

## 1. 目标

补齐 Word 读取的“有损”问题：页面设置、样式级联、段落格式、run 字体/字号/颜色、编号引用、表格合并、书签、域和锚点。以新端点 `POST /api/v1/office/word/profile` 提供，旧 `/word/read` 不变。

## 2. 交付

- `style_resolver.py`
  - docDefaults → styles（basedOn 链）→ 直接 run 格式；
  - 字体 ascii/eastAsia、字号、粗体/斜体/下划线、颜色；
  - 主题字体暂不展开，检测到 `w:*Theme` 时返回 warning。
- `doc_profile.py`
  - sections：页面尺寸/方向/页边距/页眉页脚文本/页码域；
  - styles：解析后的样式列表；
  - paragraphs：样式、对齐、缩进、段前段后、行距、keep-with-next、分页前、编号；
  - runs：文本、有效字体/字号/颜色、粗斜下划线；
  - tables：原始 `w:tc` 网格位置、`gridSpan`、`vMerge`；
  - bookmarks：名称 + 起止锚点；
  - fields：`w:instrText` / `w:fldSimple` 指令；
  - anchors：`part/paragraph_index/run_index/char_start/char_end/text_hash`，表格锚点含 `table_index/row/col`。
- `doc_profile_models.py`：Pydantic 响应模型。
- `POST /api/v1/office/word/profile`：复用现有 workspace 边界与大小限制。

## 3. 契约

```json
{
  "ok": true,
  "source_path": "office/word/<id>/input.docx",
  "summary": {"paragraphs": 12, "tables": 1, "sections": 1, "styles": 40, "bookmarks": 1, "fields": 2},
  "defaults": {"font_ascii": "Calibri", "size_pt": 11.0},
  "sections": [{"index": 0, "page_width_pt": 612.0, "page_height_pt": 792.0, "margin_top_pt": 72.0}],
  "paragraphs": [{
    "index": 0, "style": "BodyCustom", "text": "Hello", "level": 0,
    "alignment": "center", "indent_left_pt": 18.0, "line_spacing": 1.5,
    "runs": [{"index": 0, "text": "Hello", "font_ascii": "Times New Roman", "font_east_asia": "宋体", "size_pt": 14.0, "bold": true, "color": "112233", "anchor": {"paragraph_index": 0, "char_start": 0, "char_end": 5, "text_hash": "…"}}],
    "anchor": {"paragraph_index": 0, "char_start": 0, "char_end": 5, "text_hash": "…"}
  }],
  "tables": [{"index": 0, "rows": 2, "cols": 2, "cells": [{"row": 0, "col": 0, "col_span": 2, "v_merge": null}]}],
  "bookmarks": [{"name": "mark", "anchor": {"paragraph_index": 2, "char_start": 0}, "end_anchor": {"paragraph_index": 2, "char_start": 10}}],
  "fields": [{"instr": " PAGE ", "anchor": {"paragraph_index": 3}}],
  "warnings": []
}
```

## 4. 验收

- 合成 DOCX 测试覆盖页面/样式/run/段落/合并单元格/书签/PAGE 域/锚点；
- 旧 `/word/read` 测试保持通过；
- 主题字体仅告警，不阻塞读取；
- 零新增依赖；py38 / ruff / architecture 通过。

## 5. 非目标（M0b/M1）

- 不写回 DOCX、不做 track changes/内容控件；
- 不做完整主题字体展开（仅 explicit ascii/eastAsia）；
- 不计算 vMerge 的跨行 row_span（只给 vMerge 标记）；
- 不做表格单元格内段落级 run 画像（单元格文本 + 表格锚点）；
- 不做前端 Profile 查看器（M2 文档审校面板时接入）。

## 6. 文件

```
backend/office/style_resolver.py
backend/office/doc_profile.py
backend/office/doc_profile_models.py
backend/api/office_routes.py
backend/tests/unit/office/test_doc_profile.py
backend/tests/integration/test_office_routes.py
docs/technical/117-word-document-profile.md
```
