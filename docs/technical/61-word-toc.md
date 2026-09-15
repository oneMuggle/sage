# 61 — Word 目录域 + 写作技能接入自动修复（Round 13）

> 日期: 2026-09-12 · 分支: `feat/word-toc-field` · 方案:
> `docs/plans/2026-09-12_word-toc-r13-plan.md`
> 系列: Word 写作能力增强（R7 版式 #622 / R8 内容元素 #635 / R9 引用
> #640 / R10 Linter #647 / R11 写作技能 #661 / R12 自动修复 #665）

## 1. TOC 目录域（论文/长文档刚需）

`format_spec.toc`（`WordTocSpec`）：`heading_text`（默认"目录"）/
`levels`（默认 "1-3"，正则约束 + 起止顺序校验）/`placeholder_text`
（域未更新时的占位提示）。

生成流程在标题之后、正文之前插入：**目录标题段**（加粗居中普通段落，
非 Heading 样式——避免被 TOC 域自我收录、也不参与多级标题编号检查，
与参考文献节标题同理）+ **TOC 域**（`w:fldSimple`，instr 形如
`TOC \o "1-3" \h \z \u`，占位 run 提示更新域）+ **分页**（正文另起一页）。

域内容由 Word/WPS/LibreOffice 按标题样式渲染（打开后更新域/F9）——
与"标题编号交给引擎、生成器不算目录"同一思路；占位提示避免用户把
未更新域误认为失败。Linter 对偶新增 `toc/presence` 规则（要求有目录
时文档前部必须存在 instr=TOC 的域）。

## 2. 写作技能接入自动修复（Round 12 收口）

paper-writing / report-writing 的 `allowed-tools` 与第 5 步"自检与修复"
补入 `office_repair_word`：样式/编号/题注类违规先自动修复（默认
-repaired.docx 新文件）再复检；citation 类违规人工处理——形成
"自检 → 自动修复 → 复检"完整闭环。测试锁定两个 SKILL.md 正文必须
包含该工具（防回归）。

## 3. Win7 对齐与测试

零新增依赖、零 Python 工具面变更（TOC 走 office_create 的 format_spec，
无三件套变更）；不 cherry-pick（31-win7-lts.md §2）。
`tests/integration/test_office_word_toc.py` 7 项：插入位置（标题后正文
前）、instr 级别映射与自定义占位、toc=None 零变化、levels 校验（起止
顺序/下界）、Linter 正反例、技能正文防回归。

## 4. 系列状态（R7-R13）与 Round 14 候选

七轮交付：版式可控 → 元素齐全 → 引用闭环 → 产出可校验 → 流程可发现 →
违规可自愈 → **长文档目录就位**。Round 14 候选：TOC 域更新收尾
（LibreOffice headless 宏 / Word COM 可选通道）、journal 接入引用引擎、
Pillow 图片管线。
