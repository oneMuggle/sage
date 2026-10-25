# 编码代理对标差距分析·第七十五轮：todo 路由测试补齐（双分支）

- **状态**：单批次交付（分支 `feat-parity-r75`，基线 origin/main 444c4c169）
- **上游文档**：round66 §4 候选清单（延续）
- **对标对象**：r 系列测试补齐惯例，本轮自主选题

## 0. 结论速览

R74 收口后复扫：main 零新增提交；DSH-R31 的 win7 cherry-pick 尚未出现
（并行会话自有节奏，届时跳过）。继续消化候选清单，本轮选定
**todo_router.py（243 行，9 端点，路由工厂模式）**——`build_router`
依赖注入天然可测；update 的 `exclude_unset` 三态语义、`status=all`
逃生口、cancel 后行消失的 404 防御是关键行为，此前无直接单测
（既有覆盖仅 todo_service 服务层）。win7 模块逐行同源（243 行）。

## 1. 差距矩阵

| # | 差距 | 证据 | 优先级 |
| --- | --- | --- | --- |
| T-10 | todo_router 9 端点无单测 | 三态清空/status=all 逃生口/防御 404 零覆盖 | **P2** |
| —— | DSH-R31 win7 cherry-pick 未出现 | 并行会话自有节奏 | 跳过 |

## 2. 设计

`backend/tests/unit/api/test_todo_router.py`（18 例）：调用
`build_router(fake_get_service)` 后从 `router.routes` 取出闭包端点
（(method, path) 索引）直接调用；Query 默认参数显式传纯值（R66 沉淀）。

- 清单：分页映射、`status=all` → `include_completed=True` 逃生口。
- create 字段透传（含 recurrence_rule）；summary/stats 透传。
- get/update/delete/complete/cancel 命中与 404。
- update `model_dump(exclude_unset=True)` 三态语义（显式 null 清空、
  未提交键不动）。
- cancel 成功但重取行消失（并发删除）→ 404 防御。
- 载荷校验：priority/status 枚举、extra=forbid、空 title。

## 3. 实施与验证记录

- 18 例全绿（本地 3.12）；ruff 本地预检通过（PT018 前置拆分）；
  py38_hazard_scan 0 命中；全量 collect 11588 例（8 个 mcp 收集错误
  为已知本地环境伪影）。

## 4. 批次 B

（剩余候选：search/project/web_access/wiki/zotero/gateway 等路由，
后续轮次分批。）

## 5. 交付记录

- **批次 A（main）**：#1815 `a2f823ab`
  - 内容：test_todo_router.py（18 例）+ 本文档。CI 一次全绿
    （16 checks 0 failure，含 Dependency audit）。
- **批次 B（win7 对齐）**：#1818 `23495ebc`
  - 测试文件 + 文档同步至 win7（模块逐行同源）；CI 一次全绿
    （Win7 LTS py38 job 过）。
- **总账回填**：即本提交。
