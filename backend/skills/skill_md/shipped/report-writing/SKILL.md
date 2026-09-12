---
name: report-writing
description: 撰写项目文档/工作报告/内部资料/技术报告的完整工作流——格式来源三选一、大纲与术语表、分章起草、图表题注、docx 生成与格式自检。当用户要写正式项目文档或报告时使用。
license: Apache-2.0
compatibility: 需要 Round 7-10 的 office 工具面（office_create 的 format_spec、office_lint_word、office_update 快照回滚）
when_to_use: 当用户要撰写项目文档、项目总结、内部资料、需求文档、验收文档,或用"写报告""项目报告""阶段报告""写项目文档""项目文档""技术报告""内部资料""项目总结""验收文档"等表达时使用
allowed-tools: write_file office_list office_read office_create office_update office_lint_word office_repair_word ask_user_question
triggers: []
---

# 项目文档 / 报告写作

> shipped 基础版。`triggers` 留空——靠 `when_to_use` 语义判断激活。
> 与 builtin WriterSkill 的关系：WriterSkill 产纯文本；本技能走 office
> 工具面产出**格式合规的正式 docx**（可被 office_restore 回滚）。

## 触发条件

- "写一份项目阶段报告 / 验收文档"
- "把这些材料整理成正式的项目文档"
- "按公司模板写周报/纪要"（→ 走模板填充通路）

## 工作流（五步）

### 1. 格式来源三选一（先问清）

用 `ask_user_question` 确认格式来源：

- **用户单位模板**（.docx 带 {{占位符}}）→ 改走 `office_analyze_word_template`
  + `office_fill_word_template` 填充通路，本技能后续步骤只负责内容起草；
- **明示格式要求**（页边距/字号/行距/页眉/页码）→ 映射进
  `content.format_spec`，继续本工作流；
- **无要求** → 默认版式直接生成。

### 2. 大纲与术语表

确认章节结构与**项目术语表**（专有名词/缩写全称对照）。术语表用
`memory_save` 之外的方式随文档维护（写进草稿文件头部），保证分章起草
时全文术语一致。

### 3. 分章起草（write_file 落盘）

逐章 `write_file` 落盘 markdown（如 `<工作区>/report/03-进度.md`）。
图表描述写成"【图：架构图】说明文字"占位，生成时转为 `images`（配
`caption`，题注自动编号"图N"）与 `tables`（正式数据表用
`style: "three_line"` + `caption`）。

### 4. 生成或修订 docx

- 新文档 → `office_create`（doc_type=word），带 format_spec / 题注 /
  三线表；多级标题编号交给 `format_spec.numbering`，标题文本不手写编号；
- 修订已有文档 → `office_update`（支持 `dry_run=true` 预览变更清单，
  确认后应用；改前自动快照，可 `office_restore` 回滚）。

### 5. 自检与交付（交付前必做）

调 `office_lint_word`（format_spec 与生成时一致），报告违规与修复建议。
- 样式/编号/题注类违规 → `office_repair_word` 自动修复（默认写
  -repaired.docx 新文件；确认无误可 overwrite=true 原地替换），修复后
  自动复检；
- 复检至 `ok=true` 或用户接受。正式交付提醒用户：文档在工作区
`office/word/` 受管目录下，可随时用 office_list / office_read 回看。

## 不做的事（YAGNI）

- ❌ 不替用户编造项目数据（进度/指标一律来自用户材料，缺失就问）
- ❌ 不绕过审批：写工作区外路径（如桌面）让用户确认
- ❌ 不做 PPT（汇报幻灯片场景走 office_create 的 ppt 通路，另行明确需求）
