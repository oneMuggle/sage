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
  compile.py         # 可选外部 TeX 引擎编译（审计门禁/临时目录/禁 shell escape）
  diff.py            # latexdiff 红字版适配
  project.py         # 项目 zip 安全解压 + 主文件识别（不执行内容）
  pdf_audit.py       # PDF 页面尺寸/页数/字体嵌入/图片 DPI 只读审计
  compliance.py      # 规范档案：源码 + 可选 PDF 合并合规检查
  service.py         # workspace 边界、大小限制、read/analyze/fill/audit/compile/diff/extract/pdf/compliance
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
| 能力探测 | `GET /api/v1/office/latex/capabilities` | 本机 TeX 引擎 + latexdiff 可用性 |
| 编译 PDF | `POST /api/v1/office/latex/compile` | `{workspace_path, file_path, output_filename?, engine?, timeout_s?}` → PDF |
| 红字版 | `POST /api/v1/office/latex/diff` | `{workspace_path, original_path, revised_path, ...}` → diff.tex（可选 PDF） |
| 项目导入 | `POST /api/v1/office/latex/project/extract` | `{workspace_path, zip_path, output_dir_name?}` → 解压到新目录 + 主文件 |
| PDF 审计 | `POST /api/v1/office/latex/pdf/audit` | `{workspace_path, file_path, required_min_pages?, required_max_pages?, min_image_dpi?}` → 版式/字体/DPI 问题 |
| 合规检查 | `POST /api/v1/office/latex/compliance/check` | `{workspace_path, tex_path, pdf_path?, profile}` → 逐项 checks + 合并 issues |
| Agent 工具 | `office_analyze_latex_template` / `office_fill_latex_template` | analyze READ；fill WRITE_LOCAL（file_path 模式） |
| Agent 工具 | `office_audit_latex` | READ；源码级确定性审校，需 workspace 上下文 |
| Agent 工具 | `office_compile_latex` / `office_latexdiff` | WRITE_LOCAL；可选外部引擎/latexdiff |
| Agent 工具 | `office_extract_latex_project` | WRITE_LOCAL；工作区内 zip 安全解压 + 主文件识别 |
| Agent 工具 | `office_audit_latex_pdf` | READ；PDF 页数/尺寸/字体嵌入/图片 DPI 审计 |
| Agent 工具 | `office_check_latex_compliance` | READ；规范档案驱动的源码 + 可选 PDF 合规检查 |
| 前端 | `LatexPreview` | 标题/作者/警告/块渲染/源码切换 |
| 前端 | `LatexTemplatePanel` | Office 页“LaTeX 模板助手”：路径输入 → 槽位表单 → 填充输出 |
| 前端 | `LatexAuditPanel` | Office 页“LaTeX 源码审校”：路径 + 必需章节 → 问题列表 |
| 前端 | `LatexBuildPanel` | Office 页“LaTeX 编译与红字版”：编译 PDF / latexdiff |
| 前端 | `LatexProjectImportPanel` | Office 页“LaTeX 项目导入”：zip 路径 → 新目录 + 主文件 |
| 前端 | `LatexPdfAuditPanel` | Office 页“PDF 版式审计”：页数/尺寸/字体/DPI 问题列表 |
| 前端 | `LatexCompliancePanel` | Office 页“LaTeX 投稿合规检查”：规范档案 → checks + issues |

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
- 图片槽位（`type: "image"`）：值必须是工作区内图片（`.png/.jpg/.jpeg/.pdf/.eps/.svg`，≤20 MiB）；复制到 `<输出名>_assets/` 并重写 `\includegraphics` 路径；同名不同源自动 `-N` 去重；
- 输出新文件，拒绝覆盖模板/已有文件；
- 写入前校验括号/环境配对；失败不写文件；
- 不自动补 `.bib`、不处理其它资源槽位（后续 L4c+）。

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

### 4.3 可选编译与红字版

`compile` / `diff` 只在检测到本机外部工具时执行；不捆绑 TeX、不下载宏包：

- 引擎探测：`latexmk` / `xelatex` / `lualatex` / `pdflatex`；
- **编译前强制 audit**：存在 error（含 `\write18`/越界 include 等）即拒绝；
- 临时目录复制项目（≤500 文件 / 50 MiB）；固定参数 `-no-shell-escape -interaction=nonstopmode
  -halt-on-error`；环境 `openin_any=p`、`openout_any=p`、临时 `TEXMFHOME/TEXMFVAR/TEXMFCACHE`；
- 超时 1–600s；日志只回传尾部；
- 无引擎/无 latexdiff 时返回 `{ok:false, code:"no_engine"|"no_latexdiff"}`；
- `latexdiff` 生成 `diff.tex`，可选编译 `diff.pdf`；
- **注意**：这不是 OS 级沙箱；不可信文档不要编译，后续需容器/低权限隔离。

### 4.4 项目 zip 导入

`project/extract` 只做安全解压与主文件识别，不执行/不编译解压内容：

```json
{
  "ok": true,
  "project_dir": "imported",
  "main_file": "imported/paper/main.tex",
  "main_candidates": ["imported/paper/main.tex"],
  "files_count": 42,
  "bytes_written": 1234567,
  "warnings": [{"code": "unsupported_file_skipped", "message": "...", "path": "run.sh"}]
}
```

约束：

- 仅接受工作区内 `.zip`；压缩包 ≤100 MiB、解压总量 ≤200 MiB、单文件 ≤50 MiB、条目 ≤2000；
- 拒绝绝对路径、盘符、`..` 穿越、符号链接、加密 zip、重复/大小写冲突条目、压缩比异常（>200x 且 >10 MiB）；
- 拒绝 Windows 保留名/尾随点或空格/`:`（ADS）/控制字符/大小写冲突条目；
- 只解压文档/资源白名单后缀（`.tex/.ltx/.cls/.sty/.bst/.bib/`图片/字体等），其他跳过并 warning；
- 解压到工作区临时目录，成功后原子 rename 到新目录；目标已存在拒绝覆盖；
- 主文件识别：扫描含 `\documentclass` 的 `.tex/.ltx`，优先 `main/paper/document/template/sample` 命名；
- 无主文件仍解压成功，返回 `main_file: null` + `no_main_tex` warning。

### 4.5 PDF 版式审计

`pdf/audit` 使用 PyMuPDF 只读分析工作区 PDF（不修改文件、不执行 TeX）：

```json
{
  "ok": false,
  "source_path": "paper/main.pdf",
  "summary": {
    "pages": 2,
    "page_size": {"width": 595.3, "height": 841.9, "label": "A4"},
    "page_sizes": [{"width": 595.3, "height": 841.9, "pages": [1, 2]}],
    "fonts": [{"basefont": "Helvetica", "type": "Type1", "ext": "n/a", "embedded": false, "pages": [1]}],
    "images_count": 0,
    "min_image_dpi": null
  },
  "issues": [
    {"rule_id": "PDF-FONT-NOT-EMBEDDED", "severity": "error", "category": "pdf-font",
     "message": "字体未嵌入: Helvetica", "anchor": {"file": "paper/main.pdf", "page": 1},
     "fix_hint": "导出 PDF 时选择嵌入全部字体"}
  ]
}
```

规则：`PDF-ENCRYPTED`（error）、`PDF-PAGE-COUNT`（error，调用方指定 min/max）、
`PDF-PAGE-SIZE-MIXED` / `PDF-PAGE-SIZE-UNUSUAL`（warning）、
`PDF-FONT-NOT-EMBEDDED`（error，`ext` 为 `n/a`/空）、
`PDF-IMAGE-LOW-DPI`（warning，有效 DPI < 阈值且图片 ≥36pt）、
`PDF-PAGE-LIMIT`（info，>500 页只分析前 500 页）。`ok = 无 error`。

限制：单文件 ≤100 MiB；加密 PDF 直接拒绝（不尝试破解）；PyMuPDF 缺失时返回 422。

### 4.6 投稿合规检查

`compliance/check` 把规范档案与源码/PDF 审计合并为逐项检查：

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

响应 `{ok, tex_path, pdf_path, profile, checks, issues, summary}`：

- `checks`：`tex.sections`、`tex.metadata`、`tex.commands`、`pdf.page_count`、`pdf.page_size`、`pdf.fonts`、`pdf.images`，状态 `pass|warn|fail|skipped`；
- `issues` 增加 `source: tex|pdf|profile`；PDF 问题保留页码锚点；
- 新规则：`LATEX-META-REQUIRED`（必需元数据缺失）、`LATEX-COMMAND-FORBIDDEN`（禁用命令）、`PDF-PAGE-SIZE-NOT-ALLOWED`（页面尺寸不在允许列表）、`LATEX-COMPLIANCE-PROFILE`（未知元数据键，warning）；
- `require_embedded_fonts=false` 时过滤字体嵌入问题并把 `pdf.fonts` 标记 skipped；
- 未提供 PDF 时 PDF 检查全部 skipped；`ok = 无 error`。

## 5. 安全与限制

- **不执行 TeX**：只解析源码；未知命令/环境降级为文本 + warning；
- 只读工作区/项目目录内文件；`resolve` 后必须落在 root 内，拒绝绝对路径、`..`、URL、管道；
- 循环 include 检测；单文件 ≤5 MiB、项目 ≤20 MiB、include 深度 ≤20、文件数 ≤200、blocks ≤5000；
- 前端 KaTeX 由 `rehype-katex` 渲染；`LatexPreview` 不使用 `dangerouslySetInnerHTML` 渲染用户文本；
- 模板填充图片槽位：图片必须来自工作区；复制文件名清洗为 `[A-Za-z0-9._-]`，不覆盖已有文件；
- 不支持：`.cls/.sty` 宏展开、TikZ 渲染、DOCX↔LaTeX；TeX 编译/PDF 仅在检测到本机引擎时可用；
- 项目 zip 导入仅接受工作区内 `.zip`；不执行/不编译解压内容，不做病毒扫描；
- 模板填充不自动补 `.bib`；图片槽位会复制到输出目录旁的 `<输出名>_assets/`；前端模板面板使用路径输入（暂未接入通用文件选择器）。
- 源码审校只做确定性规则；PDF 审计只做页面/字体/DPI；合规检查只按档案汇总，不做视觉排版/OCR/语义审校。
- 编译/红字版依赖本机外部工具；不是 OS 级沙箱，不可信文档不应编译。

## 6. 测试

- `backend/tests/unit/office/latex/test_template.py`（12）：profile/slots/style/macros、填充转义/必填/拒绝覆盖、validator、图片槽位识别/复制/路径重写/越界/后缀/同名去重；
- `backend/tests/unit/office/latex/test_audit.py`（10）：元数据/引用/交叉引用/图表/重复 label/TODO/危险命令/必需章节/include；
- `backend/tests/unit/office/latex/test_compile.py`（6）：引擎探测/无引擎/audit gate/成功复制 PDF/输出覆盖/超时；
- `backend/tests/unit/office/latex/test_diff.py`（3）：无 latexdiff/生成 diff.tex/输出覆盖；
- `backend/tests/unit/office/latex/test_project.py`（11）：正常解压/主文件、穿越/符号链接/大小写冲突/重复条目/Windows 保留名/zip bomb/工作区外/已存在目录/无主文件/未知后缀；
- `backend/tests/unit/tools/test_office_latex_project_tool.py`（4）：上下文/非 zip/越界/成功；
- `backend/tests/unit/office/latex/test_pdf_audit.py`（9）：A4 字体未嵌入/页数上下限/混合尺寸/异常尺寸/低 DPI/加密/非 PDF/页数上限/相对路径；
- `backend/tests/unit/tools/test_office_latex_pdf_tool.py`（4）：上下文/非 PDF/越界/字体问题；
- `backend/tests/unit/office/latex/test_compliance.py`（7）：源码通过/元素缺失/禁用命令/PDF 页数尺寸字体/字体不要求/低 DPI/profile 键警告；
- `backend/tests/unit/tools/test_office_latex_compliance_tool.py`（4）：上下文/非 tex/越界/checks；
- `backend/tests/unit/tools/test_office_latex_template_tool.py`（4）：analyze/fill/缺上下文/缺必填；
- `backend/tests/unit/tools/test_office_latex_audit_tool.py`（3）：上下文/问题清单/越界；
- `backend/tests/unit/tools/test_office_latex_build_tool.py`（4）：compile/diff 上下文与降级；
- `backend/tests/integration/test_office_latex_routes.py`（15）：read + template analyze/fill + audit + compile/diff 降级 + project extract + pdf audit + compliance；
- `backend/tests/integration/test_workspace_preview_routes.py`：`.tex` 预览；
- `backend/tests/api/test_artifact_routes.py`：`.tex` artifact；
- `backend/tests/unit/tools/test_office_latex_tool.py`（4）：上下文/成功/越界/后缀；
- `backend/tests/unit/test_profiles_office_tools.py`、`test_tool_bundles_parity.py`：工具面/快照；
- 前端 `LatexPreview.test.tsx`（3）、`LatexTemplatePanel.test.tsx`（3）、`LatexAuditPanel.test.tsx`（2）、`LatexBuildPanel.test.tsx`（2）、`LatexProjectImportPanel.test.tsx`（2）、`LatexPdfAuditPanel.test.tsx`（2）、`LatexCompliancePanel.test.tsx`（2）。

## 7. 后续

- L4：容器/低权限用户等 OS 级编译沙箱、LLM 语义审校；
- `.bib` 自动补写、图片槽位；
- 通用文件选择器、槽位自动填充建议；TikZ/高级包渲染（通过可选 PDF 编译）。
