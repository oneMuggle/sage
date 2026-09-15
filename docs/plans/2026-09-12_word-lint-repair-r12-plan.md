# Word 格式自动修复 Round 12 实施计划（lint → repair → 复检闭环）

> 日期: 2026-09-12 · 分支: `feat/word-lint-repair` · 基于 main @ aa3edff0
> 系列: Word 写作能力增强（R7 版式 #622 / R8 内容元素 #635 / R9 引用
> #640 / R10 Linter #647 / R11 写作技能 #661 之后）
> Win7 对齐: **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
> 零新增依赖（复用 word_layout 既有 applier + 手写编号/题注重排）。
> 冲突规避: 不触碰 journal/curator/gateway 区域。
> **三件套清单（R9/R10 固化）**: tool_names 登记 + profiles 可见性 +
> writer profile 工具面，一次做齐。

## 背景（Round 11 合并后再分析）

Round 10 的 office_lint_word 能"查出违规 + 给修复建议"，但修复仍靠人/LLM
逐条手工执行。本轮补**确定性自动修复**：`repair_docx(path, spec)` 在
同一 FormatSpec 下把可机械修复的违规直接改掉——样式/页面类修复直接
复用 `word_layout.apply_format_spec`（对已加载文档再应用一次即是修复），
编号/题注类走确定性的文本前缀重排；语义类（citation/coverage）不可
自动修，保持报告。修复后自动复检（lint）闭环验证。

## 批次任务

### A. `backend/office/word_repair.py`（新）

`repair_docx(path, spec) -> WordRepairResult`：

- **样式/页面组**（复用 word_layout）：apply_format_spec 修复
  page/margins/size/orientation、body（Normal）、title/headings 样式、
  header 文本、footer PAGE 域
- **编号组**（确定性重排）：numbering=True 时按文档内 Heading 1-3 出现
  顺序重算前缀——剥离旧数字前缀、写入正确前缀（run 级文本重写）
- **题注组**：图/表题注按出现顺序重排 "图N　/ 表N　" 编号（保留其余
  文本）
- **语义组**：citation/coverage 不修复，保留在复检结果中
- **安全语义**：默认写**新文件** `<stem>-repaired.docx`（绝不覆盖原
  文件）；`overwrite=true` 时经临时名 + `os.replace` 原子替换原文件
- 修复后自动 `lint_docx` 复检，返回 repaired_rules / remaining lint

### B. 模型 + REST + 工具（三件套一次做齐）

- `models.py`: `WordRepairResult`（ok/repaired_rules/remaining/
  output_path）+ `WordRepairRequest`（workspace_path + file_path +
  format_spec + overwrite=false 默认 + max_size_bytes）
- REST: `POST /office/word/repair`（围栏同 lint）
- 工具: `office_repair_word`（**WRITE_LOCAL**（写盘）+
  `requires_tool_context=True`，file_path 绝对路径 + .docx 白名单 +
  `_enforce_workspace`）
- 三件套: `domain/tool_names.py` 登记 + `test_profiles_office_tools`
  可见性（WRITE_LOCAL 且 requires_tool_context=True → 未绑定隐藏）+
  writer profile 工具面/指南

### C. 测试（`backend/tests/integration/test_office_word_repair.py`）

- 全违规样本（错边距/错字号/删页码域/断编号/跳号题注）→ 修复 →
  复检 ok + repaired_rules 断言
- 默认产出 `-repaired.docx` 新文件、原文件不动；overwrite=true 原地
  原子替换
- citation/coverage 保留为 remaining
- REST roundtrip + 工具 roundtrip（含无上下文 fail-closed、围栏拒绝）
- 防漂移三件套断言

## Round 13 候选

- journal fill_from_content 接入引用引擎（需与 journal 工作流协调）
- Pillow 图片管线（压缩/转格式，main 通道懒加载）
- TOC 域插入 + Word COM/LibreOffice 域更新收尾
- report-writing 技能接入 office_repair_word
