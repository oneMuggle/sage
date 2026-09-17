# 网页访问能力优化 Round 8：web_search 多引擎并行聚合（2026-09-15）

- **状态**：方案完成，实施中
- **上游文档**：Round 1（#742/#748，搜索引擎链）、Round 2（#756/#759，查询缓存）、Round 3（#763/#765，key 加密）、Round 6/B2（#837/#842，子代理浏览器授权）
- **范围**：main 与 release/win7 双分支（后端 only；改动全部在 Round 1-3 我方文件，与并行会话的 browser/download 批次无交集）
- **编号约定**：P = 并行聚合
- **方法**：基于 Round 3 交付后的 web_tool / search_engines / search_config 勘察

## 0. 结论速览

现有引擎链是**串行 fallback**：首选引擎空/失败才试下一个——单引擎覆盖面受限（Bing 缺某条结果时用户看不到），多引擎各有所长时无法互补。Round 8 增加**并行聚合模式**（默认关闭）：前 N 个引擎并发搜索，按引擎优先级合并去重，一次调用获得更全的覆盖。

## 1. 设计

### P1 并行聚合

- **配置**：`search_config` 新增 `parallel: bool = false`（默认关闭，保持串行 fallback 现状）、`parallel_first_n: int = 2`（并发取链上前 N 个引擎，1 ≤ N ≤ 链长）。
- **执行**：`ThreadPoolExecutor`（py3.8 stdlib，零新依赖）并发跑前 N 个引擎；总体 deadline 30s（沿用单引擎超时）；单引擎异常不影响其他引擎。
- **合并去重**：按引擎链顺序（优先级）遍历各引擎结果，规范化 URL（去 fragment/尾空白）去重，截取 `limit` 条；`engine` 字段记 `parallel(eng1+eng2)`。
- **缓存**：并行结果按既有查询缓存口径写入（键 `search://<query>`、`limit=<n>`、5 分钟 TTL、`refresh` 绕过）——并行与串行的缓存键相同但内容标记引擎来源，开关切换后 5 分钟内可能命中另一模式的结果（可 `refresh` 绕过，已知限制明示）。
- **空结果语义**：全部引擎均空 → 保持 W3 空结果 + engine_errors；全挂 → success=False。

### P2 失败容忍度

并行模式下单引擎失败不产生空档：只要任一引擎返回非空即成功；失败引擎记入 `engine_errors`（与串行口径一致）。

## 2. 双分支实施策略

| 文件 | 状态 | 冲突预测 |
| --- | --- | --- |
| backend/tools/search_engines.py / search_config.py / web_tool.py | Round 1-3 我方文件，两分支同源 | 零冲突 |
| backend/tests/unit/test_search_engines.py / test_web_cache.py | 同源 | 零冲突 |

py3.8 纪律（concurrent.futures 为 stdlib）+ 零新依赖不变。

## 3. 实施批次

| 批次 | 内容 | 工作量 |
| --- | --- | --- |
| 批次 1 | P1 并行聚合 + P2 容忍度 + 单测 | 1 天 |
| 收尾 | cherry(win7) + 测试 | 0.5 天 |

## 4. 测试与验收

- 并行开启：两引擎结果按优先级合并、跨引擎 URL 去重、单引擎异常不阻断。
- 默认关闭：串行 fallback 行为逐字节不变（既有测试锁）。
- 缓存：并行结果命中 `cached: true` 且引擎零调用；`refresh` 绕过。
- 验收：`search_config` 加 `{"parallel": true}` 后同一查询返回两引擎合并结果。

## 5. 安全口径与已知限制

- 并发引擎共享同一 httpx Client（线程安全）；代理/门禁/UA 配置照常生效。
- 已知限制：并行模式下 API 引擎的配额消耗翻倍（用户自配自担）；开关切换后 5 分钟缓存窗口内可能命中旧模式结果（`refresh` 绕过）。
