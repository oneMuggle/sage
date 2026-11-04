# LaTeX 投稿合规检查（L4d）实施计划

> 日期：2026-10-31 · 分支：`feat/latex-compliance`
> 基线：`origin/main` = `c9e564d80`（L4c PR #2715 合并后）
> 前置：L3a 源码审校、L4b PDF 版式审计
> 范围：**只读合规检查**；把源码与 PDF 的确定性规则按规范档案汇总为检查项。

## 1. 目标

期刊投稿要求通常是一组规则：必需章节/元数据、页数与页面尺寸、字体嵌入、图片 DPI、禁用命令。
此前源码审校与 PDF 审计是两个独立入口，用户需要自己对照期刊要求。本阶段提供：

- 可配置规范档案（inline profile）；
- 一次调用同时检查 `.tex` 与可选 `.pdf`；
- 输出逐项 `checks`（pass/warn/fail/skipped）+ 合并后的 issue 列表（`source: tex|pdf`）。

## 2. 规范档案

```json
{
  "required_sections": ["Introduction", "Conclusion"],
  "required_metadata": ["title", "author", "abstract", "keywords"],
  "allowed_page_sizes": ["A4"],
  "required_min_pages": 8,
  "required_max_pages": 20,
  "require_embedded_fonts": true,
  "min_image_dpi": 300,
  "forbidden_commands": ["write18", "todo"]
}
```

支持元数据键：`document_class`、`title`、`author`、`abstract`、`keywords`、`affiliation`、`email`、`date`。
页面尺寸：`A4`、`Letter`、`Legal`（大小写不敏感）。

## 3. 契约

`POST /api/v1/office/latex/compliance/check`

```json
{
  "workspace_path": "/ws",
  "tex_path": "/ws/paper/main.tex",
  "pdf_path": "/ws/paper/main.pdf",
  "profile": { "...": "..." }
}
```

响应：

```json
{
  "ok": false,
  "tex_path": "paper/main.tex",
  "pdf_path": "paper/main.pdf",
  "summary": {"count": 2, "severity": {"error": 1, "warning": 1, "info": 0}},
  "checks": [
    {"id": "tex.sections", "label": "必需章节", "status": "pass", "message": "", "rule_ids": []},
    {"id": "pdf.fonts", "label": "字体嵌入", "status": "fail", "message": "1 个字体未嵌入", "rule_ids": ["PDF-FONT-NOT-EMBEDDED"]}
  ],
  "issues": [
    {"source": "pdf", "rule_id": "PDF-FONT-NOT-EMBEDDED", "severity": "error", "...": "..."}
  ]
}
```

check id：`tex.sections`、`tex.metadata`、`tex.commands`、`pdf.page_count`、`pdf.page_size`、`pdf.fonts`、`pdf.images`。

## 4. 规则映射

| 检查 | 规则 |
|---|---|
| 必需章节 | 复用 `LATEX-SECTION-REQUIRED` |
| 必需元数据 | 新增 `LATEX-META-REQUIRED`（error） |
| 禁用命令 | 新增 `LATEX-COMMAND-FORBIDDEN`（error） |
| 页数 | 复用 `PDF-PAGE-COUNT` |
| 页面尺寸 | 新增 `PDF-PAGE-SIZE-NOT-ALLOWED`（error） |
| 字体嵌入 | 复用 `PDF-FONT-NOT-EMBEDDED`；未要求时跳过并过滤 |
| 图片 DPI | 复用 `PDF-IMAGE-LOW-DPI` |

## 5. 文件

```
backend/office/latex/compliance.py          # 核心检查与 checks 汇总
backend/office/latex/service.py             # workspace 边界入口
backend/api/office_latex_routes.py          # /compliance/check
backend/tools/office_latex_compliance_tool.py  # office_check_latex_compliance
src/shared/api/latexApi.ts
src/features/office/LatexCompliancePanel.tsx
src/pages/Office.tsx
```

## 6. 安全与限制

- 只读工作区 `.tex` / `.pdf`，不修改文件、不执行 TeX；
- PDF 可选；未提供时 PDF 检查标记 skipped；
- 加密 PDF 直接拒绝；PDF 审计限制沿用 L4b（≤100 MiB、≤500 页分析）；
- 禁止命令只做源码匹配，不执行。

## 7. 实施步骤

- [x] compliance 核心 + 单测
- [x] service + REST + 集成测试
- [x] Agent 工具 + profile/bundle 同步
- [x] 前端合规面板 + Vitest
- [x] 文档（技术 105、用户手册 27）
- [x] ruff / py38 / architecture / typecheck / tests

## 8. 非目标

- 不做期刊规则库自动下载/解析；
- 不做视觉排版检查（页边距、双栏、行距）；
- 不做自动修复，只给问题与建议。
