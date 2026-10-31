# 105 — LaTeX 读取与语义预览（L0 + L1）

> 日期：2026-10-31 · 分支：`feat/latex-read-render`
> 方案：`docs/plans/2026-10-31_latex-read-render.md`、`docs/plans/2026-10-31_word-document-intelligence.md`

## 1. 定位

Sage 原先只能把 `.tex` 当纯文本读取；本功能增加**只读 LaTeX 解析 + 结构化预览**，
覆盖期刊论文/LaTeX 模板的常见结构。**不编译 TeX、不执行宏、不做模板填充**
（L2/L3 另起）。

## 2. 能力

- 解析 `.tex` 项目：主文件、`\input`/`\include`/`\subfile` 递归、循环/越界检测；
- 元数据：`\documentclass`、title/author/affil/email/date/abstract/keywords；
- 内容块：heading / paragraph / list / equation / figure / table / bibliography / code / quote；
- 引用/标签：`\cite`、`\ref`、`\eqref`、`\label`，解析后把引用替换为 `Figure N` /
  `Table N` / `Equation N` / 章节标题；
- 图片：`\includegraphics` 在 ≤2 MiB 且为常见位图/矢量格式时内联为 data URL；
- 参考文献：`thebibliography` 与 `\bibliography{...}`（复用 `backend/office/bibtex.py`）；
- 警告：未知命令/环境、缺失 include/图片/文献、循环、未定义引用、超限等；
- 输出：前端用 `react-markdown + remark-math + rehype-katex` 渲染，数学公式走 KaTeX。

## 3. 代码结构

```
backend/office/latex/
  models.py          # LatexAnchor / LatexBlock / LatexDocument / LatexWarning
  scanner.py         # 注释、命令/参数、环境配对、tabular 行/列切分
  parser.py          # 项目/文件/导言区/正文编排
  inline.py          # 内联 Markdown/纯文本转换、引用/标签/图片
  environments.py    # figure/table/list/bibliography/equation 等环境
  utils.py           # keywords 拆分
  template.py        # .tex + .cls/.sty → TemplateProfile（slots/style/macros）
  filler.py          # 槽位替换 + LaTeX 转义 + 输出新 .tex
  validator.py       # 括号/环境配对/残留占位符校验
  service.py         # workspace 边界、大小限制、read/analyze/fill
```

每个文件 <800 行（architecture-check）。零新增 Python 依赖；py38 hazard scan 0。

## 4. 接入面

| 层 | 入口 | 行为 |
|---|---|---|
| REST | `POST /api/v1/office/latex/read` | `{workspace_path, file_path}` → `{ok, kind:"latex", content, structured, truncated}` |
| 工作区预览 | `GET /api/v1/sessions/{id}/workspace/preview?path=x.tex` | 返回同一形状；`.tex/.ltx` → `kind:"latex"` |
| 产物预览 | `GET /api/v1/sessions/{id}/artifacts/{aid}/content` | `.tex` artifact → `kind:"latex"` |
| Agent 工具 | `office_read_latex` | READ；`requires_tool_context=True`；`_enforce_workspace` + `.tex/.ltx` 白名单 |
| 模板分析 | `POST /api/v1/office/latex/template/analyze` | `.tex` + `.cls/.sty` → `{document_class, packages, macros, style, metadata, slots, warnings}` |
| 模板填充 | `POST /api/v1/office/latex/template/fill` | `{workspace_path, template_path, output_filename, data}` → 新 `.tex` + `validation` |
| 源码审校 | `POST /api/v1/office/latex/audit` | `{workspace_path, file_path, required_sections?}` → issues + summary |
| Agent 工具 | `office_analyze_latex_template` / `office_fill_latex_template` | analyze READ；fill WRITE_LOCAL（file_path 模式） |
| Agent 工具 | `office_audit_latex` | READ；源码级确定性审校，需 workspace 上下文 |
| 前端 | `LatexPreview` | 标题/作者/警告/块渲染/源码切换 |
| 前端 | `LatexTemplatePanel` | Office 页“LaTeX 模板助手”：路径输入 → 槽位表单 → 填充输出 |
| 前端 | `LatexAuditPanel` | Office 页“LaTeX 源码审校”：路径 + 必需章节 → 问题列表 |

`structured` 形状：

```json
{
  "source_path": "paper/main.tex",
  "metadata": {"document_class": "article", "title": "Demo", "authors": ["Alice"]},
  "blocks": [
    {"type": "heading", "level": 1, "text": "Introduction", "anchor": {"file": "paper/main.tex", "line": 8}},
    {"type": "paragraph", "text": "Inline $x^2$."},
    {"type": "equation", "latex": "E=mc^2", "display": true},
    {"type": "figure", "src": "data:image/png;base64,...", "caption": "Architecture"},
    {"type": "table", "headers": ["A"], "rows": [["1"]]},
    {"type": "bibliography", "entries": [{"key": "knuth84", "text": "D. Knuth. 1984."}]}
  ],
  "warnings": [{"code": "unknown_command", "message": "…", "anchor": {"file": "paper/main.tex", "line": 7}}],
  "includes": ["paper/main.tex", "paper/sections/intro.tex"],
  "citations": ["knuth84"]
}
```

### 4.1 模板档案与填充

`template/analyze` 返回：

```json
{
  "ok": true,
  "kind": "latex-template",
  "source_path": "paper/main.tex",
  "document_class": "article",
  "document_options": ["11pt"],
  "packages": ["natbib", "geometry"],
  "style": {"geometry": "a4paper,margin=2cm", "citation_package": "natbib"},
  "macros": {"journalname": {"nargs": 1, "body": "#1"}},
  "slots": [
    {"name": "title", "kind": "command_arg", "type": "text", "required": true, "current_value": "Old"},
    {"name": "author", "kind": "command_arg", "type": "list", "required": true, "current_value": "Old Author"},
    {"name": "abstract", "kind": "environment_body", "type": "rich_text", "required": true, "current_value": "Old abstract."},
    {"name": "placeholder_author_note_1", "kind": "placeholder", "type": "text", "required": true, "current_value": "author_note"}
  ],
  "warnings": []
}
```

`template/fill` 规则：

- 必填槽位缺失 → 422，不写文件；
- 文本做 LaTeX 转义（`\ & % $ # _ { } ~ ^`）；
- `author/affil/institute` 数组用 ` \and ` 连接，`keywords` 用逗号；
- 只替换槽位内容，其他源码原样保留；
- 输出新文件，拒绝覆盖模板/已有文件；
- 写入前校验括号/环境配对；失败不写文件；
- 不自动补 `.bib`、不处理图片槽位（后续 L3）。

### 4.2 源码审校

`audit` 输出 `{ok, source_path, issues, summary, required_sections}`，issue 形状：

```json
{
  "rule_id": "LATEX-CITE-UNDEFINED",
  "severity": "error",
  "category": "citation",
  "message": "引用 key 未在参考文献中找到: missing",
  "anchor": {"file": "paper/main.tex", "line": 8, "column": 1},
  "evidence": {"key": "missing"},
  "fix_hint": "在 .bib 中添加该条目，或修正 \\cite key"
}
```

规则：`LATEX-DOC-CLASS`（error）、`LATEX-META-TITLE/AUTHOR/ABSTRACT`（warning）、
`LATEX-SECTION-REQUIRED`（error，调用方指定）、`LATEX-CITE-UNDEFINED`（error）、
`LATEX-CITE-NO-BIB`（warning）、`LATEX-REF-UNDEFINED`（error）、
`LATEX-FIG/TABLE-CAPTION/LABEL`（warning）、`LATEX-LABEL-DUPLICATE`（warning）、
`LATEX-TODO`（warning）、`LATEX-UNSAFE-COMMAND`（error，含 `\write18`/管道/越界路径）、
`LATEX-INCLUDE`（include 缺失/循环/越界）、`LATEX-BIBLIOGRAPHY`/`LATEX-IMAGE`（资源警告）。

`ok = 无 error`；issue 按 `(rule_id, file, line, message)` 去重。

## 5. 安全与限制

- **不执行 TeX**：只解析源码；未知命令/环境降级为文本 + warning；
- 只读工作区/项目目录内文件；`resolve` 后必须落在 root 内，拒绝绝对路径、`..`、URL、管道；
- 循环 include 检测；单文件 ≤5 MiB、项目 ≤20 MiB、include 深度 ≤20、文件数 ≤200、blocks ≤5000；
- 前端 KaTeX 由 `rehype-katex` 渲染；`LatexPreview` 不使用 `dangerouslySetInnerHTML` 渲染用户文本；
- 不支持：TeX 编译/PDF、`.cls/.sty` 宏展开、zip 项目上传、TikZ 渲染、DOCX↔LaTeX；
- 模板填充不自动补 `.bib`、不处理图片槽位；前端模板面板使用路径输入（暂未接入通用文件选择器）。
- 源码审校只做确定性规则；不做 PDF/版式/页数/字体检查，也不做 LLM 语义审校。

## 6. 测试

- `backend/tests/unit/office/latex/test_template.py`（6）：profile/slots/style/macros、填充转义/必填/拒绝覆盖、validator；
- `backend/tests/unit/office/latex/test_audit.py`（10）：元数据/引用/交叉引用/图表/重复 label/TODO/危险命令/必需章节/include；
- `backend/tests/unit/tools/test_office_latex_template_tool.py`（4）：analyze/fill/缺上下文/缺必填；
- `backend/tests/unit/tools/test_office_latex_audit_tool.py`（3）：上下文/问题清单/越界；
- `backend/tests/integration/test_office_latex_routes.py`（7）：read + template analyze/fill + audit；
- `backend/tests/integration/test_workspace_preview_routes.py`：`.tex` 预览；
- `backend/tests/api/test_artifact_routes.py`：`.tex` artifact；
- `backend/tests/unit/tools/test_office_latex_tool.py`（4）：上下文/成功/越界/后缀；
- `backend/tests/unit/test_profiles_office_tools.py`、`test_tool_bundles_parity.py`：工具面/快照；
- 前端 `src/features/office/__tests__/LatexPreview.test.tsx`（3）、`LatexTemplatePanel.test.tsx`（2）、`LatexAuditPanel.test.tsx`（2）。

## 7. 后续

- L3b：PDF 编译与版式检查（OS 级沙箱）、`latexdiff` 红字版、LLM 语义审校；
- L2 前端增强：通用文件选择器、槽位自动填充建议；
- `.bib` 自动补写、图片槽位、zip 项目上传；TikZ/高级包渲染（可选 PDF 编译通道）。
