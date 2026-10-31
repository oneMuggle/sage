# LaTeX/PDF 版式审计（L4b）实施计划

> 日期：2026-10-31 · 分支：`feat/latex-pdf-audit`
> 基线：`origin/main` = `086180e02`（L4a PR #2712 合并后）
> 前置：`docs/plans/2026-10-31_latex-compile.md`（L3b 已完成）、`2026-10-31_latex-project-import.md`（L4a）
> 范围：**只读 PDF 分析**；不修改 PDF、不重新编译。

## 1. 目标

源码审校（L3a）只能看 `.tex`。期刊排版要求通常还涉及：

- 页数与页面尺寸（A4/Letter/Legal）；
- 字体是否全部嵌入（投稿 PDF 常见硬性要求）；
- 图片有效分辨率（印刷通常 ≥300 DPI，屏幕 ≥150 DPI）；
- 是否存在加密/混合页面尺寸。

本阶段新增对工作区 `.pdf`（编译产物或外部稿）的确定性审计，返回问题与锚点（页码）。

## 2. 规则

| rule_id | severity | 触发 |
|---|---|---|
| `PDF-ENCRYPTED` | error | PDF 需要密码/已加密 |
| `PDF-PAGE-COUNT` | error | 调用方指定 min/max 页数时超出 |
| `PDF-PAGE-SIZE-MIXED` | warning | 页面尺寸不一致（>2pt 容差） |
| `PDF-PAGE-SIZE-UNUSUAL` | warning | 首页不是 A4/Letter/Legal |
| `PDF-FONT-NOT-EMBEDDED` | error | 任一字体未嵌入（`ext='n/a'`） |
| `PDF-IMAGE-LOW-DPI` | warning | 有效 DPI < 阈值（默认 150），且图片 ≥36pt |
| `PDF-PAGE-LIMIT` | info | 页数超过分析上限，只分析前 500 页 |

`ok = 无 error`。

## 3. 契约

`POST /api/v1/office/latex/pdf/audit`

```json
{
  "workspace_path": "/ws",
  "file_path": "/ws/paper/main.pdf",
  "required_min_pages": 8,
  "required_max_pages": 20,
  "min_image_dpi": 150
}
```

响应：

```json
{
  "ok": false,
  "source_path": "paper/main.pdf",
  "summary": {
    "pages": 12,
    "page_size": {"width": 595.3, "height": 841.9, "label": "A4"},
    "page_sizes": [{"width": 595.3, "height": 841.9, "pages": 12}],
    "fonts": [{"basefont": "Helvetica", "type": "Type1", "embedded": false, "pages": [1]}],
    "images_count": 4,
    "min_image_dpi": 300.0
  },
  "issues": [
    {
      "rule_id": "PDF-FONT-NOT-EMBEDDED",
      "severity": "error",
      "category": "pdf-font",
      "message": "字体未嵌入: Helvetica",
      "anchor": {"file": "paper/main.pdf", "page": 1},
      "evidence": {"basefont": "Helvetica", "type": "Type1"},
      "fix_hint": "导出 PDF 时选择嵌入全部字体"
    }
  ]
}
```

## 4. 文件

```
backend/office/latex/pdf_audit.py          # PyMuPDF 只读审计
backend/office/latex/service.py            # workspace 边界入口
backend/api/office_latex_routes.py         # /pdf/audit
backend/tools/office_latex_pdf_tool.py     # office_audit_latex_pdf
src/shared/api/latexApi.ts                 # auditLatexPdf
src/features/office/LatexPdfAuditPanel.tsx
src/pages/Office.tsx
```

## 5. 安全与限制

- 只读工作区内 `.pdf`；`resolve` 后必须落在 workspace；
- 单文件 ≤100 MiB；页数分析上限 500（超出仍报告总页数）；
- 不执行 TeX、不修改 PDF；
- PyMuPDF 延迟导入；缺失时返回 `OfficeParseError`（422）；
- 加密 PDF 直接拒绝，不尝试破解。

## 6. 实施步骤

- [x] PDF 审计核心 + 单元测试（合成 PDF）
- [x] service + REST + 集成测试
- [x] Agent 工具 + profile/bundle 同步
- [x] 前端 PDF 审计面板 + Vitest
- [x] 文档（技术 105、用户手册 27）
- [x] ruff / py38 / architecture / typecheck / tests

## 7. 非目标

- 不做视觉/OCR 层面的排版检查（页眉页脚位置、双栏、行距等）；
- 不做 PDF 修改/压缩/重新排版；
- 不做期刊模板规则库自动匹配（后续可在规则上叠加）。
