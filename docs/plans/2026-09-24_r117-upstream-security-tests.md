# R117：upstream_security（SSRF 防护层）测试补齐 + httpcore 版本门修复（2026-09-24）

- **上游文档**：parity-loop-sop；model_catalog 出网链路（R25 时代引入）
- **范围**：后端。测试新增 + 两处生产 bug 修复（httpcore 版本门）。

## 0. 结论速览

`backend/api/upstream_security.py`（210 行）是出网请求共享的 SSRF /
DNS rebinding / 内存耗尽防护层，被 `model_catalog_routes._fetch_openrouter`
与 `model_catalog.probes` 直接依赖，但至今**零测试**。本轮补测试时当场
钓出两个真 bug：

1. **upstream_security 版本门误拒全部补丁版**：`httpcore.__version__.startswith("1.0.0")`
   对 1.0.1~1.0.9 全部为 False —— 而 `httpx==0.26.0` 声明的依赖是
   `httpcore==1.*`，受支持环境现装 1.0.9。即当前受支持环境下
   `client_for_resolved_address` 必然抛 `RuntimeError`，模型目录抓取
   （OpenRouter 拉取 / probes）的固定 IP 传输整体不可用；
2. **llm_proxy 版本门精确相等**：`!= "1.0.9"` 同样脆弱，任何补丁波动
   （旧环境 1.0.0~1.0.8、未来 1.0.10+）都会让 LLM 代理整体不可用。

修复：两处统一为 **(major, minor) 系列门** `== ("1", "0")` —— 1.0.x 全系
放行（AutoBackend/_network_backend 私有契约在 1.0 系列内一致），0.x 与
1.1+ 仍拒绝。语义对齐，回归测试钉死。

## 生产修复明细

- `backend/api/upstream_security.py`：`_SUPPORTED_HTTPCORE_VERSION = "1.0.0"`
  → `_SUPPORTED_HTTPCORE_SERIES = ("1", "0")`，门禁改为
  `tuple(version.split(".")[:2]) != series` 抛同一 `RuntimeError`；
- `backend/api/llm_proxy_routes.py`：`"1.0.9"` 精确门 → 同款系列门。

## 测试

### 新增 `backend/tests/unit/api/test_upstream_security.py`（41 例）

1. `_is_dangerous_address`：loopback v4/v6、三段私网、链路本地、AWS
   metadata (169.254.169.254)、reserved、unspecified → True；公网 IP、
   非 IP 字符串、空串 → False；
2. `_configured_allowed_hosts`：env 未设 → 空；逗号分隔 + 空白 + 大小写
   归一；
3. `resolve_and_validate_upstream_host`（fake resolver 替换模块级
   `_resolve_addresses`，getaddrinfo 5 元组形状）：
   - 无 host → `ValueError`；host 字面量私网 → 拒绝且错误文案用模糊常量
     （断言不含目标 IP）；解析先于校验执行（calls 断言记录实参）；
   - 尾点剥离 + https 默认 443；http 80 / 显式 8080 端口默认矩阵；
   - rebinding：公网 host 解析出私网地址 → 模糊文案拒绝；
   - env 白名单命中 → 放行返回 pinned IP；
   - gaierror / 超时（DNS_TIMEOUT_SECONDS 压小 + resolver sleep）→
     `ValueError("DNS resolution failed")` 且信号量归还；
   - 空解析结果；信号量占满 → `capacity exhausted` 短路不解析；
   - 成功路径返回 sorted(addresses)[0]；
4. `client_for_resolved_address` / `_FixedIPNetworkBackend`：0.15.0 /
   1.1.0 → `RuntimeError`；**1.0.0 / 1.0.9 → 放行（版本门回归核心）**；
   `connect_tcp` 实参重定向（"evil.example" 实连 pinned IP）；
5. `read_response_body_limited`：content-length 超限 → 拒且 body 零消费
   （首读即炸的哨兵异步生成器）；非法 content-length 静默忽略继续流式；
   无 content-length 流式累计超限；恰好上限通过 / +1 字节拒绝；正常拼接。

### 新增 `backend/tests/unit/api/test_llm_proxy_httpcore_gate.py`（7 例）

llm_proxy 门禁矩阵：1.0.0 / 1.0.9 / 1.0.12 放行且 backend 替换生效；
0.15.0 / 1.1.0 / 2.0.0 → `RuntimeError`。

## 测试工程约束

- 模块全局 `_dns_semaphore` / `_dns_executor_instance` 用 autouse fixture
  每例重置（teardown 对 executor `shutdown(wait=False)`），避免跨用例
  泄漏；
- httpx 流式替身必须用**异步**生成器 content（httpx 拒绝对 sync stream
  做 `aiter_bytes`）；standalone `httpx.Response` 原生支持 `aiter_bytes`；
- `pytestmark = pytest.mark.unit`；async 用例走 `asyncio_mode = auto`。

## 验证

- `pytest tests/unit/api/test_upstream_security.py
  tests/unit/api/test_llm_proxy_httpcore_gate.py` + 既有
  `test_llm_proxy_url.py` / `test_llm_proxy_tls_diagnostics.py`：
  68 passed；
- `ruff check`（CI 同版本 0.4.4）：All checks passed。
- 本地环境：Python 3.12 / httpcore 1.0.9 / httpx 0.28.1；CI 用锁定
  httpx 0.26.0 —— 测试只用跨版本稳定 API。

## Win7 对齐

`upstream_security.py` 与 `llm_proxy_routes.py` 均存在于 release/win7
（blob af8ae7c4，两处同款门禁）。生产修复属 bug fix，merge 后按规则
cherry-pick 回 release/win7 开 PR；测试文件随行（py3.8 语法兼容，
win7 CI 仅 collect 门禁）。

## 明确不做

- 不把 1.1.x 纳入放行系列（私有契约仅在 1.0 系列验证过，保守拒绝）；
- 不给 `probes.py` 加集成测试（已有上游用例，且涉及真实出网）。
