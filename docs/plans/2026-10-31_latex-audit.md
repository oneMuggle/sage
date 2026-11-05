# LaTeX 源码审校（L3a）实施计划

> 日期：2026-10-31 · 分支：`feat/latex-audit`
> 基线：`origin/main` = `246265b74`（PR #2695 合并后）
> 前置：`docs/plans/2026-10-31_latex-read-render.md`（L0–L2 已完成）
> 范围：**只做源码级确定性审校**；PDF 编译、`latexdiff` 红字版、渲染级检查留 L3b。

## 1. 目标

对 `.tex` 项目执行确定性审校，输出可定位的问题清单：

- 元数据：`\documentclass`、title、author、abstract；
- 结构：必需章节（调用方指定）、空文档；
- 引用：`\cite` key 是否在 `.bib`/`thebibliography` 中；
- 交叉引用：`\ref`/`\eqref` 是否指向已定义 label；
- 图表：caption / label 是否缺失；
- 标签：重复 label；
- 卫生：TODO/占位符残留；
- 安全：`\write18`/`\openin`/`\openout`、绝对路径/管道 include、外部图片；
- include：缺文件、循环、越界（复用 parser warnings）。

## 2. 非目标（L3b）

- PDF 编译与版式检查（页数/边距/overfull/字体）；
- `latexdiff` 红字版；
- 语义审校（LLM 检查摘要/术语）；
- 自动修复（只输出问题与 fix_hint）。

## 3. 文件

```
backend/office/latex/audit.py       # 规则、issue 聚合、summary
backend/office/latex/service.py     # audit_latex_file（workspace 边界）
backend/api/office_latex_routes.py  # POST /office/latex/audit
backend/tools/office_latex_audit_tool.py  # office_audit_latex（READ）
src/shared/api/latexApi.ts          # auditLatex
src/features/office/LatexAuditPanel.tsx
```

## 4. 规则与 Issue

```json
{
  "rule_id": "LATEX-CITE-UNDEFINED",
  "severity": "error",
  "category": "citation",
  "message": "引用 key 未在参考文献中找到: knuth84",
  "anchor": {"file": "paper/main.tex", "line": 12, "column": 7},
  "evidence": {"key": "knuth84"},
  "fix_hint": "在 .bib 中添加该条目，或修正 \\cite key"
}
```

默认规则：

| rule_id | severity | 说明 |
|---|---|---|
| LATEX-DOC-CLASS | error | 缺少 `\documentclass` |
| LATEX-META-TITLE | warning | 缺少 title |
| LATEX-META-AUTHOR | warning | 缺少 author |
| LATEX-META-ABSTRACT | warning | 缺少 abstract |
| LATEX-SECTION-REQUIRED | error | 调用方指定的必需章节缺失 |
| LATEX-CITE-UNDEFINED | error | cite key 不在参考文献 |
| LATEX-CITE-NO-BIB | warning | 有 cite 但没有参考文献 |
| LATEX-REF-UNDEFINED | error | ref 指向未定义 label |
| LATEX-FIG-CAPTION | warning | 图缺少 caption |
| LATEX-FIG-LABEL | warning | 图缺少 label |
| LATEX-TABLE-CAPTION | warning | 表缺少 caption |
| LATEX-TABLE-LABEL | warning | 表缺少 label |
| LATEX-LABEL-DUPLICATE | warning | 重复 label |
| LATEX-TODO | warning | TODO/占位符残留 |
| LATEX-UNSAFE-COMMAND | error | 危险命令/路径 |
| LATEX-INCLUDE | warning/error | include 缺失/循环/越界 |

`ok = 无 error`；summary 按 severity/category 计数；issue 去重 `(rule_id, file, line, message)`。

## 5. 接入

- REST：`POST /api/v1/office/latex/audit`
  `{workspace_path, file_path, required_sections?: string[]}`
- Tool：`office_audit_latex`（READ，`requires_tool_context=True`，workspace 围栏）
- UI：Office 页 `LatexAuditPanel`：路径输入 + 可选必需章节（逗号分隔）→ 审校 →
  按 severity 分组的问题列表（显示 rule_id / anchor / fix_hint）
- 复用 `LatexTemplatePanel` 的路径处理与 `backendRequest` 模式

## 6. 实施步骤

- [x] 写 audit 规则测试（RED）
- [x] 实现 `audit.py` + `audit_latex_file`
- [x] REST + 集成测试
- [x] Agent 工具 + profile/bundle 同步
- [x] 前端 `latexApi.auditLatex` + `LatexAuditPanel` + Vitest
- [x] ruff / py38 / architecture / typecheck / 前端测试
- [x] 文档更新（技术 105、用户手册 27、手册索引）

## 7. 验收

- 干净模板零 error；
- 缺 documentclass/title/author/abstract、未定义 cite/ref、缺图表 caption/label、重复 label、
  TODO、危险命令、include 越界均能检出并带 file/line；
- `required_sections` 可配置且缺失时 error；
- REST/tool/UI 可用；
- 相关测试全绿，CI 绿。

## 8. 风险

- 规则误报：图表 caption/label 默认 warning，可后续按期刊规则包调 severity；
- `.bib` 解析失败：复用 `bibtex.py`，失败降级为 warning，不阻断其他规则；
- 危险命令扫描是 best-effort：与未来 PDF 编译沙箱叠加，不能替代 OS 级隔离；
- 无 TeX 引擎：本阶段不做版式/页数断言。

## 9. 实施记录（2026-10-31）

已完成：

- `backend/office/latex/audit.py`：元数据/必需章节/引用/交叉引用/图表 caption+label/
  重复 label/TODO/危险命令（含 `\write18`、管道、越界路径）/include 警告；
- REST `POST /api/v1/office/latex/audit`；
- Agent 工具 `office_audit_latex`（READ、workspace 围栏）；
- 前端 `LatexAuditPanel`（Office 页）+ `latexApi.auditLatex`；
- 文档：技术 105、用户手册 27（编号冲突已从 18 修正为 27）；
- 测试：L3 相关 43 项 + 全量 LaTeX/预览/工具回归 107 项；前端 `LatexAuditPanel` 2 项 +
  `Office.workspace`/`fontScaleGate` 回归；ruff/py38/architecture/typecheck 全绿。

未做（L3b）：PDF 编译/版式检查、`latexdiff` 红字版、LLM 语义审校、自动修复。
