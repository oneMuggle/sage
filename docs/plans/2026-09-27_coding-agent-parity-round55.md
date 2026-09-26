# 编码代理对标差距分析·第五十五轮：单 run 详情 API 客户端补全（RD25）

- **状态**：批次 A 交付中（分支 `feat-parity-r55-batch-a`，基线 origin/main 9ad0b9a7）
- **上游文档**：R32（RT24 持久化）、R49（RT26 retry_of）
- **编号约定**：延续 RD 系

## 0. 结论速览

后端 `GET /orch/runs/{run_id}` 已存在但前端客户端未暴露——SessionRunHistory
点击单个 run 后无法按需刷新详情。本轮补全 electron 桥接路由 + client 方法。

## 1. 差距矩阵

| # | 差距 | 证据 | 优先级 |
| --- | --- | --- | --- |
| RD25 | getRun 客户端缺失 | orchRunClient 无 getRun 方法 | **P3** |

## 2. 设计（批次 A：RD25）

- electron/commands.ts 增 `orchestration_get_run` GET 路由。
- orchRunClient 增 `getRun(runId)` 方法。
- 后端端点已存在（orch_routes.py `get_run`），零后端改动。

## 3. 批次 A 实施与验证记录

- electron/commands.ts 增 `orchestration_get_run` 路由。
- orchRunClient 增 `getRun(runId)` 方法。
- 验证：tsc/eslint 干净；orchRunClient 套件 1 例全绿。

## 4. 批次 B

（本轮为单批次交付，无批次 B）

## 5. 交付记录

（交付后回填）
