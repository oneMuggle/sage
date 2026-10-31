# LaTeX 文档预览与处理

> 适用：工作区或产物中的 `.tex` / `.ltx` 文件。支持只读语义预览；模板填充、源码审校、项目 zip 导入、PDF 版式审计、投稿合规检查，以及在本机有 TeX 引擎时的可选编译。

## 1. 打开方式

1. 在聊天里让 agent 读取工作区 `.tex` 文件，或把 `.tex` 作为产物打开；
2. 在右栏文件预览 / 产物预览中，Sage 会显示 LaTeX 预览；
3. 也可以让 agent 调用 `office_read_latex`，返回同样的结构化内容。

## 2. 预览内容

- 标题、作者、文档类；
- 章节、段落、列表；
- 行内/独立公式（KaTeX 渲染）；
- 图片（常见位图/矢量格式，≤2 MiB 内联）；
- 表格；
- 引用与交叉引用（显示为 `Figure N` / `Table N` / `Equation N` / 章节标题）；
- 参考文献（`thebibliography` 或 `.bib`）；
- 解析警告（未知命令/环境、缺图、缺文献、未定义引用等）。

右上角“源码/预览”可以切换查看原始 `.tex`。

## 3. 使用限制

- **默认不编译 PDF**：预览只做语义解析；需要 PDF 时使用第 7 节的编译面板（依赖本机 TeX 引擎）；
- 自定义 `.cls/.sty` 宏只做静态识别，复杂宏可能显示为文本并给出 warning；
- TikZ、pgfplots、siunitx 等高级包无法在预览中完整渲染，会降级为源码/占位；
- 暂不支持 zip/Overleaf 项目直连上传；请先用第 8 节把项目 zip 导入工作区；
- 只读取工作区内的文件，`\input` 不能越界；
- 大文件/深层 include 会被限制并提示 warning。

## 4. 常见问题

**公式显示为红色/原始代码？**
KaTeX 不支持的宏或包会降级显示；可切到“源码”查看，或在本地 TeX 环境编译确认。

**图片显示“暂未内联预览”？**
图片缺失、格式不支持（如 PDF 图）或超过 2 MiB；请检查路径/大小，最终以编译结果为准。

**引用显示为 `[key]` 而不是编号？**
`\label` 未定义或引用目标不在项目内；查看顶部“解析警告”里的 `undefined_reference`。

## 5. 用 LaTeX 模板助手 / Agent 填充模板

可在 **Office 页的“LaTeX 模板助手”** 中操作：

1. 在输入框填写工作区内的模板路径（如 `paper/main.tex`）；
2. 点击“分析模板”，查看槽位（title/author/abstract/keywords/`<<占位符>>`/注释）；
3. 填写槽位内容；作者/单位/关键词多个值用逗号分隔；
4. 图片槽位填写工作区内的图片路径（如 `figures/arch.png`）；填充时会把图片复制到输出文件旁的 `<输出名>_assets/`，并自动改写 `\includegraphics` 路径；
5. 指定输出文件名（默认 `main-filled.tex`），点击“填充并输出”。

也可以让 agent 使用：

- `office_analyze_latex_template`：分析模板，返回可填槽位；
- `office_fill_latex_template`：按槽位名填充，输出新的 `.tex` 文件。

规则：

- 必填槽位缺失会拒绝填充；
- 作者/单位数组用 `\and` 连接，关键词用逗号；
- 文本会自动做 LaTeX 转义；
- 图片槽位只接受工作区内 `.png/.jpg/.jpeg/.pdf/.eps/.svg`（单图 ≤20 MiB）；同名图片自动加 `-N` 后缀，不覆盖已有文件；
- 只写新文件，不会覆盖模板或已有文件；
- 填充后做括号/环境配对校验，但**不编译 PDF**。

## 6. 源码审校

Office 页的 **“LaTeX 源码审校”** 面板可做确定性检查：

1. 填写工作区内的 `.tex` 主文件路径（如 `paper/main.tex`）；
2. 可选填写“必需章节”（逗号分隔，如 `Introduction, Conclusion`）；
3. 点击“开始审校”。

检查项：

- `\documentclass` / title / author / abstract；
- 必需章节是否缺失；
- `\cite` key 是否在参考文献中、`\ref` 是否指向已定义 label；
- 图/表是否缺少 caption/label；
- 重复 label；
- TODO / `<<占位符>>` / `\todo{}` 残留；
- `\write18`、`\openin`、`\openout`、管道或绝对路径 include 等危险命令；
- include 缺失/循环/越界、参考文献/图片资源警告。

问题列表会显示 `rule_id`、severity、`file:line` 锚点与修复建议。**只做源码检查，不编译 PDF、不检查版式/页数/字体**。

## 7. 编译 PDF / 红字版

Office 页的 **“LaTeX 编译与红字版”** 面板依赖本机外部工具（不捆绑 TeX）：

**编译 PDF**

1. 填写工作区内 `.tex` 主文件路径；
2. 可选填写输出 PDF 文件名（默认 `<stem>.pdf`）；
3. 选择引擎（自动 / latexmk / xelatex / lualatex / pdflatex）；
4. 点击“编译 PDF”。

编译前会先运行源码审校：存在 error（含 `\write18` 等危险命令、越界 include）会拒绝编译。
无 TeX 引擎时提示 `no_engine`，不会生成文件。

**红字版（latexdiff）**

1. 填写原始版本与修订版本 `.tex` 路径；
2. 可选填写输出 `diff.tex` 文件名；
3. 需要 PDF 时勾选“同时编译 PDF”；
4. 点击“生成红字版”。

无 `latexdiff` 时提示 `no_latexdiff`。

> 安全提示：编译通道使用临时目录、`-no-shell-escape`、`openin_any=p`、`openout_any=p` 和超时限制，
> 但**不是 OS 级沙箱**。请不要编译来源不可信的 LaTeX 文档。

## 8. 导入 LaTeX 项目 zip（Overleaf）

Office 页的 **“LaTeX 项目导入”** 面板可以把 Overleaf / 期刊模板 zip 安全解压到工作区：

1. 先把 `.zip` 放在工作区内（如 `downloads/ieee-template.zip`）；
2. 在面板填写 zip 路径；
3. 可选填写输出目录名（默认 `latex-<zip 名>`；目录已存在时会拒绝覆盖）；
4. 点击“解压项目”，面板会显示项目目录、文件数、大小和识别到的主 `.tex`。

安全与限制：

- 拒绝路径穿越、绝对路径、符号链接、加密 zip、zip bomb 和 Windows 非法文件名；
- 只解压文档/资源白名单后缀（`.tex/.ltx/.cls/.sty/.bst/.bib`、图片、字体等），脚本等会跳过并提示；
- 限制：zip ≤100 MiB、解压总量 ≤200 MiB、单文件 ≤50 MiB、条目 ≤2000；
- **解压内容不会被执行或编译**；解压后再用模板助手/审校/编译面板处理主文件。

也可以让 agent 调用 `office_extract_latex_project` 完成同样操作。

## 9. PDF 版式审计

Office 页的 **“PDF 版式审计”** 面板用于投稿前自检：

1. 填写工作区内 `.pdf` 路径（编译产物或外部稿）；
2. 可选填写最小/最大页数、图片 DPI 阈值（默认 150）；
3. 点击“审计 PDF”。

会检查：

- 页数与页面尺寸（A4 / Letter / Legal；混合尺寸或非常规尺寸会提示）；
- 字体是否全部嵌入（未嵌入字体会报错）；
- 图片有效 DPI（低于阈值且尺寸 ≥36pt 会提示）；
- 加密 PDF 直接拒绝。

结果按页码显示 `rule_id`、严重级别与修复建议。**只读分析，不修改 PDF、不执行 TeX**。

## 10. 投稿合规检查

Office 页的 **“LaTeX 投稿合规检查”** 可把期刊要求一次性套用到源码与 PDF：

1. 填写 `.tex` 主文件路径；如已编译，再填写 `.pdf` 路径；
2. 填写必需章节（如 `Introduction, Conclusion`）、必需元数据（如 `title, author, abstract, keywords`）；
3. 可选填写允许页面尺寸（`A4` / `Letter` / `Legal`）、最小/最大页数、图片 DPI 阈值；
4. 勾选是否要求字体全部嵌入；填写禁用命令（如 `write18, todo`）；
5. 点击“开始合规检查”。

结果会按 `tex.sections`、`tex.metadata`、`tex.commands`、`pdf.page_count`、`pdf.page_size`、`pdf.fonts`、`pdf.images` 显示通过/警告/失败/跳过，并列出带文件行号或页码的问题与建议。

说明：

- 不提供 PDF 时，所有 PDF 检查标记为“跳过”；
- 取消“要求字体全部嵌入”会忽略字体未嵌入问题；
- 只做确定性规则检查，不做页边距/双栏/行距等视觉排版判断，也不修改文件。
