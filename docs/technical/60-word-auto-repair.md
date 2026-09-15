# 60 — Word 格式自动修复（Round 12：lint → repair → 复检闭环）

> 日期: 2026-09-12 · 分支: `feat/word-lint-repair` · 方案:
> `docs/plans/2026-09-12_word-lint-repair-r12-plan.md`
> 系列: Word 写作能力增强（R7 版式 #622 / R8 内容元素 #635 / R9 引用
> #640 / R10 Linter #647 / R11 写作技能 #661）

## 1. 定位

Round 10 的 office_lint_word 能"查出违规 + 给修复建议"，修复仍需逐条
手工。本轮补**确定性自动修复** `repair_docx(path, spec)`，闭环升级为
**检测 → 修复 → 复检**。

## 2. 修复策略（按违规家族）

| 家族 | 修复方式 | 复用 |
|---|---|---|
| page/*、body/*、headings/*、title/*、header/text、footer/page_number | 对已加载文档再应用一次 FormatSpec（幂等） | `word_layout.apply_format_spec` |
| numbering/sequence | 按正文 Heading 1-3 出现顺序重算前缀（剥旧前缀再写入；参考文献节标题跳过） | 与生成器/Linter 同一编号算法 |
| caption/sequence | 图/表题注按出现顺序重排 "图N　/ 表N　" 编号 | 正则重排 |
| citation/coverage | **不可自动修**（语义判断），保留在复检结果 | — |

安全语义：默认写**新文件** `<stem>-repaired.docx`（绝不覆盖原文件）；
`overwrite=True` 时临时名 + `Path.replace` 原子替换。修复后自动复检，
`remaining` 携带未消除违规。`para.text` 重写会把标题/题注段合并为单
run——格式来自样式定义，重写不损失外观（docstring 已注明）。

## 3. 接入面

REST `POST /office/word/repair`（围栏/尺寸上限同 lint）+ LLM 工具
`office_repair_word`（**WRITE_LOCAL** + `requires_tool_context=True`，
围栏与白名单对齐 office_lint_word）。三件套一次做齐：tool_names 登记、
profiles 可见性（WRITE_LOCAL 且需上下文 → 未绑定隐藏）、writer profile
工具面与指南。

## 4. Win7 对齐与测试

零新增依赖；不 cherry-pick（31-win7-lts.md §2）。
`tests/integration/test_office_word_repair.py` 10 项：全违规样本修复到
复检 ok、新文件/原地两种语义、合规文档 no-op、编号/题注重排（生成后
XML 级破坏再修，匹配真实用户改动场景）、citation/coverage 保留、REST
+ 工具 roundtrip（围栏拒绝/上下文 fail-closed）、防漂移三件套。

## 5. 系列状态（R7-R12）与 Round 13 候选

六轮交付：版式可控 → 元素齐全 → 引用闭环 → 产出可校验 → 流程可发现 →
**违规可自愈**。Round 13 候选：journal 接入引用引擎、Pillow 图片管线、
TOC 域 + COM 收尾、report-writing 技能接入 office_repair_word。
