# 59 — 写作技能（Round 11：paper-writing / report-writing SKILL.md）

> 日期: 2026-09-12 · 分支: `feat/writing-skills-r11` · 方案:
> `docs/plans/2026-09-12_writing-skills-r11-plan.md`
> 系列: Word 写作能力增强收官轮（R7 版式 #622 / R8 内容元素 #635 /
> R9 引用 #640 / R10 Linter #647）

## 1. 定位

Round 7-10 建成了"版式即配置 → 内容元素 → 引用 → 校验"的**工具面**，
但用户入口是散装工具。本轮用 SKILL.md 技能层（`when_to_use` 语义自动
激活，academic-search shipped 先例）把全栈能力封装成两个可发现工作流：
`paper-writing`（期刊论文）与 `report-writing`（项目文档/内部资料）——
正对"项目文档、期刊论文、内部资料写作"的原始场景。

## 2. 两个技能的工作流

**paper-writing**（五步，正文写明"不要跳步"）：
大纲确认（ask_user_question，格式要求→format_spec）→ 分章起草
（write_file 落盘，长文不占上下文）→ 文献准备（office_parse_bibtex 解析
.bib / 手工条目；引用标记不手写，段落 citations 填 key）→ office_create
一次成形（references + format_spec.numbering + bibliography）→
office_lint_word 自检修复到 ok。

**report-writing**（五步）：格式来源三选一（单位模板→改道
office_analyze/fill_word_template；明示要求→format_spec；无要求→默认）
→ 大纲与术语表 → 分章起草（图表占位转 images.caption / tables 三线表）
→ office_create 新建 / office_update 修订（dry_run 预览 + 快照回滚）→
office_lint_word 自检交付。

## 3. 触发设计与实现说明

- `triggers` 留空（沿用 academic-search 哲学：靠 `when_to_use` 语义判断，
  把关键中文短语留给用户派生自定义）；
- `when_to_use` 的**引号短语是唯一可靠触发词汇**（auto_activation 的
  `_matches` 是"触发短语 ⊆ 消息"子串匹配）——两个技能各自精选了
  "写论文/期刊投稿/毕业论文"与"写报告/项目文档/技术报告/阶段报告"等
  用户真实会说的短语，并经激活测试锁定；
- 零 Python 代码路径变更：shipped 目录扫描自动装载新技能，与
  academic-search 共存无冲突。

## 4. Win7 对齐与测试

纯 Markdown + 测试，零新增依赖；不 cherry-pick（31-win7-lts.md §2）。
`tests/unit/test_shipped_writing_skills.py` 11 项：shipped 目录发现、
frontmatter 合法性、无名字冲突、正文覆盖关键工具面、激活命中/不误触。
技能回归套件（auto_activation/frontmatter/integration）除本地 Windows
环境预存在问题（干净 main 同样失败，CI ubuntu 通过）外全绿。

## 5. 系列收官与 Round 12 候选

R7-R11 五轮：**版式可控 → 元素齐全 → 引用闭环 → 产出可校验 → 流程可发现**，
"项目文档/期刊论文/内部资料"写作场景的工具面与工作流均已交付。
Round 12 候选：lint 自动修复（office_update 闭环）、journal 接入引用引擎、
Pillow 图片管线、TOC 域 + COM 收尾。
