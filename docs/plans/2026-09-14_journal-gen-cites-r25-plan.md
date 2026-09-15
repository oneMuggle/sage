# journal generate 通路接入引用引擎 Round 25 实施计划

> 日期: 2026-09-14 · 分支: `feat/journal-generate-citations` · 基于 main @ f42a48a2
> 系列: Word/Office 写作能力增强第 16 轮（R21 fill 通路 #714 的 generate 延伸）
> Win7 对齐: **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
> 零新增依赖。

## 背景（Round 24 合并后再分析）

R21 打通了 journal `fill_from_content` 通路的结构化文献（`_write_sections`
的 R21 分支）。`generate_article`（LLM 自纠生成模式）的 prompt schema 仍是
`references: [str]` 纯文本——LLM 生成的文献没有编号与格式保证。本轮把
generate 通路也接入 R9 引擎：**prompt schema 增加 structured_references
结构化文献说明**，LLM 返回的条目经 JournalContent 校验后走同一条
`_write_sections` R21 分支格式化。两轮自纠机制天然兜底 LLM 产出次品
（校验失败 → 下一轮修正）。

## 批次任务

### A. prompt schema 扩展（generator.py `generate_article`）

system_prompt 的 JSON schema 增加：
`"structured_references": [{"key": str, "ref_type": "journal|book|…",
"title": str, "authors": [str], "year": str, "source": str, …}]`，
并指示：为真实文献尽量产出结构化条目（key 唯一），不要手写 [N] 编号
（引擎自动加）。

### B. 测试（test_llm_generator.py 追加）

- LLM 返回带 structured_references 的 content → 生成 docx 的参考文献段
  出现 `[1] 作者. 题名[J]. …` 格式化文本（GB/T 类型码）
- 无 structured_references 的既有用例零变化（锁定）

## Round 26 候选

- TOC 域更新收尾（headless/COM）
- Word 横排分节
- Pillow 进 main requirements
