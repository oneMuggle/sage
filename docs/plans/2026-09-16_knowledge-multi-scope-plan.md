# P13 计划——知识搜索范围支持"全部最近 wiki 项目"（多根合并）

> 日期: 2026-09-16 · 基线: main `bd6ce80a`
> 分支: `feat/knowledge-multi-scope` · 前置: P9 #818（单项目范围）

## 1. 缺口

P9 的知识范围是**单选**：多 wiki 项目并行时，用户要么逐次切换范围，
要么接受"只搜最近一个"。跨项目找一篇记得大概内容的文档是高频真实场景。

## 2. 方案

- **后端**：`knowledge_project` 支持**逗号分隔多根**
  `pathA,pathB`——逐根经 `_resolve_knowledge_scope` 授权（任一未授权
  → 403 fail-closed，与单根一致）；`_search_knowledge` 对多根逐个
  `search_wiki`（每根 limit），合并后按 score 降序、按结果路径去重，
  截取总 limit。单值（无逗号）行为与 P9 完全一致（向后兼容）。
- **前端**：范围分组新增"全部最近 wiki 项目"选项——值为全部
  wikiRecents 的逗号拼接（≤5）；单项目选项语义不变；当前范围以 ✓
  标记；localStorage 键不变（值变为逗号串即多根）。

## 3. 明确不改

- 默认域（未显式选择）仍为 recents[0]；
- 不做多选 checkbox UI（"全部"已覆盖跨项目需求，checkbox 引入
  cmdk 选中态管理复杂度不成比例）；
- 授权失败不降级放行（fail-closed）。

## 4. 测试

- 后端：3 个 wiki 项目各含唯一词 → `knowledge_project=A,C` 同时命中
  两根且排序合理；列表含未授权根 → 403；单根参数行为不变（P9 回归）。
- 前端：选择"全部"→ localStorage 为逗号拼接、请求携带多根参数；
  P9 既有用例回归。

## 5. win7 对齐

search_routes / CommandPalette 均为小块追加（win7 已由 #850 对齐到含
P9 的状态——`knowledge_project` 单值语义在 win7 与 main 一致，本批
cherry-pick 机械）。py3.8 兼容（typing.List）。

## 实施补充

- `_search_knowledge` 多根 roots 以 `Path` 包装（search_wiki 内部做
  `project_root / "wiki"` 拼接，str 会 TypeError——集成测试捕获）；
- 合并去重键 = `project_root::path`（跨根同名相对路径不互斥）；
- P9 既有单根用例回归通过（向后兼容验证）。
