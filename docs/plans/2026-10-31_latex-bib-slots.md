# LaTeX 模板 .bib 文献槽位（L5b）实施计划

> 日期：2026-10-31 · 分支：`feat/latex-bib-slots`
> 基线：`origin/main` = `bc51eda83`（L5a PR #2722 合并后）
> 范围：模板识别 `\bibliography` / `\addbibresource` 槽位，填充时校验并复制 `.bib`。

## 1. 目标

模板常写 `\bibliography{<<refs>>}` 或引用不存在的 `.bib`。本阶段：

- 分析阶段识别文献文件槽位（`type: "bibliography"`）；
- 填充阶段接受工作区 `.bib` 路径，校验后缀/大小/边界并解析条目；
- 复制到 `<输出名>_assets/`，按命令类型重写路径：
  - `\bibliography` 去掉 `.bib` 扩展；
  - `\addbibresource` 保留 `.bib`；
- 同名文献文件去重，不覆盖已有文件。

## 2. 契约

槽位示例：

```json
{
  "name": "bibliography_refs_1",
  "kind": "command_arg",
  "type": "bibliography",
  "required": true,
  "current_value": "<<refs>>",
  "command": "bibliography",
  "description": "文献：填写工作区内 .bib 路径（将复制到 <输出名>_assets/）"
}
```

填充结果新增：

```json
{"bibliographies_copied": ["paper/main-filled_assets/refs.bib"]}
```

## 3. 识别规则

- `\bibliography{<<...>>}` / `[[...]]` / `【...】`、空参数 → 必填槽位；
- 参数指向不存在的 `.bib`（含无扩展名时自动补 `.bib` 检查）→ 可选槽位 + `missing_bibliography` warning；
- 已存在 `.bib` 不生成槽位；
- `\bibliography{a,b}` 任一项缺失时生成槽位，current_value 保留原值；
- 跳过 `\bibliography` / `\addbibresource` 参数内的通用占位符，避免槽位重叠。

## 4. 安全

- 只接受工作区内 `.bib`；`resolve_within` 拒绝越界/符号链接逃逸；
- 单文件 ≤20 MiB；用现有 `parse_bibtex_file` 解析，解析失败拒绝填充；
- 复制文件名清洗为 `[A-Za-z0-9._-]`；同名不同源自动 `-N`；
- 输出 `.tex` 仍只在全部校验通过后写入。

## 5. 文件

```
backend/office/latex/template.py       # 识别 bibliography 槽位
backend/office/latex/filler.py         # 校验/复制/路径重写
src/shared/api/latexApi.ts             # slot type / bibliographies_copied
src/features/office/LatexTemplatePanel.tsx
docs/technical/105-latex-read-render.md
docs/user-manual/27-latex-preview.md
```

## 6. 实施步骤

- [x] 模板分析 bibliography 槽位 + 单测
- [x] 填充 .bib 校验/复制/路径重写 + 单测
- [x] 前端类型/提示 + 测试
- [x] 文档（技术 105、用户手册 27）
- [x] ruff / py38 / architecture / typecheck / tests

## 7. 非目标

- 不做 BibTeX→BibLaTeX 格式转换；
- 不自动补引用条目；
- 不做 `.bst`/`biblatex` 样式检查（后续）。
