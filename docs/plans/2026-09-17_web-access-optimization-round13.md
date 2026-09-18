# 网页访问能力优化 Round 13：AB6 连接复用 + X2 出网可观测（2026-09-17）

- **上游文档**：Round 5 §2.3 AB6 / §2.5 X2；Round 10-12 已交付（AU5/AU3/AU7/凭据 UI）
- **范围**：main 与 release/win7 双分支（后端 only，零新依赖，py3.8 纪律）

## 0. 结论速览

AU 系列与凭据 UI 收尾后，后端剩余最有价值的是 **AB6 连接复用**：`web_tool._get_with_redirects`
每个 hop 用 `with build_client(...)` 新建 client，TLS 握手翻倍、失去 keep-alive——代理用户
（代理 TCP 握手成本更高）体感最明显。配套 X2 给出网工具结果统一附 `net` 统计块
（attempts/elapsed_ms/bytes/escalated），为后续调优提供数据。

| 项 | 内容 | 批次 |
| --- | --- | --- |
| AB6 | 一次 execute 复用一个 httpx client（逐 hop 仍可独立 verify/proxy 判定） | 批次 1 |
| X2 | web_fetch / http_download 结果附 `net: {attempts, hops, elapsed_ms, bytes}` | 批次 2 |
| T | 单测 + CHANGELOG | 批次 2 |

## 1. 设计要点

- `build_client` 保持工厂不变；`_get_with_redirects` 改为循环外 `with build_client(...)` 一次，
  hop 内仅重建 request。verify 差异：`allows_insecure_tls(current_url)` 在多数 execute 内
  整体一致——若某 hop 判定与 client 的 verify 不一致，退化为该 hop 单独新建 client（保持安全语义）。
- `HostRateLimiter` / `retrying_send` 语义不变；统计 attempts 由 retrying_send 返回或包装计数。
- `net` 块进缓存前剥离（同 note/cached 口径）。

## 2. 双分支

改动集中 `web_tool.py`（+ http_factory.py 小改）+ `test_web_tool.py`/`test_http_factory.py`。
两分支同源文件，cherry-pick 零预期冲突。

## 3. 后续轮候选（记录）

- AB3 TLS 指纹（main only，可选依赖 httpx[http2] / curl_cffi，win7 不引入）
- 渲染分支 AU2 深检（渲染后密码框页已由 R11 AU7 覆盖，观察漏报率）
- 凭据 UI 增强：手动新增 header 型凭据入口
