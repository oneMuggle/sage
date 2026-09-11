# 58 — Word 格式 Linter（Round 10：对照 FormatSpec 校验产物）

> 日期: 2026-09-11 · 分支: `feat/word-format-linter` · 方案:
> `docs/plans/2026-09-11_word-format-linter-r10-plan.md`
> 系列: Word 写作能力增强 P3（Round 7 版式 #622 / Round 8 内容元素
> #635 / Round 9 引用 #640 的收口轮）

## 1. 定位

Round 7-9 建立了"版式即配置 → 内容元素 → 引用"的**生成侧**闭环，本轮补
**校验侧**：`lint_docx(path, spec)` 对照 FormatSpec 逐条校验任意 .docx，
输出带 rule_id / severity / 实测 vs 期望 / 中文 fix_hint 的违规清单——
闭合"生成→校验"环，并为后续自动修复（Round 11 候选）打底。与 journal
validator（#584，面向期刊 spec）规则空间不重叠。

## 2. 规则面（与生成器对偶：spec 未提供的项不产生规则）

| 规则 | 校验内容 |
|---|---|
| page/margins | 页边距 ±0.05cm（twips 取整容差） |
| page/size、page/orientation | 纸张 A4/letter、横竖向 |
| body/font_size、line_spacing、first_line_indent | Normal 样式回读 |
| title/**headings/hN**/{font_size,bold,color} | Title 与 Heading 1-3 样式定义 |
| header/text、footer/page_number | 页眉文本；`w:fldSimple instr=PAGE` 域 |
| numbering/sequence | 正文标题 "N"/"N.M"/"N.M.K" 前缀连续性与层级（跳过参考文献节标题，与生成器行为对偶） |
| caption/sequence | "图N　/ 表N　" 题注从 1 连续递增 |
| citation/coverage | 正文 `[N]`/`[N-M]` 标记覆盖 1..max（缺失 → warning） |

空 spec 恒零违规；`ok` = 无 error 级违规。

## 3. 接入面与 Round 9 流程教训

REST `POST /office/word/lint`（`_validate_file_in_workspace` 围栏 + 尺寸
上限）+ LLM 工具 `office_lint_word`（READ，`requires_tool_context=True`，
`_enforce_workspace` + 绝对路径 + .docx 后缀白名单）。

**Round 9 的 CI 三轮教训固化为本轮清单**：新增 LLM 工具一次性同步
① `domain/tool_names.py` OFFICE_TOOLS 登记；②
`test_profiles_office_tools.py` 可见性清单（primary 19→20、writer
18→19，`requires_tool_context=True` → 未绑定隐藏）；③ writer profile
工具面与指南。

## 4. Win7 对齐与测试

零新增依赖；不 cherry-pick（31-win7-lts.md §2）。
`tests/integration/test_office_word_lint.py` 15 项：合规零违规、空 spec
零规则、各规则族反例（含手工破坏编号/题注/引用标记）、REST roundtrip
（含围栏拒绝）、工具 roundtrip（含上下文 fail-closed）、防漂移三件套。

## 5. 系列（Round 7-10）小结与 Round 11 候选

四轮落地：FormatSpec 版式引擎 → 行内插图/题注/三线表/标题编号 →
GB/T 7714 引用引擎 → 格式 Linter，Word 写作"版式可控、元素齐全、引用
闭环、可校验"。候选：lint 违规自动修复（对接 office_update）、journal
接入引用引擎、paper-writing / report-writing 技能、Pillow 图片管线。
