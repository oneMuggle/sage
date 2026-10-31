# LaTeX 工作流 UX：原生文件选择与拖拽（L5c）实施计划

> 日期：2026-10-31 · 分支：`feat/latex-workflow-ux`
> 基线：`origin/main` = `ced0ab1c4`（L5b PR #2727 合并后）
> 范围：为所有 LaTeX 路径字段增加原生文件选择与拖拽；不改变后端 API。

## 1. 目标

此前 LaTeX 面板全部要求手动输入工作区路径。本阶段统一为：

- 每个路径输入旁提供“选择”按钮，调用 Electron 原生单文件选择器；
- 支持把 `.tex/.ltx/.pdf/.zip/.bib/.docx/.md` 拖到输入区域；
- 拖拽时按字段后缀白名单校验，拒绝不支持的类型；
- 路径仍写入原状态，后续 `joinWorkspacePath`/后端边界校验不变。

## 2. 组件

`src/features/office/LatexPathPicker.tsx`

```tsx
<LatexPathPicker
  value={templatePath}
  onChange={setTemplatePath}
  title="选择 LaTeX 模板"
  extensions={['tex', 'ltx']}
  placeholder="paper/main.tex"
  testId="latex-template-path"
  className="flex-1"
/>
```

- 原生选择器：`window.electronAPI.selectFile({title, filters})`；不可用时隐藏“选择”按钮；
- 拖拽：读取 Electron `File.path`；无路径时提示改用选择按钮；
- 错误（不支持后缀/无法取路径）显示在输入下方；
- `testId` 仍落在 `<input>` 上，现有测试兼容。

## 3. 接入面板

- 模板助手：`.tex/.ltx`
- 源码审校：`.tex/.ltx`
- 项目导入：`.zip`
- PDF 审计：`.pdf`
- 编译/红字版：`.tex/.ltx`（主文件、原始、修订）
- 投稿合规：`.tex/.ltx` + `.pdf`
- 期刊规范档案：`.pdf/.docx/.txt/.md/.markdown`

## 4. 文件

```
src/features/office/LatexPathPicker.tsx
src/features/office/__tests__/LatexPathPicker.test.tsx
src/features/office/LatexTemplatePanel.tsx
src/features/office/LatexAuditPanel.tsx
src/features/office/LatexProjectImportPanel.tsx
src/features/office/LatexPdfAuditPanel.tsx
src/features/office/LatexBuildPanel.tsx
src/features/office/LatexCompliancePanel.tsx
src/features/office/LatexProfileLibraryPanel.tsx
docs/technical/105-latex-read-render.md
docs/user-manual/27-latex-preview.md
```

## 5. 实施步骤

- [x] 共享路径选择器 + 单测（原生选择/拖拽/后缀拒绝）
- [x] 接入 7 个 LaTeX 面板
- [x] 现有面板测试兼容
- [x] 文档（技术 105、用户手册 27）
- [x] typecheck / ESLint / Vitest

## 6. 非目标

- 不做工作区文件浏览器/搜索选择器（原生选择器优先）；
- 不改变后端路径规则；
- 不做多文件批量选择（后续）。
