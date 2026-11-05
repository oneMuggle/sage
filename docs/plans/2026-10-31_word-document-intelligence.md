# Word 文档智能能力评估与优化方案（模板智能填充 + 规范审校）

> 日期：2026-10-31 · 状态：方案（待评审，未开始实施）
> 范围：Word / `.docx` 为主；`.doc` 走现有 pandoc 转换；新增 LaTeX / `.tex` 项目（`.cls/.sty/.bib/figures`）读取与渲染；不改变 Office 之外的能力边界
> 分支：`main`（Python 3.10 / pydantic 2.5.0）+ `release/win7`（Python 3.8 / pydantic 1.10.13 + shim）
> 结论先行：**不重写现有 Word 栈**。Sage 已经有相当完整的“生成 → 校验 → 修复 → 预览”闭环；
> 三个场景（Word 模板填充、规范审校、LaTeX 期刊模板）的真正缺口是 **读取保真度、语义模板槽位、
> 规范/范本到规则的抽取、问题定位与修订模式、渲染级校验、LaTeX 项目解析**。建议在
> `FormatSpec / Linter / Repair`、docxtpl 模板、journal 子系统之上增加一层
> “文档智能（Document Intelligence）”，分六期落地，并并行一条 LaTeX 轨道（L0–L3）。

---

## 0. TL;DR

### 0.1 现状（比预期强，但读取是“扁平化、有损”的）

Sage 当前的 Word 能力已经具备：

- **确定性生成**：`WordFormatSpec` 覆盖纸张/页边距/正文/标题/页眉页脚/页码/目录/图表目录/
  分节/首页与奇偶页；支持插图、题注、三线表、表头跨页、列宽、合并单元格、多级标题编号。
- **结构化编辑**：`office_update` 支持替换文本、追加段落/表格、改单元格、删段落、插图、
  段落样式、增删批注；原子替换，失败不改原文件。
- **模板填充**：`word_template.py` 基于 docxtpl，能扫描正文/表格/页眉页脚的 `{{占位符}}`，
  识别日期/图片/富文本/表格类型，带沙箱与危险表达式拦截；内置 6 套 Word 模板。
- **期刊模板子系统**：从 `.doc/.docx` 范本抽取字体/字号/行距/页边距/章节/引用风格，
  7 类规则校验，结构化填充，LLM 生成论文并两轮自纠。
- **格式校验与自动修复**：`lint_docx` 按 FormatSpec 逐条校验，输出 rule_id/severity/
  实测 vs 期望/中文修复建议；`repair_docx` 确定性修复并复检。
- **高级 Word 元素**：目录域与 COM 真页码刷新、图表目录、交叉引用 REF 域、脚注/尾注、
  批注读写、核心属性、GB/T 7714 引用、Office→PDF。
- **前端闭环**：`OfficeDeliveryDrawer` 已接格式检查与一键修复；`DocxNativePreview`
  用 docx-preview 做高保真预览并消毒；`OfficeGenerateForm` + `OfficeGenerateSubforms`
  已有模板选择与按 placeholder 动态渲染的槽位表单；`JournalPanel` 已有模板解析/校验/填充入口。
  但槽位只来自模板库静态声明，问题列表没有结构化定位/高亮，也没有文档对比视图。
- **LaTeX 现状**：前端已有 KaTeX 0.18.6 + `remark-math`/`rehype-katex`，但只能渲染
  Markdown 中的数学公式；后端只有 journal 的 `.doc → .docx` pandoc 适配器，
  **没有 `.tex` 解析、LaTeX 项目解析、HTML/PDF 渲染、模板填充或 LaTeX 审校能力**。

但必须清醒看到：**读取侧是面向展示/搜索的扁平 DTO，不是可往返的文档 IR**。
`read_docx` 不返回字体名、字号、颜色、对齐、缩进、行距、页面设置、编号定义、书签、
内容控件与修订；run 级只保留直接格式的粗体/斜体标记。这意味着“读模板 → 改内容 →
保持原格式”目前不能直接成立，必须先补一层 `DocumentProfile` / `StyleResolver`。

### 0.2 关键缺口

| 场景 | 已有 | 缺什么 |
|---|---|---|
| A. 模板→智能填充 | `{{ }}` 模板扫描/填充、内置模板库、期刊结构化填充、基础动态槽位表单 | 内容控件/书签/无标记范本；语义槽位 Schema；LLM 自动取数与分段生成；循环/条件块建模；填充后质量校验；任意模板 Schema 编辑 + 校验/图片上传 UI；**journal 填充会清空 body，不能用于普通模板** |
| B. 规范→规则→审校 | FormatSpec Linter/Repair、journal 7 类规则、文档格式约束文本 | 从规范条文抽取规则；从范本学习任意样式档案；任意规则 DSL 与证据链；问题定位/高亮；修订模式（track changes）；渲染级校验；规则分层/版本/冲突治理 |
| C. LaTeX 期刊模板 | 前端 KaTeX（仅 Markdown 公式）、pandoc（仅 `.doc→.docx`）、BibTeX 解析 | `.tex` 项目解析（多文件 + `.cls/.sty/.bib` + figures）；HTML/PDF 渲染；模板档案与槽位；LLM 填充；LaTeX 审校；latexdiff 修订；Win7 安全降级 |

### 0.3 推荐路线

1. **复用确定性内核**：`word_layout` / `word_lint` / `word_repair` / `edit.py` / `journal` /
   `word_template` 不推倒重来，新增适配层与规则注册机制。
2. **先补文档快照**：`DocumentProfile` + `StyleResolver` + `AnchorResolver`，让读取达到
   “可审计”的保真度；这是模板填充与规范审校共同的地基。
3. **先做“可定位的审校”**：给 `WordLintIssue` 增加锚点、实测值、期望值、来源、可修复标记；
   这是 UI 高亮、一键修复、审计报告的共同基础。
4. **再做“语义模板”**：把 `{{ }}` 扫描器升级为统一的模板 Profile（Jinja / 内容控件 / 书签 /
   启发式四种适配器），用 JSON Schema 作为 LLM 填充契约。
5. **最后做“规范抽取”**：规范条文与范本两种来源 → LLM 候选规则 → 确定性校验 + 人工确认 →
   版本化规则包；**LLM 不直接充当裁判**，最终由确定性检查器执行。
6. **修订可审阅**：所有自动修改默认输出新文件；内容级修改写 Word 原生修订 + 批注，
   不静默覆盖用户文档。
7. **双分支分层**：核心功能零新增依赖、py38 可运行；重依赖（docxcast / python-redlines /
   docling / 渲染器）只作为 main 可选增强，win7 优雅降级。
8. **LaTeX 作为第三条文档轨道**：核心做 `.tex` 项目解析 + HTML 语义渲染（KaTeX）+
   模板槽位填充；PDF 编译作为可选增强，Win7 不依赖 Tectonic（Rust 1.78+ 已把 Windows 10
   作为最低基线）。

---

## 1. 背景与目标

### 1.1 场景 A：按模板智能填写

用户上传一份既有 Word 模板（可能是单位固定格式、期刊投稿模板、项目申报书、合同模板），
系统需要：

1. 解析模板中的**可填槽位**（字段、表格行、日期、选项、图片、重复区块）；
2. 理解每个槽位的**语义与约束**（名称、类型、必填、长度、枚举、格式、来源）；
3. 根据用户提供的资料/对话上下文/工作区文档，**智能生成并填入内容**；
4. **保持模板原有版式**，不因填充破坏字体、编号、页眉页脚、表格结构；
5. 填充后做质量校验，报告未填项、超长项、格式冲突；
6. 输出可继续在 Word/WPS 中编辑的文档。

### 1.2 场景 B：按规范审校文档

用户提供一份“规范文档”——它可能是：

- **规范条文**：如 GB/T 9704、期刊投稿须知、单位公文格式规定、合同审查要点；
- **范本文件**：一份已经合规的 Word 文档，用户希望“照这个格式来”；
- **模板文件**：一份带格式但未必有占位符的标准模板。

系统需要：

1. 从规范中**抽取可执行的格式/结构/内容规则**；
2. 让用户**审阅、修改、启停**规则，形成可复用的规则包；
3. 对待审文档执行**确定性检查 + 语义检查**；
4. 输出**可定位的问题清单**（段落/表格/页眉页脚/页码/页面），带证据、严重级别、修复建议；
5. 支持**一键修复**或**生成修订版**，用户逐条接受/拒绝；
6. 修复后**复检**，并生成审计报告。

### 1.3 设计原则

1. **模板/规范即契约**：模板的槽位与规范的规则都应是机器可读契约，而不是 prompt 里的口头约定。
2. **确定性优先**：能测量的（字体、字号、行距、页边距、编号、日期格式）用确定性代码检查与修复；
   LLM 只负责语义理解、内容生成、模糊判断。
3. **证据链**：每条规则、每个问题都要能追溯到来源（规范第几条/范本哪一段/用户哪次设置）。
4. **不破坏原则**：默认写新文件；内容修改用原生修订 + 批注；绝不静默覆盖。
5. **本地优先**：文档默认不出机；只有必要的文本片段/规则候选进入 LLM，且可配置脱敏。
6. **双分支纪律**：核心路径 py38 安全；重依赖可选；win7 功能可降级但不能坏。
7. **YAGNI**：不做完整 Word 编辑器、不做协同编辑、不做宏。

### 1.4 场景 C：LaTeX 期刊模板读取与渲染

不少期刊/会议只提供 LaTeX 模板（Overleaf 项目或 zip：`main.tex` + `sections/*.tex` +
`.cls`/`.sty` + `.bib` + figures）。用户需要：

1. **读取**：识别主文件，递归解析 `\input`/`\include`/`\subfile`，提取文档类、宏包、导言区宏、
   标题/作者/摘要/关键词、章节、公式、图、表、引用、标签/交叉引用、参考文献；
2. **渲染**：在应用内看到可读视图（HTML + KaTeX）或编译后的 PDF；能定位源码行；
3. **模板化**：从 `.cls/.sty` + 示例 `.tex` 抽取模板档案与槽位，按模板智能填内容；
4. **审校**：按期刊规范/范本检查结构、引用、图表、必填章节、字数/页数、匿名要求等；
5. **修订**：输出修改后的 `.tex` 项目，或生成 `latexdiff` 红字版 PDF。

关键约束：期刊模板高度依赖自定义宏和 `.cls`，**不能简单转成 Markdown/Word 再转回**；
应以“源码为主、渲染为辅、编译可选”的方式处理。

---

## 2. 现状能力盘点

### 2.1 总览

| 能力域 | 现状 | 主要实现 | 关键限制 |
|---|---|---|---|
| Word 读取 | 段落/标题/表格/图片数/批注/核心属性/页眉页脚/脚注/尾注/目录域/图片缩略图 | `backend/office/word.py::read_docx`、`OfficeWordReadResult` | **扁平 DTO**：run 级仅直接粗体/斜体标记；不读字体名/字号/颜色/对齐/缩进/行距/页面设置/编号定义/书签/内容控件/修订/文本框 |
| Word 生成 | 结构化内容 → docx，版式即配置 | `word.py::generate_docx`、`word_layout.py`、`OfficeWordGenerateRequest` | 以“新建文档”为主；自定义样式只能改内置 Title/Normal/Heading/List；页眉页脚仅文本/对齐/PAGE 域 |
| Word 编辑 | 替换/追加/删段落/表格/样式/图片/批注 | `backend/office/edit.py::update_docx` | **明确不支持 track changes**；不碰页眉页脚/脚注/文本框；不支持表格行列增删/样式定义编辑/run 级局部格式 |
| 模板填充 | `{{ }}` 扫描与 docxtpl 渲染，正文/表格/页眉页脚 | `backend/office/word_template.py` | 只认 Jinja 占位符；类型靠关键词启发；不建模循环/条件块；无 LLM 自动填充；无内容控件/书签 |
| 内置模板库 | 6 套 Word + 2 套 Excel + 2 套 PPT，支持工作区用户模板 | `backend/office/template_library.py` | 没有 agent 工具入口；内置表格模板刻意不支持行循环（每格一个字符串） |
| 期刊模板 | `.doc/.docx → JournalSpec`，7 类规则，结构化填充，LLM 生成 + 两轮自纠 | `backend/office/journal/` | 规则固定 7 类；只服务学术论文；**填充时清空 body 重写**；page_size 硬编码 A4；`generate_article` 自纠未调用 validator |
| 格式校验 | FormatSpec 对偶 Linter，rule_id/severity/实测 vs 期望/fix_hint | `backend/office/word_lint.py::lint_docx` | 规则集固定；issue 无位置锚点/来源/证据；无内容语义规则 |
| 自动修复 | 版式/编号/题注确定性修复 + 复检 | `backend/office/word_repair.py::repair_docx` | 内容类违规不可修；输出非修订模式 |
| 目录/图表目录 | TOC/TOF 域 + 静态缓存 + Word COM 真页码刷新 | `word_layout.py`、`backend/office/toc_refresh.py` | 页码刷新仅 Windows + Word COM；无 Word 环境降级 |
| 交叉引用 | 题注书签 + REF 域 | `word_layout.py::append_ref_field` | 仅图/表题注；不覆盖标题/脚注/文献 |
| 引用体系 | GB/T 7714-2015 + APA 简化，BibTeX | `backend/office/references.py`、`bibtex.py` | 格式子集；不校验规范条文中的引用要求 |
| 脚注/尾注 | `{{fn:}}` / `{{en:}}` 内联语法 + OOXML part | `word.py`、`word_layout.py` | 读取只有文本清单，无正文锚点/编号映射 |
| 批注 | OOXML 读/写/删 | `word.py`、`edit.py` | 无修订；不支持回复/已解决状态；锚点以段落为主 |
| 预览 | docx-preview 高保真渲染 + DOM 消毒；结构化视图兜底 | `src/features/office/DocxNativePreview.tsx` | 无 issue 定位/高亮；无槽位交互 |
| 导出 | 检测本机 LibreOffice/Word COM 转 PDF | `backend/office/export_pdf.py`、`pdf_preview.py` | 未用于版式/分页校验 |
| 版本安全 | 内容哈希、写锁、幂等台账、409 冲突 | `backend/office/revision.py`、`apply_update.py` | 保证“陈旧写入被拒绝”，不保证跨进程互斥 |
| 前端 UI | 模板选择+动态槽位表单、交付抽屉 lint/修复、docx-preview 高保真预览、期刊面板 | `OfficeGenerateForm`/`OfficeGenerateSubforms`、`OfficeDeliveryDrawer`、`DocxNativePreview`、`JournalPanel` | 槽位仅静态声明；无必填/格式校验/图片上传；无 issue 定位/高亮；无文档对比/修订视图 |
| 项目约束 | 公文/合同/招投标/尽调版式预设 + 审校强度 | `project_constraint_repo.py`、`BuiltinCheckpointAndStyleBar.tsx` | 是自然语言约束文本，不是机器可执行规则 |

### 2.2 读取能力矩阵

| 能力项 | 支持程度 | 说明 |
|---|---|---|
| 正文段落文本 | ✅ 完整 | `paragraphs[]` 含 style、level、text |
| 标题层级 | ✅ 完整 | 基于样式名映射（Heading N → N，Title → 1） |
| 表格（含嵌套） | ✅ 较好 | 二维文本网格；嵌套表/单元格内图片忽略 |
| 页眉/页脚文本 | ✅ | 逐节，含 PAGE 域标记；链接前一节时返回空串 |
| 脚注/尾注文本 | ✅ | 回读清单；无正文锚点/编号映射 |
| 目录域 | ✅ 仅 instr | 不解析缓存条目结构 |
| 批注 | ✅ | 含 id/author/date/text/anchor_text；无回复/解决状态 |
| 核心属性 | ✅ | author/subject/keywords/comments/category；不读 title |
| 图片 | ✅ 数量 + 缩略图 | 不提取原始媒体/位置 |
| run 级粗体/斜体 | ⚠️ 仅直接格式 | `run.bold/italic` 渲染为 `**`/`*`；继承样式视为无格式 |
| run 级字体名/字号/颜色/下划线/删除线/高亮 | ❌ | 不读取 |
| 段落对齐/缩进/行距/段前段后 | ❌ | 不读取 |
| 自定义样式定义 | ❌ | 只返回段落 style 名，不返回样式定义 |
| 页面设置（纸张/方向/边距/分栏） | ❌ | 读取侧不返回 |
| 编号定义（numPr） | ❌ | 不解析 numbering.xml |
| 任意书签 | ❌ | 仅内部生成 REF 书签 |
| 内容控件（w:sdt） | ❌ | python-docx 1.1 无公开 API，全仓库无 `w:sdt` |
| 修订（w:ins/w:del） | ❌ | 模块 docstring 明确不提取 |
| 文本框/图形/图表 | ⚠️ 计数/缩略图 | 不解析内部文本 |
| 分页/实际版面 | ❌ | 需渲染器 |

### 2.3 写入能力矩阵

| 能力项 | 支持程度 | 说明 |
|---|---|---|
| 新建结构化文档 | ✅ | 标题/段落/列表/表格/图片/引用 |
| 页面与版式 | ✅ | 纸张/方向/边距/分节/页码格式/起始号 |
| 首页/奇偶页不同 | ✅ | 页眉页脚独立 |
| 多级标题编号 | ⚠️ 部分 | 字面 "N.M.K" 文本前缀，不是 Word 多级列表 numPr |
| 项目符号/编号列表 | ⚠️ 部分 | 使用内置 `List Bullet` / `List Number` 样式 |
| 目录/图表目录 | ✅ | TOC/TOF 域 + 缓存 + COM 刷新 |
| 交叉引用 | ⚠️ 部分 | 仅图/表题注 REF 域 |
| 脚注/尾注 | ✅ | OOXML part 挂载 |
| 批注增删 | ✅ | OOXML 级 |
| 参考文献 | ✅ | GB/T 7714 / APA 子集 |
| 页眉页脚 | ⚠️ 部分 | 文本/对齐/PAGE；不支持图片/表格/其他域 |
| 表格 | ⚠️ 部分 | 网格/三线/列宽/合并/表头重复；不支持嵌套表 |
| 段落级字体字号颜色 | ✅ | 作用于该段全部 runs |
| 自定义样式定义 | ⚠️ 部分 | 只能改内置 Title/Normal/Heading/List |
| 模板占位符填充 | ✅ | docxtpl，正文/表格/页眉页脚 |
| 任意既有文档改文本/表格/样式 | ✅ 有限 | `office_update` 的固定 op 集 |
| 内容控件填充 | ❌ | 无 SDT 写入 |
| 修订模式（track changes） | ❌ | 明确 non-goal |
| 任意 OOXML 特性 | ⚠️ | 可手工 XML，但无统一 IR |

### 2.4 场景 A 的缺口（逐项）

1. **模板识别面太窄**：只认 `{{ }}`。现实模板大量使用内容控件、书签、`【】`、`XX`、下划线空格、
   表格空单元格，甚至没有占位符（只有格式范本）。
2. **没有语义槽位模型**：当前 `TemplatePlaceholder` 只有 name/raw_tag/type/location/format_hint；
   缺必填、枚举、长度、正则、日期格式、默认值、数据来源、示例值、置信度。
3. **没有 LLM 自动填充闭环**：`office_fill_word_template` 要求调用方先给出完整 data map；
   没有“读资料 → 生成字段 → 校验 → 重试”的流程。
4. **循环/条件块未建模**：`has_jinja_control` 只告诉调用方“有控制语句”，不告诉它有哪些循环变量、
   表格行区块、条件字段，数据契约无法自动生成；内置表格模板刻意不支持行循环。
5. **填充后不校验**：只返回 `unfilled_placeholders`，不检查超长、类型错误、样式冲突、
   编号断裂、表格溢出。
6. **槽位 UI 只覆盖静态模板**：`OfficeGenerateForm` + `OfficeGenerateSubforms` 已能为内置/工作区
   模板的 placeholder 动态渲染输入框，但槽位来自模板库静态声明，不能“解析任意模板 → 生成可编辑
   Schema”；无必填/格式校验/图片上传；journal 面板只编辑标题/摘要/关键词，章节与参考文献没有
   表单；模板库也没有 agent 工具入口（只能 HTTP 实例化）。
7. **journal 不能当通用模板引擎**：`generate_structured` 的 `_write_sections` 会删除 body 全部
   段落和表格，只保留 `w:sectPr`，再按章节重写——模板中的表格、图片、封面、多节布局都会丢失。
   它适合“学术论文骨架”，不适合“保留原模板版式的槽位替换”。
8. **journal 自纠名不副实**：`generate_article` 第二轮只校验 content 形状与 abstract/keywords，
   **没有调用 `validate_document`**，也没有把文档级违规反馈给 LLM（与 docstring 不一致）。
9. **无范本学习**：journal parser 只抽固定 7 项；不能从任意范本学习段落/字符/页面/表格样式，
   生成可复用模板档案。
10. **无来源追溯**：填充内容来自哪份资料、哪段上下文，没有记录。

### 2.5 场景 B 的缺口（逐项）

1. **规则被固定模型锁死**：`WordFormatSpec` 是封闭字段集；`word_lint` 的规则是硬编码分支；
   无法表达“标题不超过 20 字”“一级标题必须是‘一、’”“成文日期右空四字”“表格表头黑体”等条文明规则。
2. **无规范抽取**：没有“规范条文 → 候选规则”的流水线，也没有人工确认与来源引用。
3. **无范本规则学习**：journal parser 是固定 7 项；没有通用的 style-learn（dominant style profile）。
4. **issue 不可定位**：`WordLintIssue` 只有 rule_id/severity/message/fix_hint，连 location 字段都没有；
   `JournalViolation.location` 只是一个展示字符串；两者都没有段落索引、表格坐标、文本片段、
   OOXML 路径、页码，UI 无法跳转高亮。
5. **无证据与来源**：规则来自哪条规范、哪个范本、哪次用户设置，不可追溯。
6. **无内容语义规则**：必填章节、结语用语、称谓/术语一致性、日期格式、金额大小写、
   引用完整性等，现有 Linter 基本不覆盖（journal 的 citation/heading 是特例）。
7. **无修订模式**：修复是直接改写/新文件；用户无法在 Word 审阅面板逐条接受/拒绝。
8. **无渲染级校验**：分页、页码位置、页边距实际排版、表格溢出、孤行/寡行、单字不成行、
   字体缺失回退，这些必须渲染后才能判断；现有仅 COM 刷新目录。
9. **无规则治理**：没有规则包分层（官方/单位/项目/用户）、版本、启停、冲突检测、批量审计。
10. **无标准规则包**：项目约束里只有 GB/T 9704 的自然语言文本，没有可执行规则集。
11. **无文档对比/修订视图**：现有 diff 是 git 文本 diff、artifact 版本文本 diff、Office 操作级 diff；
    没有两份 Word 的结构级/页面级对比，也没有 track changes/redline 的接受/拒绝界面。
12. **文件预览未接锚点**：`FilePreviewPanel`（origin/main 的 file-reference-preview 成果）只接收路径，
    无 anchor/highlight；`WordPreview` 段落无索引；`DocxBlobPreview` 渲染后 DOM 不透明。
    注意：当前工作区 HEAD（`b3bfb9dca`）尚未包含该预览面板，`origin/main`（`66299ab15`）
    才包含 `feat/file-reference-preview` 的合入提交；实施前需先同步。
13. **产物交付入口不完整**：Office 文档有 `saveAs/openOfficeDocument/showOfficeDocumentInFolder`，
    artifact 面板只有复制路径/文件管理器定位/HTML 独立窗口，没有通用下载/另存为；
    生成结果应复用 Office 文档的 `saveAs` 路径。

### 2.6 可复用资产清单（不要重复造）

| 资产 | 位置 | 复用方式 |
|---|---|---|
| FormatSpec 应用器 | `backend/office/word_layout.py::apply_format_spec` | 规则包的确定性修复器直接复用 |
| Linter | `backend/office/word_lint.py::lint_docx` | 扩展规则注册与 issue 锚点 |
| Repair | `backend/office/word_repair.py::repair_docx` | 复用修复-复检闭环 |
| 模板分析/填充 | `backend/office/word_template.py` | 作为 Jinja 适配器，外包一层统一 Profile |
| 内置模板库 | `backend/office/template_library.py` | 槽位静态声明可作为“已知模板”先验 |
| 期刊解析/校验/生成 | `backend/office/journal/` | 范本解析先例；7 类规则并入统一规则包；**仅复用 parser/validator，不复用 clear-body generator** |
| 文档编辑 op 集 | `backend/office/edit.py` | 文本/表格/样式/批注修复的执行器 |
| 批注 OOXML | `edit.py` 的 add_comment/delete_comment | 审校意见落地 |
| 版本哈希/写锁/幂等 | `backend/office/revision.py`、`apply_update.py` | 审计/修复写入的并发安全与 409 冲突 |
| 差异预览 | `backend/office/diff_preview.py` | 修复前预览与用户确认 |
| 目录/页码刷新 | `backend/office/toc_refresh.py`、`export_pdf.py` | 渲染校验的现有通道 |
| PDF 预览/导出/PDF→Word | `backend/office/pdf_preview.py`、`export_pdf.py`、`pdf_to_word.py` | 渲染与格式转换先例 |
| 高保真预览 | `src/features/office/DocxNativePreview.tsx` | issue 定位/槽位预览的渲染基座 |
| 交付抽屉 | `src/features/office/OfficeDeliveryDrawer.tsx` | 审校结果面板的入口 |
| 期刊面板 | `src/features/journal/JournalPanel.tsx` | 通用模板面板的 UI 先例 |
| 模板选择/槽位表单 | `OfficeGenerateForm.tsx`、`OfficeGenerateSubforms.tsx` | 直接扩展为 Schema 驱动表单，不另起一套 |
| 文本/操作级 diff | `ChangesSection.tsx`、`SplitDiff.tsx`、`OfficeEditPreviewDialog.tsx`、`OfficeSnapshotPanel.tsx` | 对比/修订 UI 的先例 |
| 右栏文件预览 | `origin/main:src/widgets/chat/preview/FilePreviewPanel.tsx` | 仅 origin/main；需增加 anchor/highlight |
| 项目约束 | `backend/data/project_constraint_repo.py` | 规则包的项目级挂载点 |
| 工具三件套门禁 | `tool_names.py` / `profiles.py` / `test_office_create_schema_contract.py` | 新增工具必须同步 |

### 2.7 LaTeX 能力现状

**当前结论：有 LaTeX 项目识别/文本扫描、公式渲染和 `.doc` 转换三块边角能力，但没有 LaTeX 结构解析、渲染、模板或审校能力。**

| 能力项 | 现状 | 证据 | 说明 |
|---|---|---|---|
| `.tex` 读取/解析 | ❌ 无 | 全仓无 `.tex` fixture；无 LaTeX parser 依赖 | 不能识别 `\documentclass`、章节、公式、图表、引用 |
| LaTeX 项目解析（多文件） | ❌ 无 | — | 不处理 `\input`/`\include`、`.cls/.sty`、`.bib`、figures |
| LaTeX→HTML 渲染 | ❌ 无 | `ArtifactViewer`（当前 HEAD）/`FileContentRenderer`（origin/main）无 `.tex` 分支 | 只有 Markdown 内公式可渲染；`.tex` 产物落 `<pre>` |
| LaTeX→PDF 编译 | ❌ 无 | 无 Tectonic/latexmk/TeX Live/MiKTeX 调用 | 无编译日志、无页数/版式校验 |
| LaTeX 模板档案/槽位 | ❌ 无 | journal 只支持 `.doc/.docx` | 不能从 `.cls/.sty` + 示例 `.tex` 抽槽位 |
| LaTeX 模板填充 | ❌ 无 | — | 不能按 `\title{}`/`\author{}`/环境填内容 |
| LaTeX 审校/修订 | ❌ 无 | — | 无 LaTeX 规则、无 `latexdiff` 红字版 |
| 前端公式渲染 | ✅ 部分 | `package.json:68` KaTeX 0.18.6；`remark-math`/`rehype-katex`；`MessageMarkdownParts.tsx`、`ArtifactViewer.tsx`、`HelpTab.tsx` | 仅 Markdown 数学公式；不是 `.tex` 文档渲染 |
| `.doc → .docx` | ✅ | `backend/office/journal/pandoc_adapter.py` | 仅 journal 用；系统 pandoc；30s 超时；sha256 缓存 |
| `.bib` 解析 | ✅ 部分 | `backend/office/bibtex.py` | 可解析入口，但未与 LaTeX `\cite{}`/BibTeX 流程打通 |
| LaTeX 项目识别/扫描 | ✅ 部分 | `backend/services/project_type_detector.py:71,337`、`project_profiler.py:120`、`project_workspace_inspector.py:341` | 能识别 `.tex`/bibtex/elsarticle/ieeetran/overleaf 项目并按文本/代码读取；无结构解析/渲染 |
| `.tex` 纯文本读取 | ✅ 部分 | `backend/tools/file_tool.py:264,296,359-363`、`project_workspace_inspector.py:336,422`、`project_profiler.py:580-596` | 只读原文；5 MiB 单文件上限；无结构 |
| DOCX↔LaTeX | ❌ 无 | `docs/technical/56-word-content-elements.md` 把 “LaTeX→OMML” 列为后续候选 | 无公式转换、无 LaTeX 生成 |

**接入面缺口（当前 HEAD）**

- 聊天附件白名单不含 `.tex`（`backend/api/chat_attachment_routes.py:47-67`）；`@` 解析只保留
  Office 类型（`backend/chat/attachment_resolver.py:338-346,447-453`）；Wiki ingest 不支持 `.tex`
  （`backend/wiki/file_parser.py:89-105`）。
- 工作区语义索引 `INDEXED_EXTS` 不含 `.tex/.bib`（`backend/tools/workspace_index.py:35-42`）。
- artifact 类型映射无 `.tex`，归类为 `text`，前端落到 `<pre>`
  （`backend/data/artifact_repo.py:219-273`；`src/widgets/chat/artifacts/ArtifactViewer.tsx:375-438`）。
- `src/shared/lib/fileLang.ts` 无 `tex` 映射；Shiki 已带 `latex` 语言包，可低成本接入语法高亮。
- `read_file` 单文件 5 MiB 上限；LaTeX 项目 zip 需另设项目级限制。
- `HelpTab` / `BtwOverlay` 只注册 `rehypeKatex`、缺 `remarkMath`，公式实际不渲染；
  Wiki `MarkdownPreview` 只有 `remarkGfm`，完全无公式。
- `pandoc_adapter` 仅 `shutil.which` 检测，不校验版本/平台；错误提示写死 `apt install pandoc`，
  对 Windows/Win7 不友好；`.doc` 转换失败无降级路径。

**逐项缺口（对应 1.4 的五个子场景）**

1. **项目读取**：无主文件识别、无 include 递归、无 `.cls/.sty` 宏表、无路径安全与循环检测。
2. **结构解析**：无 AST/DocumentProfile；无法区分章节、公式、图、表、引用、标签、脚注；
   无未知宏降级策略。
3. **渲染**：无 HTML 语义渲染；无 KaTeX 宏表注入；无 PDF 编译通道；无源码/预览对照。
4. **模板**：无 LaTeX TemplateProfile；无槽位锚点（命令参数/环境体/占位符/注释）；
   无填充后的 brace/ref/cite 校验。
5. **审校**：无 LaTeX 规则（文档类、必填章节、引用键、标签、图表题注、字数/页数、匿名模式）；
   无 `latexdiff` 红字版。
6. **平台**：Win7 不能依赖现代 Tectonic（Rust 1.78+ 最低 Windows 10）；不能把 TeX Live
   全量塞进安装包；必须设计“读取+HTML 渲染可用，PDF 编译可选”的降级路径。
7. **安全**：LaTeX 编译远不止 `\write18`；`\openin/\openout/\input` 在关闭 shell-escape 时
   仍可读写文件；Tectonic `--untrusted` 也不能完全阻断（CVE-2026-105744）。必须 OS 级隔离。

---

## 3. 业界参考与可借鉴模式

### 3.1 Microsoft Copilot：规则书 → 抽取 → 审阅 → 批注

Microsoft 的 Document Validation agent 模板（early access，2026）流程是：

1. 上传规则书（`.docx/.txt/.html`）；
2. 自动抽取规则，**允许人工审阅/增删/调整风险级别**；
3. 对待审文档逐条验证；
4. 以 Word 批注输出问题，带 **Critical / Advisory** 风险级别、解释与建议修复；
5. 可持久化规则（Tune Context），用样例文档评估召回/精确率。

可借鉴：**规则书即输入、抽取后必须人工确认、风险分级、批注落地、规则可持久化**。
不照搬：其限制是单文档、不支持多模态/扫描件；Sage 需要本地处理与更强格式能力。

### 3.2 Google Docs Gemini：Match the format

2026 年 3 月 Gemini for Docs 推出 “Match the format”：直接套用另一篇文档的结构与样式。
这对应场景 B 的“范本模式”——规范不一定是条文，也可能是一份“照这个来”的文件。

可借鉴：**范本档案抽取**应与条文规则抽取并列，而不是只支持文字规范。

### 3.3 WPS 智能公文 / 黑马校对：拟、校、排、印闭环

WPS 智能公文的能力组合：

- 国标模板库与文种识别；
- 关键要素（文号、密级、签发人）智能校验与填充；
- AI 排版：替换为指定字体、单字不成行、特殊名称不折行等公文专属规则；
- AI 校对 + 黑马校对：错漏、敏感词、合规、字体嵌入完整性；
- 问题定位 + 一键修正 + 批量处理 + 私有化/离线。

可借鉴：**格式检查必须能定位与一键修**；**字体嵌入/缺失检查**是中文正式文档的刚需；
**规则要按文种/单位可配置**。Sage 的差异化是本地、可扩展、与项目/记忆/文献系统打通。

### 3.4 Claude DOCX Skill / Claude for Word：OOXML 与修订

Anthropic 的 DOCX skill 与 Word 插件强调：

- 读取用 pandoc（`--track-changes=all`），复杂结构回退 OOXML；
- 编辑用 OOXML **最小精确修改**，默认输出 Word 原生修订（`w:ins`/`w:del`）与批注；
- 生成后用 LibreOffice 验证，再转回 Markdown 复核；
- 模板型起草遵循模板样式。

可借鉴：**修订模式是审校类产品的默认输出**；**最小修改**避免整篇重排；
**生成后回读/渲染验证**形成闭环。

### 3.5 开源 gongwen-skill：YAML 三层规则 + DocumentModel + style-learn

该 MIT 项目（GitHub `linhut/gongwen-skill`）与我们的场景高度重合：

- `parse`：`.docx → DocumentModel`（含文本框、修订摘要）；
- `check`：按国标检查，P0/P1/P2 分级，只读；
- `optimize`：自动修复字体/字号/行距/页边距，`--verify` 复检；
- `optimize-content`：默认 **Word 原生修订 + 批注**；
- 规则库 `rules/official/*.yaml`：`_common.yaml` 定义页面/标题/正文/表格/序号/空行，
  每种文种一个 YAML（如 `notice.yaml` 定义结语、标题格式、通知事项）；
- 三层规则：官方 / 单位 / 用户；
- `style-learn`：从标准文档学习 Run/段落/页面三级样式，生成命名模板。

可借鉴：**YAML 规则包 + P0/P1/P2 + 修复-复检 + 原生修订 + 范本样式学习**几乎就是本方案的目标形态。
注意：其规则/字体资产有 License 与标准文本版权问题，不能直接整体复制；可借鉴结构与少量通用参数，
规则内容需自行编写或由用户提供。

### 3.6 文档解析与版本对比工具

- **Docling / MarkItDown / MinerU**：强在语义结构抽取（标题、表格、阅读顺序），适合“规范条文 → 文本”
  与 RAG；但都不保证 Word 视觉样式保真，且 MarkItDown 需 Python 3.10+、Docling 依赖重。
- **python-redlines / paper-docx / Adeu**：能把两份 docx 的差异写成 Word 原生修订。
  python-redlines 需 Python 3.9+ 且依赖 .NET 预编译二进制，不适合 win7 内核。
- **docxcast**：把 Word 内容控件变成 JSON Schema，再回填，正是场景 A 的理想契约；
  但需 Python 3.9+ / python-docx 1.2+，win7 不可用。

可借鉴：**主分支可选增强，核心路径用自有轻量实现**，避免 win7 被重依赖卡死。

### 3.7 研究结论

- 2025–2026 的文档合规方案普遍采用“**LLM 抽规则 → 结构化规则存储 → 确定性验证 + LLM 语义评分 →
  人工复核 → 证据链**”，而不是“让 LLM 直接读规范当裁判”。
- “Hidden Tax” 类研究指出：把规则放在上下文里，模型往往“知道但不执行”，
  必须由模型外的机械层强制执行。这直接支持本方案的“确定性优先”原则。
- 规则治理需要：稳定 ID、版本、来源、适用范围、严重级别、测试样例、冲突/去重。

### 3.8 对本项目的 8 条启示

1. 规则包必须可分层、可版本化、可人工审阅。
2. 规则抽取是“候选生成”，不是自动生效；必须有人工确认门。
3. 格式规则尽量编译成确定性检查；语义规则才交给 LLM。
4. 审校输出必须能定位到文档结构，最好能跳转/高亮。
5. 修复必须可逆、可审阅；默认新文件 + 原生修订。
6. 范本学习与条文抽取同等重要。
7. 渲染级校验不可省略，但要作为可选能力（依赖本机 Word/LO）。
8. 模板填充与规范审校共用同一套锚点、规则、issue、修复基础设施。

### 3.9 LaTeX 生态参考

| 方案 | 角色 | 可借鉴 | 限制 |
|---|---|---|---|
| **LaTeXML** | LaTeX → HTML + MathML 语义转换 | arXiv 用它生成论文 HTML；保留定理、引用、公式结构 | Perl 外部依赖；自定义宏/包覆盖有限；慢 |
| **Pandoc** | LaTeX ↔ HTML/DOCX/Markdown | 快速转换、公式转 MathML/OMML、引用处理 | 自定义 `.cls`/宏不能完全还原；外部二进制 |
| **TexSoup** | 容错 LaTeX 解析树 | arXiv 50/50 论文解析成功、平均 668ms；可搜索/修改 | 不是完整 TeX 引擎；复杂宏只保留文本 |
| **pylatexenc** | LaTeX 语法 walker / Unicode 转换 | 纯 Python、轻量、适合文本与转义 | 不是文档转换器 |
| **plasTeX** | Python LaTeX 文档处理框架 | XML-DOM 式文档模型、可扩展输出 | arXiv 基准 11/50；宏覆盖较弱 |
| **Tectonic** | 自包含 TeX 引擎（XeTeX/TeXLive） | 单二进制、按需下载/缓存包、可复现 | Rust 1.78+ 最低 Windows 10，**Win7 不可用**；首编译需网络；沙箱仍需 OS 级 |
| **TeX Live / MiKTeX + latexmk** | 传统编译链 | 兼容性最好、期刊模板支持最全 | 体积大、安装重；Win7 版本受限 |
| **latexdiff** | 两份 `.tex` → 红字修订 `.tex`/PDF | LaTeX 审校的事实标准；支持多文件 `--flatten` | 需 Perl + TeX；只做差异标记，不是结构审校 |
| **KaTeX** | 浏览器数学公式渲染 | 快、小、同步；Sage 已集成 | 只支持数学子集；不支持 TikZ/完整文档/交叉引用编号 |
| **MathJax v4** | 浏览器数学渲染 | 宏/包覆盖更广、可访问性更好 | 体积大、异步；仍不支持 TikZ |

**关键结论**

1. **读取**：用 TexSoup 做容错结构树 + pylatexenc 做文本/转义，纯 Python、可 py38；
   pandoc/LaTeXML 作为“复杂文档”的可选增强，不作为核心依赖。
2. **渲染**：默认 HTML + KaTeX（安全、跨平台）；PDF 编译作为可选增强，检测本机引擎；
   Win7 只承诺读取 + HTML 渲染。
3. **模板**：以源码为主，解析 `.cls/.sty` 的 `\ProvidesClass`/`\RequirePackage`/`\newcommand`/
   `\newenvironment`，结合示例 `.tex` 推断槽位；不要先转 Word 再转回。
4. **修订**：LaTeX 没有 Word 式 track changes，标准做法是 `latexdiff` 生成红字版 PDF；
   保留修改后的 `.tex` + diff `.tex` + 可选 PDF。
5. **安全**：LaTeX 编译必须在 OS 级隔离中运行；`--no-shell-escape` 不等于安全；
   `\openin/\openout/\input` 仍可读写文件。默认不编译不可信文档，HTML 渲染不执行 TeX。
6. **AI 产品参考**：Overleaf + Writefull 已把 AI 嵌入 LaTeX 编辑（TeXGPT、表格/公式生成、
   语言反馈），但**没有自动按期刊模板填充**；这正是 Sage 可以差异化的方向。

---

## 4. 总体方案

### 4.1 架构

```
                         ┌──────────────────────────────────────────────┐
  模板 (.docx) ─────────▶│  TemplateProfile Extractor                   │
  规范条文 (.docx/pdf) ─▶│   ├─ JinjaAdapter (现有 docxtpl)             │
  范本 (.docx) ────────▶│   ├─ ContentControlAdapter (w:sdt)           │
  待审文档 (.docx) ─────▶│   ├─ BookmarkAdapter (w:bookmarkStart)       │
                         │   └─ HeuristicAdapter (【】/XX/空格/样式)     │
                         └───────────────┬──────────────────────────────┘
                                         │
                    ┌────────────────────▼────────────────────┐
                    │  DocumentProfile / SlotSchema (JSON)    │
                    │  + StyleProfile + StructureProfile      │
                    └────────────┬────────────────────────────┘
                                 │
        ┌────────────────────────┼───────────────────────────┐
        │                        │                           │
        ▼                        ▼                           ▼
┌───────────────┐      ┌──────────────────┐       ┌──────────────────┐
│ TemplateFiller│      │ RuleStore        │       │ AuditEngine      │
│ 取数/生成/校验 │      │ 三层规则包+版本   │       │ 确定性+语义检查   │
│ 确定性渲染     │      │ 来源/冲突/启停    │       │ 锚点/证据/分级    │
└───────┬───────┘      └────────┬─────────┘       └────────┬─────────┘
        │                       │                          │
        │                       ▼                          ▼
        │              ┌──────────────────┐       ┌──────────────────┐
        │              │ RuleExtractor    │       │ FixPlanner       │
        │              │ 条文/范本/模板    │       │ 确定性修复+LLM修订 │
        │              └──────────────────┘       └────────┬─────────┘
        │                                                  │
        ▼                                                  ▼
┌───────────────────────────────┐              ┌────────────────────────────┐
│ 输出 docx + 未填清单 + 质量报告 │              │ 修订版 docx + 批注 + 审计报告 │
└───────────────────────────────┘              └────────────────────────────┘
        └──────────────────────────┬───────────────────────────┘
                                   ▼
                    ┌─────────────────────────────────┐
                    │ 接入层：REST / Agent Tools / UI   │
                    │ OfficeDeliveryDrawer / TemplateUI │
                    └─────────────────────────────────┘
```

> LaTeX 轨道复用同一套 `DocumentProfile` / `SlotSchema` / `RulePack` / `Issue` 概念，
> 但项目解析与渲染由 `backend/office/latex/` 独立实现，见 4.9。

### 4.2 核心概念

#### DocumentProfile

对一份文档的“可检查快照”：

- `page`: 纸张、方向、页边距、页眉页脚距离、分节；
- `styles`: 语义角色 → 有效格式（字体/字号/加粗/颜色/对齐/行距/缩进/段距）；
- `structure`: 章节树、标题层级、编号体系、必需章节、表格/图/脚注清单；
- `anchors`: 每个段落/表格/单元格/域/批注的稳定锚点；
- `sources`: 样式解析来源（docDefaults / style / theme / direct）。

#### SlotSchema

模板槽位的机器契约，直接作为 LLM 的 JSON Schema：

- `name`、`label`、`description`、`type`（text/rich_text/date/number/enum/boolean/table/image/section）；
- `required`、`default`、`options`、`pattern`、`min/max`、`max_length`、`date_format`；
- `anchor`（段落/表格/单元格/内容控件 tag/书签/占位符偏移）；
- `repeat`（行/区块循环）、`condition`（条件显示）；
- `evidence`（建议来源：用户输入/工作区文档/文献库/项目资料）；
- `confidence`（自动推断置信度）。

#### RulePack

一组可执行规则的集合，支持三层覆盖：

```
builtin（系统内置） < organization（单位/项目） < user（用户）
```

每条规则：

```yaml
id: GB9704-FONT-BODY
version: 1
name: 正文使用三号仿宋_GB2312
category: style           # page/style/structure/content/table/numbering/citation/rendering
severity: P0              # P0/error 阻断；P1/warning 重要；P2/info 建议
applies_to:
  doc_type: [notice, report, official_letter]
selector:
  role: body              # 语义角色，不是硬编码段落号
  style_name: Normal
expected:
  font: 仿宋_GB2312
  size_pt: 16
  line_spacing_pt: 28
  first_line_indent_em: 2
check:
  type: deterministic     # deterministic | llm | hybrid
  tolerance: {size_pt: 0.5, margin_cm: 0.05}
fix:
  type: deterministic
  action: apply_style
source:
  document: "GB/T 9704-2012"
  clause: "5.2.2 正文"
  page: 8
```

#### Issue / Evidence

```json
{
  "rule_id": "GB9704-FONT-BODY",
  "severity": "P0",
  "category": "style",
  "message": "正文第 3 段字体为宋体，期望仿宋_GB2312",
  "expected": {"font": "仿宋_GB2312"},
  "actual": {"font": "宋体"},
  "anchor": {
    "kind": "paragraph",
    "paragraph_index": 12,
    "text_snippet": "现将有关事项通知如下……",
    "ooxml_path": "/w:document/w:body/w:p[13]"
  },
  "evidence": {"source_document": "GB/T 9704-2012", "clause": "5.2.2"},
  "fixable": true,
  "fix_kind": "deterministic"
}
```

#### RevisionPatch

对文档的最小修改计划：

- 确定性 patch：样式/页面/编号/表格属性；
- 文本 patch：插入/删除/替换，可包装为 `w:ins`/`w:del`；
- 批注 patch：锚定问题并写解释；
- 每个 patch 必须可单独接受/拒绝，且可重放。

### 4.3 场景 A：模板智能填充流水线

#### Step 1：模板摄入

- `.docx` 直接解析；`.doc` 复用 pandoc 适配器转 `.docx`（已有）；
- 安全校验：zip 大小/成员数/解压体积、宏剥离、外部关系拒绝、XML 实体禁用（复用
  `word_template._validate_docx_zip` 与安全扫描）；
- 生成 `DocumentProfile`（至少页面 + 样式角色 + 结构）。

#### Step 2：槽位抽取（四适配器）

| 适配器 | 识别对象 | 优先级 |
|---|---|---|
| ContentControlAdapter | `w:sdt` 的 alias/tag/title/类型/锁定/重复节 | 最高（最明确的契约） |
| JinjaAdapter | `{{ var }}`、`{%tr for %}`、`{% if %}` | 高（现有） |
| BookmarkAdapter | `w:bookmarkStart/End` 名称 | 中 |
| HeuristicAdapter | `【…】`、`XX/××`、下划线空格、空表格单元格、高亮文本、示例值 | 低（需人工确认） |

输出统一的 `TemplateProfile`：

```json
{
  "template_id": "...",
  "doc_type": "notice",
  "page": {"paper": "A4", "margins_cm": {"top": 2.8, "bottom": 2.8, "left": 2.7, "right": 2.7}},
  "style_roles": {
    "title": {"font": "方正小标宋简体", "size_pt": 22, "align": "center"},
    "h1": {"font": "黑体", "size_pt": 16},
    "body": {"font": "仿宋_GB2312", "size_pt": 16, "line_spacing_pt": 28}
  },
  "slots": [
    {
      "name": "doc_number",
      "label": "发文字号",
      "type": "text",
      "required": true,
      "pattern": "^[\\u4e00-\\u9fa5]+〔\\d{4}〕\\d+号$",
      "anchor": {"kind": "content_control", "tag": "doc_number"},
      "confidence": 0.98
    }
  ],
  "repeat_regions": [],
  "conditions": [],
  "required_sections": []
}
```

#### Step 3：Schema 构建与人工确认

- 自动推断的槽位（Heuristic）标记 `confidence < 0.8`，必须在 UI 中确认；
- 支持用户改名、改类型、设必填、设枚举、设默认值、绑定数据来源；
- 确认后的 Profile 可保存为工作区“用户模板”，后续复用。

#### Step 4：上下文装配

按槽位 `evidence` 策略取数：

1. 用户显式输入（表单/对话）；
2. 工作区文档/项目资料（RAG，复用现有文献库/Wiki/文件检索）；
3. 用户画像/记忆（如单位名称、发文字号规则）；
4. 对话上下文；
5. 无依据时留空或显式标注 `[待补充]`，**不编造**。

#### Step 5：LLM 结构化填充

- 把 `SlotSchema` 转为 JSON Schema 交给 LLM；
- 按章节/区块分段生成，避免一次性长文失控；
- 要求返回 `{value, evidence, confidence}`，证据不足时返回空；
- 使用 Pydantic/JSON Schema 校验；失败把错误反馈给 LLM 重试（最多 N 轮）；
- 对重复表格行，先生成数组，再按模板行克隆。

#### Step 6：确定性渲染

- Jinja 适配器：现有 docxtpl + SandboxedEnvironment；
- 内容控件适配器：OOXML 替换 `w:sdtContent`，保留 `w:sdtPr` 与 run 格式，可选解包；
- 书签适配器：在书签范围内替换文本；
- 重复区块：克隆模板行/段落（复制 `w:tr`/`w:p` 的 XML，重映射 `w:id`/关系）；
- 图片：按关系 ID 替换或插入 `InlineImage`；
- **绝不整篇重建**；只动槽位。**不复用 journal 的 clear-body generator**。

#### Step 7：校验与修复闭环

填充后自动执行：

1. 未解析占位符/控件残留检查；
2. Schema 校验（类型/枚举/长度/正则/日期）；
3. 模板 Profile 的格式审计（字体/字号/行距/编号/表格）；
4. 结构审计（必需章节/标题层级/表格列数）；
5. 可选渲染校验（页数、页码、溢出、字体缺失）；
6. 不通过则回到 Step 5 重试（最多 2–3 轮），仍失败则输出问题清单。

#### Step 8：输出与归档

- 写新文件，命名冲突拒绝覆盖；
- 记录 artifact + 生成记录（模板 ID、槽位值、证据、校验结果）；
- UI 提供“预览 → 调整 → 重新生成 → 下载”。

### 4.4 场景 B：规范 → 规则 → 审校流水线

#### Step 1：规范摄入

三种来源：

| 来源 | 解析方式 | 产出 |
|---|---|---|
| 规范条文（.docx/.pdf/.txt/.html） | python-docx / 现有 PDF 读取 / 可选 Docling、MarkItDown（main） | 分节文本 + 表格 + 页码/条目 |
| 范本 .docx | `DocumentProfile` + 样式统计 | `StyleProfile` + `StructureProfile` |
| 模板 .docx | 复用 journal parser + 新 Profile | `StyleProfile` + 槽位 |

#### Step 2：规则候选抽取

**条文模式**：

- 按标题/条款分段；
- LLM 用固定 JSON Schema 抽取候选规则：检查对象、期望值、容差、适用范围、严重级别、来源；
- 确定性后校验：单位换算（cm/pt/twips/EMU）、数值范围、枚举合法、正则可编译；
- 无法机器化的条款（如“语言得体”）标记为 `manual` 或 `llm`，不伪装成确定性规则。

**范本模式**：

- 统计每个语义角色的主导格式（众数/中位数/分布）；
- 提取页面设置、页眉页脚、编号体系、表格样式、章节骨架；
- 期望值 = 主导值；容差按测量误差；离群值列为“模板自身不一致”提示；
- 用户确认“以范本为准”的规则子集。

**模板模式**：

- journal parser 的 7 类规则并入；
- 补充页面/页眉页脚/表格/编号/结构规则；
- 修正 `page_size` 硬编码 A4 的限制（从 `sectPr` 读取）。

#### Step 3：去重、冲突与人工复核

- 按 `(category, selector, expected)` 聚类去重；
- 冲突规则（同一选择器不同期望值）标记冲突，要求用户选择；
- 每条规则展示：来源原文、抽取置信度、影响的文档片段示例；
- 用户可启停/改值/改级别/加测试样例；
- 通过后写入 RuleStore，生成版本号。

#### Step 4：RuleStore（三层规则包）

```
builtin/
  gb9704.yaml            # 可执行参数（字体/字号/页边距/层级序号），来源标注
  journal-general.yaml
  report-general.yaml
organization/
  <workspace>/org-rules.yaml
user/
  <user>/my-rules.yaml
```

合并规则：同 ID 高优先级覆盖低优先级；不同 ID 追加；冲突在加载时检测并告警。
规则包可导出/导入（YAML/JSON），便于单位内分发。

#### Step 5：执行检查

```
待审 .docx
  → DocumentProfile（StyleResolver + StructureResolver + AnchorResolver）
  → 规则编译（RulePack → 检查器列表）
  → 确定性检查（页面/样式/编号/结构/表格/引用）
  → 语义检查（LLM，带规则原文与文档片段）
  → Issue 聚合（排序/去重/分级）
  → 审计报告 / UI
```

确定性检查优先，LLM 检查只处理无法测量的规则；两者都产出统一 Issue 结构。

#### Step 6：问题定位与展示

- `anchor` 支持：段落索引、表格索引+行列、页眉/页脚、脚注/尾注、域、内容控件、书签；
- 前端在 `DocxNativePreview` 渲染后的 DOM 中按段落顺序打 `data-doc-anchor`，
  点击 issue 滚动并高亮；结构化视图兜底；
- 问题列表支持按严重级别/类别/规则/位置过滤；
- 每条问题显示：期望 vs 实测、来源条款、修复方式、置信度。

#### Step 7：修复与修订

两类修复：

| 类型 | 执行方式 | 输出 |
|---|---|---|
| 确定性 | `apply_format_spec` / 样式/编号/表格 fixer | 新文件或原地（用户确认） |
| 语义 | LLM 生成替换文本 → 包装为 `w:ins`/`w:del` + 批注 | 修订版，用户逐条接受/拒绝 |

修复策略：

- 默认“只读审计”；
- 用户可选择“修复选中问题”或“修复全部可自动修复项”；
- 每条修复记录 rule_id + 原值 + 新值 + 依据；
- 修复后自动复检，输出剩余问题；
- 绝不在用户未确认时覆盖原文件；
- 写入复用 `revision.py` 的内容哈希/写锁/幂等语义，冲突返回 409。

#### Step 8：审计报告

- JSON（给系统/Agent）；
- Markdown/HTML（给人看）；
- 可选 docx 报告（问题清单 + 统计 + 规则来源）；
- 可选“批注版 docx”（每条问题落在原文位置）。

### 4.5 模板/规范/文档的统一锚点

所有能力共用一套锚点模型，避免三套坐标系：

```json
{
  "paragraph_index": 12,
  "table_index": null,
  "row": null,
  "col": null,
  "story": "body",
  "sdt_tag": null,
  "bookmark": null,
  "field_instr": null,
  "text_hash": "sha1:..."
}
```

- `paragraph_index` 对应 `doc.paragraphs` 顺序（含表格内段落时需明确 story）；
- 表格内锚点用 `table_index/row/col`；
- `text_hash` 用于文档变更后的锚点重定位；
- 渲染后通过顺序映射到 docx-preview DOM。

### 4.6 修订模式（track changes）设计

现状：`edit.py` 明确不支持 track changes；`word_layout` 直接写最终格式；`read_docx` 不读修订。

建议实现一个最小但完整的 `RevisionWriter`：

1. 文本插入：`<w:ins w:id w:author w:date><w:r>…</w:r></w:ins>`；
2. 文本删除：`<w:del …><w:r><w:delText>…</w:delText></w:r></w:del>`；
3. 替换：删除旧文本 + 插入新文本，保持原 run 的 rPr；
4. 段落插入/删除：`w:ins`/`w:del` 包住 `w:p`（注意 `w:del` 内不允许 `w:p` 的边界规则）；
5. 格式变更：`<w:rPrChange>` / `<w:pPrChange>` 记录原格式；
6. 批注：复用现有 comments part，锚定范围；
7. ID 分配：全局递增，避免与现有修订冲突；
8. 作者/时间：使用“Sage 审校”与当前时间，可配置；
9. 输出后回读校验：`w:ins`/`w:del` 结构合法、Word/WPS 可打开。

分阶段：

- Phase 1：文本替换/插入/删除 + 批注（覆盖 80% 审校场景）；
- Phase 2：格式变更修订 + 段落级修订；
- Phase 3：可选接入 `python-redlines` 做任意两版本对比（main only）。

### 4.7 渲染级校验（可选增强）

纯 OOXML 无法判断分页、页码位置、表格是否溢出、孤行寡行、字体回退。方案：

| 通道 | 平台 | 用途 | 降级 |
|---|---|---|---|
| Word COM | Windows + pywin32 | 精确分页、域刷新、导出 PDF | 无 Word → 跳过 |
| LibreOffice headless | Linux/macOS/Windows（若安装） | 导出 PDF | 未安装 → 跳过 |
| 无渲染器 | 所有平台 | 仅 OOXML 检查 | 标记 `render_verified=false` |

PDF 几何检查：

- 用 PyMuPDF/pdfplumber 提取页面尺寸、文本块坐标、字体名；
- 校验：页边距、页眉页脚位置、页码格式、表格/文本越界、字体是否为预期字体（未回退）；
- 与 Word 实际渲染可能有差异，报告中标注“渲染器敏感”。

**win7 注意**：LibreOffice 新版本对 Win7 支持有限；不捆绑；仅检测本机已有 Word/WPS COM。
无渲染器时功能仍可用，只是不做分页级断言。TOC 真页码目前也只有 Word COM 通道。

### 4.8 双分支能力分层

| 层 | 能力 | main | release/win7 | 依赖 |
|---|---|---|---|---|
| Core | 文档读取/生成/编辑、FormatSpec、Linter、Repair、docxtpl 模板、journal | ✅ | ✅ | python-docx 1.1.2 / docxtpl 0.20.0 / lxml（均已具备） |
| Core+ | 内容控件/书签适配器、最小 RevisionWriter | ✅ | ✅ | 纯 OOXML，无新依赖 |
| Enhanced | docxcast 内容控件 Schema | ⚠️ 可选 | ❌ | Python 3.9+/python-docx 1.2 |
| Enhanced | python-redlines 任意版本对比 | ⚠️ 可选 | ❌ | Python 3.9+/.NET 二进制 |
| Enhanced | Docling/MarkItDown 规范条文解析 | ⚠️ 可选 | ❌ | Python 3.10+/重依赖 |
| Enhanced | 渲染级 PDF 几何校验 | ⚠️ 可选 | ⚠️ 视本机 Word/WPS | PyMuPDF / COM / LO |

原则：**核心路径不引入任何新依赖**；增强能力通过能力位探测，缺失时返回可读降级信息。

### 4.9 LaTeX 文档智能方案

LaTeX 不是“另一种 Word”，不能先转 DOCX 再转回。方案以 **源码为主、渲染为辅、编译可选**：

#### 4.9.1 项目模型与解析

```
LatexProject
  root_dir
  main_file                 # 含 \documentclass 的文件
  files[]                   # main + \input/\include/\subfile
  document_class            # article / IEEEtran / elsarticle / llncs / acmart / ctexart ...
  class_options[]           # journal, 10pt, twocolumn ...
  packages[]                # \usepackage
  macros[]                  # \newcommand/\renewcommand/\def/\newenvironment
  metadata                  # title/author/affil/email/date/abstract/keywords
  sections[]                # section/subsection/paragraph 树
  equations[]               # inline/display/equation/align/...
  figures[]                 # includegraphics + caption + label
  tables[]                  # tabular/tabularx/longtable + caption + label
  citations[]               # \cite/\citep/\citet keys
  labels[] / refs[]         # \label/\ref/\eqref/\autoref
  bibliography              # \bibliography/\addbibresource + .bib
  warnings[]                # unknown macro / missing file / unresolved ref ...
  anchors[]                 # file + line/column + AST path
```

**项目解析器**

- 主文件识别：扫描 `*.tex` 中 `\documentclass`；多个候选时让用户确认，不猜；
- 递归解析 `\input{...}`、`\include{...}`、`\subfile{...}`；只允许工作区/项目目录内相对路径，
  拒绝绝对路径、`..` 逃逸、URL、管道；限制深度/文件数/总大小；循环检测；
- `.cls`/`.sty`：只做**静态解析**（`\ProvidesClass`、`\LoadClass`、`\RequirePackage`、
  `\newcommand`、`\renewcommand`、`\newenvironment`、`\def`、`\geometry`、`\setlength`、
  `\bibliographystyle` 等），绝不执行 TeX；
- `.bib`：复用 `backend/office/bibtex.py` 的解析；把 `\cite{}` key 与条目对齐；
- 图片：解析 `\includegraphics`，限制在项目目录内；支持 png/jpg/pdf/svg，PDF 图片先记占位；
- 编码：UTF-8；兼容 `ctex`/`xeCJK` 中文；`%` 注释保留但不渲染。

**解析器技术选择**

| 组件 | 选择 | 理由 |
|---|---|---|
| 结构树 | TexSoup | 容错、可遍历/修改；arXiv 基准 50/50；纯 Python |
| 文本/转义 | pylatexenc | LaTeX ↔ Unicode、转义；纯 Python |
| 复杂文档可选 | pandoc / LaTeXML | 标准文章转换更好；自定义宏/类有限；外部依赖 |
| 备用 | plasTeX | py>=3.6；XML-DOM 模型；基准成功率较低，仅作后备 |

未知宏策略：保留宏名与参数文本，渲染为可见占位 + warning；**不因未知宏崩溃**。

**锚点**

LaTeX 锚点统一为：

```json
{
  "file": "sections/intro.tex",
  "line": 42,
  "column": 7,
  "latex_path": "document/section[2]/p[1]",
  "kind": "command_arg",
  "command": "\\author",
  "arg_index": 0,
  "label": "sec:intro",
  "citation_key": null,
  "text_hash": "sha1:..."
}
```

#### 4.9.2 渲染分层

| 层 | 能力 | 平台 | 安全 | 输出 |
|---|---|---|---|---|
| **Tier 1（核心）** | 结构树 → HTML（标题/段落/列表/公式/图/表/引用/参考文献）+ KaTeX | 全平台（含 Win7/Chromium 106） | 不执行 TeX | 应用内预览 + 源码行映射 + warnings |
| **Tier 2（可选）** | 真实 TeX 编译 → PDF | 检测本机引擎 | 必须 OS 级沙箱 | PDF iframe + 编译日志/错误定位 |
| **Tier 3（可选）** | pandoc / LaTeXML → HTML/MathML | main | 外部进程，仍按不可信输入处理 | 更接近标准论文的语义 HTML |

**Tier 1 HTML 渲染细节**

- 块级：标题层级、段落、列表、引用块、定理/证明环境、代码/verbatim、脚注；
- 数学：`$...$`、`$$...$$`、`\(...\)`、`\[...\]`、`equation/align/gather/multline/cases`；
  把导言区简单 `\newcommand` 注入 KaTeX `macros` 配置；KaTeX 不支持的（TikZ、siunitx、
  化学式）显示源码 + warning，不伪造；
- 图：`\includegraphics` → `<img>` data URL；缺图/PDF 图显示占位；
- 表：`tabular/tabularx/longtable` → HTML table；`\multicolumn`/`\multirow`/`\hline` 尽力；
- 引用：`\cite` 显示 `[key]` 或从 `.bib` 解析作者-年份；未定义 key 高亮；
- 交叉引用：`\ref/\eqref/\autoref` 用 label 映射；未定义高亮；
- 参考文献：`thebibliography` 或 `.bib` 列表；
- 源码映射：每个 HTML 块带 `data-latex-anchor`，点击问题可跳到源码行；
- 消毒：HTML 经 DOMPurify；KaTeX `trust: false`；不执行任何 TeX 宏。

**Tier 2 PDF 编译适配器**

- 引擎探测顺序：本机 `latexmk`/`xelatex`/`lualatex`/`pdflatex` → Tectonic（仅 main，Win10+）
  → 无引擎则返回“不可编译”的可读提示；
- 中文文档优先 `xelatex`/`lualatex`；英文可用 `pdflatex`；
- 编译参数：`-no-shell-escape`、`-interaction=nonstopmode`、`-halt-on-error`、
  `openin_any=p`、`openout_any=p`、固定 `TEXMFHOME`/`TEXMFCACHE` 到临时目录；
- 输出：PDF + `.log` 解析（错误/警告/overfull box/undefined ref）；
- Tectonic：`--untrusted --only-cached`，使用本地 bundle/缓存，禁止联网下载；
- **不可信文档默认不编译**；用户显式确认后才进入沙箱编译。

**UI**

- `LatexPreview`：源码树 / 渲染预览 / PDF 三视图切换；warnings 面板；点击 warning 跳源码行；
- 项目面板：主文件、include 树、`.cls/.sty`、`.bib`、figures；上传 zip 解压后的文件树；
- 工具栏：刷新、编译 PDF（能力位可用时）、导出 PDF、导出项目 zip、复制源码行；
- 集成到 `FileContentRenderer`（origin/main；当前 HEAD 用 `ArtifactViewer`）与右栏
  `FilePreviewPanel`；两者都需补 `.tex`/项目 zip 分支与源码行 anchor；
- 现有 `ArtifactViewer` 的 Markdown + KaTeX 管线可复用于轻量公式片段，但 LaTeX 文档用独立
  `LatexPreview`。

#### 4.9.3 LaTeX 模板档案与槽位

**从 `.cls/.sty` 抽取**

- 文档类名/选项、`\LoadClass`、`\RequirePackage`；
- 自定义命令/环境：名称、参数个数、默认值、是否只在导言区；
- 版式参数：`\geometry{...}` 边距、`\linespread`、字号选项、`twocolumn`、
  `\bibliographystyle`/biblatex 风格、页眉页脚/页码；
- 期刊特有命令：`\journalname{}`、`\articletype{}`、`\received{}`、`\corres{}` 等；
- 方法：静态正则 + 轻量 token 扫描；复杂宏只记录“存在 + 参数形状”，不展开。

**从示例 `.tex` 抽取**

- 元数据：`\title{}`、`\author{}`、`\affil{}`/`\affiliation{}`/`\institute{}`、`\email{}`、
  `\date{}`、`abstract` 环境、`\keywords{}`/`keyword` 环境；
- 章节骨架：`\section` 顺序、必填章节、附录、致谢、参考文献；
- 图表模式：`figure`/`table` + caption + label 的用法；
- 引用风格：`\cite`/`\citep`/`\citet`、`natbib`/`biblatex`、`\bibliographystyle`；
- 槽位候选：
  - `command_arg`：`\title{...}`、`\author{...}`、`\affil{...}`、期刊特有命令；
  - `environment_body`：abstract、keywords、acknowledgments；
  - `placeholder`：`<<...>>`、`[[...]]`、`TODO`、`XXX`、`【...】`、示例段落；
  - `comment`：`% TODO`、`% write here`；
  - `example_content`：示例文本/表格行/作者列表（低置信度，需确认）。

**复用统一 `SlotSchema`**：类型增加 `latex`（text/rich_text/date/enum/table/image/citation_list/
equation/section），锚点用 4.9.1 的 LaTeX anchor；置信度/必填/枚举/正则/长度与 Word 模板一致。

#### 4.9.4 填充与校验

**填充**

- 只改槽位对应节点：命令参数、环境体、占位符、表格行/作者列表；
- LaTeX 转义：`& % $ # _ { } ~ ^ \` 等；保留原有 `\textbf`/数学/引用结构；
- 作者/单位列表：按模板宏逐个生成，重复项克隆；
- 表格：克隆 `tabular` 行，保持列数/对齐；
- 图片：复制到项目 `figures/`，改写 `\includegraphics` 相对路径；
- 引用：生成 `\cite{}`，必要时补 `.bib` 条目；不得编造文献；
- 公式：保留/生成 LaTeX 数学；不做 Markdown 化；
- 输出**新项目目录/zip**，绝不覆盖模板；同时保留修改前的源码 diff。

**校验（不依赖编译）**

- 括号/环境配对；`\begin`/`\end` 匹配；
- 必填槽位/必填章节；
- 未定义 `\ref`/`\cite` key；重复 label；
- 缺失图片/`.bib` 文件；
- 文档类/宏包存在；
- 禁止的危险命令/路径；
- 可选：编译后检查错误/警告/页数/overfull。

#### 4.9.5 审校与修订

**LaTeX 规则（确定性为主）**

| 类别 | 示例 |
|---|---|
| 文档类/宏包 | 必须 `\documentclass{...}`；禁止/要求特定 package |
| 结构 | 必填章节、章节顺序、摘要/关键词/致谢/附录 |
| 元数据 | title/author/affil/email/date 完整；匿名模式 |
| 引用 | `\cite` key 必须在 `.bib`；未引用条目；引用风格 |
| 标签/引用 | 每个 figure/table/equation 有 label；`\ref` 可解析；重复 label |
| 图表 | caption 存在/格式；figure 文件存在；表格列数一致 |
| 长度 | 字数/页数/摘要长度（页数需编译） |
| 卫生 | TODO/XXX/作者注释/旧宏/禁用命令/绝对路径 |
| 安全 | `\write18`/`\openin`/`\openout`/管道/绝对路径/越界 include |

**语义规则**：LLM 检查摘要/标题/术语/引用完整性等，与 Word 场景共用 `RulePack` 机制。

**修订**

- LaTeX 没有 Word track changes；标准做法：
  1. 生成修改后的 `.tex`（保留原文件）；
  2. 若本机有 `latexdiff`，生成 `diff.tex`；
  3. 若有 TeX 引擎，编译 `diff.pdf`（红字/下划线）；
  4. 输出 `original.tex`、`revised.tex`、`diff.tex`、`diff.pdf`（可选）；
- 可选 `latexrevise` 接受/拒绝标记；
- 不用 `w:ins/w:del`，也不把 LaTeX 转成 Word 修订。

#### 4.9.6 与 Word 智能层的统一

- `DocumentProfile.source_format = "latex"`；`TemplateProfile.format = "latex"`；
- `SlotSchema.anchor.kind` 增加 `latex_command_arg` / `latex_environment_body` /
  `latex_placeholder` / `latex_comment`；
- `RulePack.applies_to.format = [docx, latex]`；selector 增加 `latex.document_class`、
  `latex.section`、`latex.caption`、`latex.citation_style`、`latex.package`、`latex.command`；
- `Issue.anchor` 增加 `file/line/column/latex_path/label/citation_key`；
- `AuditReport` 统一输出；LaTeX 报告可附源码行、diff PDF、编译日志；
- 模板/规则抽取、LLM 填充、审校、修复计划共用同一套编排，不另起一套产品逻辑。

#### 4.9.7 安全与沙箱

**HTML 渲染（默认）**

- 不执行 TeX；只解析/渲染；
- HTML 消毒（DOMPurify）；KaTeX `trust: false`；不渲染原始 HTML/`\href`；
- 图片/路径限制在项目目录；不读取任意本地文件；
- 未知宏只展示文本，不执行。

**PDF 编译（可选，高风险）**

- 默认对不可信文档关闭；
- 编译前预扫描并拒绝/剥离：
  `\write18`、`\openin`、`\openout`、`\read`、`\input|`、管道、绝对路径、`..` 逃逸、
  `\include`/`\input`/`\includegraphics`/`\lstinputlisting`/`\verbatiminput`/`\import`
  的越界路径；
- 运行参数：`-no-shell-escape`、`openin_any=p`、`openout_any=p`、固定临时 TEXMF、
  `-interaction=nonstopmode -halt-on-error`；
- OS 级隔离：容器（Docker）优先；Linux 可用 bubblewrap/nsjail；Windows 用低权限用户 +
  临时目录 + Job Object；无隔离能力时只允许“可信文档 + 用户显式确认”；
- 禁止网络；限制 CPU/内存/磁盘/时间；只挂载项目目录；编译后清理；
- Tectonic：`--untrusted --only-cached`，但**不能只依赖该标志**（CVE-2026-105744 显示
  `--untrusted` 未阻断 `\openout`）；仍需 OS 隔离；
- 项目 zip：zip bomb、路径穿越、符号链接、超大文件、成员数限制；只解压到临时目录。

#### 4.9.8 依赖与双分支分层

| 层 | 能力 | main | release/win7 | 依赖 |
|---|---|---|---|---|
| Core | `.tex` 项目解析、结构树、HTML+KaTeX 渲染、模板档案/填充、源码审校 | ✅ | ✅ | TexSoup + pylatexenc（纯 Python；需 py38 实测） |
| Core | `.bib` 解析、源码 diff | ✅ | ✅ | 现有 `bibtex.py` / difflib |
| Enhanced | PDF 编译（latexmk/xelatex/lualatex/MiKTeX） | ⚠️ 检测本机 | ⚠️ 仅用户自装且兼容 Win7 的引擎 | 外部 TeX 发行版；不捆绑 |
| Enhanced | Tectonic 编译 | ⚠️ 可选 | ❌ | Rust 1.78+ 最低 Windows 10 |
| Enhanced | pandoc / LaTeXML 转换 | ⚠️ 可选 | ⚠️ 视版本 | 外部二进制 |
| Enhanced | latexdiff 红字版 | ⚠️ 可选 | ⚠️ 视 Perl+TeX | 外部工具 |
| Enhanced | LaTeX→OMML / DOCX↔LaTeX | ⚠️ 可选 | ❌（latex2mathml >=3.10） | pandoc / latex2mathml |

**原则**

- 核心读/渲染/模板/审校**不依赖 TeX 引擎**，保证 Win7 可用；
- PDF 编译是“可选增强”，没有引擎时 UI 明确提示“仅预览，未编译”；
- Tectonic 首次编译需联网下载包，违背“本地优先”；默认禁用，仅用户显式允许或已配置
  本地 bundle 时启用，并加 `--only-cached`；
- 不把 TeX Live/MiKTeX/Tectonic 塞进安装包；
- 新增 Python 依赖前在 `sage-backend-py38` 实测；若不兼容，核心退化为自研轻量 tokenizer
  或使用 plasTeX（py>=3.6），或把该能力限定 main-only。

---

## 5. 与现有代码的映射

### 5.1 复用（不改）

- `backend/office/word_layout.py`：FormatSpec 应用、题注、目录、REF、页眉页脚；
- `backend/office/word_lint.py`：现有检查器；
- `backend/office/word_repair.py`：修复-复检；
- `backend/office/edit.py`：文本/表格/样式/批注 op；
- `backend/office/journal/parser.py`、`validator.py`：范本解析与 7 类规则（**不复用 generator 的 clear-body 逻辑**）；
- `backend/office/word_template.py`：Jinja 适配器；
- `backend/office/template_library.py`：内置模板与已知槽位；
- `backend/office/revision.py`、`apply_update.py`、`diff_preview.py`：写入安全与预览；
- `backend/office/toc_refresh.py`、`export_pdf.py`、`pdf_preview.py`、`pdf_to_word.py`：渲染与转换通道；
- `src/features/office/DocxNativePreview.tsx`：高保真预览；
- `src/features/office/OfficeDeliveryDrawer.tsx`：交付/质检入口；
- `src/features/journal/`：面板先例；
- `backend/office/bibtex.py`：`.bib` 解析，供 LaTeX 引用/参考文献；
- 前端 KaTeX 0.18.6 / `remark-math` / `rehype-katex`：LaTeX 数学公式渲染。

### 5.2 扩展（小改）

| 文件/模型 | 改动 | 兼容性 |
|---|---|---|
| `WordLintIssue` | 增加可选 `category`、`expected`、`actual`、`anchor`、`source`、`fixable`、`fix_kind`、`confidence` | 可选字段，旧调用方忽略；`extra="forbid"` 不破坏 |
| `WordLintResult` | 增加 `rule_pack`、`render_verified`（可选） | 可选字段 |
| `WordFormatSpec` | 增加 `fonts`（角色→字体，解决当前字体全局设置） | 可选；不传则行为不变 |
| `WordPageSetupSpec` | 补页眉/页脚距离、栏数（如未覆盖） | 可选 |
| `OfficeWordReadResult` | 增加 `styles`/`sections`/`fields`/`bookmarks`（可选） | 可选字段；与 `DocProfile` 并存 |
| `edit.py` | 增加 `set_paragraph_style` 的字体族/行距/缩进；增加修订 op | 新 op，旧 op 不变 |
| `word_lint.py` | 规则注册 + 自定义检查器接口 | 内部重构，输出兼容 |
| `word_repair.py` | 修复计划可返回逐条 patch + 修订模式 | 默认行为不变 |
| `template_library.py` | 内置模板槽位补 `required/options/format`；支持行循环 | 向后兼容 |
| `office_journal_routes.py` | 增加通用模板/规则端点（或新建路由文件） | 新增端点 |

### 5.3 新增模块（建议目录）

```
backend/office/document_intel/
  __init__.py
  models.py              # TemplateProfile / SlotSchema / RulePack / Issue / RevisionPatch
  anchors.py             # 锚点模型与解析（段落/表格/页眉页脚/域/控件/书签）
  style_resolver.py      # 样式继承 + theme + direct formatting 解析
  doc_profile.py         # DocumentProfile 构建
  template/
    __init__.py
    profile.py           # 统一 TemplateProfile
    adapters/
      content_control.py # w:sdt 读写
      jinja.py           # 包装现有 docxtpl 扫描器
      bookmark.py        # 书签名识别
      heuristic.py       # 【】/XX/空格/空单元格
    filler.py            # 取数 → LLM 填充 → 校验 → 渲染
    schema.py            # SlotSchema ↔ JSON Schema
  rules/
    __init__.py
    model.py             # RulePack/Rule 模型
    store.py             # 三层规则包加载/合并/版本
    extract_prose.py     # 条文 → 候选规则
    extract_exemplar.py  # 范本 → StyleProfile
    compiler.py          # Rule → 检查器/修复器计划
  checks/
    __init__.py
    page.py
    style.py
    structure.py
    table.py
    numbering.py
    content.py           # 日期/术语/结语/必填章节等
    citations.py
    registry.py          # 检查器注册
  audit.py               # 审计编排、Issue 聚合、报告
  fixers.py              # 确定性修复计划
  revisions.py           # w:ins/w:del 修订写出
  render_verify.py       # PDF 几何/字体校验（可选）
  report.py              # JSON/Markdown/docx 审计报告
```

约束：

- 每个文件 < 800 行（`architecture-baseline.json`），新文件超限直接 CI 红；
- `models.py` 只依赖 pydantic，保持 canary 前提；docx 依赖放执行模块并惰性导入；
- **pydantic 双版本**：main 2.5.0 / win7 1.10.13 + `backend/compat/win7/pydantic_compat.py`
  的 shim。新模型沿用现有 `ConfigDict` 导入方式，或在 win7 上从 compat 导入；更稳的做法是
  规则/IR 的纯数据模型用 `dataclasses`（frozen）以规避 v1/v2 差异。
- `from __future__ import annotations` + `typing.List/Dict/Optional` 注解风格，降低 py38 成本；
- 运行期不要用 3.9+/3.10+ API（见 `backend/tools/py38_hazard_scan.py`）。

### 5.4 API / Tools / UI

**REST（新增，挂 `/api/v1/office/document-intel/*`）**

- `POST /template/analyze` → TemplateProfile（扩展现有 analyze-template，保留旧端点）
- `POST /template/fill` → 填充结果（扩展现有 fill-template）
- `POST /rules/extract` → 候选规则（条文/范本/模板）
- `POST /rules/save`、`GET /rules/list`、`DELETE /rules/{id}`
- `POST /audit` → Issue 列表 + 报告
- `POST /audit/fix` → 修订版/修复版 + 复检结果
- `POST /audit/report` → docx/HTML 报告

**Agent Tools（新增，必须同步三件套）**

- `office_analyze_template_schema`（READ）
- `office_fill_template_semantic`（WRITE_LOCAL，需上下文）
- `office_extract_rules`（READ/WRITE，规则包写入需确认）
- `office_audit_document`（READ）
- `office_apply_audit_fixes`（WRITE_LOCAL，需上下文）
- `office_instantiate_template`（WRITE_LOCAL，补模板库 agent 入口）
- 可选：`office_compare_documents`（READ，生成修订版）

同步清单（每次新增工具必须做）：
1. `backend/domain/tool_names.py` 的 `OFFICE_TOOLS`；
2. `backend/agents/profiles.py` 的 primary/writer 白名单 + 默认常量；
3. `test_profiles_office_tools.py` 可见性计数；
4. `test_office_create_schema_contract.py` 若涉及 schema；
5. `src/shared/api/types.ts` 契约；
6. writer/paper-writing/report-writing SKILL.md；
7. i18n 文案。

**UI（优先扩展现有组件，不另起一套）**

- 模板面板：在 `OfficeGenerateForm` 的“从模板创建”模式上扩展——
  上传任意模板 → 解析 Profile → 可编辑槽位列表（改名/类型/必填/枚举/默认值）→
  Schema 驱动表单（补必填/格式校验/图片上传）→ 一键 AI 填充 → 预览 → 生成；
- journal 面板：`JournalContentEditor` 按 `spec.headings` 生成章节输入，补参考文献编辑器，
  不再只编辑标题/摘要/关键词；
- 审校面板：扩展 `OfficeDeliveryDrawer` 或新 `DocumentAuditPanel.tsx`——
  规范/范本选择 → 规则包选择 → 审计 → 问题列表（可过滤）→ 点击定位 → 修复选中/全部 →
  复检 → 导出报告；
- 规则包管理（可放在项目设置或 Office 页）：规则列表、来源、级别、启停、导入/导出、冲突提示；
- 预览锚点：优先用结构化 `WordPreview`（按段落索引 + `scrollIntoView` + 高亮），因为它有
  段落数组可映射；docx-preview 视图作为只读对照，渲染后按 issue 文本/范围包裹高亮。
  `FilePreviewPanel` 增加 `anchor` 参数（`openFilePreviewAt(path, anchor)`）；
- 文档对比/修订视图：基于 `SplitDiff` / `ArtifactViewer` / `OfficeEditPreviewDialog` 的先例，
  新增两份 Word 的结构级/页面级对比与修订接受/拒绝界面。

**前端接入路径（IPC）**

- 新增 API client：`src/shared/api/officeApi.ts` 或新 `src/shared/api/documentIntelApi.ts`；
- `invoke` → `electron/commandRoutes/office.ts`（或新域文件）→ `commandRoutes/index.ts` 注册 →
  后端 `backend/api/office_routes.py` 或新 `backend/api/document_intel_routes.py`；
- 新增 IPC 命令后必须运行 `npm run ipc:manifest` 重新生成 `electron/ipc-manifest.json`（禁止手改）；
- artifact 路径走 `src/features/artifacts/artifactApi.ts` + `backendRequest`，不经过 ipc-manifest；
- 类型同步 `src/shared/api/types.ts` / `src/shared/api/types/templateAndTaskTypes.ts`；
- 测试：`src/shared/api/__tests__/officeApi.test.ts`、`electron/__tests__/commandRoutes.office.test.ts`、
  组件测试（`OfficeGenerateForm` / `OfficeDeliveryDrawer` / `DocxNativePreview` / `WordPreview`）。

### 5.5 LaTeX 新增模块与接入点

**建议目录**

```
backend/office/latex/
  __init__.py
  models.py                # LatexProject / LatexDocument / MacroTable / LatexAnchor
  project.py               # 主文件识别、include 递归、路径安全、zip 解压
  parser.py                # TexSoup + pylatexenc → 结构树
  macros.py                # .cls/.sty 静态宏表与版式参数
  render_html.py           # 结构树 → HTML + KaTeX 占位 + warnings
  render_pdf.py            # 引擎探测/编译/日志解析（可选）
  sandbox.py               # 编译沙箱与危险命令预扫描
  template.py              # LaTeX TemplateProfile + 槽位抽取
  filler.py                # 槽位替换 + LaTeX 转义 + 图片/bib/引用
  validator.py             # 括号/环境/引用/标签/文件/必填项校验
  revisions.py             # 源码 diff + latexdiff 适配
  journal.py               # LatexJournalSpec / 期刊模板专用规则
  anchors.py               # file/line/column/AST path 锚点
```

**复用**

- `backend/office/bibtex.py`：`.bib` 解析与引用条目；
- `backend/services/project_type_detector.py` / `project_workspace_inspector.py`：
  已有的 LaTeX 项目识别与文本扫描，可复用为项目发现入口；
- 现有 PDF 预览 iframe / artifact 预览链路：编译后 PDF 直接复用；
- 前端 KaTeX / remark-math / rehype-katex：公式渲染；
- 统一 `SlotSchema` / `RulePack` / `Issue` / `AuditReport`（来自 `document_intel`）；
- `FileContentRenderer` / `FilePreviewPanel`（origin/main）扩展 `.tex`/zip 分支；
- 工具三件套 / profile / ipc-manifest 同步机制。

**REST（新增，挂 `/api/v1/office/latex/*`）**

- `POST /project/analyze` → LatexProject 结构摘要 + warnings
- `POST /project/render` → HTML（含 KaTeX 标记）+ 源码行映射
- `POST /project/compile` → PDF（能力位可用时）+ 编译日志
- `POST /template/analyze` → LaTeX TemplateProfile + SlotSchema
- `POST /template/fill` → 新项目/zip + 校验结果
- `POST /audit` → Issue 列表 + 报告
- `POST /revision/diff` → revised.tex + diff.tex + 可选 diff.pdf
- `GET /capabilities` → 本机引擎/工具能力位

**Agent Tools（新增，必须同步三件套）**

- `office_read_latex`（READ）
- `office_render_latex`（READ）
- `office_compile_latex`（WRITE_LOCAL，需上下文，沙箱）
- `office_analyze_latex_template`（READ）
- `office_fill_latex_template`（WRITE_LOCAL，需上下文）
- `office_lint_latex`（READ）
- `office_repair_latex`（WRITE_LOCAL，需上下文）
- 可选：`office_latexdiff`（READ/WRITE，生成红字版）
- 新增 `latex-paper-writing` / `journal-latex-submission` 技能：声明
  `office_read_latex` / `office_analyze_latex_template` / `office_fill_latex_template` /
  `office_lint_latex` / `office_compile_latex` 的允许集与“解析→填充→校验→编译→导出”流程。

**前端**

- `LatexPreview`：源码/渲染/PDF 三视图 + warnings + 源码行定位；
- `LatexProjectPanel`：文件树、主文件、`.cls/.sty`、`.bib`、figures、编译按钮；
- `LatexTemplatePanel`：模板档案 + 槽位表单 + AI 填充 + 预览；
- 扩展 `FileContentRenderer`（origin/main；当前 HEAD 为 `ArtifactViewer`）：`.tex` → `LatexPreview`；
  `.zip`（含 `\documentclass`）→ 项目预览；
- 扩展 `FilePreviewPanel`：支持 `.tex` anchor（file/line）跳转；
- 扩展 `DocumentAuditPanel`：LaTeX issue 列表 + 源码行高亮 + diff PDF 入口。

**测试**

- 后端：project resolver（include/循环/越界/zip）、parser（标准/自定义宏/未知宏）、
  render_html（章节/公式/图/表/引用）、template/fill、validator、sandbox（危险命令/超时）、
  render_pdf（引擎缺失降级/日志解析）；
- 前端：`LatexPreview`、`LatexProjectPanel`、`LatexTemplatePanel`、`.tex` 文件预览、
  KaTeX 公式、warning 跳转；
- E2E：上传 Overleaf zip → 渲染 → 填充 → 校验 → 下载项目/PDF。

---

## 6. 分阶段实施

> 每个阶段独立可验证，遵循 TDD；先确定性、后 LLM；先只读审计、后自动修复。
> Word 主线 M0–M5 与 LaTeX 轨道 L0–L3 并行，LaTeX 复用主线产出的统一模型。

### M0：文档快照与锚点（1–2 周）

**交付**

- `style_resolver.py`：解析 docDefaults → styles（basedOn 链）→ theme → direct formatting；
  正确处理 `w:rFonts` 的 ascii/eastAsia/hAnsi/cs 与 theme 属性优先级；
- `anchors.py`：段落/表格/页眉页脚/域/批注锚点；
- `doc_profile.py`：页面、样式角色、结构、编号、表格；
- 读取侧补齐：页面设置、段落对齐/缩进/行距、run 字体/字号/颜色、编号定义、书签；
  以 `DocumentProfile` 形式提供（不改旧 `read_docx` 字段，避免破坏契约）；
- 黄金样本集：中文公文、期刊论文、报告、合同、复杂表格、页眉页脚、脚注、批注、合并单元格。

**验收**

- 黄金样本的页面/样式角色抽取与人工标注一致率 ≥ 95%；
- 锚点在文档重排后仍能基于 `text_hash` 重定位；
- 零新增依赖；py38 hazard scan 通过。

### M1：语义模板 Profile + 填充（2–3 周）

**交付**

- 四种适配器；统一 `TemplateProfile` / `SlotSchema`；
- 现有 Jinja 路径迁移到适配器（行为不变，回归绿）；
- 内容控件/书签的读取与填充；
- 重复表格行/条件块建模；
- 填充后 Schema + 格式审计 + 重试；
- 扩展现有模板 UI：`OfficeGenerateForm` + `OfficeGenerateSubforms` 支持任意模板的
  可编辑槽位与 Schema 驱动表单（补必填/格式校验/图片上传）；
- journal 面板补章节/参考文献表单；
- 补 `office_instantiate_template`，让 LLM 可按模板库 ID 实例化；
- 修正 journal 两个已知缺陷：`generate_article` 真正调用 `validate_document` 并反馈；
  `page_size` 从 `sectPr` 读取而非硬编码 A4。

**验收**

- 覆盖三类模板：Jinja、内容控件、无占位符范本；
- 模板原有格式在非槽位区域零变化（XML diff 校验）；
- 未解析占位符为 0；超长/类型错误 100% 被拦截；
- 生成 + 审计闭环在 5 个真实模板上通过；
- journal 回归全绿，且自纠确实消除 validator 违规。

### M2：规则包 + 确定性审校 + 定位（2–3 周）

**交付**

- `RulePack/Rule` 模型与三层存储；
- 规则编译器 → 现有检查器 + 新检查器（页面/样式/结构/表格/编号/内容基础项）；
- Issue 扩展（锚点/期望/实测/来源/可修复）；
- `DocumentAuditPanel`：问题列表 + 点击定位 + 过滤；
- 定位链路：`WordPreview` 段落索引 + `scrollIntoView` + 高亮；`WordLintIssue` 增加 anchor 字段；
  若 `feat/file-reference-preview` 已同步，则给 `FilePreviewPanel` 增加 `anchor` 参数；
- 确定性修复 + 复检；
- 内置 GB/T 9704 可执行规则包（仅通用参数，来源标注，不复制标准全文）。

**验收**

- 黄金样本上确定性规则精确率 ≥ 98%、召回率 ≥ 95%（可测量项）；
- 每条 issue 可定位到原文段落/表格；
- 修复后复检通过率 ≥ 90%，修复幂等；
- 旧 `office_lint_word` / `office_repair_word` 行为不变。

### M3：规范/范本 → 规则抽取（3–4 周）

**交付**

- 条文抽取：分段 → LLM 候选 → 确定性后校验 → 去重/冲突 → 人工复核 → 规则包；
- 范本抽取：StyleProfile（主导值 + 分布 + 容差）+ 结构骨架；
- 规则复核 UI：来源原文、置信度、样例、启停、测试；
- RuleStore 版本与导出/导入。

**验收**

- 在 10 份真实规范 + 5 份范本上，候选规则人工接受率 ≥ 80%；
- 每条规则有来源；无来源规则不可保存；
- 规则冲突 100% 被识别并要求选择；
- 抽取结果可复现（同输入同规则集）。

### M4：语义审校 + 原生修订（2–3 周）

**交付**

- 语义检查器：必填章节、结语/称谓、日期格式、术语一致性、金额大小写、引用完整性；
- `RevisionWriter`：文本替换/插入/删除 + 批注；
- 修复计划：确定性 + 语义修订混合；逐条接受/拒绝；
- 文档对比/修订视图：基于现有 `SplitDiff`/`ArtifactViewer` 先例，展示修订前后与接受/拒绝状态；
- 修复后复检 + 审计报告（JSON/Markdown/docx）。

**验收**

- 修订版在 Word/WPS 审阅面板可见，接受/拒绝后文档合法；
- 语义检查误报率 < 10%（人工标注集）；
- 每条修订有 rule_id/来源/依据；
- 原文件零覆盖。

### M5：渲染级校验 + 批量 + win7 收口（2–3 周）

**交付**

- Word COM / LibreOffice 适配器；PDF 几何检查（页边距/页码/溢出/字体）；
- 批量审计与报告；
- win7 核心路径验证（无内容控件/修订依赖的部分）；
- 性能：100 页文档审计 < 30s（不含 LLM/渲染）；LLM 检查按需。

**验收**

- 有渲染器时，页边距/页码/字体检查与人工一致率 ≥ 95%；
- 无渲染器时功能可用，报告标注未验证；
- win7 py38 全量测试绿；main 性能达标。

### LaTeX 轨道 L0–L3（与 M0–M5 并行）

> LaTeX 与 Word 共用 `SlotSchema` / `RulePack` / `Issue` / `AuditReport`，但解析与渲染独立。
> 建议在 M0 完成后启动 L0，与 M1/M2 并行。

#### L0：LaTeX 项目读取与锚点（1–2 周）

**交付**

- `LatexProject` 模型与项目解析器（主文件识别、include 递归、路径安全、zip 解压）；
- TexSoup + pylatexenc 结构解析（章节、公式、图、表、引用、标签、参考文献、脚注）；
- `.cls/.sty` 静态宏表；未知宏降级；
- `.bib` 与 `\cite{}` 联动；补 `parse_bibtex_file` 的路由/工具入口（当前存在但未被使用）；
- LaTeX anchor（file/line/column/AST path/label/citation key）；
- 黄金项目集（article/IEEEtran/elsarticle/llncs/acmart/ctexart/多文件/自定义 cls）；
- 接入面：聊天附件白名单、`@` 解析、Wiki ingest、workspace index、artifact kind、
  `fileLang.ts` 支持 `.tex`/`.bib`/项目 zip；修正 pandoc 的版本/平台探测与 Windows 友好错误提示。

**验收**

- 20 个真实 arXiv/期刊项目解析成功率 ≥ 95%（标准结构）；未知宏不崩溃；
- include 越界/循环/zip bomb 全部拒绝；
- 解析 50 页项目 < 2s（不含渲染）。

#### L1：HTML 语义渲染与预览（2–3 周）

**交付**

- AST → HTML（标题/段落/列表/定理/代码/脚注/图/表/引用/参考文献）；
- KaTeX 公式渲染（含简单宏表注入）；TikZ/高级包降级为源码 + warning；
- 源码行映射与 warnings 面板；
- `LatexPreview` + `LatexProjectPanel`；
- `.tex`/项目 zip 接入文件预览与 artifact；
- 修正 `HelpTab`/`BtwOverlay` 缺 `remarkMath`、Wiki `MarkdownPreview` 无公式的现有问题；
- Shiki `latex` 语言高亮 + `fileLang.ts` 映射（低成本）。

**验收**

- 标准结构渲染覆盖率 ≥ 95%；KaTeX 覆盖常见数学 ≥ 90%；
- 未知宏/不支持环境均显示 warning，不白屏；
- HTML 消毒与 KaTeX `trust:false` 测试通过；
- 50 页项目渲染 < 3s。

#### L2：LaTeX 模板档案与填充（2–3 周）

**交付**

- 从 `.cls/.sty` + 示例 `.tex` 抽取 `LatexTemplateProfile`；
- 槽位：命令参数、环境体、占位符、注释、示例内容；
- `SlotSchema` 映射与人工确认 UI；
- 填充器：LaTeX 转义、作者列表、表格行、图片、引用、`.bib`；
- 填充后校验（括号/环境/必填/引用/标签/文件）；
- `LatexTemplatePanel` + AI 填充闭环。

**验收**

- 5 个真实期刊模板可解析并生成槽位；
- 非槽位源码零变化（源码 diff 校验）；
- 填充后不编译也能通过结构校验；有引擎时编译成功率 ≥ 90%；
- 未定义引用/缺失图片 100% 被拦截。

#### L3：LaTeX 审校、修订与可选编译（2–3 周）

**交付**

- LaTeX 规则包（文档类/必填章节/元数据/引用/标签/图表/长度/卫生/安全）；
- 源码审校 + 可选 PDF 版式检查（页数/边距/overfull/字体）；
- `latexdiff` 红字版（可选）+ `latexrevise` 接受/拒绝（可选）；
- 编译适配器（latexmk/xelatex/lualatex/MiKTeX；Tectonic main-only）+ 沙箱；
- `DocumentAuditPanel` 支持 LaTeX issue + 源码行跳转。

**验收**

- 确定性规则精确率 ≥ 98%、召回率 ≥ 95%；
- 每个 issue 有 file/line/anchor；
- 危险命令/越界路径/超时/内存超限全部被拦截；
- 无引擎时只读/HTML 功能完整，报告标注“未编译”；
- Win7 全量测试绿。

---

## 7. 测试与质量门禁

### 7.1 测试层次

- **单元**：样式解析、锚点、槽位推断、规则编译、检查器、修订 XML；
- **集成**：模板分析→填充→审计→修复→复检；规范抽取→保存→审计；
- **REST/工具**：端点 roundtrip、工作区围栏、上下文 fail-closed；
- **前端**：槽位表单、问题列表、点击定位、修复确认；
- **LaTeX**：项目解析（include/循环/越界/zip）、结构解析（标准宏/自定义宏/未知宏）、
  HTML 渲染（章节/公式/图/表/引用）、模板抽取/填充、源码校验、编译沙箱、日志解析、
  `latexdiff`；前端 `LatexPreview` / `LatexProjectPanel` / `LatexTemplatePanel`；
- **E2E**：上传模板→填写→生成→审阅；上传规范→确认规则→审计→修复；
  上传 LaTeX 项目 zip→渲染→填充→校验→导出；
- **回归**：现有 `office` 全部测试不得回退。

现有相关测试可直接复用/扩展：`test_word_template.py`（17）、`test_template_library.py`（24）、
`test_office_word_lint.py`（18）、`test_office_word_repair.py`（11）、`test_edit.py`（23）、
`test_word_comments.py`（11）、`test_read_fidelity.py`（19）、journal 全套约 87 项、
`test_office_create_schema_contract.py` 等。
前端：`OfficeGenerateForm.test.tsx`、`OfficeGenerateSubforms.p141.test.ts`、
`OfficeDeliveryDrawer.test.tsx`、`DocxNativePreview.test.tsx`、`DocxBlobPreview.test.tsx`、
`OfficeStructuredPreviews.p142.test.ts`、`JournalValidationReport.test.tsx`、
`JournalContentEditor.test.tsx`、`officeApi.test.ts`、`journalApi.test.ts`、
`commandRoutes.office.test.ts`。

### 7.2 黄金样本集

至少覆盖：

1. 中文公文（GB/T 9704 版式、红头/版记/页码）；
2. 期刊论文（标题/作者/摘要/章节/参考文献/图表）；
3. 企业报告（目录/多级标题/表格/页眉页脚）；
4. 合同（条款编号/表格/签署页）；
5. 复杂表格（合并单元格/跨页表头/嵌套表）；
6. 内容控件模板、Jinja 模板、书签模板、无占位符范本；
7. 脏数据：损坏 zip、超大文件、宏文件、外部关系、XML 实体、超长文本；
8. LaTeX 期刊项目：IEEEtran / elsarticle / llncs / acmart / ctexart、多文件 `\input`、
   自定义 `.cls/.sty`、`.bib`、figures、公式、表格、TikZ（预期降级）；
9. 恶意 LaTeX：`\write18`、`\openout`、`\openin`、`\input` 绝对路径/管道、zip bomb、
   超深 include、超大文件、循环 include。

### 7.3 指标

| 指标 | 目标 |
|---|---|
| 可测量规则精确率 | ≥ 98% |
| 可测量规则召回率 | ≥ 95% |
| 语义规则误报率 | < 10% |
| 模板槽位识别准确率（显式） | ≥ 99% |
| 模板槽位识别准确率（启发式） | ≥ 85%，低置信度必须人工确认 |
| 非槽位区域格式零变化 | 100% |
| 修复后复检通过率 | ≥ 90% |
| 修订版 Word/WPS 可打开 | 100% |
| 100 页审计耗时（无 LLM/渲染） | < 30s |
| LaTeX 项目解析成功率（标准结构） | ≥ 95% |
| LaTeX HTML 渲染覆盖率（常见结构） | ≥ 95% |
| LaTeX 槽位识别准确率（显式命令/环境） | ≥ 95% |
| LaTeX 填充后结构校验通过率 | 100% |
| LaTeX 编译成功率（有引擎时） | ≥ 90% |
| LaTeX 危险命令/越界路径拦截率 | 100% |
| 50 页 LaTeX 项目解析 / 渲染耗时 | < 2s / < 3s |

### 7.4 门禁

- 后端覆盖率 80%（`ci.yml` `--cov-fail-under=80`）；
- 前端覆盖率棘轮（当前 statements 67 / branches 79 / functions 65 / lines 67，只升不降）；
- `architecture-check`：新文件 ≤ 800 行，baselined 文件不得增长；
- py38 hazard scan：禁止 3.9+/3.10+ 运行期 API；
- 新增工具三件套 + schema 契约测试；
- 现有 `office` 回归全绿。

---

## 8. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 读取保真度不足（无字体/字号/页面/编号） | 审校误报、模板无法保真 | M0 先补 `DocumentProfile`；黄金样本对照 Word 实际显示 |
| OOXML 保真度不足（python-docx 不支持的部件） | 编辑后文档损坏/丢格式 | 只动必要节点；round-trip 黄金测试；未知部件原样保留；失败回滚 |
| 样式继承/theme 解析错误 | 误报/漏报 | 独立 StyleResolver + theme 优先级测试；与 Word 实际显示对照 |
| Word/WPS/LibreOffice 渲染差异 | 渲染校验不一致 | 报告标注渲染器；以 Word 为准；差异样本集 |
| 中文字体缺失/未嵌入 | 版式漂移 | 字体可用性检查；不捆绑专有字体；提示安装/替代 |
| LLM 规则抽取幻觉 | 错误规则进入审校 | 只生成候选；确定性后校验；人工确认；来源必填；置信度门槛 |
| LLM 语义审校误报 | 用户不信任 | 分级；证据引用；可关闭；误报样本回归 |
| 修订 XML 结构错误 | Word 报“内容有问题” | 严格按 OOXML schema；Word/WPS 双端验证；失败降级为批注 |
| 内容控件/重复节实现复杂 | 延期 | 先支持文本/日期/下拉/复选；重复节后置；可选 docxcast（main） |
| journal 清空 body 的旧逻辑被误用 | 模板版式丢失 | 明确禁止把 journal generator 当通用模板引擎；新填充器只做槽位替换 |
| 性能（大文档/多规则/LLM） | 卡顿/超时 | 后台任务队列；分块；确定性优先；LLM 按需；缓存 |
| 安全（zip 炸弹/宏/XXE/提示注入） | RCE/数据泄露 | 复用现有 zip 限制；禁宏；禁外部实体；内容当数据不当指令 |
| 版权（GB/T 全文/字体） | 法律风险 | 不内置标准全文与专有字库；规则参数自行编写/用户提供；来源标注 |
| pydantic v1/v2 分歧 | win7 ImportError/行为差异 | 新模型用 dataclass 或从 win7 compat shim 导入；main/win7 双测试 |
| jinja2 未钉版 | 依赖漂移 | 在 requirements 中显式 pin 与 win7 一致的版本 |
| **PyMuPDF 版本分歧**（main ≥1.25 / win7 1.24.11） | PDF 检查行为差异 | 能力位探测；版本分支测试；不依赖新 API |
| 外部二进制（pandoc/LibreOffice/Word COM） | 功能不可用 | 能力位探测；可读降级提示；不宣称跨平台等价 |
| 当前工作区 HEAD 落后 origin/main | 文件预览/引用能力不可用 | 实施前同步 origin/main；方案中的 `FilePreviewPanel` 明确标注为 origin/main 成果 |
| win7 兼容 | 分支差异 | 核心零新增依赖；增强能力能力位探测；py38 扫描；win7 全量测试 |
| LaTeX 编译安全（`\write18`/`\openout`/`\input`） | 任意文件读写/RCE | 默认不编译不可信文档；OS 级沙箱；禁用 shell escape；路径限制；预扫描；超时/资源限制 |
| Tectonic 不支持 Win7 | win7 无法编译 PDF | 核心只做 HTML 渲染；PDF 编译改为检测本机 TeX 引擎；不捆绑 Tectonic |
| TexSoup/pylatexenc 与 py38 不兼容 | win7 无法解析 | 先实测；不兼容则退化自研 tokenizer 或 plasTeX；或限定 main-only |
| 自定义 `.cls/.sty` 宏不可静态展开 | 渲染/槽位识别不全 | 宏表 + 未知宏降级 + warning；不执行 TeX；让用户确认低置信度槽位 |
| HTML 渲染与 PDF 版式不一致 | 用户误判 | 明确“语义预览”；最终以编译 PDF 为准；提供编译按钮/提示 |
| TikZ/高级宏包无法 HTML 渲染 | 预览缺图 | 显示源码/占位 + warning；有引擎时走 PDF 编译 |
| latexdiff/Perl/TeX 缺失 | 无法生成红字版 | 可选能力；降级为源码 diff + 修改后 `.tex` |
| LaTeX 编码/CJK 字体问题 | 中文渲染/编译异常 | UTF-8；ctex/xeCJK；xelatex/lualatex；字体缺失提示 |
| `latex2mathml` 需 Python 3.10+ | win7 无 OMML 转换 | 仅 main 可选；win7 用 pandoc 或跳过公式转换 |
| 规则包膨胀/维护 | 难维护 | 分层；按文种拆分；测试样例；版本；冲突检测 |

---

## 9. YAGNI / 明确不做

- 不做完整 WYSIWYG Word 编辑器（继续用 Word/WPS 编辑）；
- 不做在线协同编辑/云同步（Won't-v1，桌面定位）；
- 不做宏/VBA 编辑与执行；
- 不做扫描件 OCR（已有 SAGE_OCR opt-in，另案）；
- 不做数字签名/盖章；
- 不做任意 `.doc` 写入（只读经 pandoc 转 `.docx`）；
- 不做“LLM 直接当规则引擎”（规则必须落到确定性检查器或显式的语义检查器）；
- 不做规则市场/跨用户共享（先支持导出/导入）；
- 不一次性覆盖所有 GB/T 9704 条款（先通用参数 + 结构/样式，内容类后置）；
- 不把 journal 的 clear-body generator 扩展成通用模板引擎（另建槽位填充器）；
- 不捆绑完整 TeX 发行版 / Tectonic（体积、许可、Win7 兼容都不可控）；
- 不在核心里实现 TikZ/pgfplots 渲染（只做源码占位；有引擎时走 PDF）；
- 不执行任意 `.cls/.sty`（只静态解析宏与参数）；
- 不承诺任意自定义宏 100% 还原（未知宏必须显式 warning）；
- 不做 LaTeX OCR / 手写公式识别；
- 不做“LaTeX→Word 全保真转换”（pandoc 仅作可选辅助，不保证期刊类）。

---

## 10. 推荐决策（待评审确认）

1. **技术路线**：采用“现有引擎 + 适配层”，不引入 Aspose/ONLYOFFICE 等重依赖；
   Aspose 仅作为未来商业授权可选项，不进入核心路径。
2. **模板契约**：内容控件优先、Jinja 兼容、书签/启发式兜底；SlotSchema 用 JSON Schema 兼容格式。
3. **规则表示**：YAML 规则包，三层覆盖；确定性检查器为主，LLM 检查器显式标注。
4. **修订输出**：自研最小 `RevisionWriter`（核心双分支），可选 `python-redlines`（main）做任意版本对比。
5. **渲染校验**：检测本机 Word COM / LibreOffice，不捆绑；无渲染器时明确降级。
6. **内置规则**：只内置可执行参数与来源标注，不复制标准全文/专有字体；用户可导入单位规则包。
7. **UI 入口**：模板面板放 Office 页；审校面板从 OfficeDeliveryDrawer 扩展；
   项目约束中的“文书版式/审校强度”升级为可绑定规则包（保留自然语言约束作为补充）。
8. **数据模型**：IR/规则用 frozen dataclass 或 pydantic-shim 兼容写法，避免 v1/v2 分叉。
9. **LaTeX 核心**：TexSoup + pylatexenc 做项目解析，HTML + KaTeX 做默认渲染；
   **核心不依赖 TeX 引擎**。
10. **LaTeX 编译**：作为可选增强，检测本机 latexmk/xelatex/lualatex/MiKTeX；
    Tectonic 仅 main（Win10+），Win7 不承诺 PDF 编译；不捆绑 TeX 发行版。
11. **LaTeX 模板填充**：源码优先，只做槽位替换；不先转 DOCX 再转回。
12. **LaTeX 修订**：`latexdiff` 红字版 + 修改后 `.tex`；不套用 Word track changes。
13. **LaTeX 安全**：HTML 渲染不执行 TeX；PDF 编译默认关闭、仅可信文档、必须 OS 级沙箱
    + 危险命令预扫描。

---

## 11. 参考资料

- Microsoft Copilot Document Validation agent template（规则书、Critical/Advisory、批注建议修复）：
  https://learn.microsoft.com/en-us/microsoft-365/copilot/copilot-tuning-document-validation-template
- Microsoft Copilot document writing agent template（模板/风格/结构）：
  https://learn.microsoft.com/en-us/microsoft-365/copilot/copilot-tuning-document-writing-template
- Google Docs Gemini “Match the format”（2026-03）：
  https://techcrunch.com/2026/03/10/google-rolls-out-new-gemini-capabilities-to-docs-sheets-slides-and-drive/
- WPS 智能公文 / 黑马校对（拟校排印、国标模板、格式定位与修正）：
  https://software.it168.com/a2024/1226/6873/000006873830.shtml
  https://365.wps.cn/content/4000615da6e441698a418641a232d8ac.html
- Anthropic Claude DOCX skill（OOXML、tracked changes、pandoc/LibreOffice 验证）：
  https://github.com/anthropics/skills/tree/main/skills/docx
- 开源 gongwen-skill（YAML 三层规则、DocumentModel、P0/P1/P2、style-learn）：
  https://github.com/linhut/gongwen-skill
- 开源 gongwen-gbt9704-skill（GB/T 9704 生成与核验）：
  https://github.com/DrBituan/gongwen-gbt9704-skill
- docxtpl 文档（Jinja 模板限制、循环、RichText）：
  https://docxtpl.readthedocs.io/
- docxcast（内容控件 → JSON Schema → 回填）：
  https://pypi.org/project/docxcast/
- python-redlines（两份 docx 差异 → 原生修订）：
  https://pypi.org/project/python-redlines/
- Docling / MarkItDown（语义解析，非样式保真）：
  https://github.com/docling-project/docling
  https://github.com/microsoft/markitdown
- LaTeX 生态：
  - TexSoup（容错 LaTeX 解析树；arXiv 基准）：
    https://github.com/alvinwan/TexSoup
    https://pypi.org/project/TexSoup/
  - pylatexenc（LaTeX 语法 walker / Unicode 转换）：
    https://github.com/phfaist/pylatexenc
  - plasTeX（Python LaTeX 文档处理框架）：
    https://pypi.org/project/plasTeX/
  - LaTeXML（arXiv HTML 使用的 LaTeX→HTML+MathML）：
    https://dlmf.nist.gov/LaTeXML/
  - Tectonic（自包含 TeX 引擎）：
    https://tectonic-typesetting.github.io/
  - Rust Windows 7 基线（Rust 1.78 起最低 Windows 10）：
    https://blog.rust-lang.org/2024/02/26/Windows-7/
  - Docling / Tectonic 安全公告（`\openout`/`\write18`，CVE-2026-105744）：
    https://github.com/docling-project/docling/security/advisories/GHSA-x3q2-h9hx-4r4j
  - latexdiff（LaTeX 红字修订）：
    https://ctan.org/pkg/latexdiff
  - Overleaf + Writefull（LaTeX 编辑器内 AI 能力参考）：
    https://help.writefull.com/writefull-for-overleaf--user-guide
  - Pandoc（LaTeX ↔ HTML/DOCX 转换）：
    https://pandoc.org/
  - KaTeX / MathJax（浏览器公式渲染）：
    https://katex.org/
    https://www.mathjax.org/
- 规则抽取与治理研究：
  - SAGE: Governed Artifact Generation from Enterprise Guidelines, arXiv 2609.17775
  - Executable Governance for AI: Translating Policies into Rules Using LLMs, arXiv 2512.04408
  - The Hidden Tax（LLM 规则遵守需要模型外机械执行）
- 项目内相关文档：
  - `docs/technical/55-word-format-spec-engine.md`
  - `docs/technical/58-word-format-linter.md`
  - `docs/technical/60-word-auto-repair.md`
  - `docs/technical/55-journal-template-subsystem.md`
  - `docs/technical/54-office-parity-tracking.md`
  - `docs/technical/90-word-footnotes-design.md`
  - `docs/technical/76-word-toc-page-refresh.md`
  - `docs/plans/2026-09-26_office-doc-revision.md`（版本一致性，非修订模式）
