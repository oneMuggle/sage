# DSH 对标优化·第三十二轮：C2g——非流式聊天/attach/中断/steer/进化/learn 路由组迁出

- **状态**：批次 A 交付中（分支 `feat-dshopt-r32-c2g-routes`，基线 origin/main 含 R31）

## 0. 结论速览

7 个端点（/chat、/chat/stream/active、/chat/stream/{id} attach、
/interrupt、/chat/steer、/evolution/logs、/learn，约 333 行）迁出至
`backend/api/legacy_chat_routes.py`。/chat/stream producer 留
legacy_routes。路径/行为零变更，include 模式同前。

legacy_routes 2619 → 2359 行（C 系列 5463 → 2359）。

## 验证

- 7 路径注册冒烟；tests/api 230 例 + chat 流/中断/steer 回归 25 例全绿
- ruff 通过；py38 AST 3.8 兼容；baseline 无需更新（缩行）
