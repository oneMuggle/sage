# Office 文档 AI 能力评估与优化方案（2026-11）

> 类型：能力评估 + 优化建议方案（**未实施**，待评审后排期）
> 基线：`docs/technical/54-office-parity-tracking.md`（2026-09 对标矩阵）
> 对标时间：2026-11-21；目标分支：`main`（逐项标注 `release/win7` 兼容策略）

## 1. 背景与目标

Sage 的定位是**本地优先的桌面 AI 工作台**（数据不出机、Win7 LTS 长尾支持、与记忆/编排/项目工作台深度集成）。
截至 2026-11，Office 方向已经形成全链路能力：读取（docx/xlsx/pptx/pdf/LaTeX）、生成（四格式 + 期刊模板）、编辑（dry-run diff + 快照）、审校（确定性规则 + LLM + 渲染级检查）、模板填充（Word/PPT/PDF 表单）、工作流（文档库 / 规范书 / AI 侧栏 / 生成工作台）。

主流 AI 应用在 2025–2026 完成了从“文件问答 / 一次性生成”到“**原生原位编辑 + 模板保真 + 可视质量闭环 + 智能体/沙箱**”的跃迁：

- **Microsoft 365 Copilot**：2026-04 起 Word/Excel/PowerPoint 的 agentic 编辑 GA，直接在文件内执行多步原生操作（受模板、主题、公式、动画约束），变更可审阅、可回退；2026-11 Office 并入 Copilot app 并 GA，保留 OneDrive 权限/合规/协同[^copilot-ga][^copilot-office]。
- **Claude**：沙箱内创建/编辑 `.docx/.xlsx/.pptx/.pdf`；开源 `anthropics/skills` 的 docx/pptx/xlsx 技能给出工程范式——OOXML `unpack → 编辑 XML → repack`、`validate.py` XSD 校验、`merge_runs.py` 跨 run 合并、跟踪修订/批注 helper、LibreOffice 公式重算、渲染成图做视觉自检[^claude-files][^anthropic-skills-docx][^anthropic-skills-xlsx][^anthropic-skills-pptx]。
- **ChatGPT**：上传 512MB/文件、200 万 token（文本类），Data Analysis 用 Python 沙箱；ChatGPT Work 可按规定格式、保留公式/版式/模板创建与编辑 docx/xlsx/pptx（PowerPoint 暂不含桌面 Work 流程），Excel 可通过 add-in 直接操作打开的簿[^openai-upload][^openai-work][^openai-data]。
- **Gemini / Google Workspace**：Side panel 内写作/生成；2026-10 起 Slides 支持**整份演示批量编辑**（原生可编辑幻灯片，可撤销/版本历史），Gemini App 内新增文件生成/预览/编辑并导出 PPTX/PDF，Sheets 提供交互式 canvas 与单元格级引用[^google-workspace-2026-10][^google-workspace-features]。
- **WPS 灵犀**：文档内同屏侧栏“就地读写”，Word 支持修订/批注模式，Excel 多步推理与跨 Sheet 清洗，PPT 支持上传模板生成与复杂数学公式，PDF 支持保排版翻译；本地/云端沙箱、权限模式、技能生态[^wps-lingxi][^wps-lingxi-docs]。
- **Kimi**：单文件 100MB/单次 50 个文件，K3 百万 token 上下文与原生多模态；可端到端输出可编辑 docx/xlsx/pptx/pdf，Word 支持插入批注与修订建议[^kimi-capability][^kimi-docs].

**目标**：在保持本地/离线与中文规范差异化的前提下，把 Sage 的 Office 能力从“功能齐全”推进到“**主流级的编辑深度与交付质量**”，并给出可独立验收的分期路线。

## 2. 现状评估（基于代码与文档实测）

### 2.1 已具备能力

> 规模基线：`backend/office/` 约 121 个 Python 模块、3.7 万行；LLM 工具面共 **39 个 `office_*` 工具**（6 个工具包：core/pdf/template/analysis/journal/quality）。测试：unit/office 114 文件 1,065 用例、tools 281 用例、integration 394 用例。

| 层 | 能力 | 关键实现 |
|---|---|---|
| 输入解析 | 附件统一提取 pdf/docx/xlsx/pptx（25MB/10 个/100k 字符，zip 中央目录预算 + 30s 超时）；PDF 页标记、图表抽取、页码引用；本地 OCR（RapidOCR/Tesseract，Office 默认关闭）；LaTeX 只读解析 | `backend/api/chat_attachment_routes.py`、`backend/office/pdf*.py`、`backend/office/ocr.py`、`backend/office/latex/`（§131/§156/§116/§105） |
| 结构化画像 | Word 页面/样式级联/段落/run/表格合并/书签/域/锚点（只读）；主题字体未展开、vMerge 不计算 row_span、不输出修订/内容控件（已知限制） | `backend/office/doc_profile.py`、`style_resolver.py`（§117） |
| 生成 | `office_create` 生成 docx/xlsx/pptx（PDF 走 `office_generate_pdf`；`office_create` 的 `pdf` 枚举存在分派漂移，见 G16）；Word 目录/域/交叉引用/脚注尾注/题注/页码格式/核心属性；Excel 条件格式/数据验证/图标集/公式/图表；PPT 布局模板与占位符；期刊模板 N1–N8；Design Studio 导出 | `backend/tools/office_create_tool.py`、`backend/office/{word,excel,ppt,journal,charts}.py`（§55、§66–68、§72–96、§151） |
| 编辑 | `office_update` dry-run diff；Word 9 ops / Excel 10 ops / PPT 7 ops；pre-edit 快照/恢复/归档；快照 vs 当前 state-diff（Word 段落/表格、Excel 单元格、PPT 页级） | `backend/office/edit.py`、`diff_preview.py`、`snapshot_diff.py`、`storage.py`（§48、§134） |
| 修订与批注 | Word 原生修订 `w:ins/w:del` + 批注（限段落直接普通 run）；审校一键修复 + 复检 | `backend/office/word_revision_writer.py`、`word_fix.py`（§119） |
| 审校 | RulePack 15 类确定性检查器 + GB/T 9704 内置包；LLM 语义审校（**仅 Word**）；渲染级审计（Word→PDF→PyMuPDF：尺寸/边距/字体/页码）；批量审计 + Markdown 报告；规范书抽取/激活/绑定 | `backend/office/word_audit.py`、`word_render_audit.py`、`word_batch_audit.py`、`ai_review.py`（§119–122、§134） |
| 模板 | Word 模板 Profile（内容控件/书签/占位符/Jinja/图片/页眉页脚）填充；PPT 模板版式枚举 + 占位符填充；PDF AcroForm 填写 | `word_template_profile*.py`、`ppt_template.py`、`pdf_forms.py`（§118） |
| 工作流 | 文档库（搜索/筛选/排序/去重/归档）、规范书库、AI 侧栏（选区改写/对话/审校/指令式修改）、生成工作台（NL/参考文档/模板对话/迭代）、规则管理 v17、审校历史/成本 | `src/features/office/*`、`backend/api/office_*_routes.py`（§134、用户手册 §37） |
| 配套 | Excel soffice 重算回写缓存值；旧格式 `.doc/.xls/.ppt` soffice 转换导入；50MiB 编辑上限；工作区路径围栏、zip 预算、二进制写保护、工具权限分级 | `excel_recalc.py`、`legacy_import.py`、`path_safety.py`、`backend/tools/permissions.py` |

### 2.2 关键差距（逐项有证据）

| # | 差距 | 证据 | 影响 |
|---|---|---|---|
| G1 | **PPT 编辑深度不足** | `update_pptx` 仅 7 个 op；`append_slide` 固定 blank layout + 文本框，不走模板版式；无复制页/重排/图表编辑/主题读取/批注 | 无法像 Copilot/Gemini/WPS 那样对存量 deck 做结构化改造 |
| G2 | **Word 修订/批注不可读回** | §119 已知限制：`python-docx` 的 `paragraph.text` 不含 `w:ins` 文本与 `w:delText`；预览/复检看不到待接受文本；修订仅支持段落直接 run；批注仅新增/删除且锚定整段（无回复/解决/线程）；页眉页脚/脚注/尾注/TOC 只能生成侧设置，`office_update` 无对应 op | 用户在 Sage 内看不到修改痕迹，也必须回 Word 接受/拒绝 |
| G3 | **视觉质量闭环只覆盖 Word 结构项** | 渲染审计仅检查页面尺寸/边距/字体/页码；无内容溢出/重叠/空页/图表遮挡检查；xlsx/pptx 无渲染审计；生成流程无“渲染→看图→修复”闭环 | 首轮成品率依赖 LLM 自觉；与 Claude/灵犀的“生成后自检”体验有差距 |
| G4 | **复杂文档解析保真不足** | 无 Docling/MarkItDown/unstructured；Office OCR 默认关闭（`office_enabled=false`）；主题字体未展开、vMerge 无 row_span、修订/内容控件不在 profile；扫描/复杂表格/公式无系统化视觉兜底 | 复杂 PDF/扫描件/双栏论文的问答与 RAG 质量受限 |
| G5 | **任意文档操作通道缺位** | 受控代码沙箱设计待评审未上线（§54）；无 Anthropic 式 OOXML 底层通道（unpack/edit/validate/merge_runs/comments/accept_changes） | SmartArt、图表数据、复杂页眉页脚等需求只能“报不支持” |
| G6 | **Excel 治理闭环不完整** | 有 soffice 重算，但无“重算后错误值（#REF!/#DIV/0!）检测与报告”；编辑 op 缺行/列插入删除、合并单元格、数据验证/条件格式的**编辑**（生成侧已有） | 生成/编辑工作簿可能带着公式错误交付 |
| G7 | **附件/大文档策略落后** | 聊天附件 25MB/10 个/100k 字符；Office 编辑 50MiB 上限；主流为 100–512MB、百万 token 上下文 | 年报、长篇论文、多文件对比场景受限 |
| G8 | **AI 审校仅 Word** | 用户手册 §37：“该格式不支持 AI 审校，目前只对 Word 做语义审校” | Excel/PPT 仅有人工检查或生成期约束 |
| G9 | **跨文档/跨版本对比入口缺失** | 仅有快照 vs 当前的结构 diff（`snapshot_diff.py`），无任意两文件对比、无 PDF diff | 合同改版、论文修订、报表环比需用户手工比对 |
| G10 | **Office 能力未技能化** | 已有 Skills 体系与规则包，但 Office 操作未封装为可组合技能（脚本 + 校验 + 说明） | 扩展性弱于 Claude skills、灵犀技能市场；用户自定义工作流成本高 |
| G11 | **前端呈现断层** | 生成结果只有结果卡（无内联预览，§134 §11 已承认）；`TemplateLibrary` 只显示名称/描述，缩略图逻辑只存在于未挂载的 `OfficeGenerateForm`/`OfficeGenerateSubforms`；聊天附件中 docx/xlsx/pptx 无富预览（PDF 有 `MediaPdfPreview`）；Excel 图表、PPT 图片不在结构化预览中渲染；`@` Office 引用 chip 不可点击预览；Word 模板 Profile/填充后端已有但无前端入口 | “能处理”但“看不到/用不上”，体验与主流“边看边改”差距明显 |
| G12 | **文档与代码漂移** | 技术 §123 与用户手册 §30 仍描述 `OfficeGenerateForm`/“4 个文件选择器”，实际为 `GenerateWorkspace`/`OfficeIntake`；`OfficeGenerateForm` 为孤儿组件；设计工作台 Office 融合（Word→大纲/图表嵌入/Live Artifact）只有后端入口，前端 M7 未做 | 维护者与用户被过时文档误导；能力“存在但不可达” |
| G13 | **PDF 通用编辑与读取保真缺失** | 无合并/拆分/旋转/水印/页码/删页；读取不返回图片（图片抽取仅在聊天附件链路）；表格仅识别文本层线框表；PDF→Word 为文本级重建；表单 `flatten` 只是置 read-only | PDF 场景弱于 WPS/Kimi/ChatGPT；合同/年报处理受限 |
| G14 | **Excel 读侧与模板边界** | 读取不解析图表/透视表/数据验证/条件格式；无宏/VBA；无合并单元格编辑 op；`hbar` 图表仅 PNG 且打包版不含 matplotlib；PPT/Excel 模板实例化是字面 marker 替换，无控制流/行循环 | 读不懂自己生成的高级特性；模板复用能力有天花板 |
| G15 | **性能与并发瓶颈** | LibreOffice 转换用全局 `threading.Lock` 串行所有导出/预览/缩略图；公式子进程单槽；附件 25MB/30s、PDF 50MB/1 万页、Wiki 20MB/10s、CSV 1 万行等限制分散，Word/Excel/PPT 普通读取无统一上限；编辑锁仅进程内，外部 Word/WPS 修改只能靠 revision 检测 | 多任务下排队；大文件策略不可预期 |
| G16 | **工具面小裂缝** | `office_create` 的 doc_type 枚举含 `pdf` 但生成分派不支持；`office_delete` 只允许 docx/xlsx/pptx；`workspace_search` 只识别三件套；Wiki 队列抽取路径不支持 PDF（流式路由支持）；项目资料索引中 PDF 仅占位 | 用户/Agent 触发“看似支持实则失败”的路径 |

### 2.3 对标矩阵（2026-11 更新）

> 图例：✅ 具备；⚠️ 部分/受限；❌ 缺失；— 不适用。**Sage 列为代码实测**，其它列以官方公开信息为准（见脚注）。

| 能力 | M365 Copilot | Claude | ChatGPT | Gemini | WPS 灵犀 | **Sage** |
|---|---|---|---|---|---|---|
| 四格式生成（docx/xlsx/pptx/pdf） | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 原位编辑（存量文件结构化修改） | ✅ 原生 app 内 | ✅ 沙箱 + skills | ✅ Work | ✅ Docs/Sheets/Slides 内 | ✅ 同屏侧栏 | ⚠️ Word 强 / Excel 中 / PPT 弱 |
| 模板/品牌保真 | ✅ | ✅ 模板/母版 | ✅ “match existing file/master deck” | ✅ 品牌版式 | ✅ 上传模板 | ✅ Word/PPT 模板填充；⚠️ 版式感知新增弱 |
| 跟踪修订/批注 | ✅ | ✅ OOXML 层 | ⚠️ | ✅ | ✅ 修订/批注模式 | ⚠️ 可写不可读回、无接受/拒绝 UI |
| 公式/图表 | ✅ 原生 | ✅ recalc + 图表 | ✅ Python | ✅ | ✅ 保留公式 | ✅ 生成+重算；⚠️ 错误闭环缺 |
| 渲染级视觉自检 | ✅ 原生渲染 | ✅ PDF→图→视觉检查 | ✅ 沙箱渲染 | ✅ | ✅ 交付式成品 | ⚠️ 仅 Word 结构项 |
| 任意代码/操作沙箱 | ✅ | ✅ | ✅ | ✅ | ✅ 本地/云 | ❌ 设计待评审 |
| 复杂解析（版面/表格/公式/扫描） | ✅ | ✅ | ✅ 视觉 | ✅ | ✅ WPS 文档底座 | ⚠️ 轻量提取 + opt-in OCR |
| 大文件/长上下文 | ✅ | 30MB/文件 | 512MB、2M token | ✅ | 50MB 建议 | ⚠️ 25–50MB |
| 多文件/版本对比 | ✅ | ✅ | ✅ | ✅ | — | ⚠️ 仅快照 diff |
| 实时协同/云同步 | ✅ | ✅ Artifacts | — | ✅ | ✅ | ❌（Won't-v1，桌面定位） |
| **本地/离线、数据不出机** | ❌ | ❌ | ❌ | ❌ | ⚠️ 端侧/云端双轨 | ✅ **差异化** |
| **中文公文/期刊规范** | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ✅ | ✅ **差异化** |
| **Win7 LTS** | ❌ | ❌ | ❌ | ❌ | ⚠️ | ✅ **差异化** |

## 3. 优先级与优化原则

**原则**：优先补“交付质量”和“编辑深度”，而不是追云协作；所有新增能力必须能在本地/离线路径下工作，外部依赖（LibreOffice、视觉模型、Docling）一律可选并可降级。

- **P0（下一迭代）**：G1 PPT 编辑深度、G2 修订读回、G3 视觉闭环、G6 Excel 错误闭环。
- **P1（随后 1–2 个迭代）**：G4 解析适配器与视觉兜底、G5 OOXML 底层通道 + Office Skills、G9 多文档对比、G8 Excel/PPT 审校、G11 前端呈现断层、G12 文档/代码漂移、G13 PDF 通用编辑、G14 Excel 读侧对称、G16 工具面裂缝。
- **P2（按需）**：G7 大文件策略、G10 技能生态、G15 性能与并发、分享导出。
- **不做**：实时多人协作、云同步、把文档处理整体搬到云端——与“本地优先”定位冲突。

## 4. 技术方案

### 4.1 分层架构：统一文档操作层 + 两条编辑通道

```
Agent / 工作台 UI
   │  office_* 工具 + REST
   ▼
Document Ops Layer（统一入口）
   ├─ 高层通道：python-docx / openpyxl / python-pptx 语义 op（现有 edit.py）
   └─ 底层通道：OOXML unpack → edit XML → repack（新增）
        · validate.py 等价校验（XSD 子集 + xml:space 修复）
        · merge_runs.py（跨 run 文本可查找）
        · comment helper / accept_changes
   ▼
Render & Verify（新增）：soffice → PDF → PyMuPDF → 页面图 / VLM 检查
   ▼
快照 / diff / 审计 / 验证历史
```

- 高层通道保持“安全、可解释、可 dry-run”；底层通道只在高层 op 表达不了时启用（修订、批注、SmartArt、复杂页眉页脚），且必须经过 XSD/最小校验与安全解包（拒绝 symlink 与路径穿越，限制成员数与解压体积）。
- 两条通道共用快照、diff、审计、渲染校验，避免第二套写回实现。

### 4.2 Render & Verify 质量闭环（对应 G3）

1. **渲染**：复用 `export_pdf.py`（LibreOffice/Word COM，进程内串行锁）把 docx/xlsx/pptx 转 PDF；PyMuPDF 逐页出 PNG（分辨率可配）。
2. **确定性检查**：页面尺寸/边距/字体/页码（已有 Word 实现，抽成通用）；空页、内容越界、图片缺失、表格跨页断裂（基于文本块与绘制对象几何）。
3. **视觉检查（可选）**：配置了视觉模型时，抽首末页 + 关键页送 VLM，检查重叠/截断/图表可读性/排版明显异常；未配置时只跑确定性检查。
4. **修复循环**：生成或重大编辑后自动执行，最多 2 轮（发现 → 形成修复 op → 应用 → 复检），最终把“通过/降级/未通过”与检查报告返回给工具/工作台。
5. **降级契约**：无 soffice / 无视觉模型 / 超时一律返回 warning，不阻塞主流程（对齐现有 `render_unavailable` 模式）。
6. **接入面**：`office_create` / `office_update` 增加 `verify: "auto" | "off"`（默认 auto 仅对生成与结构性编辑）；结果卡展示缩略图与检查结论；任务中心展示进度。

### 4.3 PPT 深度编辑与模板版式（对应 G1）

- **ops 扩展**（`backend/office/edit.py`）：`duplicate_slide`（复制 slide part 及其媒体/图表/关系，复用 `ppt_template.py` 的包操作经验）、`move_slide`、`add_slide(layout=名, placeholders={idx: 文本})`、`set_run_format`（字体/字号/颜色/加粗）、`replace_image`、`add_chart`（复用 `charts.py`）、`add_comment`。
- **模板路径**：`office_analyze_ppt_template` 增加缩略图（soffice 渲染），供 LLM/用户选版式；`office_fill_ppt_template` 支持按 layout 名批量新增页 + 占位符填充（当前只按页号+占位符 idx 填文本）。
- **读取侧**（`ppt.py`）：补充 layout 名、占位符清单、图表数据、主题字体/配色、批注、备注分组。
- **兼容**：`python-pptx==0.6.23` 固定在 py38/win7；新 op 只用 0.6.x API + lxml 补丁，win7 同步前跑同一套 fixture。

### 4.4 Word 修订/批注读回与接受拒绝（对应 G2）

- **解析**：`doc_profile.py` / 预览解析器输出 `revisions[]`（w:ins / w:del / w:move*）与 `comments[]`（含锚点范围）；`read_docx` 增加 `view="accepted" | "original" | "all"`（默认 accepted 保持旧行为，all 展示修订）。
- **写回扩展**：修订写入从“段落直接 run”扩展到超链接、域、表格单元格；支持逐条接受/拒绝，注意“删除段落标记 = 与下段合并”的语义（Anthropic `accept_changes.py` 的已知坑），提供等价实现并补 fixture。
- **编辑 op 补齐**：页眉页脚、脚注/尾注、TOC/TOF 的 `office_update` op（当前只在生成侧可设置）；批注回复/解决线程按需评估。
- **前端**：预览显示插入（下划线/颜色）/删除（删除线）/批注气泡；AI 审校面板增加“全部接受 / 逐条接受拒绝”，复用现有 diff 渲染。
- **契约**：结构化预览、复检、导出均以 accepted 视图为准；保留 original 视图用于对照。

### 4.5 Excel 读写对称与错误治理（对应 G6/G14）

- **重算闭环**：生成/编辑含公式的 xlsx 后自动 `refresh_formula_cache`（已有）；随后 `load_workbook(data_only=True)` 扫描错误值（#REF!/#DIV/0!/#VALUE!/#NAME? 等）与空缓存，输出 `formula_errors[]` 到工具结果与工作台。
- **op 扩展**：插入/删除行列、合并/取消合并单元格、数据验证、条件格式、定义名称；全部走 openpyxl 并进 dry-run/diff。
- **读侧对称**：回读图表、条件格式、数据验证、合并单元格，与生成侧一致；打包版图表渲染保障（matplotlib 缺失时降级为原生图表）。
- **验收**：公式错误必须显式报告，不允许“静默无缓存”；与 `formulas` 本地求值引擎（main-only）交叉校验关键单元格。

### 4.6 解析管线适配器与视觉兜底（对应 G4）

- **抽象**：`DocumentExtractor` 协议 + 注册表；输出统一 `StructuredDoc`（Markdown + 元素树 + 锚点：page/table/figure/paragraph/sheet/cell）。
- **后端**：
  - 默认轻量后端（现状：python-docx/openpyxl/python-pptx/PyMuPDF）保持零新增依赖；
  - `markitdown` 适配器（轻量，Office/PDF→Markdown，含 OCR 插件可接视觉模型）作为可选依赖，评估 win7 可移植性；
  - `docling` 适配器（版面分析、阅读顺序、表格结构、公式、OCR、统一 DoclingDocument）**仅 main**，作为 extras 安装，路由到复杂 PDF/扫描件场景。
- **路由策略**：按格式/大小/是否扫描/表格复杂度选择后端；解析结果带 content_hash 缓存（已有 `read_cache.py`）。
- **视觉兜底**：扫描页/复杂表格/公式 → 页面渲染 →（优先）本地 OCR /（可选）视觉模型；Office/PDF 的 OCR 默认策略从“opt-in”升级为“设置控制的自动”（`office_enabled` 默认仍关，但工作台提供一键开启与提示）。
- **RAG 接入**：结构化块与页码/表格锚点进入 Wiki/RAG，引用可回链到页/表/单元格。

### 4.7 多文档/跨版本对比（对应 G9）

- 统一 `POST /office/compare`：两个路径 + 格式 → 结构化 diff（Word 段落/表格、Excel sheet/cell、PPT 页、PDF 文本/页），复用 `snapshot_diff` / `diff_preview` 的条目形状与红绿渲染；输出 Markdown 报告供导出。
- 工作台入口：文档库多选 →「对比」；审校面板可选择“与上一快照/与另一文件”对比。

### 4.8 安全与沙箱（对应 G5）

- **优先确定性通道**：OOXML 底层操作以“白名单 helper + 校验”方式提供，不开放任意代码执行。
- **若上线沙箱**：子进程隔离、默认无网络（可域名白名单）、工作区围栏、CPU/内存/墙钟限制、审计日志、默认关闭、显式授权；沿用工具权限分级与审批链。复用待评审的 `specs/2026-09-19-office-sandbox-security-review.md` 结论。
- **不可信文档**：解包拒绝 symlink/路径穿越；XML 解析用 `defusedxml`；zip 炸弹预算（已有 10,000 成员上限的做法）。

### 4.9 Office Skills 封装（对应 G10）

- 新增内置技能包（`SKILL.md` + `scripts/` + `references/`）：
  - `office-docx`：创建/编辑/修订/批注/接受拒绝；
  - `office-xlsx`：公式、格式、图表、重算与错误检查；
  - `office-pptx`：模板版式、复制/重排、图表/媒体；
  - `office-pdf`：表单、拆分合并、页级引用。
- 技能通过受控执行器调用 helper 脚本；工具白名单、workspace 围栏、输出截断沿用现有约定。

### 4.10 前端呈现一致性（对应 G11/G12）

- **生成结果内联预览**：`GenerateWorkspace` 结果卡直接嵌入 `DocumentCanvas`（复用文档页预览），而不是只给「在文档页打开」；进度可复用 `backend/office/progress.py` 的轮询机制与设计工作台的流式进度实现。
- **模板缩略图**：把未挂载 `OfficeGenerateSubforms` 里的 `templateThumbnail` 逻辑接回现役 `TemplateLibrary`；PPT 模板选版式同样走缩略图（与 M2 合并）。
- **聊天附件富预览**：docx/xlsx/pptx 附件对齐 PDF 的 `MediaPdfPreview`——点击 chip 打开右栏富预览（docx-preview / 结构化 xlsx/pptx），并保留“打开原文件/在文档工作台打开”入口。
- **结构化预览补图**：Excel 渲染图表、PPT 渲染图片与版式缩略图；Word 内嵌图片上限（当前 10 张）改为可展开。
- **`@` 引用 chip 可点击**：与文件引用 chip 一致，点击打开右栏预览，右键保留打开/定位/复制。
- **补齐已有后端能力的前端入口**：Word 模板 Profile/填充（§118）表单、Design Studio 的 Word→大纲/图表嵌入/Live Artifact（M7）。
- **清理漂移**：删除或明确废弃孤儿组件 `OfficeGenerateForm`；修正技术 §123 与用户手册 §30 的过时描述；生成 tab 文档统一为 `GenerateWorkspace` + `OfficeIntake`。

### 4.11 PDF 通用操作与读取补齐（对应 G13）

- **页面操作**（PyMuPDF）：合并、拆分、旋转、删除页、抽取页、水印、页码；作为独立工具与 REST 暴露，纳入文档库管理。
- **读取补齐**：页面图片返回（复用 `services/attachment_pdf.py` 的抽取逻辑）；表格识别保留线框表，复杂表可选 Docling/TableFormer 兜底；扫描页 OCR 走统一策略。
- **PDF→Word 保真**：嵌入图片、保留表格位置与页内顺序（当前为文本级重建）。
- **表单 flatten**：使用 PyMuPDF 真正扁平化 appearance；XFA 明确提示不支持。
- **验收**：合并/拆分/旋转/删页 fixture；图片与表格抽取基准；flatten 后字段不可再编辑。

### 4.12 工具面与路径一致性（对应 G14/G16）

- `office_create` 的 `pdf` 枚举二选一：移除，或分派到 `office_generate_pdf`（消除 schema 漂移）。
- `office_delete` / `workspace_search` 覆盖 pdf/csv。
- Excel 读侧补齐：图表、条件格式、数据验证的回读，与生成侧对称；新增合并单元格编辑 op。
- 模板控制流：Excel/PPT 模板实例化支持行循环/条件块的显式 schema（或明确文档化“不支持”，不再隐式期待）。
- Wiki 抽取路径统一支持 PDF；项目资料索引接入 PDF 快速提取；评估未接线的 `services/rag-service`（接入或删除）。
- 验收：工具名/schema/实现/文档四方一致，纳入现有 tool_names / architecture 反漂移门禁。

## 5. 涉及的文件与模块

| 模块 | 文件 |
|---|---|
| 编辑/通道 | `backend/office/edit.py`、新增 `backend/office/ooxml/`（unpack/pack/validate/merge_runs/comments/accept_changes） |
| PPT | `backend/office/ppt.py`、`ppt_template.py`、`backend/tools/office_ppt_template_tool.py` |
| Word | `backend/office/word.py`、`doc_profile.py`、`style_resolver.py`、`word_revision_writer.py`、`word_audit.py`、`word_render_audit.py`、`word_template_profile*.py` |
| Excel | `backend/office/excel.py`、`excel_recalc.py`、`excel_eval.py`、`formula_worker.py`、`charts.py`、`template_library.py`、`template_thumbnail.py`、`workspace_search.py` |
| 解析/OCR | `backend/office/pdf.py`、`pdf_forms.py`、`pdf_to_word.py`、`pdf_preview.py`、`export_pdf.py`、`backend/services/attachment_pdf.py`、`backend/office/ocr.py`、`backend/services/ocr/*`、`backend/wiki/extract.py`、新增 `backend/office/extractors/` |
| 工作流/API | `backend/api/office_*_routes.py`、`backend/api/rules_routes.py`、`src/features/office/*`、`src/widgets/chat/MessageClientMeta.tsx`、`src/widgets/chat/OfficeRefChip.tsx`、`src/widgets/chat/MediaPdfPreview.tsx`、`electron/commandRoutes/office.ts`、`electron/ipc-manifest.json` |
| 前端一致性 | `src/features/office/GenerateWorkspace.tsx`、`TemplateLibrary.tsx`、`OfficeStructuredPreviews.tsx`、`DocxNativePreview.tsx`、`OfficePreviewPanel.tsx`、`src/pages/office/*`；清理 `OfficeGenerateForm.tsx`/`OfficeGenerateSubforms.tsx` 的孤儿/未挂载状态 |
| 依赖 | `backend/requirements.txt`（docling/markitdown 为 extras）、`backend/requirements-py38.txt`（不新增） |
| 文档 | 更新 `docs/technical/54`、§117–123、§134；新增技术章节与用户手册说明 |
| 测试 | `backend/tests/unit/office/*`、`backend/tests/integration/test_office_*`、`src/features/office/__tests__/*`、fixture 集（中英文/表格/图表/扫描/长文档） |

## 6. 实施步骤（里程碑）

> 每项独立可验证；遵循 TDD（先写失败测试）与双分支策略（main 先行，win7 按兼容性裁剪 cherry-pick）。

### M1 — Render & Verify 闭环（P0，对应 G3）

- [x] 抽取通用渲染服务：任意 docx/xlsx/pptx → PDF → 逐页 PNG（复用 `export_pdf.py`）→ `backend/office/render_verify.py`
- [x] 通用确定性检查（页面/边距/字体/页码 + 空页/越界/缺图）
- [x] REST 端点 `POST /api/v1/office/render/verify`（含 `status=passed/degraded/failed`、缩略图 data URL）
- [x] `office_create` 默认 `verify: auto`（一次生成检查）；`office_update` 默认 `off`（避免每轮编辑等待转换器），均可显式指定
- [x] 渲染在**工作区临时目录的副本**上执行，不覆盖用户已有 `<stem>.pdf`、不留产物（审查 H1）
- [x] `repair=true` 默认输出 `<stem>-repaired.docx` 并保留源文件；`repair_overwrite=true` 才原地替换且先做快照（审查 H2）
- [x] 可选 VLM 抽页检查（视觉模型不可用时静默降级）—— `visual_pages` + `visual_checker` 可插拔钩子，失败降级为 `visual_check_failed`；具体视觉模型适配随 M6 落地
- [x] 自动修复循环（发现 → 修复 op → 复检，≤2 轮）—— `repair=true` 且请求含显式期望值（size/margins/page number）且为 `.docx` 时启用，调用 `word_fix`
- [ ] 工作台结果卡缩略图 + 检查报告；任务中心进度 —— REST 已返回缩略图，前端接入待 M1b
- [ ] fixture 基准：缺陷检出率 ≥80%、误报 ≤10%、无 soffice 环境不阻塞

> **实施记录（2026-11-21，M1a 后端切片）**
> - 新增：`backend/office/render_verify.py`（`verify_rendered_pdf` / `verify_document` / `verify_for_tool`，`passed/degraded/failed`）
> - 扩展：`backend/office/word_render_audit.py` 的 `audit_rendered_pdf(max_pages=...)`（向后兼容）
> - 端点：`backend/api/office_lifecycle_routes.py` → `POST /render/verify`
> - 工具：`office_create` 默认 `verify=auto`、`office_update` 默认 `verify=off`，结果附加紧凑 `render_verify` 摘要
> - 审查修复（H1/H2/H3）：渲染副本隔离、修复默认另存 + 可选快照覆盖、update 默认不跑转换器
> - 后续优化：隔离渲染每次复制源文件（≤50MiB），可按 `(path, mtime, size)` 缓存校验结果
> - 测试：`test_render_verify.py`（13）+ `test_office_render_verify_routes.py`（4）+ 工具级 5 条；Office 全量 1733 单测 + 440 集成通过；ruff / py38 / silent-exceptions / architecture 门禁通过
> - 基线：`architecture-baseline.json` 中 `office_create_tool.py` 1625 → 1702（有意增长）

### M2 — PPT 深度编辑（P0，对应 G1）

- [x] `update_pptx` 扩展 duplicate/move/append_slide(layout+placeholders+position)/set_run_format/replace_image/add_chart
- [ ] 模板缩略图（按 layout 渲染）+ 按 layout 新增页填充 —— 填充已完成，缩略图待 M2b
- [x] `read_ppt` 补 layout/占位符/图表数据（主题字体与批注待 M5 OOXML 通道）
- [ ] golden deck（10 页，含图表与模板）套用与 LibreOffice 打开无修复提示
- [ ] win7（python-pptx 0.6.23）兼容 fixture 通过
- [ ] PPT 批注写入（`add_comment`）—— 依赖 M5 OOXML 底层通道

> **实施记录（2026-11-21，M2a 编辑/读取切片）**
> - 编辑：`update_pptx` 新增 `duplicate_slide`（形状+关系深拷贝）、`move_slide`、`append_slide` 的 layout/placeholders/position、`set_run_format`（find 或 shape/paragraph/run 定位）、`replace_image`（原位替换保层级）、`add_chart`（column/bar/line/pie）
> - 读取：`PptSlideContent` 新增 `layout` / `placeholders` / `charts`；`read_ppt` 抽取版式名、占位符（idx/type/name/text）、图表类别与系列
> - 测试：`test_ppt_edit_ops.py`（8）；PPT 相关回归 74 通过；ruff 通过

### M3 — Word 修订/批注读回与接受拒绝（P0，对应 G2）

- [x] 解析 `w:ins/w:del`（含作者/时间/段落锚点），`read_docx` 结果附加 `tracked_changes`
- [x] 接受/拒绝：`POST /office/word/tracked-changes/resolve`（accept/reject，输出新文件或 overwrite 原地替换）
- [ ] 前端预览显示修订/批注并逐条接受拒绝（后端与 REST 已就绪）
- [ ] 修订写入扩展到超链接/域/表格单元格；删除段落标记合并语义
- [x] round-trip 测试：修订写入 → 读取 → accept/reject（正文段落；跨 run 由 writer 测试覆盖）

> **实施记录（2026-11-21，M3a 修订读回/接受拒绝）**
> - 新增：`backend/office/word_tracked_changes.py`（`extract_tracked_changes` / `read_word_tracked_changes` / `resolve_word_tracked_changes`）
> - 模型：`WordTrackedChange`（kind/text/author/date/paragraph_index）；`OfficeWordReadResult.tracked_changes`
> - 端点：`POST /office/word/tracked-changes`、`POST /office/word/tracked-changes/resolve`
> - 测试：unit 6 + integration 2；Word 读取回归通过；ruff/py38/architecture 通过
> - 已知限制：读取/接受拒绝均覆盖 OOXML body 段落（含表格文本）；行/单元格级修订（`w:trPr`/`w:tcPr`）读取未覆盖；跨段落书签与删除段落标记合并语义待后续

### M4 — Excel 读写对称与错误治理（P0，对应 G6/G14）

- [x] 公式健康扫描：错误值（#REF!/#DIV/0! 等）与缺失缓存；`POST /office/excel/formula-health`
- [x] 重算结果附带 `formula_count/formula_error_count/missing_cache_count/formula_errors`
- [x] op 扩展：`insert_rows/delete_rows/insert_cols/delete_cols/merge_cells`
- [x] 读侧补齐：图表、条件格式、数据验证回读（`ExcelSheetContent.charts/conditional_formats/data_validations`）
- [ ] 数据验证/条件格式的编辑 op、定义名称（后续）
- [ ] 与本地求值引擎交叉校验关键单元格（后续）
- [ ] 打包版图表渲染保障（matplotlib 缺失时的降级或内置替代）

> **实施记录（2026-11-21，M4a Excel 读写对称）**
> - 新增：`backend/office/excel_health.py`（`scan_formula_health` / `check_formula_health`）
> - 扩展：`excel_recalc` 成功后扫描并返回计数；`read_xlsx` 返回图表/条件格式/数据验证；`update_xlsx` 新增行列增删与合并单元格
> - 测试：`test_excel_m4.py`（9）；Excel 相关回归 43 通过；ruff/py38/architecture 通过

### M5 — OOXML 底层通道 + Office Skills（P1，对应 G5/G10）

- [x] `backend/office/ooxml/`：安全解包/打包（成员数/大小/压缩比/路径穿越/symlink 拒绝）、结构校验（必需部件/XML 合法性/DTD 拒绝）、`xml:space` 修复、`merge_docx_runs`
- [x] `office_ooxml` 工具（validate/merge_runs）接入 office_quality 能力包/权限/工具快照
- [x] shipped skills：`office-ooxml`（结构维护）、`office-xlsx`（表格工作流）、`office-pdf`（读取/生成/表单）；docx/ppt 起草沿用 `report-writing` / `ppt-making`
- [x] 安全测试：zip 炸弹/路径穿越/symlink/DTD-ENTITY/坏 ZIP
- [ ] XSD 全量校验（当前为必需部件 + XML 合法性的结构子集）
- [ ] docx comment helper 收敛进 ooxml 包（现由 `office_update add_comment` / `office_revise_word` 提供）
- [ ] Demo：按模板生成带批注与修订的合同并在 Sage 内接受/拒绝

> **实施记录（2026-11-21，M5a OOXML 通道 + 技能）**
> - 新增：`backend/office/ooxml/archive.py` / `validate.py` / `runs.py`
> - 端点：`POST /office/ooxml/validate`、`POST /office/ooxml/merge-runs`
> - 工具：`office_ooxml`（WRITE_LOCAL，validate/merge_runs），已同步 `tool_names` / 权限 / bundle / 前端能力包 / 工具快照
> - 技能：`shipped/office-ooxml|office-xlsx|office-pdf/SKILL.md`
> - 测试：OOXML 单测 10 + 端点 3 + 工具 6；技能/工具注册回归 209；Office 全量 2243 passed / 2 skipped；ruff/py38/architecture 绿

### M6 — 解析适配器、PDF 操作与多文档对比（P1，对应 G4/G8/G9/G13/G16）

- [x] `DocumentExtractor` 注册表 + `light` 默认后端（docx/xlsx/pptx/pdf/csv → 统一 Markdown + 锚点）
- [x] `markitdown` / `docling` 可选适配器（运行时探测，不新增硬依赖；auto 优先可选后端，缺失回退 light）
- [x] 视觉兜底基础：Office/PDF 扫描页 OCR 已有设置开关（`ocr_config.office_enabled`）；复杂版面 VLM 抽页检查仍待后续
- [x] PDF 通用操作：合并/拆分/旋转/抽页/删页/水印/页码（`backend/office/pdf_ops.py`）
- [x] PDF 读取补齐：页面图片返回（opt-in、单图 ≤1.5MB/总预算 20MB、`image_count`）+ 真 appearance flatten（旧版 PyMuPDF 回退只读位）
- [ ] PDF 复杂表格兜底（Docling/TableFormer 路线随可选后端）
- [x] `office_create` 的 pdf 枚举：明确拒绝并引导 `office_generate_pdf`（消除分派漂移）
- [x] 工具面一致性：`office_delete` / `workspace_search` 覆盖 pdf/csv；Wiki 队列 PDF 路径
- [x] `POST /office/extract`（统一提取）与 `POST /office/compare`（Word/Excel/PPT/PDF/CSV diff + Markdown 报告）
- [x] 工作台对比入口（前端；后端已就绪）—— 文档库「对比」按钮 + `OfficeCompareDialog`（左右各选一份 → 行级 diff 汇总 + Markdown 报告）
- [x] 聊天附件 docx/xlsx/pptx 富预览（附件链路复用 `WordPreview`/`ExcelPreview`/`PptPreview`）；Excel 图表 / 条件格式 / 数据验证、PPT 版式 / 占位符 / 图表在结构化预览中渲染；`@` Office chip 点击右栏预览（跨工作区 chip 不劫持点击）
- [x] PPT 图片在结构化预览中渲染（`read_ppt` opt-in 提取内嵌图片 + 字节预算；前端图片网格 + 省略计数）
- [ ] Word 模板 Profile/填充前端入口
- [ ] Excel/PPT 基础规则审校（范围/锚点/只读），AI 语义审校视成本评估

> **实施记录（2026-11-21，M6a PDF 页面操作）**
> - 新增：`backend/office/pdf_ops.py`（merge/split/rotate/extract/delete/watermark/page-numbers，工作区围栏 + 原子写）
> - 端点：`POST /office/pdf/{merge,rotate,pages,split,watermark,page-numbers}`
> - 测试：unit 8 + integration 2；ruff/py38/architecture 通过
> - 限制：水印默认 Helvetica（非 ASCII 自动切 `china-s`）；`split` 输出按区间顺序编号

> **实施记录（2026-11-21，M6b 解析适配器 + 跨文档对比 + 工具面）**
> - 新增：`backend/office/extractors/`（base/light/optional/service）与 `backend/office/compare.py`
> - 端点：`POST /office/extract`、`POST /office/compare`
> - 工具面：`office_delete` 支持 pdf/csv；`workspace_search` 识别 pdf/csv；Wiki 队列 `extract_text_for_ingest` 支持 PDF（`--- page N ---`）
> - 可选后端：`pip install markitdown` 或 `docling`（main only）后 auto 自动启用；默认 light 无新增依赖
> - 测试：提取/对比 unit 10 + 端点 3；工具面回归 44；Office 全量 2274 passed / 2 skipped；ruff/py38/silent/architecture 绿

> **实施记录（2026-11-22，M6c PDF 图片与 flatten）**
> - `read_pdf` / `PdfReadRequest` 新增 `include_images`、`max_images_per_page`；`PdfPageContent.image_count` 恒回填
> - 图片预算：单图 ≤1.5MB、单次总预算 20MB，返回 `data_url`（JPEG/PNG）
> - `office_read_pdf` 工具与 `/office/pdf/read` 同步参数；默认关闭，避免普通读取膨胀
> - `fill_pdf_form(flatten=True)` 使用 `Document.bake(widgets=True)` 真扁平化；旧版 PyMuPDF 回退只读位
> - 测试：PDF 读取/表单/工具 58 passed；Office 全量 2260 passed / 2 skipped；门禁绿

> **实施记录（2026-11-23，M6c 安全返工：审查 BLOCK 修复）**
> - 审查代理判 BLOCK 的根因：预算在**解码之后**才判定（用户可控 PDF 里的位图 = 解压炸弹）、
>   工具面返回**被截断的 base64**（响应体静默损坏）、工具面**没有上界**；
>   第二轮复审判 BLOCK 的两条：JPX 字典尺寸不可信（伪造 /Width /Height 可绕预检）、
>   `include_images=False` 仍枚举图片（病理 PDF 单页 0.1s）
> - 解码前预检：`MAX_EMBEDDED_IMAGE_PIXELS`（12MP）+ `MAX_EMBEDDED_IMAGE_DECODED_BYTES`（64MB），
>   超限图跳过并 `logger.warning`，PDF 其余部分照常读出
> - **过滤器白名单**：只有 Flate/LZW/RunLength（裸样本）与 DCTDecode 的字典尺寸可信；
>   JPX/JBIG2/CCITT 码流自带真实尺寸 → **解码前整链拒绝**；ASCII85/Hex 链头包装照常放行
> - **`include_images=False` 根本不枚举**（不调 `get_images`）；枚举/解码/返回三档独立上限
> - 预览归一：统一 JPEG（去 alpha → RGB）+ 最长边缩放到 `MAX_EMBEDDED_IMAGE_EDGE`（1024px）
> - 资源三分离：输出预算（base64 20MB）/ 常驻缓存字节（`cache_bytes`）/ 已跳过 xref（`skipped`）
> - 服务端 clamp：`max_images_per_page` 收敛到 `MAX_IMAGES_PER_PAGE`（10），负数/非数字 → 0
> - 工具面默认 **metadata-only**（只回宽高/数量，零解码），`embed_image_data` 显式开关才嵌像素；
>   输出预算不足时先按大图优先丢 `data_url`（记入 `images_omitted`），而不是整包截断
> - `fill_pdf_form` 产物加 `MAX_PDF_OUTPUT_SIZE` 上限；原子临时文件 + `Path.replace` 落盘
> - 测试：unit 29（过滤器白名单/伪造尺寸回归/零枚举/预算/clamp/metadata-only/归一化）
>   + 端点 5 + 工具面 6；PDF 相关 95 passed；ruff / py38 兼容门禁 / architecture 棘轮绿

> **实施记录（2026-11-23，M6b 前端批次：对比入口 / 读侧 extras 渲染 / chip 点击预览）**
> - 前端契约：`src/shared/api/types/officeCompareTypes.ts` + `src/shared/api/officeCompareApi.ts`（`POST /api/v1/office/compare`）
> - 对比入口：`src/features/office/OfficeCompareDialog.tsx` + `src/pages/Office.tsx` 文档库「对比」按钮；
>   路径统一走 `officeDocumentRelativePath()`（`office/<doc_type>/<id>/<filename>`），与右栏预览一致
> - 读侧 extras 渲染：`OfficeStructuredPreviews.tsx` 补 PPT 版式/占位符/图表 + Excel 图表/条件格式/数据验证；
>   `src/shared/api/types.ts` 补对应 wire 类型
> - `@` Office chip：`src/widgets/chat/OfficeRefChip.tsx` message 变体点击 → 右栏 `openFilePreview()`；
>   发送时工作区 ≠ 当前工作区时不劫持点击（右键菜单仍可用）
> - i18n：zh/en 各 +20 key；feature barrel 审计符号 17 → 18
> - 测试：新增 2 个测试文件 + 扩展 2 个；前端 100 文件 / 547 用例绿；tsc / eslint / prettier / architecture 棘轮绿
> - 双分支：main PR #3232 + win7 PR #3233（cherry-pick 同步，无 Python 依赖变更）
> - 限制：PPT 内嵌图片像素后端未提取 → 本批不渲染 PPT 图片缩略图

> **实施记录（2026-11-23，M6d Excel 图表数值 + PPT 图片渲染）**
> - PPT 读取：`read_ppt` / `OfficePptReadRequest` 新增 `include_images`（默认 False）、`max_images_per_slide`（默认 3，≤10）、`embed_image_data`（默认 False）；`PptSlideContent.images` + `images_omitted`
> - 图片预算：单图原始 ≤1.125MB、全文档 ≤15MB、最多检查 500 张；跨页共享预算字典；超限计入 `images_omitted`；`include_images=False` 不枚举
> - Excel 图表：`_extract_sheet_charts` 输出 `categories` / `series_items[{name, values}]` / `truncated`（每图 ≤50 点）；openpyxl `series.val`/`cat` 解包 `numRef/strRef/numLit/strLit`
> - 前端：`MiniChart.tsx` 迷你 SVG 柱状图（PPT 图表与 Excel `series_items`；旧缓存无值回落文字清单）；`PptPreview` 图片网格 +「另有 N 张图片未内联」；`office.preview.chartTruncated` i18n
> - 预览路径开启 embed：`DocumentPreview`、`useOfficeDocuments.readByType`、`artifact_reader._structured_or_none`（结构化预览数据源）；普通读取默认关闭
> - 测试：后端新增 unit 10（`test_ppt_images_m6d.py` / `test_excel_chart_values_m6d.py`），端点既有 3 例改用 `OfficePptReadRequest`；Office/artifact 回归 1385 passed / 2 skipped；前端新增 2 文件 7 用例，相关回归 33 passed
> - 门禁：ruff / py38 兼容 / silent-exceptions / architecture 棘轮（baseline 更新 office_routes 861、excel 1246，新增 useOfficeDocuments 801、types 822）/ tsc / eslint / prettier 全绿

### M7 — 前端一致性与漂移清理（P1，对应 G11/G12）

- [ ] 生成结果内联预览（复用 `DocumentCanvas`），结果卡不再只给「在文档页打开」
- [ ] `TemplateLibrary` 接回缩略图（现逻辑在未挂载的 `OfficeGenerateSubforms`），PPT 模板选版式走同一缩略图
- [ ] 清理孤儿 `OfficeGenerateForm`；修正技术 §123 / 用户手册 §30 的过时描述（`GenerateWorkspace` + `OfficeIntake`）
- [ ] Design Studio Office 融合前端入口（Word→大纲 / 图表嵌入 / Live Artifact，原 M7 未做项）
- [ ] 前端测试：生成内联预览、缩略图（附件预览、chip 点击已由 M6b 前端批次覆盖）

### M8 — 大文件、并发与可选沙箱（P2，对应 G7/G15）

- [ ] 统一文件大小/页数/行数限制配置与错误码（Word/Excel/PPT 普通读取纳入）
- [ ] 附件/编辑上限可配置；流式解析与缓存命中率优化
- [ ] 转换并发：全局锁 → 有界队列 + 任务中心排队/超时提示（导出/预览/缩略图共用）
- [ ] 外部修改检测增强（revision 已是基础；补充文件监听/冲突提示）
- [ ] 附件线程超时可取消（协作式取消，避免 `wait_for` 只截断 await）
- [ ] 沙箱设计评审通过后实施（默认关闭 + 显式授权 + 审计）

## 7. 风险评估与依赖

| 风险 | 影响 | 缓解 |
|---|---|---|
| LibreOffice/Word COM 缺失（Linux/精简环境） | 渲染/重算/旧格式不可用 | 全链路降级为 warning；能力位暴露；文档说明安装方式 |
| Win7 / Python 3.8 限制 | 新依赖不可用 | docling 仅 main；markitdown 评估后决定；pydantic v1 垫片；py38 语法检查门禁 |
| `python-pptx 0.6.23` 能力有限 | 新 op 难实现 | 优先 0.6.x API + lxml 直接操作 OOXML；复制 slide 参照 anthropics 的包注册做法 |
| OOXML 底层通道破坏文件 | 文档损坏 | XSD/最小校验 + 打开测试 + 快照 + 原子替换；默认不改原件 |
| 视觉检查成本/时延 | 生成变慢、token 成本上升 | 抽页策略（首末+关键页）、开关可配、异步执行、仅 auto 模式 |
| 文档内容提示注入 | 被文档指令劫持 | 系统提示声明文档不可信；工具输出截断；沙箱无网络 |
| 双分支同步成本 | CI 棘轮/架构基线冲突 | 每里程碑单独 PR；win7 cherry-pick 前跑 py38/架构门禁；按分支实测数值更新基线 |
| 大依赖（docling）体积 | 安装包膨胀 | extras 安装、运行时能力探测、不影响默认包 |
| matplotlib 不在打包依赖 | 图表 PNG 在安装包内不可用（`hbar` 仅 PNG） | 内置替代或打包补齐；否则明确降级为原生图表 |
| PyMuPDF 主/Win7 版本差异（main 1.25+ / win7 1.24.11） | `find_tables` 等 API 行为不一致 | 按分支 fixture；能力探测降级 |
| main 工作树的 `requirements-py38.txt` 与 release/win7 不一致（pydantic 2.5 vs 1.10.13） | 误判 Win7 约束 | 以 release/win7 分支为准，同步前核对 |
| LibreOffice 转换全局串行锁 | 多任务排队、长任务互相阻塞 | M8 有界队列 + 任务中心排队/超时提示 |

**依赖**：LibreOffice（可选）、本机 Word COM（Windows 可选）、视觉模型端点（可选）、`docling`/`markitdown`（可选 extras）。

## 8. 验收标准（整体）

1. 生成/编辑后的 docx/xlsx/pptx 在 Word/Excel/PowerPoint 与 LibreOffice 打开均无“需要修复”提示（fixture 集 100%）。
2. xlsx 含公式产物 0 个静默错误：所有公式错误均出现在 `formula_errors[]`。
3. Word 修订/批注在 Sage 预览可见，并可接受/拒绝；accepted 视图与 Word 接受后一致（fixture 对照）。
4. PPT 可完成“模板套用 → 版式新增 → 复制/重排 → 图表/图片替换”全流程。
5. 复杂 PDF/扫描件基准集（≥30 份）关键信息抽取较现状提升 ≥25%，引用可回链页码/表格。
6. Render & Verify 在无 soffice/无视觉模型环境下降级且不阻塞。
7. `main` 与 `release/win7` CI 全绿（含 py38、架构、ruff、tsc、vitest）；新增依赖不进默认安装包。
8. PDF 合并/拆分/旋转/删页/水印可用；读取返回页面图片与表格；表单 flatten 后字段不可再编辑。
9. 工具名/schema/实现/文档四方一致（含 pdf/csv 覆盖），反漂移门禁纳入 `office_create/office_delete/workspace_search`。

## 9. 对标资料来源

[^copilot-ga]: Microsoft Copilot Blog, "Copilot's agentic capabilities in Word, Excel, and PowerPoint are generally available" (2026-04-22). https://www.microsoft.com/en-us/copilot/blog/2026/04/22/copilots-agentic-capabilities-in-word-excel-and-powerpoint-are-generally-available/
[^copilot-office]: Microsoft Community Hub, "Office at Ignite 2026: From apps to agentic system of work" (2026-11-17). https://techcommunity.microsoft.com/blog/microsoft-copilot-blog/office-at-ignite-2026-from-apps-to-agentic-system-of-work/4572226
[^claude-files]: Claude Help Center, "Create and edit files with Claude" (updated 2026-11). https://support.claude.com/en/articles/12111783-create-and-edit-files-with-claude
[^anthropic-skills-docx]: anthropics/skills, `skills/docx/SKILL.md`（unpack→edit→zip、merge_runs、修订、批注、validate、LibreOffice 渲染自检）. https://github.com/anthropics/skills/blob/HEAD/skills/docx/SKILL.md
[^anthropic-skills-xlsx]: anthropics/skills, `skills/xlsx/SKILL.md`（openpyxl 公式、`recalc.py` 重算与错误检查）. https://github.com/anthropics/skills/blob/HEAD/skills/xlsx/SKILL.md
[^anthropic-skills-pptx]: anthropics/skills, `skills/pptx/SKILL.md`（模板版式、duplicate slide、图表/媒体部件、缩略图）. https://github.com/anthropics/skills/blob/main/skills/pptx/SKILL.md
[^openai-upload]: OpenAI Help Center, "Uploading files and audio to ChatGPT". https://help.openai.com/en/articles/8555545-uploading-files-and-audio-to-chatgpt
[^openai-work]: OpenAI Help Center, "Creating and editing documents, spreadsheets, and presentations with ChatGPT Work". https://help.openai.com/en/articles/20001278-creating-and-editing-documents-spreadsheets-and-presentations-with-chatgpt-work
[^openai-data]: OpenAI Help Center, "Data analysis with ChatGPT". https://help.openai.com/en/articles/8437071-data-analysis-with-chatgpt
[^google-workspace-2026-10]: Google Workspace Updates (October 2026)：Slides 整份演示批量编辑、Gemini App 内文件创建/预览/编辑. https://workspaceupdates.googleblog.com/2026/10/
[^google-workspace-features]: Google Workspace Help, "Get started with Google Workspace with Gemini". https://support.google.com/docs/answer/13952129
[^wps-lingxi]: WPS 灵犀官网（一句话生成可编辑 Word/Excel/PPT 成品）. https://www.lingxi.cn/
[^wps-lingxi-docs]: WPS 灵犀专业版产品文档（文档处理矩阵、执行环境、权限模式、版本更新）. https://www.lingxi.cn/docs
[^kimi-capability]: Kimi 帮助中心，《Kimi 能做什么？》（100MB/50 个文件、K3 1M token）. https://www.kimi.ai/zh-hans/help/others/capability
[^kimi-docs]: Kimi 帮助中心，《Kimi 文档与 Kimi 表格概览》（可编辑 docx/xlsx/pptx/pdf、批注与修订）. https://www.kimi.ai/zh-hans/help/docs-and-sheets/docs-and-sheets-overview

## 10. 实施进度总览（2026-11-23）

> 分支：main（PR #3232）+ release/win7（PR #3233，cherry-pick 同步）。

| 里程碑 | 状态 | 提交 | 验证 |
|---|---|---|---|
| 方案文档 | ✅ | `ed06172ed` | — |
| M1 Render & Verify（核心） | ✅ | `309549f65` | unit 13 + integration 4 + tool 5 |
| M1b 修复循环 + 视觉钩子 | ✅ | `4ccfefaf4` | unit 15 |
| M2 PPT 深度编辑/读取 | ✅ | `966e1670f` | unit 8 + PPT 回归 74 |
| M3 Word 修订读回/接受拒绝 | ✅ | `76e8c77b6` | unit 6 + integration 2 |
| M4 Excel 读写对称/公式健康 | ✅ | `4230094e5` | unit 9 + Excel 回归 43 |
| M6a PDF 页面操作 | ✅ | `25cecbca1` | unit 10 + integration 2 |
| M6a 边界修复 | ✅ | `a128c99d2` / `4bc14a695` | split 原子性 + 中文水印 |
| 工具面 PDF 守卫 | ✅ | `4d1f52982` | tool 33 |
| 全量 Office 回归 | ✅ | — | 2215 passed / 2 skipped |
| 门禁 | ✅ | — | ruff / py38 / silent-exceptions / architecture |
| M5 OOXML + Skills | ✅ | 本轮提交 | OOXML 单测 10 + 端点 3 + 工具 6；全量 2243 passed |
| M6b 解析适配器 + 对比 + 工具面 | ✅ 后端 | 本轮提交 | unit 10 + 端点 3 + 工具面 44；全量 2274 passed |
| M6c PDF 图片读取 + 真 flatten | ✅ | 本轮提交 | 80 PDF 相关测试（安全返工后）；architecture 棘轮绿 |
| M6b 前端批次（对比入口 / 读侧 extras / chip 预览） | ✅ 前端 | `45adac67c` | main PR #3232 + win7 PR #3233；前端 100 文件 / 547 用例 |
| M6d Excel 图表数值 + PPT 图片渲染 | ✅ | 本轮提交 | 后端 unit 10 + 回归 1385；前端 7 新用例 / 回归 33；门禁绿 |
| M7 前端接入 | ⏳ | — | 未开始（M6b 前端批次已先行落 A/B/C/D 四项） |
| M8 大文件/并发/沙箱 | ⏳ | — | 未开始 |

**环境说明**：本机无 LibreOffice / Word COM，渲染与重算通过注入导出器与降级路径测试；真实转换需在带转换器的机器上做验收。
