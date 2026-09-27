# 编码代理对标差距分析·第六十六轮：usage_routes 路由测试补齐（双分支）

- **状态**：单批次交付（分支 `feat-parity-r66`，基线 origin/main 23bc26798）
- **上游文档**：R32（RT24 持久化）、R46（RT25 索引）、R63（RT27 聚合）
- **对标对象**：r 系列测试补齐惯例（r163-r169），本轮自主选题

## 0. 结论速览

R65 收口后 main 零外部漂移（win7 亦无新交付），本轮转为主动差距扫描：
对照 40 个 backend/api 路由模块与 tests/unit/api/ 现有测试文件，发现
**usage_routes.py（321 行 5 端点）完全无单测**——它是 RT24/RT25 用量
持久化的直接出口（U14 徽章、requests 面板、trend 图、CSV 导出），双分支
同源（main 与 win7 均 321 行同端点）。本轮补齐 18 例单测，随后对齐 win7。

## 1. 差距矩阵

| # | 差距 | 证据 | 优先级 |
| --- | --- | --- | --- |
| T-3 | usage_routes 5 端点无单测 | ls-tree 对照：40 路由 25+ 无专属测试 | **P2** |
| —— | 其余 24 个未覆盖路由 | 后续轮次分批（见 §4） | P3 |

## 2. 设计

- `backend/tests/unit/api/test_usage_routes.py`（18 例）：
  - summary/session：tracker 委派与默认 range（monkeypatch 单例）。
  - /requests：分页/排序/session 过滤、known_cost 与 price_snapshot
    语义、字段映射（created_at_iso）、DB 异常降级（error 字段）。
  - /trend：day/hour 桶、cache_hit_rate 派生（eligible=prompt+creation）、
    session 过滤、异常降级。
  - /export.csv：15 列表头、null 成本写空串 + known_cost TRUE/FALSE、
    first_token_ms/latency_ms 空值、session 过滤。
  - DB 层用真实 sqlite3 内存表（schema 对齐 SELECT 列），monkeypatch
    `backend.data.database.get_database`；路由函数直接调用，**所有
    Query 默认参数显式传纯值**（直接调用不走 FastAPI 校验层，
    Query 对象会泄漏进 sqlite 绑定——本地首轮 9 红实证）。

## 3. 实施与验证记录

- 18 例全绿（本地 3.12）；py38_hazard_scan 0 命中（测试将随对齐批次
  上 win7，全 py38 安全写法）；全量 collect-only 11308 例（+18）。
- 本地全量收集存在 8 个 mcp 测试收集错误——经对照实验（移除本文件后
  8 错依旧）确认为本地环境伪影（site-packages 的 mcp SDK 遮蔽模块名），
  与本批次无关，CI 环境无此现象。

## 4. 批次 B

（后续轮次候选：artifact/media/metrics/system/prompt/question/search/
project/theme/todo/web_access/wiki/zotero/gateway 等路由的测试分批补齐；
legacy_* 组随 DSH 迁移节奏跟进。）

## 5. 交付记录

- **批次 A（main）**：#1760 `d5df5590`
  - 内容：test_usage_routes.py 18 例 + 本文档。
  - 一轮 CI 红：ruff PT018（复合 assert 未拆分）——修复后终跑全绿
    （16 checks 0 failure）。PT018 已列入后续测试编写自查项。
- **批次 B（win7 对齐）**：#1761 `8abaf25f`
  - cherry-pick 测试提交（py38 安全写法直接适用）；同样经历
    PT018 修复 cherry-pick 后全绿（Win7 LTS py38 job 过）。
- **总账回填**：即本提交。
