# 交叉引用占位符（{{fig:}}/{{tbl:}} → 图N/表N）Round 45 实施计划

> 日期: 2026-09-18 · 分支: `feat/cross-ref-placeholders` · 基于 main @ 139e905d
> 系列: Word/Office 写作能力增强第 46 轮
> Win7 对齐: **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
> 依赖: 零新增。

## 背景

正文里"如图 N 所示"的 N 由引擎按题注顺序分配——LLM/用户手写编号在
插图增删后会错位。本轮引入交叉引用占位符：段落文本写 `{{fig:架构图}}` /
`{{tbl:汇总表}}`（按题注文本匹配），生成时替换为"图N"/"表N"；未命中
任何题注即生成失败（fail-fast，与 citations 未定义 key 同哲学）。

## 批次任务

### A. word.py

- 题注编号映射前置（bucketing 区）：`figure_caption_numbers` /
  `table_caption_numbers`（caption → 首个编号；跨段落位置 + 文末钳制
  两段循环与正文 figure_no 同一守卫）；
- R42 图/表目录条目改为复用映射（文档序 = dict 插入序）；
- `_resolve_cross_refs(text, ...)`：正则 `\{\{(fig|tbl):([^}]+)\}\}` →
  图N/表N，未命中抛 ValueError（外层统一包 OfficeGenerateError）；
- 正文段落循环：`para.text` 用点改为解析后的 body_text（标题分支同步）。

### B. word_lint.py

- 新规则 `cross_ref/residue`：正文存在未解析占位符（`{{fig:`/`{{tbl:`
  残留——手工编辑/旧文档场景）→ error；复用域缓存跳过迭代器。

### C. 契约与文档

- office_create schema：content 描述补占位符语法；
- SKILL.md step 3 补"如图 N 所示"占位符写法；
- types.ts 零变更（text 仍为 string）；
- 技术文档 82 号、README 索引、CHANGELOG。

## 验证

- 新测试：替换端到端、fail-fast、residue lint；word 家族回归 + ruff。

## Round 46 候选

- REF 域升级（占位符 → Word 交叉引用域 + 题注书签）
- Word COM 前端徽章细分（需前端协调）
