# LaTeX 模板图片槽位（L4c）实施计划

> 日期：2026-10-31 · 分支：`feat/latex-image-slots`
> 基线：`origin/main` = `5a85affe4`（L4b PR #2714 合并后）
> 范围：模板分析识别图片槽位 + 填充时复制图片并重写 `\includegraphics` 路径。

## 1. 目标

期刊模板常用 `\includegraphics{<<fig1>>}`、`example-image` 或引用不存在的图片作为占位。
当前模板助手只能填文字，图片需要用户手工替换。本阶段：

- 分析阶段识别图片占位/缺失图片，返回 `type: "image"` 槽位；
- 填充阶段接受工作区图片路径，校验后缀/大小/边界；
- 把图片复制到 `<输出文件名>_assets/`，并把 `\includegraphics` 路径改为相对输出文件的路径；
- 同名图片自动去重（`chart.png` / `chart-1.png`）。

## 2. 契约

模板分析槽位新增：

```json
{
  "name": "image_figure1_1",
  "kind": "command_arg",
  "type": "image",
  "required": true,
  "description": "图片：填写工作区内图片路径（将复制到 <输出名>_assets/）",
  "current_value": "<<figure1>>",
  "command": "includegraphics",
  "anchor": {"file": "paper/main.tex", "line": 12}
}
```

填充请求 `data` 示例：

```json
{"image_figure1_1": "figures/arch.png"}
```

路径解析：相对路径优先按模板所在目录解析，其次按工作区根解析；绝对路径必须落在工作区内。
支持后缀：`.png .jpg .jpeg .pdf .eps .svg`；单图 ≤20 MiB。

填充结果新增：

```json
{"images_copied": ["paper/main-filled_assets/arch.png"]}
```

## 3. 识别规则

- `\includegraphics{<<...>>}` / `[[...]]` / `【...】` → 必填图片槽位；
- 参数为空 → 必填图片槽位；
- 参数包含 `placeholder` / `example-image` → 必填图片槽位；
- 参数指向不存在的图片 → 可选图片槽位 + `missing_image` warning；
- 已存在且正常的图片不生成槽位，避免模板里每张图都变成表单。

## 4. 文件

```
backend/office/latex/template.py       # 识别 image 槽位
backend/office/latex/filler.py         # 校验/复制图片 + 路径重写
backend/office/latex/models.py         # type 注释补充 image
src/shared/api/latexApi.ts             # slot type / images_copied
src/features/office/LatexTemplatePanel.tsx  # 图片槽位输入提示
docs/technical/105-latex-read-render.md
docs/user-manual/27-latex-preview.md
```

## 5. 安全

- 图片只能来自工作区；`resolve_within` 拒绝越界/符号链接逃逸；
- 拒绝不支持后缀与超限文件；
- 复制目标文件名会清洗为 `[A-Za-z0-9._-]`，避免 LaTeX 特殊字符；
- 不覆盖已有图片：同名不同源自动加 `-N` 后缀；
- 输出 `.tex` 仍只在全部校验通过后写入；写失败不回滚已复制图片（结果中可观察）。

## 6. 实施步骤

- [x] 模板分析图片槽位 + 单测
- [x] 填充图片校验/复制/路径重写 + 单测
- [x] 前端类型/提示 + 测试
- [x] 文档（技术 105、用户手册 27）
- [x] ruff / py38 / architecture / typecheck / tests

## 7. 非目标

- 不做图片裁剪/压缩/格式转换；
- 不做远程 URL 图片下载；
- 不处理 `.bib` 或其它资源槽位（后续）。
