# DSH 对标优化·第十七轮：测试稳定化 + 总账收敛

- **状态**：批次 A 交付中（分支 `feat-dshopt-r17-stabilize`，基线 origin/main 含 R16）
- **系列定位**：`dsh-opt` 对标系列第 17 轮（总账 [dsh-opt-index.md](dsh-opt-index.md)）。

## 0. 结论速览

C1 三刀（R14/R15/R16）合入后，legacy_routes 的 async 路由 handler 数从
7 降至 3（chat/chat_stream_create/chat_stream_attach），但 async safety
守卫测试仍断言 7（R14 前的旧值），legacy smoke 中的 r38 测试也因
TM2 的 context_pressure 事件干扰而 flake。本轮同步修复这两个测试
并回填总账 R11-R16 全部 SHA。

## 变更

1. async safety 守卫测试：合并 memory 双模块 + skills 模块扫描，
   计数从 7 修正为 6（legacy 3 + skills 3）
2. r38 skill_activation 测试：过滤 context_pressure 事件（TM2 新增）
3. dsh-opt-index.md 总账回填 R11-R16 全部双分支 SHA

## 验证

- async safety 4 例全绿 + r38 3 例全绿
- ruff 全过
