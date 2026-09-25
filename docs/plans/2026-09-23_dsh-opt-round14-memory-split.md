# DSH 对标优化·第十四轮：C1 第一刀——记忆 API 路由组拆分

- **状态**：批次 A 交付中（分支 `feat-dshopt-r14-memory-split`，基线 origin/main 含 R13）
- **系列定位**：`dsh-opt` 对标系列第 14 轮（总账 [dsh-opt-index.md](dsh-opt-index.md)）。
- **上游文档**：round12（B3b）、dsh-opt-index.md 系列路线（C1 条目）
- **对标对象**：DeepSeek Harness Capability Seam 三角色拆分——路由文件只做
  HTTP↔domain 翻译，装配收进独立层；棘轮"只许缩小不许增长"。

## 0. 结论速览

`legacy_routes.py`（基线 5553 行，全库最大文件）按域切第一刀：**记忆 API
路由组**（12 端点 + 请求模型 + 序列化助手，原 4780-5551 行尾段）迁出为
两个文件：

- `backend/api/legacy_memory_routes.py`（601 行）：记忆核心（save/search/
  delete/diagnostics/recent-writes/undo-write）+ 用户/项目画像 CRUD +
  `with_db_lock`（镜像 orch_routes 模式，`_SQLITE_LOCK` 经 import 共享
  同一对象，锁语义不变）；
- `backend/api/legacy_memory_list_routes.py`（550 行）：memory/list +
  memory/summaries + enrich 助手 + 分页常量。

`legacy_routes.py` 收缩到 4783 行（棘轮 **5553 → 4783，净 -770**），
经 include_router 链挂载——**路径、前缀、行为零变更**，前端零感知。
既有幂等 DDL 与防御块不动；下一刀（profiles/skills 组）按同模式续切。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| C1a | legacy_routes.py 5553 行：路由+装配+域逻辑混杂 | 全库最大文件、棘轮榜首 | dsh：路由=HTTP 翻译，域=seam | **P1** |

## 2. 设计（批次 A：C1a）

- **切割边界**：`# ==================== 记忆 API ====================`
  （4780）至文件尾 orch include 之前（5551）整块迁出；`with_db_lock`
  按 D3 模式在新文件重建（`make_with_db_lock(globals())` + import 共享
  `_SQLITE_LOCK`）；`_MEMORY_LIST_*` 分页常量随 list/summaries 片段入
  第二文件。
- **双文件**：核心 601 行 / list+summaries 550 行，均低于 800 新文件上限；
  两 router 均由 legacy_router include（13 + 2 = 15 条 /memory 路径全可达）。
- **测试迁移**：`test_memory_routes.py` / `test_memory_diagnostics.py` 的
  `from backend.api import legacy_routes` 改指向
  `legacy_memory_routes`（其余测试零感知）。

## 3. 批次 A 实施与验证记录

- **抽取**：`legacy_memory_routes.py`（601 行）/ 
  `legacy_memory_list_routes.py`（550 行）；`with_db_lock` 镜像
  orch_routes 模式（make_with_db_lock + import 共享 _SQLITE_LOCK）；
  `_MEMORY_LIST_*` 常量随 list 片段入第二文件。
- **挂载**：legacy_routes 尾部双 include（同 orch_routes 模式）；
  15 条 /memory 路径经链全部可达（脚本断言）。
- **测试迁移**：test_memory_routes / test_memory_diagnostics 的导入
  改指 legacy_memory_routes（2 文件 11 处引用）；其余测试零感知。
- **验证**：memory_routes 7 例 + memory_diagnostics + perf 全套 8 例
  全绿；ruff 全过（--fix 修剪 58 个孤儿导入）；py38 AST 3.8 通过；
  baseline 同步（legacy_routes 4783，净 -770）。
- **流程教训**：本轮实施误在主仓库工作区直接进行——发现后用
  `git checkout -b` 将未提交改动整体迁入 feature 分支（工作区改动
  随 checkout 迁移），主仓库 main 未受污染。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

- **main**：（PR 占位）
- **win7 对齐**：（cherry-pick 占位；前后端同树）
