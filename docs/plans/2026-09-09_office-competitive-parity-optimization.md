# 2026-09-09 Office 功能对标主流 AI 软件的差距分析与优化方案

## 背景与目标

Sage 的 Office 模块（`backend/office/`，18 个模块约 5700 行，25 个单测文件 ~300 用例 + 28 集成用例）已完成 CRUD 闭环：创建/读取/编辑/删除/归档/恢复、pre-edit snapshot、@ 引用注入、Word 模板填充、AcroForm 表单。但与 2026 年主流 AI 办公能力（Microsoft 365 Copilot、Claude、ChatGPT、Gemini、WPS AI）相比，差距集中在五个维度：

1. **生成物表现力** —— 无图表、无图片、几乎无样式控制；
2. **读取保真度** —— 纯文本摘要、公式文本丢失、PDF 表格是 stub；
3. **PDF 互通** —— 后端能力对 LLM 和前端完全不可见；
4. **视觉反馈** —— 预览是纯文本、编辑前无 diff 确认；
5. **架构天花板** —— 固定工具集 vs 主流的「代码沙箱」模式，功能追赶永远慢一拍。

本方案给出按批次落地的优化路线，目标是：**批次 1 两周内清完接线型欠账，批次 2 两个月内补齐感知差距最大的能力，批次 3 作为季度级战略项立项讨论**。

---

## 对标基准（2026-09 公开能力）

| 产品 | 关键能力 | 对 Sage 的启示 |
|---|---|---|
| Microsoft 365 Copilot | 2026-04 agentic 能力 GA：多步骤、应用内原生操作（改格式/插图表），Work IQ 层跨 Word/Excel/PPT/Outlook 编排 | 多步任务编排 + 生成后自校验 |
| Claude | skills 模式：沙箱内写代码调 python-docx/openpyxl 生成 docx/xlsx/pptx/PDF，表达力无上限；Cowork 处理本地文件 | 受控代码沙箱是「终极形态」 |
| ChatGPT | Code Interpreter 上传 xlsx 做数据分析（透视/统计/图表图片输出），产出真实可下载文件 | `office_analyze` 类数据分析工具 |
| Gemini | Sheets「Fill with Gemini」自动填充；Slides 生成原生可编辑多页演示并匹配品牌版式（2026-06/07） | 模板/主题匹配生成 |
| WPS AI / 豆包 / Kimi | AI 推荐图表类型（可视化 30 秒）、PPT 一键生成+改写+导出、深度中文格式兼容、本地数据处理 | 本地化 + 中文场景是 Sage 天然主场 |

**共同的分水岭**：主流产品不让 LLM 走「固定操作清单」，而是让它直接操作文档库（写代码）——功能上限只取决于库本身。Sage 每加一个能力都要新增工具 schema、参数校验、prompt 声明、前端类型，这是追赶永远慢一拍的根因（对应批次 3 的战略项）。

---

## 现状基线（事实清单，含代码依据）

### 能力矩阵

| 能力 | Word (.docx) | Excel (.xlsx) | PPT (.pptx) | PDF |
|---|---|---|---|---|
| 生成 | 标题/多级列表/表格/CJK 字体（`word.py generate_docx`） | pandas 写字符串行（`excel.py generate_xlsx`） | 固定几何文本框（`ppt.py generate_ppt`） | reportlab，仅 base-14 Helvetica（`pdf.py:207,211`） |
| 读取 | 段落+样式级、表格文本网格、图片仅计数 | `data_only=True` 仅缓存值，无公式文本 | 标题+要点+备注+计数 | 仅文本；表格/图片 stub（`pdf.py:140-142`） |
| 编辑（`edit.py`） | replace_text / append_paragraphs / append_table / set_table_cell / delete_paragraph | set_cells / append_rows / add_sheet / rename_sheet / delete_sheet | replace_text / set_slide_title / set_slide_bullets / set_slide_notes / append_slide / delete_slide | **无** |
| LLM 工具 | 7 个 `office_*`（`backend/domain/tool_names.py:49-57`） | 同左 | 同左 | **0 个**（仅 HTTP 端点） |
| 模板 | docxtpl 分析+填充（仅 HTTP 端点） | 无 | 无 | AcroForm 读取+填充+flatten（仅 HTTP 端点） |

### 关键事实

- 前端 `OfficeDocType = 'ppt' | 'word' | 'excel'`（`src/shared/api/types.ts:948`）——**PDF 被排除在整个 UI 之外**。
- `docs/superpowers/specs/2026-09-05-word-template-pdf-operations-design.md` §3.3（Phase 5）已规划 `office_read_pdf / office_generate_pdf / office_read_pdf_form / office_fill_pdf_form / office_analyze_word_template / office_fill_word_template` 六个工具，HTTP 端点也在 `backend/api/office_routes.py:464-524` 运行，但 `backend/tools/` 里一个都没注册。
- 全仓库 grep `add_chart|add_picture` 为零——生成物没有一张图、一个图表。`docs/plans/2026-07-16_office-features.md:526-540` 已设计 `add_chart`（LineChart/BarChart/PieChart）但从未实施。
- Excel 无法编写公式；编辑保存后 openpyxl 丢弃缓存计算值（`edit.py:375-381` 已有注释）。
- @ 注入摘要严重有损（`backend/chat/attachment_resolver.py`）：Word 只取**每段第一句**（`_digest_word`:51-66），Excel 每表只取**前 5 行**（`_digest_excel`:69-84）；`OFFICE_EXTS` 不含 `.pdf`（:91）。
- 唯一的样式控制是 Word 字体族（`word.py:31-101`，PR #482）；`edit.py` 模块头（:40-41）明确非目标："no style/formatting surgery, no charts / images / macros editing, no track-changes"。
- `OfficePptGenerateRequest.template`（`models.py:241`）是死参数——接受 `'default'|'minimal'` 但 `generate_ppt` 从不读取。
- `.snapshots/` 无保留策略（技术债 L3，`docs/technical/48-office-crud-completion.md` §8）。
- 前端文档列表仅 Save As / Open / Show in Folder（`OfficeDocumentList.tsx:6-15`），archive/restore/snapshot 后端能力无 UI 入口。
- 预览纯文本（`src/features/office/OfficePreviewPanel.tsx`）：缩进标题+HTML 表格+要点列表，无视觉保真。
- `docs/user-manual/09-office.md` §9.4.4 建议用户「把重要源文档放在工作区外」——对自家编辑能力的信任缺口。
- 依赖现状：`backend/requirements.txt:58-69` 已含 python-pptx/python-docx/openpyxl/pandas/docxtpl/PyMuPDF/reportlab；`requirements-bundled.txt:81-104` 中 pandas 未进 Win7/Py3.8 打包清单（无 py38 wheel）。
- 根目录 `PARITY.md` 是内部状态一致性标准，与竞品对标无关；office 无长期追踪的对标基线文档。

---

## 差距总览

| # | 维度 | Sage 现状 | 主流水平 | 批次 |
|---|---|---|---|---|
| G1 | PDF 对 LLM/前端可见性 | 0 工具、UI 无 PDF | 全格式文件对话 | 1 |
| G2 | PDF 中文输出 | Helvetica 无 CJK 字形 | 原生支持 | 1 |
| G3 | Excel 公式 | 不能写、读不到公式文本 | 读/写/求值 | 1 |
| G4 | @ 注入上下文质量 | 首句/5 行，有损 | 全文结构化注入 | 1 |
| G5 | 图表与图片 | 不支持 | 一句话生成图表 | 2 |
| G6 | 数据分析 | 无 | 上传即分析+图表 | 2 |
| G7 | 样式控制 | 仅 Word 字体族 | 字号/颜色/版式/主题 | 2 |
| G8 | 读取保真度 | 纯文本、PDF 表格 stub | 结构化 markdown/表格 | 2 |
| G9 | 编辑信任闭环 | 无 diff 预览，手册让用户「重要文档放外面」 | 改前预览+版本回滚 | 2 |
| G10 | 预览 | 纯文本 | 所见即所得/高保真渲染 | 2 |
| G11 | Office→PDF 导出 | 无 | 标配 | 2 |
| G12 | 表达力架构 | 固定工具集 | 代码沙箱（Claude/ChatGPT） | 3 |
| G13 | 模板库 | 仅 Word docxtpl，无模板库 | 模板/品牌版式生成 | 3 |
| G14 | 审阅/转换长尾 | 无批注/修订/OCR/PDF→Word | Copilot 审阅场景 | 3 |
| G15 | 多步任务编排 | office 任务未接 orchestration | Copilot agentic 多步操作 | 3 |

---

## 批次 1（P0 快赢，约 2 周，零新依赖）

> 特征：全是「已规划未接线」「纯前端补齐」「bug 级修复」，风险低、感知立竿见影。

### 1.1 PDF/模板能力包装成 LLM 工具（收 G1）

按 `2026-09-05-word-template-pdf-operations-design.md` §3.3 的 Phase 5 设计，把已有 HTTP 端点接线为 LLM 工具：

| 新工具 | 复用的既有实现 |
|---|---|
| `office_read_pdf` | `backend/office/pdf.py read_pdf` |
| `office_generate_pdf` | `backend/office/pdf.py generate_pdf` |
| `office_read_pdf_form` | `backend/office/pdf_forms.py` |
| `office_fill_pdf_form` | `backend/office/pdf_forms.py`（含 flatten/XFA 检测） |
| `office_analyze_word_template` | `backend/office/word_template.py` |
| `office_fill_word_template` | `backend/office/word_template.py`（含 InlineImage ≤10MB、zip-bomb 防护） |

涉及文件：
- `backend/domain/tool_names.py` —— 新增 6 个工具名
- `backend/tools/office_read_pdf_tool.py` 等 6 个 wrapper（对齐 `office_tool.py` 的 `requires_tool_context` 模式；create/fill 类工具沿用 `office_create_tool.py` 的 `output_dir` + 工作区外审批模式）
- `backend/tools/__init__.py:122-141` 注册
- `backend/agents/profiles.py:606-622` 能力 prompt 同步声明（避免 L2 prompt-drift 复发）；primary 全量，writer 给「只读 + 生成」子集
- `backend/tests/unit/tools/` wrapper 用例 + `backend/tests/integration/` 路由→工具一致性用例

验收：LLM 在对话中能「读这个 PDF 并总结」「把这份模板的 {{name}} 填成 xxx」「生成一个 PDF」。

### 1.2 前端纳入 PDF（收 G1）

- `src/shared/api/types.ts:948` `OfficeDocType` 加 `'pdf'`
- `src/pages/Office.tsx` + `src/features/office/` 预览/列表/生成表单支持 pdf 分支（预览先复用文本面板，高保真渲染见 2.6）
- `src/shared/api/officeApi.ts` 补 `office_pdf_read` / `office_pdf_generate` IPC 通道（`electron/officeIpc.ts` 透传）

### 1.3 修 PDF 中文输出（收 G2，bug 级）

`pdf.py:207,211` 仅 base-14 Helvetica，无 CJK 字形，与设计文档 §11.3「支持中英文混排」验收冲突。方案：`reportlab.pdfbase.cidfonts.UnicodeCIDFont('STSong-Light')` 注册 CID 字体（零体积成本，查看器需含亚洲字体包）；若实测兼容性不足，回退方案为内嵌思源黑体子集（体积 +几 MB，走 bundled 清单评审）。

验收：中英文混排 PDF 在无额外字体的查看器中正常显示；新增 `test_pdf_cjk.py` 用例。

### 1.4 Excel 公式闭环（收 G3）

- 生成/编辑：`generate_xlsx` / `set_cells` 接受公式字符串（openpyxl 原生支持 `=SUM(A1:A10)`，以 `=` 开头即按公式写入，不做字符串强转）
- 读取：`office_read` 增加 `mode=formula`（openpyxl `data_only=False` 读公式文本，`edit.py` 路径已证明可行），`summary` 模式同时给「公式 + 缓存值」对照
- 无法本地求值时在读取结果尾部显式标注「公式计算值需在 Excel 中打开后生效」
- 已有回归保护：`backend/tests/integration/test_excel_roundtrip.py::test_roundtrip_formula_survives_edit_but_cached_value_drops`

验收：LLM 能「在合计行写 =SUM 公式」并读回确认公式存在。

### 1.5 @ 注入摘要质量升级（收 G4）

`backend/chat/attachment_resolver.py`：

| 类型 | 现状 | 改为 |
|---|---|---|
| Word | 每段第一句 | 标题层级 + 整段 + 表格转 markdown |
| Excel | 表名 + 前 5 行 | 表头 + 行/列数 + 数值列统计特征（min/max/均值/空值数）+ 前 N 行（N 按字节预算自适应） |
| PDF | 不支持 | 加入 `OFFICE_EXTS`，摘要 = 元数据 + 逐页文本前若干行 |

同时把摘要生成逻辑下沉到 `backend/office/` 供 `office_read` 的 `section=summary` 复用，消除两套有损逻辑（`persist_read_summary` 已有 upsert 语义，保持不变）。

验收：LLM 仅凭 @ 注入即可正确回答「这篇文档第 3 节讲了什么」「这张表哪列缺失值最多」。

### 1.6 清理死参数（防漂移）

`models.py:241` `OfficePptGenerateRequest.template`：要么实现 `default/minimal` 两套几何布局，要么删除字段并同步前端类型。二选一，不留死接口。

### 1.7 Snapshot 保留策略 + 前端版本/归档 UI（收 G9 一半，还 L3 债）

- 保留策略：`backend/office/storage.py:320-363` `snapshot_pre_edit` 后追加清理——每文档保留最近 N 份（默认 10）+ 目录总大小上限（默认 100MB），超限删最旧；策略常量进 `models.py` 配置
- 前端：`OfficeDocumentList.tsx` 补「归档/恢复」操作（后端 `office_archive`/`office_restore` 路由与工具均已就绪，PR #538）；文档详情补 snapshot 列表 + 一键回滚（读 `.snapshots/` 目录 + `restore from snapshot` 端点，需新增 1 个 route）

验收：用户手册 FAQ Q2（09-office.md）改写为「自动保留最近 10 个快照，可在文档详情回滚」。

---

## 批次 2（P1 差距收口，约 2 个月）

### 2.1 图表与图片插入管线（收 G5，感知价值最高）

- `backend/office/charts.py`（新）：matplotlib→PNG 通用产物（中文字体注册复用 1.3 的字体方案）；依赖在 `requirements.txt` 加 matplotlib，**不进 `requirements-bundled.txt`（Win7/Py3.8 无 wheel，与 pandas 现状一致，走 main 通道）**
- Excel 原生图表：openpyxl `add_chart`（LineChart/BarChart/PieChart），按 `2026-07-16_office-features.md:526-540` 的既有设计落地
- Word：`python-docx` `add_picture`（支持 base64 或工作区文件，对齐 docxtpl InlineImage 的安全约束）
- PPT：`python-pptx` `add_picture` + 图片占位布局
- LLM 接口：`office_create`/`office_update` 的 content 结构增加 `images: [{data|path, width, height}]` 与 `charts: [{type, title, data, target}]` 字段；`_OFFICE_CREATE_CAPABILITY_PROMPT` 同步
- 测试：图表/图片 round-trip 用例进 `backend/tests/integration/`

### 2.2 `office_analyze` 数据分析工具（收 G6，对标 ChatGPT Code Interpreter）

新工具 `office_analyze`：xlsx → pandas（已 bundle）→ 统计/透视/聚合/清洗 → 输出结构化结果给 LLM + 可选生成分析报告 xlsx（含图表，复用 2.1）。安全边界：只读源文件、产物走 `office_create` 既有审批流。Sage 数据不出本机，是相对云端产品的天然卖点，写入能力 prompt。

### 2.3 样式能力分级开放（收 G7）

**前置**：修订 `edit.py:40-41` 与 `word.py/excel.py/ppt.py` 模块头的非目标声明，避免能力-文档漂移（L2 教训）。分级交付：

| 轮次 | Word | Excel | PPT |
|---|---|---|---|
| a | 字号/加粗/颜色/对齐 | 列宽/数字格式/填充色 | 布局选择（替换 `ppt.py:268-273` 硬编码几何） |
| b | 页边距/页眉页脚/页面方向 | 冻结窗格/条件格式 | 主题色/字体方案 |

实现原则：走 `edit.py` 的 op-dict 扩展（如 `set_run_style` / `set_column_width` / `set_theme`），保持「全有或全无 + 原子替换」的既有事务语义。

### 2.4 读取保真度升级（收 G8，编辑正确性的前提）

- Word `read_docx`：输出结构化 markdown（标题层级 + 表格 + 列表），run 级粗体/斜体保留为 markdown 语法
- PDF：用 PyMuPDF 自带 `find_tables()` 填掉 `pdf.py:140-142` 的 tables stub
- Excel `read_xlsx`：增加列格式信息（数字格式/列宽/合并区域），供 LLM 保格式编辑

### 2.5 office_update 改前 diff 预览 + 确认（收 G9）

后端已有 approval 机制 + pre-edit snapshot，补最后一环：

- 新 route `POST /office/update/preview`：应用 ops 到临时副本，返回「变更 diff」（段落级 before/after、单元格 before/after）
- 前端确认弹窗展示 diff → 确认 → 应用 → 提示「可回滚」（联动 1.7 的快照 UI）
- `docs/user-manual/09-office.md` §9.4.4 的「重要文档放工作区外」建议改写为 diff+快照工作流

对齐 PHILOSOPHY「透明可控」，也是 Copilot/ChatGPT canvas 级体验标配。

### 2.6 预览升级为 HTML 渲染（收 G10）

`OfficePreviewPanel.tsx` 纯文本 → 高保真 HTML，不捆绑 LibreOffice（守住 non-goal）：

- docx：mammoth（docx→HTML，保留标题/表格/列表/粗斜体）
- xlsx：openpyxl 读取 → 按 sheet 分页 HTML 表格（数字格式渲染）
- pptx：按页卡片化（标题+要点+图片缩略）
- 后端新增 `GET /office/doc/{id}/preview`（返回 HTML 或结构化 JSON，前端渲染）；大文件走既有 `max_output_bytes` 截断 + 分页

### 2.7 Office→PDF 导出（收 G11，可选增强）

检测本机已装转换器：MS Word（docx2pdf，COM）或 LibreOffice（`soffice --headless --convert-to pdf`）；有则启用、无则 UI 降级提示。不捆绑任何大件，non-goal 不破坏。注意：`--headless` 子进程需超时与僵尸进程回收（参考 `electron/officeIpc.ts` 的 staging 生命周期模式）。

---

## 批次 3（P2 战略项，季度级，先立项讨论）

### 3.1 受控代码沙箱（收 G12，本方案最重要的一条架构建议）

固定工具集模式决定 Sage 永远在追功能。建议为可信 profile 开放「python 片段执行」：审批门禁（复用 out-of-workspace 审批 UI）+ 工作区目录沙箱（复用 `path_safety.resolve_within`）+ 禁网 + 资源超时，环境内可 import openpyxl/python-docx/python-pptx/pandas。一次性解锁全部表达力，终结「每加一个能力 = schema+校验+prompt+前端类型」的循环。

- 与 Win7 冲突：仅 main 通道，bundled 清单不变
- 安全评审前置：对标 Claude skills 的沙箱边界，产出独立设计文档后再动工

### 3.2 模板库（收 G13）

- 内置模板（周报/会议纪要/报价单/项目计划等 5-10 套）+ 用户模板目录（工作区 `office/templates/`）
- docxtpl scanner 补 `TABLE`/`RICH_TEXT` 占位符类型（枚举在 `models.py:334-351` 已存在但扫描器从不产出）
- 前端 `/office` 生成表单加模板选择；Excel/PPT 模板（openpyxl/python-pptx 均支持从模板文件加载）二期

### 3.3 审阅与转换长尾（收 G14）

- Word 批注/修订：读取（OOXML 层解析 comments.xml/track changes）+ 添加批注（python-docx 扩展）
- PDF→Word/PPT 转换、OCR（pytesseract，可选依赖按需提示安装）
- 排期放最后：依赖重、场景窄，先给 3.1 让路

### 3.4 office 任务接入 orchestration（收 G15）

「生成一份 20 页带图表的报告」类多步任务走既有 orchestration 管线（拆解→执行→校验），并增加**生成后自校验**步骤：工具执行后自动 `office_read` 回读、比对意图（如「应有 5 张图表」），失败自动重试。对标 Copilot agentic 的「多步原生操作」体验，是批次 2 能力之上的编排层增益。

---

## 实施顺序与依赖

```
批次1: 1.3 ─┐
       1.1 ─┼─→ 1.2（前端 PDF）          （无相互依赖，可并行）
       1.4  1.5  1.6  1.7
批次2: 2.1（图表管线）─→ 2.2（analyze 复用图表）
       2.4（保真读取）─→ 2.3（样式编辑需要先看见格式）
       2.5  2.6  2.7（独立）
批次3: 3.1 → 3.2 → 3.3 / 3.4
```

## 验收标准（批次级）

| 批次 | 验收 |
|---|---|
| 1 | LLM 工具数 7→13+；前端可见 pdf；中文 PDF 无豆腐块；Excel 公式可写可读；@ 注入后 LLM 能答对文档细节问题；快照自动清理；归档/恢复有 UI |
| 2 | 「画一张销售趋势图」一句话产出含原生图表的 xlsx；「分析这张表」产出统计报告；编辑前有 diff 确认；预览接近真实版式；本机有 Office/LibreOffice 时可导出 PDF |
| 3 | 沙箱模式下 LLM 能完成任一批次 1/2 工具无法表达的文档操作；内置模板可用；多步报告任务端到端跑通并自校验 |

## 风险与非目标

- **Win7 LTS（Python 3.8）**：matplotlib/新依赖不进 `requirements-bundled.txt`；批次 1 全部能力对 py38 兼容（无新依赖），契约测试 `test_office_bundled_requirements.py` 继续把关
- **不捆绑 LibreOffice/MS Office**：2.7 与未来转换能力全部走「检测本机、可选启用」
- **prompt 漂移**：每次加工具同步 `profiles.py` 能力声明，纳入 PR checklist
- **范围**：在线协编辑、云同步、版本控制（git 级）维持 `2026-07-16_office-features.md` 的 "Won't (v1)" 结论不变

## 长期追踪机制

本方案的对标矩阵（差距总览表）作为 office 竞品对标基线，落库为独立文档后每轮发布更新勾选状态；建议在后续对标轮次（parity-rN）中将 office 维度纳入打分。

## 参考

- 内部：`docs/technical/48-office-crud-completion.md` §8（L1-L10 已知限制）、`docs/superpowers/specs/2026-09-05-word-template-pdf-operations-design.md` §3.3/§10、`docs/plans/2026-07-16_office-features.md`（Phase 3 未建项）
- 外部（2026-09 检索）：
  - Microsoft 365 Blog — Copilot agentic capabilities GA：<https://www.microsoft.com/en-us/microsoft-365/blog/2026/04/22/copilots-agentic-capabilities-in-word-excel-and-powerpoint-are-generally-available/>
  - Claude Help Center — Create and edit files：<https://support.claude.com/en/articles/12111783-create-and-edit-files-with-claude>
  - Google Blog — Gemini Workspace updates (2026-03)：<https://blog.google/products-and-platforms/products/workspace/gemini-workspace-updates-march-2026/>
  - Workspace Updates — Native editable presentations in Slides：<https://workspaceupdates.googleblog.com/2026/06/create-fully-native-and-editable-presentations-with-Gemini-in-Google-Slides.html>
  - WPS AI 图表实操指南：<https://www.wps.cn/article/ban-gong-xiao-lv-shu-ju-ke-shi-hua-2026-NK6lasDc.html>
