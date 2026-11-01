# Word M5a：渲染级校验

> 日期：2026-11-01 · 分支：`feat/word-render-audit`
> 基线：`origin/main` = `0ecbbd70e`（M4c 合并后）
> 上游方案：`docs/plans/2026-10-31_word-document-intelligence.md`（M5）

## 1. 目标

在结构审校之外增加**渲染后**校验：DOCX 经本机 LibreOffice/Word COM 转 PDF，
再用 PyMuPDF 检查真实排版结果：

- 页面尺寸（A4/Letter 或与首页一致性）；
- 正文块与页面边缘距离（页边距，排除页眉/页脚带）；
- PDF 实际使用字体（子集前缀已归一）；
- 可选逐页页码存在性。

无转换器时**不报错**：返回 `rendered=false` + `render_unavailable` warning，
结构审校仍可用。

## 2. 接口

```http
POST /api/v1/office/word/audit/render
```

```json
{
  "workspace_path": "/ws",
  "file_path": "/ws/doc.docx",
  "expected_size": "A4",
  "margins_cm": {"top": 3.7, "bottom": 3.5, "left": 2.8, "right": 2.6},
  "allowed_fonts": ["仿宋_GB2312", "Times New Roman"],
  "require_page_number": true,
  "margin_tolerance_cm": 0.3,
  "page_number_band": 0.15,
  "timeout_seconds": 120
}
```

响应：`ok/rendered/method/page_count/issues[{page_index,category,severity,message,expected,actual}]/warnings`。

- `category`：`page` / `margin` / `font` / `page_number`；
- 页面尺寸与页边距违规为 `error`；字体与页码缺失为 `warning`；
- `ok=false` 仅当存在 `error` 级 issue。

## 3. 实现

- `backend/office/word_render_audit.py`：
  - `audit_word_render`：校验路径 → 调 `export_to_pdf`（复用 LibreOffice/Word COM、进程内锁）→ `audit_rendered_pdf`；
  - `audit_rendered_pdf`：纯 PDF 读取，便于用合成 PDF 单测；
  - 页码检测：页面底部 15% 文本带内出现纯数字/“第 N 页”；
  - 字体比较：去子集前缀 `ABCDEF+`，允许名互为子串（Arial ↔ ArialMT）。
- 路由：`WordAuditRenderRequest` + 端点；workspace/尺寸上限复用既有围栏。
- 测试注入 `export_fn`，不依赖本机 soffice。

## 4. 实施步骤

- [x] 模型：`WordRenderIssue` / `WordRenderAuditResult`
- [x] 引擎：渲染 + PDF 检查
- [x] 路由 `/audit/render`
- [x] 测试：5 单元（尺寸/边距/字体/页码/降级）+ 2 路由
- [x] 文档：121 + README
- [x] 门禁：ruff / py38 / architecture / pytest / CI

## 5. 验收

- 有转换器时能指出页面尺寸、越界正文、非允许字体、缺失页码；
- 无转换器时返回 rendered=false + warning，不抛错；
- 合成 PDF 单测覆盖主要检查；
- 旧审校/修复/修订接口行为不变。

## 6. 非目标

- 批量审计与报告导出（M5b）；
- 前端渲染审计面板（M5c）；
- 文本溢出单元格/分栏、图表越界等专业排版检查；
- Word COM 精确页码/页眉页脚识别（当前用文本带近似）。
