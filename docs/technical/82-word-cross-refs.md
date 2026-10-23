# 82 — 交叉引用占位符（{{fig:}}/{{tbl:}} → 图N/表N，Round 45）

> 日期: 2026-09-18 · 分支: `feat/cross-ref-placeholders`
> 系列: Word/Office 写作能力增强第 46 轮

## 1. 定位

正文"如图 N 所示"的 N 由引擎按题注顺序分配——手写编号在插图增删后
错位。本轮引入交叉引用占位符：段落文本写 `{{fig:架构图}}` /
`{{tbl:汇总表}}`（按题注文本匹配），生成时替换为"图N"/"表N"；未命中
任何题注即生成失败（fail-fast，与 citations 未定义 key 同哲学）。

## 2. 变更

- `word.py`：
  - 题注编号映射前置（`figure_caption_numbers` / `table_caption_numbers`
    ，caption → 首个编号，跨段落位置 + 文末钳制两段循环与正文
    figure_no 同一守卫）；R42 图/表目录条目改为复用映射（dict 插入序
    = 文档序），编号三处（正文题注/目录条目/交叉引用）严格一致；
  - `_resolve_cross_refs`：正则 `\{\{(fig|tbl):([^}]+)\}\}` → 图N/表N，
    未命中抛 ValueError（外层统一包 OfficeGenerateError）；
  - 正文段落循环：bullet/numbered/普通段与标题分支全部经解析后落笔。
- `word_lint.py`：新规则 `cross_ref/residue`——正文残留 `{{fig:` /
  `{{tbl:` 占位符（手工编辑/外部导入场景的死文本）→ error；复用
  R44 的域缓存跳过迭代器（目录缓存行不误报）。
- 契约：office_create schema content 描述补占位符语法；SKILL.md
  step 3 补"不要手编 N"写法；types.ts 零变更（text 仍为 string）。

## 3. Win7 对齐与测试

新功能不 cherry-pick 到 release/win7（31-win7-lts.md §2）；零新增依赖。
`test_word_cross_refs.py` 4 项：替换端到端（含全角间距与无残渍）、
未命中 fail-fast、无题注不占号（第二张图是图1）、残留 lint 检出。
word 家族回归 + ruff 全绿。
