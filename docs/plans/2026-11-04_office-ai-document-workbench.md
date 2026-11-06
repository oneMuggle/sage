# 文档与验收：AI 文档工作台重构方案

> 状态：Phase 0 ✅ 已交付（main #2869 / win7 #2876）；**Phase 1 ✅ 已交付**（M1 文档库、M2.5 规范书库、M3 AI 审校与修订，已归档至技术手册 §133 / 用户手册 §36）；Phase 2–4 未开始，本文件继续作为后续路线图保留。
> 基线：`origin/main`（功能分支 `feat/office-ai-phase1`），
> 对照 `origin/main` 的「审校与规范」能力。
> 目标分支：main 先行，再按项目双分支策略 cherry-pick / 适配到 release/win7。

## 1. 背景与目标

用户对 `/office`「文档与验收」页面提出 6 项体验问题：

1. 文档处理标签页用 4 个独立框分别处理 Word / Excel / PPT / PDF，冗余；
2. 历史记录列表无法点击，点条目没有反应；
3. 重复导入同一文件时没有去重/合并策略；
4. 文档高保真显示无法显示；
5. 看不到 AI 辅助检查、校验、修改相关面板；
6. 文档生成看起来是纯自动化程序，没有 AI 参与。

本方案把 `/office` 从「文件操作面板」升级为「AI 文档工作台」，对标主流产品：

- **Microsoft 365 Copilot（Word）**：prompt 起草、改写/精简/翻译、基于文档对话、建议逐条接受/拒绝；
- **Gamma / Canva Magic Design**：一句话生成大纲 → 逐页/逐节生成 → 单节重生成；
- **Notion AI**：基于工作区上下文问答、续写、总结，标注来源；
- **WPS AI**：全文校对/润色/改写，保留修订痕迹。

另外，用户还提出了一个超出原始 6 项的问题：**许多文档（特别是 Word）有严格的格式/版式要求，且对应说明文件（投稿规范、单位写作规范等）应能作为审校依据**。这个需求通过新增的「格式规范书库」（M2.5）承接——从说明文件中 LLM 辅助提取规则包，绑定到工作区/文档，作为 AI 审校与起草的硬约束。

核心原则：

- **入口统一**：一个拖放区 + 一个选择文件按钮，自动识别格式；
- **文档为中心**：左侧文档库，中间预览画布，右侧 AI 助手；
- **建议可审阅**：AI 修改先出 diff，逐条接受/拒绝，禁止静默改写；
- **规则先行、AI 补充**：确定性规则做快速基础检查，LLM 做语义级问题；
- **规范书驱动**：以用户导入的格式/版式说明文件作为审校与起草的硬约束；
- **全程可回退**：应用前自动快照，审计历史可回放；
- **渐进披露**：保留原来的确定性「快速创建」，AI 起草作为增强模式。

## 2. 现状核实（代码依据）

| # | 用户现象 | 结论 | 根因与代码位置 |
|---|----------|------|----------------|
| 1 | 四个框分别处理 Word/Excel/PPT/PDF | 属实 | `src/pages/Office.tsx:292-335` 渲染 4 个 `OfficeFilePicker`，每个 `docType` 固定、只接受一种扩展名（`OfficeFilePicker.tsx:83-88`）。 |
| 2 | 历史记录无法点击 | 属实 | `OfficeDocumentList.tsx:316-423` 的 `<li>` 没有 `onClick`；只有右侧图标按钮（归档/版本/另存/打开/文件夹）。点文件名/行空白无任何反馈。 |
| 3 | 没有处理重复项 | 属实 | 导入每次生成新的 `randomUUID()` 作为暂存目录（`electron/officeIpc.ts:241-267`、`129-162`），语义就是「永远新建一份」；`office_documents` 表没有 content hash（`backend/data/database.py:904-920`）；列表也没有同名/同内容标记。 |
| 4 | 高保真显示无法显示 | 部分属实，两个具体根因 | ① 高保真开关只在探测到 LibreOffice（soffice）或 Word COM 时渲染（`officeCapabilities.ts:14-20`、`OfficePreviewPanel.tsx:525-556`），Excel/PPT 没有转换器时开关直接消失，用户看不到入口；② 转换结果以 `data:application/pdf;base64,…` 直接塞进 iframe（`OfficePreviewPanel.tsx:639-645`，后端 `backend/office/pdf_preview.py:94-99`），Chromium 内嵌 PDF viewer 对 `data:` URL 支持不稳定，典型表现是空白/无法显示；PDF 原文预览同样使用 data URL（`OfficePreviewPanel.tsx:311-342`）。此外 Excel/PPT 没有类似 Word `docx-preview` 的原生兜底渲染。 |
| 5 | 看不到 AI 检查/校验/修改面板 | 属实（且比用户预期更弱） | `origin/main` 有「审校与规范」tab（`WordRuleExtractionPanel` + `WordBatchAuditPanel`），但 release/win7 尚未同步该 tab；即便在 main，审校/修复/修订也基本是规则包确定性逻辑，`use_llm` 只出现在「规则包提取」接口（`backend/api/office_word_audit_routes.py:95,274-283`），审校、修复、修订本身不调用 LLM。 |
| 6 | 文档生成没有 AI 参与 | 属实 | `/office` 的生成是结构化表单 + 模板占位符填充（`OfficeGenerateForm.tsx`），后端 `generate_ppt/word/excel`、`templates/instantiate` 均为确定性生成（`backend/api/office_routes.py:458-559`）。LLM 只能通过聊天里的 `office_create` 工具间接写文档，生成 tab 本身没有 AI 起草/改写链路。 |

补充事实：

- 已有可复用的 AI 基础设施：`backend/orchestration/llm_factory.build_llm_client_from_settings()`；
- 已有可复用的文档能力：规则审校 `word_audit`、修复 `word_fix`、修订痕迹 `word_revision_writer`、快照 `OfficeSnapshotPanel`、自检历史 `office_self_checks`；
- 现有仓库只有 `docx-preview` 一个前端渲染库（`package.json:62`），Excel/PPT 版式预览没有现成依赖。

## 3. 目标信息架构

```
/office 文档与验收
├─ 文档工作台（原「文档处理」）
│  ├─ 统一导入区（拖放 / 选择，自动识别格式，可多选）
│  ├─ 文档库（可点击、搜索、筛选、排序、重复标记/清理）
│  ├─ 格式规范书库（从说明文件提取规则、绑定到工作区/文档）
│  └─ 文档详情
│     ├─ 预览：结构视图 ↔ 版式视图（不可用时给出原因与安装引导）
│     ├─ 当前规范书（可切换）
│     ├─ AI 助手：审校 / 合规 / 摘要 / 翻译 / 改写 / 问答
│     ├─ 修改建议：问题列表（标注「规范书规则」vs「AI 建议」）→ diff → 接受/忽略/批量应用
│     └─ 版本与审计：快照、自检历史、AI 审校历史
├─ 文档生成（AI 起草）
│  ├─ 快速创建（保留现有确定性表单/模板，作为「空白创建」）
│  └─ AI 起草：需求 → 规范书 → 参考资料 → 大纲 → 分节生成 → 组装导出 → 规范书交付检查
├─ 审校与规范（main 已有，后续同步 win7）
└─ LaTeX（main 已有，后续同步 win7）
```

## 4. 技术方案

### M1 统一导入与文档库

**前端**

- 新增 `OfficeIntake` 组件替换 4 个 picker：
  - 单一拖放区 + 原生选择按钮；
  - 扩展名自动识别：`.docx/.doc → word`、`.xlsx/.xls/.csv → excel`、`.pptx/.ppt → ppt`、`.pdf → pdf`；
  - 支持多文件（`dialog.showOpenDialog({ properties: ['openFile', 'multiSelections'] })`）；
  - 每个文件显示独立导入进度与结果；不支持的格式给出可接受列表。
- `OfficeDocumentList` 改为可点击：
  - 行点击/回车加载预览并选中；
  - 悬停显示操作，键盘可聚焦；
  - 支持按类型/状态/时间筛选、按更新时间排序、关键词搜索；
  - 重复项显示「重复」徽标，提供「保留最新并归档其余」的清理动作。

**Electron / 后端**

- `office:pick-and-import` 扩展为多文件 + 自动识别 docType；
- 暂存后计算 SHA-256（流式，避免大文件整读），把 `content_hash` 带入导入结果；
- `office_documents` 增加可空列 `content_hash TEXT`（幂等迁移，参考现有 `derived_from/archived_at` 迁移方式），加 `(workspace_path, content_hash)` 索引；
- 新增导入预检：在 `completeOfficeImport` 前返回同哈希文档列表；
- 重复处理三选项：
  1. **打开已有**：丢弃本次暂存（`discardOfficeImport`），直接加载已有文档预览；
  2. **作为新版本导入**：保留新文件，写入 `derived_from = 已有文档 id`；
  3. **仍然导入副本**：保留新文件，不建版本关系。
- 同名不同哈希：提示「同名但内容不同」，默认按新版本处理；
- 历史数据兼容：`content_hash` 为空时不参与重复判断，后台可懒回填。

**验收标准**

- 同一文件重复拖入 → 弹出去重对话框，不再无声新增两条；
- 点击历史条目 → 右侧立即加载预览；
- 支持一次导入多个不同类型文件，自动分流。

### M2 预览与高保真

**关于「高保真」涉及的转换器**

- **LibreOffice**：开源免费的办公套件，我们用的是它的命令行工具 `soffice`（可无头运行，Win/Linux/macOS 通用，安装包约 300MB，不收费）；
- **Microsoft Office（Word 的 COM 自动化）**：需要用户机器上装了正版 Word，通过 Windows COM 接口做转换，只在 Windows 有效；
- **`docx-preview`（已内置）**：JavaScript 库，直接读 docx 二进制渲染成 HTML，不需要装任何外部软件，Word 文档开箱可用。

**视图切换始终可见**

- 把「高保真」开关改为三段式视图切换：`结构视图 / 版式视图 / 版式视图不可用`；
- 不可用时按钮仍显示，`title`/内联提示说明原因（未检测到 LibreOffice / Word，或格式不支持），并提供「重新检测」「安装指引」；
- 能力探测结果从 [环境] 浮层同步到预览工具栏，不再因为探测失败而隐藏入口。

**修复 data URL 预览**

- PDF iframe 改为 `Blob` URL：前端把 base64 转 `Blob`，`URL.createObjectURL` 后挂载，切换/卸载时 `revokeObjectURL`；
- 后端可保留 data URL 契约，也可新增字节流/分块接口，避免 20MB base64 峰值；
- 原文 PDF 预览同步修复；
- Phase 0 用真机验证 Chromium 106 下 `data:` vs `blob:` 的行为差异。

**各格式版式预览（无需转换器即可工作的优先项）**

| 格式 | 方案 | 是否需要外部软件 | 说明 |
|------|------|-------------------|------|
| Word | 保留 `docx-preview` 原生渲染 | 否（已内置） | 默认走版式；继续保留 DOMPurify 消毒 |
| PDF | 原生 viewer（blob URL） | 否 | 高保真天然可用 |
| Excel | 新增 SheetJS（`xlsx`）读取 + 轻量网格渲染 | 否 | 展示列宽、合并单元格、表头样式；公式仍走结构化视图；库选型需 spike |
| PPT | 新增 pptx 渲染库（如 `pptx-preview`）或后端生成幻灯片缩略图 | 否 | 无转换器时提供「版式预览（实验）」；失败回落结构视图 |
| 通用兜底 | 用户装了 LibreOffice / MS Office 时，可用其做完整转换 | 是（可选增强） | 不把「装转换器」包装成必须步骤 |

**性能与安全**

- 渲染上限、虚拟滚动/分页；大文档按需渲染；
- 文档内容视为不可信输入：消毒、禁止脚本、路径围栏、大小上限；
- 切换文档时取消在途转换/渲染请求（复用现有 stale-read guard）。

### M2.5 格式规范书库

很多文档（特别是 Word）有严格的格式/版式/内容要求，对应的「说明文件」是审校的依据。把「规范书」作为一等公民，从「零散规则包」升级为「可管理、可绑定、可追溯」的规范库。

**概念模型**

一份规范书 = 一份说明文件（Word/PDF/Markdown 等）+ 从中提取的规则包 + 出处/版本/生效范围。

**前端「规范书库」面板**（挂在「文档工作台」里作为独立面板或新 tab）

- 列出当前工作区所有规范书（名称、来源文件、规则数、更新时间、是否默认）；
- 导入：拖放一份 Word/PDF/Markdown 说明文件 → LLM 辅助提取规则（复用 `extract_word_rules` 的 `use_llm=True` 路径）→ 展示为可编辑规则包 → 用户确认保存；
- 编辑/版本：规则包可手动增删改；提取结果保留来源段落作为依据；支持多版本共存；
- 激活/绑定：为工作区设置默认规范书；也能为单个文档切换不同规范书（例如不同期刊有不同的投稿规范）；
- 与 main 分支现有 `WordRuleExtractionPanel` 的关系：那个面板作为规范书导入流程的一个子页面继续存在；规范书库是其更完整的产品形态。

**数据模型**

- 新增 `office_spec_documents` 表：`(id, workspace_path, name, source_file_path, source_content_hash, rulepack_id, is_default, created_at, updated_at)`；
- 与现有 `word_rulepacks` 一对一关联；
- 文档级绑定复用 `office_documents.active_spec_id`（新增可空列）；
- 工作区默认绑定复用 `workspace_settings`（已有）。

**审校流程接入**

- AI 审校时，**先跑当前绑定规范书的规则**（确定性、免费、高优先级），**再跑 LLM 语义审校**；
- 问题列表里每个 issue 都标注 `source: spec:<id>` 或 `source: llm`，用户能清楚区分「这是格式硬性要求」vs「这是 AI 建议」；
- 支持「按规范书自动批量修正」—— 确定性规则优先应用，LLM 建议仍需逐条确认；
- 没有绑定规范书的文档：直接走 LLM 语义审校 + 通用规则兜底。

**AI 起草接入**

- 起草时选择规范书，AI 在生成大纲、填充内容时就把规范书的格式/结构/术语要求作为约束注入 prompt；
- 模板模式：规范书的占位符规范直接映射到模板槽位，AI 按规范建议值填充；
- 完成后自动按规范书做一次交付检查，问题直接回到文档详情处理。

**后端改动**

- 新增 `office_spec_routes.py`：CRUD、提取、激活、绑定；
- 复用：`extract_word_rules`（含 LLM 路径）、`word_rulepacks` 存储；
- 规范书提取时，来源段落、LLM 置信度、规则 id 全部持久化，便于追溯；
- 提取失败的兜底：纯人工创建规则包（LLM 不可用时也能用）。

**分支同步**

- 规范书库作为独立功能，main 和 win7 都要有；
- main 的 `WordRuleExtractionPanel` 保留为快捷入口（「新建规范书」的简化流程）。

### M3 AI 审校与修改

> **核心原则**：AI 审校以 M2.5 中绑定的规范书规则包为**主要依据**，LLM 语义审校作为**补充**；问题列表里每条都标注来源（`spec:<id>` vs `llm`），让用户能清楚区分「这是格式硬性要求」和「这是 AI 建议」。

**后端新增 `office_ai_review_routes.py`**

- `POST /office/ai/review`
  - 入参：`workspace_path`、`file_path`、`spec_id`（可选，不传则用文档绑定/工作区默认）、`scope`（全文/选区/指定段落）、`use_llm`、`max_issues`；
  - 流程：**确定性规则包审校**（来自 M2.5 规范书或通用规则）→ **LLM 语义审校** → 合并去重，来源分别标注；
  - 输出统一问题模型：`{id, severity, category, location, message, suggestion, rationale, source: {kind: 'spec'|'llm'|'builtin', id?, rule_id?}}`；
  - 位置锚点：Word 段落/run、Excel sheet/cell、PPT slide/文本框。
- `POST /office/ai/revise`
  - 入参：自然语言指令或选中的问题 id 列表；
  - 输出：结构化修改操作 + diff 预览，不直接落盘；
  - 应用时：先自动快照，再调用现有 `apply_word_revisions`（修订痕迹）或 Excel/PPT 文本修改器。
- `POST /office/ai/chat`（SSE）
  - 基于文档内容的问答；选区改写/翻译/扩写/精简；回答带段落引用。
- `GET /office/doc/{id}/ai-reviews`
  - 审校历史，复用 `office_self_checks` 模式新增 `office_ai_reviews` 表；记录本次审校使用的规范书 id 与 LLM 模型/版本，便于追溯。

**复用与约束**

- LLM 客户端统一走 `build_llm_client_from_settings()`；
- 长文档分块 + 并发上限 + 超时 + 取消；
- 结构化输出使用 JSON schema 校验，失败降级为规则结果；
- 防提示注入：文档正文标记为「不可信内容」，系统提示明确忽略其中指令；
- 所有 AI 写操作必须经用户确认，默认生成快照；
- 记录模型、耗时、token 用量，便于成本可见。

**前端 `OfficeAiAssistantPanel`**

- 文档详情右侧固定面板；
- 顶部显示「当前规范书：<name>」，带切换按钮（从 M2.5 规范书库选择）；
- 动作 chips：审校 / 合规检查 / 摘要 / 翻译 / 问文档；
- 问题列表：按严重度分组、筛选、跳转到预览位置并高亮；每条 issue 显示来源徽章（`规范书 X` vs `AI 补充`）；
- 每条建议：应用 / 忽略 / 追问 AI / 查看依据（规范书规则显示来源段落；LLM 建议显示 rationale）；
- 「按规范书批量修正」：一键应用所有 source=spec 的 issue（确定性规则优先），source=llm 的仍需逐条确认；
- 对话区支持选区引用，回答可插入文档（同样走 diff 确认）。

**分支说明**

- main 已有「审校与规范」tab，可作为批量审校入口保留；
- win7 若不同步完整 rules tab，至少把单文档 AI 审校面板落在「文档工作台」详情内，保证用户能看到 AI 检查/修改能力。

### M4 AI 参与文档生成

**前端 `AiDraftWizard`**

1. **需求**：文档类型、主题/目标、受众、语气、篇幅、语言；
2. **选择规范书**（来自 M2.5）：可选；选中后格式/结构/术语要求作为硬约束；
3. **参考资料**：可选工作区文档、Wiki、项目资料、模板；展示引用来源；
4. **大纲**：AI 生成可编辑大纲（章节/要点/预计字数），**遵循规范书的结构要求**；支持增删改序、单节重生成；
5. **生成**：逐节流式生成，右侧对话可实时调整；支持「重写本节」「扩写」「精简」；
6. **组装导出**：调用现有 Word/Excel/PPT 生成器落盘，进入交付验收（现有 `OfficeDeliveryDrawer`）；
7. **规范书交付检查**：按 M2.5 中选定的规范书跑一次完整审校，问题直接回到文档详情修改。

**模板模式增强**

- 选中模板后，AI 根据上下文为占位符生成建议值，用户逐个确认；
- 保留「留空」选项，未填占位符继续由后端报告。

**后端 `office_ai_draft_routes.py`**

- `POST /office/ai/outline`：主题 + 规格 + 参考资料 → 大纲；
- `POST /office/ai/draft/section`（SSE）：单节生成/重写；
- `POST /office/ai/assemble`：确认后的大纲/正文 → 调用现有生成器；
- `POST /office/ai/fill-template`：模板占位符 → 建议值；
- 上下文检索复用项目现有 RAG / workspace 读取能力，回答与草稿标注来源；
- 草稿状态按会话持久化，支持中断后继续。

**产品形态**

- 默认展示「AI 起草」；「快速创建」折叠为「空白创建 / 模板填充」，不删除既有能力；
- 生成过程接入任务中心（进度、可切页、可取消）。

## 5. 实施步骤

### Phase 0：诊断与快速修复（1–2 天，1–2 个 PR）

- [ ] 真机验证 `data:` / `blob:` PDF iframe 行为，确认高保真空白根因；
- [x] PDF 预览改 blob URL（高保真 + 原文预览）；
- [x] 高保真入口始终可见，补充不可用原因与安装引导；
- [x] 历史记录行可点击加载预览 + 键盘可访问；
- [x] 统一导入组件（自动识别 + 单/多文件）替换 4 个 picker；
- [x] 导入侧重复检测 MVP：content hash + 「打开已有 / 新版本 / 副本」；
- [x] 补充单元测试（`OfficeIntake.test.tsx` 8 例 + `OfficePreviewPanel.test.tsx` blob/禁用态断言）；
- [ ] Playwright 冒烟。

### Phase 1：文档库、规范书库与 AI 审校（2–3 周）

- [x] `office_documents.content_hash` 迁移与回填策略（Phase 0 去重 MVP 中落地）；
- [x] 文档库搜索/筛选/排序/重复清理（list 端点 `q`/`doc_type`/`sort` + `duplicate-groups` 端点；前端搜索栏 / 类型下拉 / 排序下拉 / 重复徽标 / 一键清理归档）；
- [x] **M2.5 规范书库 MVP**：`office_spec_documents` 表、规范书库 UI（`OfficeSpecLibrary`）、LLM 辅助提取（复用 `extract_word_rules` 的 `use_llm` 路径）、工作区默认绑定、文档级绑定；
- [x] `office_ai_review_routes.py`：审校 + 历史 + **修订端点（`POST /office/ai/revise`）**；
- [x] `OfficeAiAssistantPanel`：问题列表、来源徽章（规范书 vs AI）、来源过滤、逐项勾选 + 「应用到文档」确认对话框；
- [x] 审校流程接入 M2.5 规范书：有绑定时先跑规范书规则，再跑 LLM 补充（`run_review_async` 合并去重）；
- [x] Word 修订痕迹应用 + 自动快照（`apply_word_revisions` 写 `w:ins`/`w:del`；`snapshot_pre_edit` 落 `.snapshots/<epoch_ms>-<filename>`）；
- [x] 审计历史（`office_ai_reviews`）与成本记录（token 数入历史行）；
- [x] 安全评审：提示注入、路径、大小、未确认写入（H1/H2 跨工作区越权已修，M1–M6/L2 同步修复）。

### Phase 2：AI 起草（2–3 周）

- [ ] 大纲生成与编辑；
- [ ] 分节流式生成 + 单节重生成；
- [ ] 参考资料选择与引用展示；
- [ ] 组装导出接入现有生成器与交付验收；
- [ ] 模板占位符 AI 建议值；
- [ ] **AI 起草接入 M2.5 规范书**：选择规范书后，大纲结构/格式/术语要求注入 prompt；生成后自动跑规范书交付检查；
- [ ] 生成会话持久化与任务中心集成。

### Phase 3：版式渲染与批量能力（2 周）

- [ ] Excel SheetJS 网格版式预览 spike + 实现；
- [ ] PPT 版式预览 spike（库 vs 后端缩略图）+ 实现；
- [ ] 批量 AI 审校（rules tab 增强）；
- [ ] 性能与包体积评估（architecture-baseline / bundle ratchet）。

### Phase 4：win7 同步

- [ ] 按项目双分支策略 cherry-pick；
- [ ] pydantic v1 / Python 3.8 适配；
- [ ] 评估「审校与规范」「LaTeX」tab 的同步范围；
- [ ] 双分支测试与安装包冒烟。

## 6. 涉及文件与模块（预期）

**前端**

- `src/pages/Office.tsx`
- `src/features/office/OfficeIntake.tsx`（新增）
- `src/features/office/OfficeDocumentList.tsx`
- `src/features/office/OfficePreviewPanel.tsx`
- `src/features/office/OfficeSpecLibrary.tsx`（新增：规范书库面板）
- `src/features/office/OfficeAiAssistantPanel.tsx`（新增）
- `src/features/office/AiDraftWizard.tsx`（新增）
- `src/features/office/OfficeGenerateForm.tsx`
- `src/features/office/useOfficeDocuments.ts`
- `src/shared/api/officeApi.ts`、类型定义

**Electron**

- `electron/officeIpc.ts`（多文件、自动识别、hash、预检）
- `electron/preload.ts`（如需新增桥接）

**后端**

- `backend/data/database.py`（content_hash 迁移、AI 审校表、规范书表）
- `backend/office/storage.py`（写入/查询 hash、规范书读写）
- `backend/api/office_routes.py`（生成/列表契约扩展）
- `backend/api/office_spec_routes.py`（新增：规范书库 CRUD、提取、绑定）
- `backend/api/office_ai_review_routes.py`（新增）
- `backend/api/office_ai_draft_routes.py`（新增）
- `backend/office/ai_review.py`、`ai_draft.py`（新增服务层）
- 复用：`word_audit.py`、`word_fix.py`、`word_revision_writer.py`、`word_rule_extract.py`（含 LLM 路径）、`selfcheck_history.py`、`orchestration/llm_factory.py`

## 7. 测试与验收

- 单元测试：去重判断、hash、问题合并、diff 应用、UI 状态；
- 集成测试（pytest）：导入预检、AI 审校/修订路由、生成路由、快照与历史；
- E2E（Playwright）：统一导入 → 去重对话框 → 点击历史 → 版式视图 → AI 审校 → 应用建议 → AI 起草导出；
- 覆盖率 ≥ 80%；
- 真机验收：Win7 安装包下的高保真、PDF viewer、LLM 端点连通性；
- 回归：现有 office 测试全绿，bundle ratchet 与 architecture-baseline 按分支实测更新。

## 8. 风险评估与依赖

| 风险 | 影响 | 缓解 |
|------|------|------|
| `data:` PDF 行为待真机确认 | 高保真修复方向 | Phase 0 先验证，再决定 blob 转换或后端字节流 |
| Excel/PPT 前端渲染库成熟度 | 版式预览效果与包体积 | 先 spike，失败则回落后端缩略图/结构化视图 |
| LLM 延迟与成本 | AI 审校/起草体验 | 规则先行、分块、并发上限、可取消、成本展示 |
| 规范书提取质量 | 审校依据准确性 | 提取结果人工可编辑；保留来源段落便于追溯；LLM 置信度低时提示人工确认 |
| 长文档上下文窗口 | 审校遗漏 | 分块 + 合并去重 + 位置锚点 |
| 提示注入 | 文档内容操纵模型 | 正文标记不可信、系统提示隔离、输出 schema 校验 |
| 误改写 | 用户数据风险 | 一律 diff + 确认 + 自动快照 + 修订痕迹 |
| 双分支差异 | win7 功能缺失/回归 | main 先行，Phase 4 专门同步与 py38/pydantic v1 适配 |
| DB 迁移 | 旧数据兼容 | 加可空列 + 幂等迁移 + 缺失 hash 不参与判重 |
| 包体积棘轮 | CI 失败 | 新依赖按需动态 import，Phase 3 单独评估 |

外部依赖：

- LLM 端点与配置（沿用现有设置页/网关）；
- LibreOffice 或 Word COM（仅作为版式预览增强，不作为必需项）；
- 前端渲染库选型（SheetJS、pptx 渲染库）需先做技术 spike。

## 9. 分支与交付策略

- 按项目规则：main 为主开发分支，release/win7 按功能对齐原则同步；
- Phase 0 可拆成独立小 PR（预览修复 / 统一导入 / 历史点击 / 去重）便于快速回归；
- Phase 1–2 每个里程碑一个 PR，均带计划文档勾选进度；
- AI 功能默认受设置页开关控制（未配置 LLM 时显示「未配置模型」并禁用，而不是报错）；
- 不删除既有确定性能力，AI 作为增强路径。

## 10. 不在范围内

- 完整 Office 编辑器（复杂排版、宏、公式编辑）；
- 实时多人协作；
- 云端存储/同步；
- 自动升级 LibreOffice/Office 依赖；
- 对历史文档做全量 hash 回填的强制迁移（仅提供懒回填/后台任务）。
