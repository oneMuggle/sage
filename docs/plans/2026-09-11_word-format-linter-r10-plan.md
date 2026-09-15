# Word 格式 Linter Round 10 实施计划（对照 FormatSpec 校验产物 + 修复建议）

> 日期: 2026-09-11 · 分支: `feat/word-format-linter` · 基于 main @ 8a32d912
> 系列: Word 写作能力增强 P3（Round 7 版式 #622 / Round 8 内容元素 #635 /
> Round 9 引用 #640 之后的收口轮）
> Win7 对齐: **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
> 零新增依赖（纯 python-docx 回读 + 确定性规则）。
> 冲突规避: 不触碰 `backend/office/journal/`（其 validate 面向期刊 spec，
> 本轮 Linter 面向 FormatSpec，规则空间不重叠；集成留后续协调）。
> **流程教训（Round 9）**: 新增 LLM 工具必须同步 ① `domain/tool_names.py`
> 登记、② `test_profiles_office_tools.py` 可见性清单、③ writer profile
> 工具面。本轮在三处一次性做齐。

## 背景（Round 9 合并后再分析）

Round 7-9 建立了"版式即配置 → 内容元素 → 引用"的生成侧闭环，但**校验侧**
仍是空白：生成的 docx 是否真的符合 FormatSpec？用户拿来的旧文档是否符合
单位的格式要求？目前只能靠人眼或 journal validate（面向期刊 spec）。
本轮补齐 **docx 格式 Linter**：对照 FormatSpec 逐条校验任意 .docx，输出
带严重级与修复建议的违规清单——闭合"生成→校验"，也是后续自动修复
（Round 11 候选）的地基。

## 批次任务

### A. `backend/office/word_lint.py`（新，纯回读零写入）

`lint_docx(path, spec: WordFormatSpec) -> WordLintResult`：

- **page**：页边距（±0.05cm 容差，twips 取整）/ 纸张尺寸 / 横竖向
- **body**：Normal 样式字号 / 行距倍数 / 首行缩进（±0.05cm）
- **headings**：Title 与 Heading 1-3 的字号 / 加粗 / 颜色（style 层回读）
- **header/footer**：页眉文本一致性；footer 是否含 PAGE 域
  （`w:fldSimple[@w:instr='PAGE']`）
- **numbering**（spec.numbering=True 时）：扫描正文 Heading 1-3 段落，
  校验 "N" / "N.M" / "N.M.K" 前缀的连续性与层级合法性（跳号/层级回退
  非法 → error）
- **captions**：扫描 "图N　…" / "表N　…" 段落，编号必须从 1 连续递增
  （跳号 → error）
- **citations**：扫描正文 `[N]` / `[N-M]` 标记，编号必须 ⊆ [1, max] 且
  1..max 全部出现（缺失 → warning——可能是文末表未生成）
- 每条违规：`rule_id`（如 `page/margins`、`caption/sequence`）、
  `severity`（error|warning）、`message`（含实测值 vs 期望值）、
  `fix_hint`（中文修复建议）
- spec 中未提供的项不产生规则（None = 不检查），与生成器对偶
- 结果含 `ok`（无 error 级违规）汇总

### B. 模型 + REST + 工具（一次性三处同步）

- `models.py`: `WordLintIssue`（rule_id/severity/message/fix_hint）+
  `WordLintResult`（ok/issues/checked_rules 计数）+ `WordLintRequest`
  （workspace_path + file_path 受 `path_safety`/`resolve_within` 围栏 +
  format_spec + optional file max size 5MB）
- REST: `POST /office/word/lint`（OfficeParseError/路径越界走既有信封）
- 工具: `office_lint_word`（READ + `requires_tool_context=True`，doc_id /
  file_path 双模式对齐 office_read_pdf 先例）
- **Round 9 教训三件套**：`domain/tool_names.py` OFFICE_TOOLS 登记 +
  `test_profiles_office_tools.py` 可见性清单（requires_tool_context=True
  → 未绑定隐藏）+ writer profile 工具面与指南

### C. 测试（`backend/tests/unit/office/test_word_lint.py` +
`backend/tests/integration/test_office_word_lint.py`）

- 单元：对 generate_docx 产物逐规则正/反断言（合规零违规；改边距/字号/
  行距/删页码域/跳号题注/断号引用各产生对应 issue 与 fix_hint）
- 集成：REST route + 工具 roundtrip + tool_names/profiles 门禁三件套 +
  "spec 为空 → 零规则零违规"

## Round 11 候选

- 自动修复（lint 违规 → office_update 修复动作）
- journal fill_from_content 接入引用引擎
- `paper-writing` / `report-writing` SKILL.md 技能
- Pillow 图片管线 / TOC 域 + Word COM 收尾
