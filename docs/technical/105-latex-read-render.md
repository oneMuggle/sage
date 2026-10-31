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
  service.py         # workspace 边界、大小限制、read_latex_file
```

每个文件 <800 行（architecture-check）。零新增 Python 依赖；py38 hazard scan 0。

## 4. 接入面

| 层 | 入口 | 行为 |
|---|---|---|
| REST | `POST /api/v1/office/latex/read` | `{workspace_path, file_path}` → `{ok, kind:"latex", content, structured, truncated}` |
| 工作区预览 | `GET /api/v1/sessions/{id}/workspace/preview?path=x.tex` | 返回同一形状；`.tex/.ltx` → `kind:"latex"` |
| 产物预览 | `GET /api/v1/sessions/{id}/artifacts/{aid}/content` | `.tex` artifact → `kind:"latex"` |
| Agent 工具 | `office_read_latex` | READ；`requires_tool_context=True`；`_enforce_workspace` + `.tex/.ltx` 白名单 |
| 前端 | `LatexPreview` | 标题/作者/警告/块渲染/源码切换 |

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

## 5. 安全与限制

- **不执行 TeX**：只解析源码；未知命令/环境降级为文本 + warning；
- 只读工作区/项目目录内文件；`resolve` 后必须落在 root 内，拒绝绝对路径、`..`、URL、管道；
- 循环 include 检测；单文件 ≤5 MiB、项目 ≤20 MiB、include 深度 ≤20、文件数 ≤200、blocks ≤5000；
- 前端 KaTeX 由 `rehype-katex` 渲染；`LatexPreview` 不使用 `dangerouslySetInnerHTML` 渲染用户文本；
- 不支持：TeX 编译/PDF、`.cls/.sty` 宏展开、zip 项目上传、TikZ 渲染、DOCX↔LaTeX。

## 6. 测试

- `backend/tests/unit/office/latex/test_parser.py`（12）：元数据/章节/公式/列表/图表/引用/文献/include/安全/未知命令/锚点；
- `backend/tests/integration/test_office_latex_routes.py`（4）：REST 成功/越界/404/extra 字段；
- `backend/tests/integration/test_workspace_preview_routes.py`：`.tex` 预览；
- `backend/tests/api/test_artifact_routes.py`：`.tex` artifact；
- `backend/tests/unit/tools/test_office_latex_tool.py`（4）：上下文/成功/越界/后缀；
- `backend/tests/unit/test_profiles_office_tools.py`、`test_tool_bundles_parity.py`：工具面/快照；
- 前端 `src/features/office/__tests__/LatexPreview.test.tsx`（3）。

## 7. 后续

- L2：`.cls/.sty` 宏表、模板槽位、智能填充、结构校验；
- L3：LaTeX 审校规则、`latexdiff` 红字版、PDF 编译（OS 级沙箱）；
- zip 项目上传与安全解压；TikZ/高级包渲染（可选 PDF 编译通道）。
