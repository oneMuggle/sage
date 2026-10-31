# LaTeX 读取与渲染（L0 + L1 第一刀）实施计划

> 日期：2026-10-31 · 分支：`feat/latex-read-render` · worktree：`.worktrees/feat-latex-read-render`
> 基线：`origin/main` = `66299ab15`
> 总方案：`docs/plans/2026-10-31_word-document-intelligence.md`（§4.9、L0–L3）
> 结论：本刀只做 **LaTeX 项目读取 + 结构化渲染 + 现有预览链路接入**，不做模板填充、审校、PDF 编译。

## 1. 背景与目标

期刊/会议大量使用 LaTeX 模板（`main.tex` + `sections/*.tex` + `.cls/.sty` + `.bib` + figures）。
Sage 当前只能把 `.tex` 当纯文本读取；前端 KaTeX 只渲染 Markdown 公式。本刀交付：

1. 识别并解析 `.tex` 项目（单文件 + `\input`/`\include` 递归）；
2. 抽取元数据、章节、段落、列表、公式、图、表、引用、标签/交叉引用、参考文献；
3. 返回结构化渲染块，前端用现有 KaTeX 渲染数学公式；
4. 接入现有 artifact / 工作区文件预览（`FileContentRenderer`）；
5. 提供 REST + Agent 工具入口，后续模板填充/审校复用同一套模型。

**非目标（后续 L2/L3）**：模板槽位与填充、LaTeX 审校规则、PDF 编译、`latexdiff`、zip 项目上传、
DOCX↔LaTeX、TikZ 渲染、完整 `.cls/.sty` 宏展开。

## 2. 技术选择

- **不新增 Python 依赖**：本刀实现一个零依赖的容错扫描器（`backend/office/latex/`），
  保证 `sage-backend-py38` / Win7 可用。总方案里的 TexSoup + pylatexenc 作为 L2 的可选升级：
  若扫描器对真实期刊项目的覆盖率不足，再评估引入，并保留同样接口。
- **不做 TeX 执行**：只解析源码，不编译、不执行宏；未知命令/环境降级为文本 + warning。
- **渲染契约**：后端返回结构化 blocks（不是 HTML），前端用 React + KaTeX 渲染，降低 XSS 面。
- **复用现有预览链路**：`.tex` 归类为 `latex`，走 `artifact_reader` / `workspace_preview`，
  由 `FileContentRenderer` 统一渲染；`ArtifactViewer` / `FilePreviewPanel` 自动受益。
- **py38 安全**：`from __future__ import annotations`、`typing.List/Dict/Optional`、
  不用 `Path.is_relative_to`（3.9+），用 `os.path.commonpath`。

## 3. 涉及文件

### 3.1 新增后端模块

```
backend/office/latex/
  __init__.py
  models.py          # LatexAnchor / LatexInline / LatexBlock / LatexDocument / LatexWarning
  scanner.py         # 零依赖扫描：命令/环境/参数/注释/位置
  parser.py          # 项目解析：metadata / sections / blocks / refs / cites / includes
  renderer.py        # 结构模型 → 前端渲染块（含 math/link/cite 标记）
  service.py         # workspace 边界、大小限制、读文件、编排
  errors.py          # LatexError / LatexParseError / LatexPathError（映射 422/400/403）
```

### 3.2 后端接入

- `backend/office/models.py` 或 `latex/models.py`：API 请求/响应模型；优先放 `latex/models.py`，
  避免继续膨胀 `office/models.py`（当前 1530 行，已接近架构上限）。
- `backend/api/office_latex_routes.py`：`POST /api/v1/office/latex/read`。
- `backend/api/office_routes.py`：`router.include_router(_latex_router)`（与 journal 同模式）。
- `backend/data/artifact_repo.py`：`_EXT_KIND_MAP[".tex"] = "latex"`。
- `backend/api/artifact_routes.py`：`kind == "latex"` → `artifact_reader.read_latex(...)`。
- `backend/data/artifact_reader.py`：`read_latex(artifact_id)` / `read_latex_path(path)`；
  返回 `{ok, kind:"latex", content, structured, truncated?}`。
- `backend/api/workspace_preview_routes.py`：`.tex` → `artifact_reader.read_latex_path(...)`。
- `backend/tools/office_latex_tool.py`：`office_read_latex`（READ，workspace 文件路径）。
- `backend/domain/tool_names.py`：`OFFICE_TOOLS` 加 `office_read_latex`。
- `backend/agents/profiles.py`：primary / writer 白名单 + 默认常量。
- `backend/tests/unit/test_profiles_office_tools.py`：可见性计数更新。
- `backend/tests/unit/tools/test_office_create_schema_contract.py`：不受影响（不涉及 create schema）。
- `backend/tools/tool_bundles.py`：注册工具。

### 3.3 前端接入

- `src/shared/api/types.ts`（或新 `latexTypes.ts`）：`LatexPreviewBlock` 等类型。
- `src/features/office/LatexPreview.tsx`：渲染 blocks + KaTeX + warnings + 源码切换。
- `src/widgets/chat/preview/FileContentRenderer.tsx`：`content.kind === 'latex'` 分支。
- `src/features/artifacts/artifactApi.ts`：`ArtifactKind` 加 `'latex'`。
- `src/shared/lib/fileLang.ts`：`.tex` → `latex`（Shiki 已带 latex 语言包）。
- `src/features/office/__tests__/LatexPreview.test.tsx`。
- `src/widgets/chat/preview/__tests__/FileContentRenderer.latex.test.tsx`（或现有测试追加）。
- 如需通过消息内文件引用打开：`workspaceApi.resolveFiles` / `_kind_for_preview` 已覆盖 `.tex`。

## 4. 数据契约

### 4.1 解析结果

```json
{
  "ok": true,
  "kind": "latex",
  "source_path": "paper/main.tex",
  "metadata": {
    "document_class": "article",
    "title": "Example",
    "authors": ["A. Author"],
    "affiliations": ["Example University"],
    "abstract": "…",
    "keywords": ["LaTeX", "preview"]
  },
  "blocks": [
    {"type": "heading", "level": 1, "text": "Introduction", "anchor": {"file": "paper/main.tex", "line": 12}},
    {"type": "paragraph", "segments": [
      {"type": "text", "text": "As shown in "},
      {"type": "ref", "target": "fig:arch", "text": "Figure 1"},
      {"type": "text", "text": ", the model is "},
      {"type": "math", "latex": "O(n^2)", "display": false}
    ], "anchor": {"file": "paper/main.tex", "line": 14}},
    {"type": "equation", "latex": "E = mc^2", "display": true, "anchor": {"file": "paper/main.tex", "line": 20}},
    {"type": "figure", "src": "figures/arch.png", "caption": "Architecture", "label": "fig:arch", "anchor": {"file": "paper/main.tex", "line": 25}},
    {"type": "table", "headers": ["A", "B"], "rows": [["1", "2"]], "caption": "Results", "label": "tab:res", "anchor": {"file": "paper/main.tex", "line": 30}},
    {"type": "bibliography", "items": [{"key": "knuth84", "text": "…"}], "anchor": {"file": "paper/main.tex", "line": 40}}
  ],
  "warnings": [
    {"code": "unknown_command", "message": "未识别命令 \\foo，已按文本渲染", "anchor": {"file": "paper/main.tex", "line": 18}},
    {"code": "undefined_reference", "message": "未找到标签 fig:missing", "anchor": {"file": "paper/main.tex", "line": 19}}
  ]
}
```

### 4.2 Inline segments

`text` / `strong` / `emph` / `code` / `math` / `ref` / `cite` / `link`。
未知命令降级为 `text`（保留参数文本）+ warning。

### 4.3 限制

- 单文件 ≤ 5 MiB（与 `read_file` 一致）；项目总大小 ≤ 20 MiB；include 深度 ≤ 20；文件数 ≤ 200；
- blocks ≤ 5000；超限截断并附 `truncated` warning；
- 仅允许工作区/项目目录内的相对路径；拒绝绝对路径、`..` 逃逸、URL、管道、符号链接逃逸；
- 循环 include 检测（realpath 集合）；
- 编码 UTF-8（带 BOM 兼容）。

## 5. 实施步骤

- [x] 步骤 1：写解析器/渲染契约测试（RED）
- [x] 步骤 2：`models.py` + `scanner.py` 最小扫描器
- [x] 步骤 3：`parser.py` 元数据/章节/段落/公式/列表
- [x] 步骤 4：图/表/引用/标签/参考文献/include 递归
- [x] 步骤 5：`renderer.py` 结构化 blocks + warnings（实现为 `parser` 的 blocks 输出 + 前端 `LatexPreview`）
- [x] 步骤 6：`service.py` 路径安全/大小限制/错误映射
- [x] 步骤 7：REST 路由 + 集成测试
- [x] 步骤 8：artifact/workspace preview 接入 + 测试
- [x] 步骤 9：Agent 工具 `office_read_latex` + profiles/登记/防漂移测试
- [x] 步骤 10：前端 `LatexPreview` + `FileContentRenderer` 接入 + Vitest
- [x] 步骤 11：ruff / pytest / py38 hazard scan / typecheck / 前端测试
- [x] 步骤 12：文档追加技术手册与用户手册章节（功能完成后）

## 6. 测试计划

### 6.1 后端单元

`backend/tests/unit/office/latex/test_parser.py`

- 元数据：title/author/affil/email/date/abstract/keywords；
- 章节/段落/列表；
- 行内 `$...$`、`\(...\)`、display `$$...$$`、`\[...\]`、equation/align；
- figure/includegraphics/caption/label；
- table/tabular/caption/label；
- `\cite`/`\ref`/`\eqref`/`\label`；
- `thebibliography` 与 `\bibliography{refs}`；
- 注释 `%` 与转义 `\%`；
- 未知命令/环境 → 文本 + warning；
- include 递归、缺文件、循环、越界；
- 行号锚点；
- 大小/块数限制。

### 6.2 后端集成

- `POST /api/v1/office/latex/read` 成功/404/403/413/422；
- `/sessions/{sid}/workspace/preview?path=paper.tex` → `kind:"latex"` + `structured`；
- artifact `.tex` → `kind:"latex"`；
- `office_read_latex` 工具 roundtrip（workspace 围栏、上下文 fail-closed）。

### 6.3 前端

- `LatexPreview`：标题/段落/公式/图/表/引用/警告；
- KaTeX 渲染（`.katex` 存在、错误降级为源码）；
- 源码/预览切换；
- `FileContentRenderer` latex 分支；
- 恶意 HTML/命令不执行（只作为文本）。

## 7. 安全

- 不执行 TeX；未知命令只保留文本；
- 只读工作区内文件；include 路径 realpath 边界校验；拒绝符号链接逃逸；
- 前端 KaTeX `trust:false`、`throwOnError:false`；不使用 `dangerouslySetInnerHTML` 渲染用户文本；
- 后端返回结构数据，HTML 由 React 生成；如用 KaTeX innerHTML，仅限 KaTeX 输出；
- 大小/深度/块数限制，防 DoS；
- zip 支持不在本刀范围（后续 L2 单独做安全解压）。

## 8. 验收

- 10 个真实/类 arXiv LaTeX 样本解析成功率 ≥ 95%（标准结构）；
- 未知命令/环境不崩溃，均有 warning；
- 工作区预览能显示 `.tex` 的标题/章节/公式/图/表/引用；
- `office_read_latex` 工具可见且受 workspace 围栏；
- 后端 pytest 相关全绿；ruff 全绿；py38 hazard scan 0；
- 前端 typecheck + Vitest 相关全绿；
- 零新增 Python 依赖。

## 9. 风险与对策

| 风险 | 对策 |
|---|---|
| 自研扫描器覆盖不足 | 先覆盖期刊常用命令/环境；未知降级；L2 可替换 TexSoup |
| 宏/自定义命令复杂 | 不展开，保留参数文本 + warning；后续宏表增强 |
| include 路径逃逸 | realpath + commonpath 边界；拒绝绝对路径/管道 |
| 大项目解析慢 | 大小/深度/块数限制；后续缓存（content hash） |
| 前端 KaTeX 不支持 TikZ | 显示源码 + warning；PDF 编译留 L3 |
| Win7/py38 | 无新依赖；py38 注解风格；hazard scan |
| 与现有 artifact 预览冲突 | 新增 `latex` kind，不改旧 kind 行为；回归测试 |

## 10. 实施记录（2026-10-31）

已完成：

- 新增 `backend/office/latex/`：`models.py` / `scanner.py` / `parser.py` / `inline.py` /
  `environments.py` / `utils.py` / `service.py`，零第三方依赖，py38 hazard scan 0。
- REST `POST /api/v1/office/latex/read`。
- artifact / workspace preview 的 `.tex` → `kind:"latex"` + `structured`。
- Agent 工具 `office_read_latex`（READ、`requires_tool_context`、workspace 围栏）。
- 前端 `LatexPreview` + `FileContentRenderer` 接入 + `ArtifactKind` / `fileLang`。
- 测试：后端相关 77 项全绿；前端相关 9 项 Vitest 全绿；ruff / typecheck / eslint /
  architecture-check 全绿。
- 已知边界：无 TeX 编译；`.cls/.sty` 仅识别常用宏，不展开；无 zip 项目上传；
  TikZ/高级包降级为文本/图片占位；`parser.py` 已拆分为 <800 行模块。

## 11. L2 实施记录（2026-10-31）

已完成后端核心：

- `template.py`：从 `.tex` + 同目录/根目录 `.cls/.sty` 抽取 `LatexTemplateProfile`
  （document_class/packages/macros/style/metadata/slots/warnings/includes）；
- `filler.py`：按槽位替换（command_arg / environment_body / placeholder / comment），
  LaTeX 转义，作者/单位/关键词数组用 `\and` / 逗号连接，输出新 `.tex`，绝不覆盖模板；
- `validator.py`：花括号/环境配对/残留占位符校验；
- REST：`POST /api/v1/office/latex/template/analyze`、
  `POST /api/v1/office/latex/template/fill`；
- Agent 工具：`office_analyze_latex_template`（READ）、
  `office_fill_latex_template`（WRITE_LOCAL，file_path 模式）；
- 测试：L2 相关 33 项 + 全量 LaTeX/预览/工具回归 93 项全绿；ruff / py38 / architecture-check 全绿。

尚余：前端模板面板（路径选择/槽位表单）、`.bib` 自动补写、图片槽位、zip 项目上传。

## 12. 后续（不在本 PR）

- L2：`.cls/.sty` 宏表、模板槽位、智能填充、校验；
- L3：LaTeX 审校规则、`latexdiff`、PDF 编译/沙箱；
- zip 项目上传与安全解压；
- 如需更强解析：TexSoup/pylatexenc 适配器（保持 `LatexDocument` 契约不变）。
