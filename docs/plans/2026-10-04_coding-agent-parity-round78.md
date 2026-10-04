# 编码代理对标差距分析·第七十八轮：Zotero 路由测试补齐（双分支）

- **状态**：单批次交付（分支 `feat-parity-r78`，基线 origin/main 38c5f7992）
- **上游文档**：round66 §4 候选清单（延续）
- **对标对象**：r 系列测试补齐惯例，本轮自主选题

## 0. 结论速览

R77 收口后，`feat-parity-r78` 工作树于 2026-09-29 起草了
`backend/tests/unit/api/test_zotero_routes.py`（18 例）后中断：文件未提交、
5 例失败未修、无方案文档、无 PR、worktree 落后 main 30 个提交。本轮
（2026-10-04）收敛：追平 main、修掉 5 例测试侧问题、补本方案文档、按
`unit/api/` 惯例交付，并做 win7 对齐。

Zotero 只读集成（#1367/#1370，r94/r98 收口）的 HTTP 面
`backend/api/zotero_routes.py`（248 行，6 端点）此前只有 r94 的 11 例
（`backend/tests/unit/test_zotero_routes.py`，TestClient 桩 + 主路径）。
本轮新增的 18 例补上此前零覆盖的语义：单例复用与 db_path 变更重建、
`_get_configured_db_path` 的 settings→env 回退、`set_db_path` 持久化失败
仍 200、`_item_to_summary` / `_item_to_detail` 缺省值、503 信封降级。

## 1. 差距矩阵

| # | 差距 | 证据 | 优先级 |
| --- | --- | --- | --- |
| T-13 | zotero_routes 单例 / 回退 / 降级语义无单测 | r94 只覆盖主路径；单例重建、settings→env 回退、持久化失败、映射缺省零覆盖 | **P2** |
| T-13a | `ZoteroDatabaseNotFoundError` 构造参数是「搜索过的路径列表」，传字符串会被逐字符 join 出坏消息 | 本轮首跑实测 `Searched: n, o,  , z, …` | 记录；测试侧对齐，不在本轮改生产代码 |

## 2. 设计

`backend/tests/unit/api/test_zotero_routes.py`（18 例，直接调用路由函数，
ZoteroClient / settings_repo / 模块级单例全 monkeypatch）：

- 映射：`_item_to_summary` / `_item_to_detail` 缺省值（summary 不含
  `attachments` 属既有响应形状）。
- status：可用（stats 透传）；DB 未找到 → 200 + error（不抛 5xx）；
  503 信封降级。
- search / item / annotations / collections：参数透传与映射、`ghost` 404。
- `set_db_path`：清空单例缓存、持久化落 settings_repo、持久化失败仍返回 ok。
- `_get_client`：同 db_path 复用单例、override 变更重建（Path 归一化比较）、
  缺库包装为 503。
- `_get_configured_db_path`：settings 优先、缺省回落 `ZOTERO_DB_PATH`、
  repo 异常回落 env。

## 3. 实施与验证记录

首跑（起草态）：13 passed / 5 failed——全部是测试侧问题，生产代码未改：

1. `test_item_to_summary_defaults`：断言笔误（`out["attachments"] not in out`
   求值即 KeyError，应为 `"attachments" not in out`）。
2. `test_status_db_not_found_degrades` / `test_get_client_wraps_missing_db_as_503`：
   异常构造参数应为列表（字符串被逐字符 join，见 T-13a）。
3. `test_set_db_path_persists_and_clears_cache`：前置断言写反——autouse 夹具
   先把单例重置为 None，需先预热 `_get_client()` 再断言缓存存在。
4. `test_get_client_rebuilds_on_db_path_change`：路由把 override 归一化为
   `Path`，应按 `Path(second.db_path)` 比较（Windows 下即 WindowsPath）。

另清掉起草态的两处问题：F401（`SimpleNamespace` 未使用导入）与 PT018
（三处 `assert A and B` 拆分为独立断言），`ruff format` 归一化。

收敛后：**18 例全绿**（本地 Python 3.12.10 / fastapi 0.136.3 /
pytest 9.0.3）；`ruff check` + `ruff format --check` 干净；
`py38_hazard_scan` 0 命中。纯测试新增，无生产代码改动。

## 4. 批次 B

win7 线 `backend/api/zotero_routes.py` 与 `backend/zotero/*` 同源存在
（win7 此前只有 `test_zotero_client.py`，无路由测试），批次 B 为同文件
移植 + 文档同步，无适配差异。

## 5. 交付记录

- **批次 A（main）**：待填（本提交推送后开 PR）。
  - 内容：`backend/tests/unit/api/test_zotero_routes.py`（18 例）+ 本文档。
- **批次 B（win7 对齐）**：批次 A 之后同轮交付（遵循 R76/R77 惯例）。
- **总账回填**：`docs/plans/parity-rounds-index.md` R78 行待批次 A/B 合并后回填。
