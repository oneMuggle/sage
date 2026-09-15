# 写作技能 Round 11 实施计划（paper-writing / report-writing SKILL.md）

> 日期: 2026-09-12 · 分支: `feat/writing-skills-r11` · 基于 main @ d2865fb7
> 系列: Word 写作能力增强收官轮（Round 7 版式 #622 / R8 内容元素 #635 /
> R9 引用 #640 / R10 Linter #647 之后，把全栈能力封装为 Agent 可发现的工作流）
> Win7 对齐: **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
> 纯 Markdown + 测试，零 Python 代码路径变更、零新增依赖。
> 冲突规避: 不触碰 journal/curator/gateway 区域。

## 背景（Round 10 合并后再分析）

Round 7-10 建成了"版式即配置 → 内容元素 → 引用 → 校验"的**工具面**闭环，
但面向用户的入口仍是一盘散工具：LLM 需要在没有流程指引的情况下自行拼装
office_create 的 format_spec / references / citations / office_lint_word。
SKILL.md 技能层（when_to_use 语义自动激活）是把这些能力组织成**可发现
工作流**的既定机制（academic-search shipped 先例）。本轮补两个 shipped
写作技能，正对原始场景"项目文档、期刊论文、内部资料写作"。

## 批次任务

### A. `backend/skills/skill_md/shipped/paper-writing/SKILL.md`（新）

期刊论文写作工作流：大纲确认（ask_user_question）→ 分章起草
（write_file 落盘 markdown，产出不占上下文）→ 文献获取
（office_parse_bibtex 解析 .bib / 手工条目）→ office_create 生成 docx
（references + 段落 citations + format_spec.numbering + bibliography，
标题不手写编号）→ office_lint_word 自检 → 修复迭代。
allowed-tools: write_file / office_create / office_parse_bibtex /
office_lint_word / ask_user_question。

### B. `backend/skills/skill_md/shipped/report-writing/SKILL.md`（新）

项目文档/内部资料工作流：格式来源三选一（用户单位模板 docxtpl 填充 /
format_spec 显式规范 / 默认版式）→ 大纲与术语表 → 分章起草 → 图表题注
与三线表 → office_create/office_update 生成与修订 → office_lint_word
自检 → 快照回滚兜底（office_restore）。
allowed-tools: write_file / office_list / office_read / office_create /
office_update / office_lint_word / ask_user_question。

### C. 触发设计

when_to_use 覆盖"写论文 / 期刊投稿 / 毕业论文 / 写报告 / 项目文档 /
技术报告 / 内部资料 / 需求文档"等表达；triggers 留空（沿用 academic-search
哲学：靠语义判断，把关键短语留给用户自定义派生）。两个技能与 builtin
WriterSkill 的轨道关系在文档中说明（WriterSkill 产纯文本；本技能走
office 工具面产正式文档）。

### D. 测试（`backend/tests/unit/test_shipped_writing_skills.py`）

- shipped 目录扫描装载：两个新技能被 SkillMdHotLoader 发现，frontmatter
  解析通过（name/when_to_use/allowed-tools 合法）
- auto_activation：论文类消息命中 paper-writing、报告类消息命中
  report-writing、无关消息不误触
- 防回归：与既有 shipped 技能（academic-search）共存无名字冲突

## Round 12 候选

- lint 违规自动修复（office_lint_word → office_update 修复动作闭环）
- journal fill_from_content 接入引用引擎（需与 journal 工作流协调）
- Pillow 图片管线（压缩/转格式，main 通道懒加载）
- TOC 域插入 + Word COM/LibreOffice 域更新收尾
