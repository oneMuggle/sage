# MCP 会话交付物：ArenCard 能力移植到 Sage 的实现方案

日期：2026-09-19 ｜ 参考实现：`reference/ArenCard`（Python 本地工具，Windows，已实测验证）
目标分支：sage `main` 通道（FastAPI backend + Electron 21 / Chromium 106 + React 18 前端）
关联文档：`docs/superpowers/specs/2026-09-16-arena-automation-model-probe-design.md`（既有 CDP 观测设计）、`docs/technical/50-arena-source-license-audit.md`（移植纪律）

## 1. 背景与目标

ArenCard 是一个纯本地工具，三个页签三项能力。对照 sage 现状：

| 能力 | ArenCard 做法（已实测） | sage 现状 |
|---|---|---|
| 批量注册 | 纯 HTTP 协议 6 步（无浏览器、无验证码），10minutemail 免注册邮箱，动态代理每账号换 IP | ❌ 无任何协议代码（`magic-link` 全仓 0 命中）；`backend/tests/integration/test_arena_registration_flow.py` 只是 mock 浅测 |
| 自动抽卡 | 纯协议：建会话 → 从 Trigger.dev run events 读模型名 → 命中改名保留 / 未命中归档；429 门闸 + 自动换 IP | ❌ 无协议抽卡；✅ 已有 CDP 流量观测判模型（`arena_observation.py`，慢路径，依附浏览器会话） |
| 账号管理 | 账号池 + 每号抽卡历史 + IP 绑定/批量重绑 | ✅ 账号池（SQLite + Fernet + 状态机 + 失败隔离）与 REST 已建；❌ 无 IP 绑定/抽卡历史字段；❌ 前端零 arena 页面 |

目标：以 sage 现有基建为地基，把 ArenCard 的**纯协议注册**、**纯协议抽卡**及其**代理 / 门闸 / reCAPTCHA token** 子系统移植为 sage 的可选能力（feature-flag），补齐接线与 UI。

## 2. ArenCard 参考分析

### 2.1 注册协议（`arena_core.py`）

纯协议 6 步，单账号 15~30s（瓶颈在等邮件）：

| # | 步骤 | 关键细节 |
|---|---|---|
| 1 | 取临时邮箱 | `GET https://10minutemail.one/zh` 提取 HTML 内 JWT（有效期 23h）；随机 10 位 `[a-z0-9]` 本地名 + catch-all 域名轮换（`dbwot.com` / `ygwpr.com` / `imxwe.com`），免注册 |
| 2 | `POST /nextjs-api/sign-up` | `{recaptchaToken:"", provisionalUserId:<uuid4>}` → 服务端不校验 reCAPTCHA，返回 `access_token` |
| 3 | `POST /nextjs-api/sign-up/magic-link` | `{email, fullName, shouldLinkHistory:false, marketingConsent:false, registeredCountryCode:"US"}` 发验证邮件 |
| 4 | 收信提取链接 | 轮询 `GET web.10minutemail.one/api/v1/mailbox/{email}`（Bearer JWT + `X-Request-ID` + `X-Timestamp`；401 → 刷新 JWT 重试）；正则 `https://arena\.ai/nextjs-api/callback\S+`；`GET` 该链接跟随重定向到 `/auth/set-password?token=...` 提取 token |
| 5 | `POST /nextjs-api/auth/set-password` | `{password, token}`；密码规则：≥8 位且含大写+小写+数字+特殊符 |
| 6 | 验证 + 查额度 | `POST /nextjs-api/sign-in/email` 登录验证（失败则重设密码再试一次）；`GET /api/me` 取 user id；`GET /api/billing/balance` 取 `creditsRemaining`（约 15000/天） |

实测结论（必须继承的经验）：

- **TLS 指纹是生死线**：原生 requests 会被 Cloudflare 判为脚本（403）；必须 curl_cffi `impersonate="chrome131"`，且**不要手写 User-Agent**（会出现「Windows UA + Mac Chrome 指纹」矛盾组合）。
- **邮箱服务永远直连**：10minutemail 会拉黑部分机房/代理 IP（实测 10 条约 4 条 TLS 被断）；只有 arena 侧需要代理且 IP 要一致。
- 10minutemail 100 并发查询无速率限制；注册并发建议 3~5（受邮件到达速度限制）。

### 2.2 抽卡协议（`arena_draw.py`）

一抽 = 一个新会话（模型是对话级分配的）：

| # | 步骤 | 端点 / 细节 |
|---|---|---|
| 1 | 登录 | `POST /nextjs-api/sign-in/email`（会话内复用，不重复登录） |
| 2 | 取 reCAPTCHA **Enterprise** V3 token | 常驻离屏浏览器加载 `https://arena.ai/agent/`，`grecaptcha.enterprise.execute("6LeTGMcsAAAAALuIlkVwIxaAuZA8VledA6d3Nnb0", {action:"agentic_chat_submit"})`；无头浏览器出票 100% 被拒，必须真浏览器；token ~2 分钟可复用 |
| 3 | 建会话 | `POST /nextjs-api/stream/create-chat`，body `{message:{id:uuid4, role:"user", parts:[{type:"text",text:"1+1="}]}, timezone, recaptchaV3Token}` → `{id}`（sid） |
| 4 | 取会话凭据 | `POST /api/chat/trigger-token` `{sessionId}` → JWT（scope 含 `read:runs:<runId>`） |
| 5 | 订阅输出流 | `GET /ai-proxy/realtime/v1/sessions/{sid}/out`（SSE，`Authorization: Bearer`，`x-trigger-source:sdk`，`x-trigger-realtime-streams-version:v2`）→ 帧 `records[].headers` 里的 `public-access-token`（内含 run_id） |
| 6 | 读模型名 | `GET https://api.trigger.dev/api/v1/runs/{runId}/events`（Bearer）；`message=="ai.streamText.doStream"` 的事件：`style.icon="ai-provider-<provider>"` 得供应商；`style.accessory.items` 中 `icon=="tabler-cube"` 的 `text` = 模型名；内部配置名从原始 JSON 正则 `"modelName"\s*:\s*"([^"]{2,80})"`（如 `gpt-6-astra-low`，可再拆档位 low/medium/high/max） |
| 7 | （可选）思考强度 | 读 span 详情 `GET /api/v1/runs/{runId}/spans/{spanId}`：`token.usage.recorded` span 顶层 properties 有 `reasoningTokens/inputTokens/outputTokens/cacheReadTokens/modelName`；比模型名晚落盘，需要时必须 `want_internal=True` 多等 |
| 8 | 处置 | 命中（官方名或内部名任一匹配正则）：`PATCH /api/history/agentic/{sid} {title}` 改名为 `内部名·r<reasoningTokens>`；未命中：归档（默认）`POST /api/chat/{sid}/archive` / 删除 `DELETE /api/chat/{sid}` / 保留 |

### 2.3 限速门闸与换 IP（`arena_draw.py`）

- **双层节奏**：全局最小请求间隔（所有实例共用，UI「请求间隔」）+ 每账号独立 429 退避。
- **每账号门闸**（key = 邮箱本地名，一号一闸互不牵连）：429 → 阶梯 15s → 30s → 60s → 90s；该账号建会话间隔同步抬高 `min(60, 5*(level+1))`；240s 未再遇 429 自动降一级。
- **Cloudflare 挑战识别**：429 响应体含 `just a moment` / `cf-chl` / `attention required` → 等待无效，必须换 IP；命中后 180s（CF_HOLD）内该出口 IP 视为已死。
- **轮内换 IP**：`set_switch_level(n)` —— 阶梯到第 n 档即中止本轮，`draw_once` 返回 `switch=True`，上层重绑代理后整轮重跑（不当作失败）。
- **reCAPTCHA 拒绝计数**：每次被拒 +1（重试也算）；拒绝→等 10s 换新 token 重试；429→等 20s 换新 token；建会话 backoff 序列 (0, 15, 30, 60)，同轮内复用同一 token。全局拒绝数到阈值 → 换 token 浏览器的出口 IP。
- **IP 绑定（bindings）**：注册时用的代理记为该账号的 IP；抽卡默认沿用（一号一出口）；`proxy_sid` 从代理 URL 提取 `sid-XXXX`（辣酱会话 ID），代理池续期后按同 sid 找回同一条实现「重绑同 IP」；`proxy_alive` 双端点探测（ipify + ifconfig.me，8s）。

### 2.4 代理子系统（`proxy_relay.py` + `arena_core.py`）

- **动态代理 API**（`api.haiwaidaili.net/abroad` 风格）：params `token/num/format=2/protocol/country/sep=1/csep=""` → `{data:[{ip,port}]}`；支持 http/socks5、国家码、每账号/每波次轮换。
- **粘贴代理池**：兼容 4 种凭据格式（`host:port:user:pass`、`user:pass:host:port`、`user:pass@host:port`、`host:port@user:pass`），顺序/随机轮转，去重。
- **本地 CONNECT 中转（关键专利点）**：辣酱类代理**CONNECT 只要带 Host 头就拒绝**（最小 CONNECT → 200；+Host → 拒；+UA → 200），而 curl_cffi 的 CONNECT 必带 Host → 直连必败。解法：curl_cffi → `127.0.0.1:<本地端口>`（自建 relay，用最小 CONNECT 无 Host 连上游）→ arena.ai（TLS 端到端，指纹不丢）。
- **端口必须 bind 0 系统分配**：Windows `SO_REUSEADDR` 允许多进程重复绑定同一固定端口，实测 11 个进程同听 20000 导致实例间 IP 隔离失效。

### 2.5 账号管理页签

账号列表、每账号抽过的模型历史、批量重绑 IP（新代理池刷新 + 同 sid 找回）。

## 3. sage 现有基础盘点

### 3.1 已建成（可直接复用）

| 模块 | 位置 | 内容 |
|---|---|---|
| 账号池 | `backend/services/arena_accounts.py`（250 行） | SQLite + Fernet（PBKDF2-HMAC-SHA256，480k 迭代，machine_id 盐）；状态机 available/reserved/degraded/disabled/destroyed；失败隔离阈值 3；`reserve/release/record_failure/enable/soft_delete` |
| 账号 REST | `backend/api/arena_routes.py`（173 行） | `/api/v1/arena` 前缀；账号 CRUD + 启用 + 失败记录；feature-flag 门控（403）；模块级单例 `init_arena_service()` 模式 |
| 浏览器适配器 | `backend/services/arena_adapter.py`（210 行） | CDP 驱动：`check_login_state / detect_captcha / fill_login / fill_verification_code / submit_message / wait_for_response` + Thinking 过滤器 —— **浏览器路径**已有 |
| CDP 观测判模型 | `backend/services/arena_observation.py`（197 行） | 常驻 CDP 订阅 Network 事件 → 证据 → 判定（慢路径，依附浏览器会话） |
| 模型探针 | `backend/services/model_probe_py/`（classify/idmap/registry）+ `model_probe_worker.py` | arena-model-probe 移植，python/node 双 backend |
| CDP 基建 | `backend/tools/browser_cdp.py` | `cdp_command` 浏览器会话抽象 |
| 邮箱抽象 | `backend/services/temporary_mail/base.py` | async `TemporaryMailProvider` ABC（create_mailbox / wait_for_code / destroy / _fetch_messages）+ `Mailbox` dataclass |
| 配置模型 | `backend/config/arena_automation.py` | pydantic：`enabled / max_accounts(5-20) / max_concurrent_sessions(2-10) / mail_provider / probe_backend...`（extra=forbid） |
| 事件总线 | `backend/orchestration/event_hub.py` | UI 实时事件通道 |
| HTTP 约定 | `backend/requirements.txt` | httpx==0.26.0；cryptography 50.0.1 |
| 测试骨架 | `backend/tests/unit/services/test_arena_accounts.py`、`test_arena_adapter.py`、`backend/tests/integration/test_arena_registration_flow.py` | 已有（后者为 mock 浅测） |
| 设计规范 | `docs/superpowers/specs/2026-09-16-arena-automation-model-probe-design.md` | 既有设计：CDP 观测 + 账号池 + 临时邮箱；Win7 章节（Chromium 106 / py38 / 零新依赖纪律） |

### 3.2 缺口（本方案要补的）

1. **接线断裂**：`main.py` 只 `include_router(arena_router)`，lifespan 里**没有**调用 `init_arena_service()` → 生产环境所有 `/api/v1/arena/*` 恒 503。
2. **配置文件缺失**：`arena_automation.yaml` 全仓不存在（只有 pydantic 模型）。
3. **邮箱 provider 无实现**：`temporary_mail/` 只有 `base.py`；config 默认 `mail_provider: "mailtm"` 但没有 `mailtm.py`。
4. **协议客户端为零**：sign-up / magic-link / set-password / create-chat / trigger-token / trigger.dev 全部 0 命中。
5. **无代理子系统**、**无 reCAPTCHA token 通道**、**无抽卡引擎**、**无 429 门闸**。
6. **前端零 arena 页面**（`src/` 0 命中）；需按 feature 式目录新增。

## 4. 总体设计

### 4.1 双通道架构（协议快路径 + 既有浏览器路径）

```
 UI  src/features/arena（三个页签，对齐参考）
      │ REST + EventHub（SSE 日志/结果流）
 FastAPI  backend/api/arena_routes.py（扩展注册/抽卡/代理/token 窗口路由）
      ├───────────────┬───────────────────────┐
 ┌────────────┐ ┌───────────────┐ ┌────────────────────────┐
 │ 协议路径(新) │ │ 浏览器路径(有) │ │ 账号池(有,扩展绑定字段)  │
 │ arena_protocol│ │ ArenaAdapter  │ │ arena_accounts         │
 │ 注册6步/抽卡  │ │ +CDP 观测判模型│ │ SQLite+Fernet+状态机   │
 │ curl_cffi可选 │ │ Win7 兜底通道 │ │ + proxy/credits/draws  │
 └─────┬──────┘ └───────────────┘ └────────────────────────┘
       │ reCAPTCHA V3（抽卡需要）
 ┌─────┴──────────────────────────────┐
 │ Electron 离屏隐藏窗口 + IPC（新）     │  arena.ai/agent/ 内
 │ arena-token-window: mint/health/ip  │  grecaptcha.enterprise
 └────────────────────────────────────┘
       代理出口：proxy_relay（本地最小 CONNECT 中转）+ 代理池/动态 API
```

### 4.2 关键设计决策

- **D1 双通道互补，Win7 零新增**：协议路径是批量注册 / 批量抽卡的快路径（无浏览器、注册 15~30s/号、抽卡 5~15s/轮）。既有浏览器路径（`ArenaAdapter` + `ModelObservationService`）保留为 Win7 通道与协议路径失效时的兜底。Win7（py38、零新依赖、Chromium 106）不加任何新代码，继续走已实现的浏览器路径。
- **D2 token 服务用 Electron 隐藏窗口**：参考实现是「独立 WebView2 子进程 + 127.0.0.1 HTTP」；sage 本身就是 Electron，改用**离屏隐藏 BrowserWindow + IPC**（`show:false`），无额外运行时、无本地 HTTP 端口暴露、进程生命周期随主程序。加载 `https://arena.ai/agent/`，`grecaptcha.enterprise.execute` 出票（Enterprise V3，sitekey 见 §10）。
- **D3 TLS 指纹走可选依赖**：curl_cffi 放入 `backend/requirements-optional.txt`（与 matplotlib/formulas/Pillow 同待遇：仅 main 通道、懒加载、缺失时降级浏览器路径并给出可读错误）。Win7 通道不受影响。缺 curl_cffi 时协议客户端退回 httpx（HTTP/2 开），指纹降级、403 风险升高 —— 此时 UI 提示走浏览器路径。
- **D4 CONNECT relay 原样移植**：纯 stdlib socket/threading 实现（重写为 sage 风格，不拷贝文件），两通道通用；上游一条一个本地端口（bind 0）。
- **D5 门闸映射账号状态机**：每账号 429 门闸（阶梯 15/30/60/90）触发时同步 `record_failure()`（既有失败隔离）；门闸 level≥2 或 CF 命中 → 该账号标 degraded；换 IP 成功后 `gate_reset` + `release_account` 计数重置。
- **D6 邮箱 provider 按既有 ABC 实现**：先 `tenminmail`（10minutemp.one，§2.1 细节），mailtm 作为第二 provider 预留。**邮箱请求恒直连**（参考实测代理拉黑）。
- **D7 移植纪律**：按 `docs/technical/50-arena-source-license-audit.md` 结论 —— 仅借鉴逻辑与实测常量，从零重写，不逐字拷贝；`reference/ArenCard` 无 LICENSE 文件，审计文档增补一节记录该新源。
- **D8 协议常量单点维护**：所有端点 / sitekey / 正则 / 阶梯参数集中在 `arena_protocol.py` 常量区（带来源注释），协议变更时单点修改 + fixture 回归。

## 5. 详细设计

### 5.1 数据层

**arena_accounts 表迁移**（SQLite，启动时幂等 `ALTER TABLE ... ADD COLUMN`，失败吞错兼容旧库）：

```sql
ALTER TABLE arena_accounts ADD COLUMN proxy_url  TEXT;   -- 绑定代理（注册时所用）
ALTER TABLE arena_accounts ADD COLUMN proxy_sid  TEXT;   -- 辣酱 sid（续期重绑同 IP）
ALTER TABLE arena_accounts ADD COLUMN exit_ip    TEXT;   -- 最近实测出口 IP
ALTER TABLE arena_accounts ADD COLUMN credits    INTEGER;-- 最近一次额度
ALTER TABLE arena_accounts ADD COLUMN last_draw_at TEXT;
ALTER TABLE arena_accounts ADD COLUMN draw_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE arena_accounts ADD COLUMN source     TEXT;   -- manual | registered
```

**新表 arena_draws**（抽卡历史，每号每轮一行）：

```sql
CREATE TABLE IF NOT EXISTS arena_draws (
  id TEXT PRIMARY KEY,            -- uuid4
  account_id TEXT NOT NULL REFERENCES arena_accounts(id) ON DELETE CASCADE,
  model TEXT, internal TEXT, provider TEXT, tier TEXT,
  reasoning_tokens INTEGER, input_tokens INTEGER, output_tokens INTEGER,
  session_id TEXT, run_id TEXT, kept INTEGER NOT NULL DEFAULT 0,
  error TEXT, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_arena_draws_account ON arena_draws(account_id, created_at);
```

**配置扩展**（`ArenaAutomationConfig`，extra=forbid 保留；yaml 默认全关）：

```yaml
# config/arena_automation.yaml（新增）
enabled: false
max_accounts: 5
max_concurrent_sessions: 2
mail_provider: tenminmail          # tenminmail | mailtm
account_idle_timeout_sec: 300
failure_isolation_threshold: 3
probe_backend: python
registration:
  enabled: false
  concurrency: 3                   # 参考建议 3~5
  mail_timeout_sec: 90
  domains: []                      # 空 = 参考默认三域轮换
draw:
  enabled: false
  keep_pattern: ""                 # 正则；空 = 全保留
  require_reasoning: false
  miss_action: archive             # archive | delete | keep
  rename_hit: true
  base_gap_sec: 3.0                # 全局最小请求间隔
  switch_level: null               # 429 到第几档换 IP；null = 轮内死等
  stream_wait_sec: 90
  captcha_retries: 2
proxy:
  api_url: ""
  api_token: ""
  country: ""
  protocol: http                   # http | socks5
  rotation: per_account            # per_account | per_wave
  pool_text: ""                    # 粘贴池（优先于 API）
```

### 5.2 协议客户端（新 `backend/services/arena_protocol.py`）

- **HTTP 层**：`_http_session()` 工厂 —— 优先懒加载 `curl_cffi.requests`（`impersonate="chrome131"`），失败回退 httpx（HTTP/2）；**不手写 User-Agent**（交给 impersonate；httpx 兜底时用固定 Chrome UA，接受指纹降级）。每账号独立 session（cookie 隔离）。
- **注册原语**（§2.1 六步，含 401→刷 JWT、set-password 失败重设一次、get_balance 4 次 × 3s 重试）。
- **抽卡原语**（§2.2 八步）：`login / create_chat / session_token / read_run_token`（SSE 逐帧解析 `public-access-token`，90s 超时）`/ fetch_run_events`（8 次 × 3s，`want_internal=True` 等到内部名落盘）`/ parse_models / parse_tier / read_usage`（span 详情最多 8 个，0.25s 间隔，429 即止）`/ rename_chat / archive_chat / delete_chat`。
- **SSE / 触发器常量**：`x-trigger-source: sdk`、`x-trigger-realtime-streams-version: v2`、`api.trigger.dev/api/v1/runs/{id}/events|spans/{spanId}`。
- 全部同步方法（job 层用线程池跑，不占 event loop —— 与参考的线程模型一致，且 FastAPI 路由内用 `run_in_executor`）。
- `run_id_from_token`：JWT payload `scopes` 中 `read:runs:<runId>`。

### 5.3 代理子系统（新 `backend/services/arena_proxies.py` + `backend/services/proxy_relay.py`）

- **ProxyRelay**（`proxy_relay.py`）：`local_url(upstream) -> http://127.0.0.1:<port>`；每上游一个监听 socket（`bind("127.0.0.1", 0)`）；收到 CONNECT 后向上游发**最小 CONNECT**（`CONNECT host:port HTTP/1.0`，绝不带 Host；有凭据则加 `Proxy-Authorization: Basic`）；200 后双向 pipe；线程模型同参考。
- **ProxyPool**：4 格式解析（`split_credentials` 启发式：端口段 + 主机段判别）、顺序/随机、去重、错误带行号。
- **ProxyApi**：haiwaidaili 风格取号（§2.4），返回统一 `scheme://[user:pw@]host:port`。
- **出口探测**：`proxy_exit_ip`（ipify，失败回退 ifconfig.me，8s，再失败显示代理主机）；`proxy_alive` 双端点。
- **rebind**：`proxy_sid(url)` 提取 `sid-XXXX` → 新池内同 sid 优先（IP 续期），找不到按轮转取新；回写 `arena_accounts.proxy_url/proxy_sid/exit_ip`。

### 5.4 注册编排器（新 `backend/services/arena_registration.py`）

- **Job 模型**：`{id, count, concurrency, proxy_mode, status: running|stopped|done, results[], log[]}`，模块级 registry（同 `arena_routes.py` 单例风格）。
- **单账号流程**（线程池 worker）：
  1. 邮箱 provider 建 mailbox（直连）
  2. 代理分配（按 rotation；直连模式为空）→ `local_proxy()` 转本地中转
  3. `arena_protocol.register_one`（§2.1；`cancel` 检查点可打断等邮件）
  4. 成功 → `ArenaAccountService.create_account(email, password, notes=批次号)`，回写 `proxy_url/proxy_sid/exit_ip/credits/source="registered"`；失败 → 记录并继续
- **密码**：按 arena 规则生成（§2.1）。
- **导出**：`data/arena/accounts_YYYYMMDD_HHMMSS.txt`，格式 `邮箱----密码----额度`（与参考一致）。
- 并发默认 3，上限 5（参考实测邮件是瓶颈）。

### 5.5 抽卡引擎（新 `backend/services/arena_draw_engine.py`）

- **单轮 `draw_once`**（对齐参考 §2.2/§2.3）：
  登录 → 取 V3 token（IPC → Electron 隐藏窗口；无 token 来源直接判失败，不做付费降级）→ create-chat（backoff 0/15/30/60，同轮复用 token；CF 或到 switch_level → 抛 `RateLimited(switch=True)` 上抛）→ trigger-token → SSE 读 public-access-token → run_id → fetch_run_events → parse_models →（可选）read_usage → `model_matches`（官方名或内部名任一命中；`require_reasoning` 时零推理 token 视为不命中）→ 命中改名保留 / 未命中按 `miss_action` 处置（归档失败自动退删除）→ 写 `arena_draws` + 更新账号 `last_draw_at/draw_count` + EventHub `arena:draw-result`。
- **门闸**（per-account，key=邮箱本地名）：`GATE_LADDER=(15,30,60,90)`、`GATE_DECAY_AFTER=240`、`CF_HOLD=180`、账号间隔抬高 `min(60, 5*(lvl+1))`、CF 识别三关键字；`gate_reset` 于换 IP 成功后调用；门闸事件经 EventHub `arena:gate` 推 UI。
- **换 IP 循环**（job 层）：`draw_once` 返回 `switch=True` → 按 rotation 取下一条代理（或池内同 sid 续期）→ `proxy_alive` 探测 → 重绑账号记录 → `gate_reset` → 整轮重跑；无代理（直连）时退化为纯门闸等待。
- **reCAPTCHA 拒绝**：计数（每号 + 全局）；拒绝→10s 换新 token；429→20s 换新 token；全局拒绝超阈值 → EventHub 提示「建议更换 token 窗口出口 IP」（token 窗口支持代理时自动重开窗口）。
- **批次**：`{account_ids|all, rounds_per_account, ...}`；每号串行、跨号按 `base_gap_sec` 错开。

### 5.6 reCAPTCHA token 窗口（新 `electron/arena-token-window.ts` + IPC）

- 主进程创建 `BrowserWindow({show:false, webPreferences:{contextIsolation:true}})`，`loadURL("https://arena.ai/agent/")`。
- 就绪判定：`document.readyState==="complete" && window.grecaptcha?.enterprise`（参考坑：`ready` 只是提示位，出票前必须再探一次 grecaptcha，失败则重载页面重试一次）。
- 出票 JS：`grecaptcha.enterprise.execute(KEY,{action:"agentic_chat_submit"})` → 轮询 `window.__tok`（0.15s，30s 超时）。
- IPC：
  - `arena:token-mint` → `{token}`（60s 超时）
  - `arena:token-health` → `{ready, count, error, exit_ip, uptime}`
  - `arena:token-ip` → 页面内 `fetch(ipify)` 诊断实际出口（排查「token 从哪个 IP 出的」）
  - `arena:token-reload` / 生命周期随主程序（app quit 时 destroy）。
- 可选：`session.setProxy` 让窗口走代理（换 token 出口 IP 能力）。
- backend 侧：`ArenaTokenClient`（经现有 backend↔Electron 通道取 token；**未连接 Electron 时抽卡直接报「token 窗口不可用」**，不做浏览器 fallback 自动切换，避免语义漂移 —— fallback 由 UI 显式选择「浏览器路径抽卡」）。

### 5.7 API 扩展（`backend/api/arena_routes.py` 增量，沿用 403 flag 门控）

```
POST   /api/v1/arena/registration/jobs              {count, concurrency, proxy_mode} → {id}
GET    /api/v1/arena/registration/jobs
POST   /api/v1/arena/registration/jobs/{id}/stop
GET    /api/v1/arena/registration/jobs/{id}/results
GET    /api/v1/arena/registration/export/{id}       → accounts_*.txt 下载

POST   /api/v1/arena/draw/jobs                      {account_ids|all, rounds, keep_pattern, miss_action, ...} → {id}
POST   /api/v1/arena/draw/jobs/{id}/stop
GET    /api/v1/arena/draw/jobs/{id}
GET    /api/v1/arena/draws?account_id=&limit=       抽卡历史

POST   /api/v1/arena/proxies/test                   {proxy_url} → {exit_ip, alive}
POST   /api/v1/arena/accounts/{id}/rebind           {pool_refresh: true} → 新 proxy_url/exit_ip
GET    /api/v1/arena/token-window                   {ready, count, exit_ip, error}
```

事件（EventHub 主题）：`arena:registration-log`、`arena:registration-result`、`arena:draw-log`、`arena:draw-result`、`arena:gate`。

### 5.8 UI（新 `src/features/arena`，React 18 + Radix + TanStack Query）

- `pages/ArenaPage.tsx`：顶层三页签（Radix Tabs），对齐参考的页签结构；入口挂到既有侧边栏/路由（`src/pages/settings` 同级或独立路由，随现有路由约定）。
- `components/RegisterTab.tsx`：数量 / 并发 / 代理（API 与粘贴池两个子模式 + 「测试代理」）/ 开始-停止 / 日志流（EventHub SSE）/ 结果表格（邮箱、密码、额度）/ 导出下载。
- `components/DrawTab.tsx`：目标模型正则（空=全保留）/ 只留推理 开关 / 未命中策略（归档-删除-保留）/ 请求间隔 / 换 IP 档位 / 账号多选（来自账号池）/ 开始-停止 / 实时抽卡卡流（模型、内部名、档位、推理量、会话名、kept）。
- `components/AccountsTab.tsx`：账号池表格（状态、额度、绑定代理/出口 IP、抽卡次数）/ 单账号抽卡历史展开 / 重绑按钮（单号 + 批量）/ 手动添加账号（保留既有入口能力）。
- `src/shared/api/arena.ts`：API client（复用 `src/shared/api-client` 既有模式）+ EventHub 订阅 hook。

### 5.9 接线修复（P0 必做）

1. `backend/main.py` lifespan：加载 `config/arena_automation.yaml`（缺失 → 默认 `enabled=false`，保持现状不炸）；`enabled` 时 `init_arena_service(db_path=data/arena.sqlite, encryption_key=derive_arena_key(machine_token, machine_id), config=...)`；app shutdown 时 `close()`。
2. 新增 `config/arena_automation.yaml`（§5.1，默认全关）。
3. `temporary_mail/tenminmail.py` + provider 注册表（`__init__.py` 增加 `get_provider(name)` 工厂；mailtm 后续补）。
4. EventHub 注册 §5.7 各主题。

## 6. 文件清单

**新增**

| 文件 | 说明 |
|---|---|
| `backend/services/arena_protocol.py` | 协议客户端（注册+抽卡原语，常量单点区，curl_cffi/httpx 双后端） |
| `backend/services/arena_registration.py` | 批量注册 job（线程池、结果导出） |
| `backend/services/arena_draw_engine.py` | 抽卡引擎（draw_once、门闸、换 IP 循环） |
| `backend/services/arena_proxies.py` | ProxyPool / ProxyApi / 出口探测 / rebind |
| `backend/services/proxy_relay.py` | 本地最小 CONNECT 中转（纯 stdlib） |
| `backend/services/temporary_mail/tenminmail.py` | 10minutemp.one provider |
| `electron/arena-token-window.ts` | 离屏 reCAPTCHA 窗口 + IPC |
| `src/features/arena/**` | 三页签 UI |
| `src/shared/api/arena.ts` | 前端 API client |
| `config/arena_automation.yaml` | 配置（默认全关） |
| `backend/tests/unit/services/test_arena_protocol_parse.py` | parse_models / parse_tier / run_id_from_token / CF 识别（真实抓包 fixture） |
| `backend/tests/unit/services/test_arena_draw_gate.py` | 门闸阶梯 / 衰减 / CF_HOLD / switch_level |
| `backend/tests/unit/services/test_arena_proxies.py` | 4 格式解析 / 轮转 / rebind 同 sid |
| `backend/tests/unit/services/test_proxy_relay.py` | 本地 fake 上游验证最小 CONNECT 语义 |
| `backend/tests/unit/services/test_tenminmail.py` | httpx MockTransport 全链路 |
| `backend/tests/integration/test_arena_registration_api.py` | 注册 job API（协议+邮箱 mock） |

**修改**

| 文件 | 改动 |
|---|---|
| `backend/api/arena_routes.py` | §5.7 新路由 |
| `backend/services/arena_accounts.py` | schema 迁移 + rebind/credits/draws 访问方法 |
| `backend/config/arena_automation.py` | 配置扩展（registration/draw/proxy 子模型 + yaml 加载） |
| `backend/main.py` | lifespan 接线（§5.9.1） |
| `backend/services/temporary_mail/__init__.py` | provider 注册表 |
| `electron/main/**` | token 窗口生命周期挂接 |
| `backend/requirements-optional.txt` | `curl_cffi`（main 通道，注释同 matplotlib 待遇） |
| `docs/technical/50-arena-source-license-audit.md` | 增补 ArenCard 源（无 LICENSE → 仅借鉴逻辑） |

## 7. 阶段划分（每阶段可独立验收）

| 阶段 | 内容 | 验收标准 |
|---|---|---|
| P0 接线修复 | main.py init + yaml + tenminmail provider + EventHub 主题 | `POST /api/v1/arena/accounts` 不再 503；tenminmail 单测绿；默认关时行为与现状一致 |
| P1 协议注册 | `arena_protocol.py` + `arena_registration.py` + 注册 API + 导出 | 协议 mock 集成测试绿；真实冒烟：3 账号注册成功、额度回写、导出格式与参考一致 |
| P2 代理子系统 | `proxy_relay.py` + `arena_proxies.py` + DB 迁移 + rebind + 测试端点 | relay 对 fake 上游（验证 CONNECT 无 Host）单测绿；`/proxies/test` 返回出口 IP；rebind 同 sid 场景测试绿 |
| P3 token 窗口 | `electron/arena-token-window.ts` + IPC + `/token-window` | health `ready=true`；mint 出的 token 真实 create-chat 通过（人工冒烟 1 次） |
| P4 抽卡引擎 | `arena_draw_engine.py` + 抽卡 API + 门闸 + 换 IP 循环 + `arena_draws` | 门闸/parse 单测绿；真实冒烟：10 轮抽卡，命中改名、未命中归档、429 触发退避、（有代理时）换 IP 重跑 |
| P5 UI | 三页签 + SSE 日志流 | UI 可完整操作两类 job（启动/停止/日志/导出/重绑） |
| P6 收口 | e2e（playwright 既有 e2e 框架）+ 审计文档增补 + CHANGELOG + 本方案归档 | CI 全绿；`test_arena_*` 既有测试不回退 |

## 8. 测试策略

- **单元**：协议解析（`parse_models/parse_tier/run_id_from_token`/CF 挑战识别，用参考环境真实抓包做 fixture）、门闸状态机、代理池 4 格式、relay CONNECT 语义（本地 fake 上游 server）、tenminmail（MockTransport）。
- **集成**：注册 job（协议客户端 + 邮箱 provider 双 mock，断言账号入库字段与导出内容）、抽卡 job（trigger.dev + SSE 用录制 fixture）、rebind 流程。
- **真实冒烟**（人工执行，记录到 `docs/verification/2026-09-19-aren-card-port.md`）：注册 ×3、抽卡 ×10（含命中/未命中/429 场景）、代理换 IP ×1。
- **兼容**：`backend/tests/unit/services/test_arena_accounts.py`、`test_arena_adapter.py`、`backend/tests/integration/test_arena_registration_flow.py` 全绿不回退。

## 9. 风险与回退

| 风险 | 概率 | 影响 | 回退 |
|---|---|---|---|
| Chromium 106（Electron 21）出 reCAPTCHA V3 分数偏低 | 中 | 协议抽卡被拒率高 | token 窗口实测拒绝率；超阈值 → UI 显式切「浏览器路径抽卡」（ArenaAdapter 真发消息 + CDP 观测判模型，既有能力）；注册路径不受影响（无需 token） |
| curl_cffi 在个别平台安装失败 | 低 | 协议路径指纹降级 | 懒加载回退 httpx（提示）→ 浏览器路径；Win7 本来就走浏览器路径 |
| 10minutemp.one 域名/接口波动 | 中 | 注册失败 | provider 可插拔（mailtm 预留）；域名轮换列表可配置；失败账号可手动补 |
| arena 端点 / token 结构变更 | 中 | 协议路径失效 | 常量单点区（D8）+ 录制 fixture 回归；浏览器路径不受端点变更影响 |
| 账号风控 / 封禁 | 固有 | 账号损失 | 门闸 + 一号一 IP + 注册与抽卡 IP 一致（bindings 语义）+ 并发上限 5 + 保留手动账号入口 |
| 与既有 spec 非目标冲突（「不做未授权账号创建」） | — | 范围争议 | 本方案为用户显式授权的扩展：注册仅限用户本人发起的 job，feature-flag 独立（`registration.enabled`），凭据仍 Fernet 加密、不落日志；在审计与 CHANGELOG 中明示 |

## 10. 附录：实测协议常量（取自 reference，实现时单点维护）

```python
ARENA = "https://arena.ai"
TRIGGER_API = "https://api.trigger.dev"
MAIL_SITE = "https://10minutemail.one/zh"
MAIL_API = "https://web.10minutemail.one/api/v1"
MAIL_DOMAINS = ["dbwot.com", "ygwpr.com", "imxwe.com"]          # catch-all 轮换
JWT_RE = r"eyJhbGciOiJIUzI1NiJ9\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"
VERIFY_LINK_RE = r"https://arena\.ai/nextjs-api/callback\S+"
RECAPTCHA_V3_KEY = "6LeTGMcsAAAAALuIlkVwIxaAuZA8VledA6d3Nnb0"   # Enterprise V3
RECAPTCHA_ACTION = "agentic_chat_submit"
TOKEN_PAGE = "https://arena.ai/agent/"
DRAW_TEXT = "1+1="
GATE_LADDER = (15.0, 30.0, 60.0, 90.0)
GATE_DECAY_AFTER = 240.0
CF_HOLD = 180.0
CREATE_CHAT_BACKOFFS = (0, 15, 30, 60)
CF_MARKERS = ("just a moment", "cf-chl", "attention required")
PROXY_SID_RE = r"sid-([A-Za-z0-9]+)"
TIER_RE = r"^(?P<base>.+?)[.-](?P<tier>low|medium|high|max)(?:[.-](?P<date>\d{6,8}))?$"
MODEL_NAME_RE = r'"modelName"\s*:\s*"([^"]{2,80})"'
```

端点速查：

| 用途 | 方法 | 路径 |
|---|---|---|
| 创建用户 | POST | `/nextjs-api/sign-up` |
| 发验证邮件 | POST | `/nextjs-api/sign-up/magic-link` |
| 设密码 | POST | `/nextjs-api/auth/set-password` |
| 登录 | POST | `/nextjs-api/sign-in/email` |
| 个人信息 | GET | `/api/me` |
| 查额度 | GET | `/api/billing/balance` |
| 建会话（抽卡） | POST | `/nextjs-api/stream/create-chat` |
| 会话凭据 | POST | `/api/chat/trigger-token` |
| 输出流 | GET(SSE) | `/ai-proxy/realtime/v1/sessions/{sid}/out` |
| 改会话名 | PATCH | `/api/history/agentic/{sid}` |
| 归档/取消 | POST | `/api/chat/{sid}/archive` / `unarchive` |
| 删会话 | DELETE | `/api/chat/{sid}` |
| run 事件 | GET | `api.trigger.dev/api/v1/runs/{runId}/events` |
| span 详情 | GET | `api.trigger.dev/api/v1/runs/{runId}/spans/{spanId}` |
