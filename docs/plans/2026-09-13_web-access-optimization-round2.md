# 网页访问能力优化 Round 2：反爬韧性——路由指引 + 抓取缓存 + UA 现代化（2026-09-13）

- **状态**：方案完成，实施中
- **上游文档**：[2026-09-13_web-access-optimization-round1.md](./2026-09-13_web-access-optimization-round1.md)（Round 1 已交付：PF-1 + 批次1-5，main #742 / win7 #748）；本文落地其 backlog 的 B1、B3 与勘察新项
- **范围**：main 与 release/win7 双分支（后端 only，零前端）
- **编号约定**：G = 路由指引；C = 缓存；U = UA
- **方法**：基于 Round 1 交付后的代码勘察（web_tool / web_render / search_engines，附 `file:line`）

## 0. 结论速览

Round 1 解决了"能不能用"（搜索多源/代理）、"够不够用"（登录态/渲染深度）；本轮解决**硬反爬站点的韧性**与**重复抓取的限流/成本问题**：

1. **G1 反爬失败无路由指引**：`web_fetch` 收到 403/429/503 时只报"HTTP 请求失败"，模型不知该转 browser 通道（真 Chrome 指纹）或配置代理——Round 1 已交付 browser 通道与代理，缺的只是失败面的指引。
2. **C1 无抓取缓存**：同一 URL 反复抓取每次全量出网（Round 1 勘察 backlog B3）；对限流站是二次伤害，对 token 是纯浪费。主流工具（ZCode WebFetch 15min、Perplexity 全量缓存）标配。
3. **U1 UA 过时**：固定 `Chrome/120`（web_tool.py:34）在 2026 年已是"一年半前的浏览器"，是廉价的 bot 信号；升级到现代版本号，一处常量改动。

## 1. 差距与证据

| # | 差距 | 证据 | 优先级 |
| --- | --- | --- | --- |
| G1 | 403/429/503 无反爬指引：`raise_for_status` 的 HTTPStatusError 被归一为通用失败文案 | web_tool.py:342、:443；search 全链失败文案 web_tool.py:127 | P1 |
| C1 | 无 TTL 缓存：重复 URL 全量出网；渲染分支（成本最高）同样不缓存 | web_tool.py 全文（无 cache 引用） | P1 |
| U1 | UA 固定 Chrome/120 | web_tool.py:34 | P2 |

## 2. 方案设计

### 2.1 G1 反爬路由指引

`WebFetchTool.execute` 的 `httpx.HTTPError` 分支细化：捕获 `httpx.HTTPStatusError` 且 `status_code in (403, 429, 503)` 时，错误文案追加反爬语义与两条出路：

```
http_403: 站点拒绝访问（可能反爬/风控）
（出路1：经 coder 用 browser_launch + browser_navigate 真浏览器通道；
 出路2：设置 → 网络中配置代理后重试；也可 web_search 换搜索引擎源）
```

`web_search` 全链失败的 `error` 尾部追加代理指引（"可在设置中配置代理或 Tavily/智谱 API 引擎"）。

### 2.2 C1 web_fetch TTL 缓存

**新模块 `backend/tools/web_cache.py`（新文件 = 双分支零冲突）**：

- 进程级内存缓存：`OrderedDict` LRU（上限 50 条）+ `time.monotonic()` TTL（15 分钟），`threading.Lock` 保护（工具跑在 executor 线程）。
- 缓存对象：**静态/渲染分支成功(2xx)后的抽取产物 dict**（title/text/links/tables/status_code/content_type/encoding/rendered），键 = 规范化 URL（去 fragment、保留 query）。
- 组装时机：命中后按本次请求的 `mode` / `max_length` 重新裁剪，与即时抓取同构。
- **不缓存**：`mode=raw`（原始 HTML 体积大、重复价值低）、带 `credential_domain` 的请求（登录态响应有时效语义，误缓存易混淆）、非 2xx。
- 绕过：`web_fetch` 新增 `refresh: bool = false` 参数，true 时跳过读缓存并在成功后回填。
- 命中标记：结果附 `cached: true`，模型可感知。

### 2.3 U1 UA 现代化

`_DEFAULT_HEADERS` 的 UA 升级为 `Chrome/126` 同款字符串（一处常量；win7 末代 Chrome 109 无法真实模拟，但 UA 声明与 TLS 指纹解耦，多数静态风控只看 UA 版本新鲜度）。

## 3. 双分支实施策略

| 文件 | 两分支状态 | 冲突预测 |
| --- | --- | --- |
| backend/tools/web_cache.py（新） | 不存在 | 零冲突 |
| backend/tools/web_tool.py | Round 1 cherry 后已同源 | 零冲突 |
| backend/tests/unit/test_web_cache.py（新） | 不存在 | 零冲突 |
| backend/tests/unit/test_web_tool.py | 同源 | 零冲突 |

Round 1 后 `web_tool.py` 双分支已归同源（#748 cherry 完成），本轮改动面小且全部在同源文件，cherry(win7) 直接干净落地。py3.8 纪律 + 零新依赖不变。

## 4. 实施批次

| 批次 | 内容 | 工作量 |
| --- | --- | --- |
| 批次 1 | G1 路由指引 + U1 UA（web_tool.py）+ 单测 | 0.5 天 |
| 批次 2 | C1 TTL 缓存（web_cache.py + web_fetch 接线 + refresh 参数）+ 单测 | 1 天 |
| 收尾 | cherry(win7) + 测试 | 0.5 天 |

## 5. 测试与验收

- `test_web_cache.py`（新）：TTL 过期、LRU 淘汰、命中标记、refresh 绕过、非 2xx 不缓存、raw/凭据不缓存、并发写安全（ smoke）。
- `test_web_tool.py` 扩展：403/429 文案含反爬指引与 browser 通道字样、cache 命中不发第二次请求（respx 计数）、refresh 强制出网。
- 验收：同 URL 二次 `web_fetch` 返回 `cached: true` 且零网络请求；403 站点错误文案含"browser_launch"指引。

## 6. 安全口径与已知限制

- 缓存纯内存、进程内，不落盘——无静态泄密面；credential 请求不入缓存（避免登录态内容跨会话复用）。
- TTL 15 分钟内内容可能过期：`cached: true` 明示，模型可 `refresh=true` 取新。
- 已知限制：缓存不含负缓存（403 等失败不缓存，每次重试；限流站请配合 browser 通道）；UA 现代化不改变 TLS 指纹，硬风控站点仍需 browser 通道（Round 1 §6 口径不变）。
