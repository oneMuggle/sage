# MCP 会话交付物：ArenCard 能力移植到 Sage 的实现方案（v2 · 已核实版）

日期：2026-09-19 ｜ 参考实现：`reference/ArenCard`（Python + Tkinter + WebView2，Windows，已实测）
目标：sage `main` 通道（FastAPI 后端 + Electron 21 / Chromium 106 + React 18 前端）
关联文档：

- `docs/superpowers/specs/2026-09-16-arena-automation-model-probe-design.md`（既有设计 spec，本文多处引用其章节号）
- `docs/technical/50-arena-source-license-audit.md`（移植纪律）
- `docs/mcp-aren-card-implementation.md`（上一轮会话草案；本文在其基础上**核实并修正 4 处**，差异见附录 C）

本文所有结论均已对照源码核实，引用格式为 `文件:行号`。

---

## 0. 结论速览

**一句话**：sage 已经有"账号池 + 浏览器路径判模型"的地基，缺的是 ArenCard 的**纯协议快路径**（注册 6 步、抽卡 8 步）及其三个支撑子系统（TLS 指纹 HTTP、本地 CONNECT 代理中转、reCAPTCHA V3 出票窗口）。移植量集中在 8 个新后端模块 + 1 个 Electron 窗口 + 1 个前端 feature 目录，分 7 个阶段可独立验收。

**三件必须先做的事**（不做则后面全是返工）：

1. **S0 可行性尖峰**：Electron 21 = Chromium 106，而参考实现用的是 WebView2（常青 Chromium）。**106 能否出被 arena 接受的 reCAPTCHA Enterprise V3 token 是本项目最大的未知数**，必须用半天先验证，再决定抽卡路径的形态（详见 §8 S0）。
2. **修复密钥不稳定**：spec §7.1 规定 Fernet key 由 `SAGE_LOCAL_AUTH_TOKEN` 派生，但 `electron/main.ts:465` 每次后端重启都 `randomBytes(32)` 重新生成 → 账号密码**重启后永久无法解密**。必须改为持久化主密钥（§5.2）。
3. **修复接线断裂**：`backend/main.py:895-898` 只 `include_router(arena_router)`，lifespan 里从未调用 `init_arena_service()` → 生产环境所有 `/api/v1/arena/*` 恒 503（`backend/api/arena_routes.py:63-66`）。

**好消息（草案遗漏的复用点）**：`backend/services/run_trace_resolver.py`（380 行，已有单测）**已经实现了抽卡协议第 4~6 步的全部解析逻辑**——SSE 帧解析、`public-access-token` 提取、JWT 校验、run_id 提取、模型/供应商/token 数/成本解析、8×3s 重试。抽卡引擎应复用它而不是重写一套解析器（§4 D1、§5.5）。

**需要用户拍板的决策点**：见 §12（5 项，其中 1 项与既有 spec 的非目标直接冲突）。

---

## 1. 现状盘点（已核实）

### 1.1 可直接复用的资产

| 模块 | 位置 | 提供什么 | 备注 |
|---|---|---|---|
| 账号池 | `backend/services/arena_accounts.py`（250 行） | SQLite + Fernet 加密凭据、5 态状态机（available/reserved/degraded/disabled/destroyed）、LRU `reserve_account`、失败隔离（阈值 3）、`derive_arena_key`（PBKDF2-SHA256/480k） | `derive_arena_key:29` 逻辑正确，**但入参 token 来源不稳定**（§1.3-A） |
| 账号 REST | `backend/api/arena_routes.py`（173 行） | `/api/v1/arena/accounts` CRUD + isolate/enable/stats；feature-flag 403 门控（`:69`）；模块级单例 `init_arena_service`（`:46`） | 已有单测 `backend/tests/unit/api/test_arena_routes.py` |
| **Trigger.dev 解析** | `backend/services/run_trace_resolver.py`（380 行） | `parse_sse_frame:55`、`extract_public_access_token:66`（同时支持 headers 为 list-pair 与 dict 两种形态）、`decode_jwt_payload:90`、`extract_run_id_from_claims:109`（新 `run` claim + 旧 `scopes`）、`validate_jwt_claims:136`（iss/aud/exp/pub）、`parse_token_count:177`、`parse_cost_usd:198`、`extract_models_from_trace:215`（tabler-cube 模型名 / ai-provider-* 供应商 / tabler-hash token / tabler-currency-dollar 成本）、`RunTraceResolver:273`（8 次 × 3s 重试） | **抽卡协议 4~6 步已就绪**，且已被 `arena_observation.py:14` 消费 |
| 浏览器路径 | `backend/services/arena_adapter.py`（210 行） | CDP 驱动：`check_login_state`、`detect_captcha`、`fill_login`（逐字符输入防机器人）、`fill_verification_code`、`submit_message`、`wait_for_response`、`ThinkingFilter` | 选择器集中在 `_SELECTORS:50`，易维护 |
| CDP 观测 | `backend/services/arena_observation.py`（197 行） | 常驻 CDP 网络事件 → 证据 → `RunTraceResolver` → verdict | 慢路径，依附浏览器会话 |
| 判模型内核 | `backend/services/model_probe_py/{classify,idmap,registry}.py` + `model_probe_worker.py` | 证据加权与判定（`run.trace.model` 权重 1.00）、python/node 双后端 | 抽卡结果可复用同一套 idmap 归一化 |
| 邮箱抽象 | `backend/services/temporary_mail/base.py`（72 行） | `TemporaryMailProvider` ABC（async）+ `Mailbox` dataclass | **接口不匹配注册流程**（§1.3-B） |
| 配置模型 | `backend/config/arena_automation.py`（25 行） | pydantic `ArenaAutomationConfig`，`extra=forbid`，v1 兼容写法 | 无 yaml 加载器、无 yaml 文件 |
| 本地鉴权 | `backend/api/local_auth.py` | `SAGE_LOCAL_AUTH_TOKEN` 能力令牌 + 中间件；`get_local_auth_token():54` | 新增路由自动受保护 |
| HTTP 重试 | `backend/services/http_retry.py` | `retry_on_status`（`arena_adapter.py:19` 已在用） | 协议层可复用 |
| yaml 配置惯例 | `backend/main.py:185-220`（`_build_compute_adapter`）+ `backend/config/ghm.yaml` | 「读 `backend/config/<name>.yaml`；文件缺失/enabled=false → 返回 None；解析异常 → warning 降级，不阻塞启动」 | **arena yaml 应放 `backend/config/arena_automation.yaml`**，不是仓库根 `config/` |
| 可写数据目录惯例 | `backend/main.py:403-412` | `${SAGE_USER_DATA_DIR}` 优先，dev 回退 `<project>/backend/data/` | arena.sqlite / 导出文件都应走这里 |
| 前端 NDJSON 流 | `backend/api/orch_run_control.py:91`（`after_seq` 续传）+ `electron/relay.ts:247` + `electron/eventRouting.ts:15` + `src/shared/api/orchEventStream.ts` | 「后端 NDJSON 流 → Electron 主进程中继 → renderer `listen(channel)`」完整链路 | 任务日志流直接照抄这套（§5.10） |
| 次级窗口惯例 | `electron/main.ts:1575-1601`（`sage:artifact-window:open`）、`electron/skillsIpc.ts` 注册模式（`main.ts:1627-1636`） | `isTrustedRenderer` 守卫 + 模块化 IPC 注册 + `() => backendAuthToken` 注入 | token 窗口照此形态落地 |
| 可选依赖惯例 | `backend/requirements-optional.txt`（69 行，全部注释态 + 每节「为什么单独放」说明）、`backend/requirements-py38.txt` | 懒加载 + 缺失优雅降级 | curl_cffi 按同待遇（§4 D3） |
| 测试骨架 | `backend/pytest.ini`（testpaths=tests、markers unit/integration/e2e/slow、单测 120s 超时）；已有 `test_arena_accounts.py`、`test_arena_adapter.py`、`test_arena_observation.py`、`test_run_trace_resolver.py`、`integration/test_arena_registration_flow.py` | 新增测试有明确落点 | 120s 超时意味着**任何单测不得真连网/真等邮件** |

### 1.2 缺口（核实为「零」的部分）

| 缺口 | 核实方式 |
|---|---|
| 协议客户端（sign-up / magic-link / set-password / create-chat / trigger-token） | 全仓搜索 `magic-link\|create-chat\|trigger-token\|curl_cffi\|recaptcha` 仅命中 `backend/services/arena_adapter.py`（选择器里有 `recaptcha` 字样）与 `run_trace_resolver.py`（trigger.dev 读取） |
| `backend/config/arena_automation.yaml` | `find` 全仓无该文件；`backend/config/` 只有 `arena_automation.py` 与 `ghm.yaml` |
| 邮箱 provider 实现 | `backend/services/temporary_mail/` 只有 `__init__.py`(7 行) + `base.py`(72 行)，无 `mailtm.py`（而 config 默认值恰是 `mail_provider="mailtm"`） |
| 代理子系统（动态 API / 粘贴池 / CONNECT 中转 / 出口探测 / rebind） | 全仓无 `proxy_relay`、无 `haiwaidaili`、无 `ipify` 相关代码 |
| 429 门闸、换 IP 循环、reCAPTCHA 拒绝计数 | 无 |
| 抽卡引擎、抽卡历史表 | 无 `arena_draws` 表，无 draws 相关字段 |
| token 出票窗口 | `electron/` 下无 arena 相关文件（46 个文件逐一核对） |
| 前端 arena 界面 | `src/` 下无 arena 相关文件；`src/App.tsx:196-212` 路由表无 `/arena` |
| 运行库 | 全仓无 `arena.sqlite`（服务从未被初始化，**因此没有存量数据迁移负担**） |

### 1.3 既有实现的三个硬伤（P0 必修）

**A. 加密密钥不稳定 → 账号密码重启即失效**

- spec §7.1（第 556 行）："Passwords encrypted with Fernet key derived from `SAGE_LOCAL_AUTH_TOKEN`"。
- 实际：`electron/main.ts:465`
  `backendAuthToken = process.env.SAGE_LOCAL_AUTH_TOKEN ?? randomBytes(32).toString('base64url')`
  —— 每次拉起后端（每个 generation）都重新生成；`backend/api/local_auth.py:49-51` 在独立/dev 启动时同样 `secrets.token_urlsafe(32)`。
- 后果：`derive_arena_key(token, machine_id)` 每次启动得到不同 key，`Fernet.decrypt` 全部 `InvalidToken`。账号池是"跨重启持久化"需求（spec G4），当前设计无法满足。
- 另外：spec §7.1 要求的 `machine_id`（hostname + username + MachineGuid 的哈希）**全仓没有实现**（搜索 `MachineGuid|/etc/machine-id|getnode` 零命中）。

**B. 邮箱 ABC 与注册流程不匹配**

- `base.py` 只暴露 `wait_for_code(...) -> Optional[str]`（4~8 位数字验证码，`DEFAULT_CODE_PATTERN:27`）。
- 注册流程需要的是**从邮件正文提取 URL**（`https://arena.ai/nextjs-api/callback...`），再 GET 该 URL 跟随重定向取 `set-password?token=`（`reference/ArenCard/arena_core.py:443-495`）。
- `Mailbox` 强制 `password` 与 `provider_token` 字段；而 10minutemail 是 catch-all 免注册（本地名随机生成，无邮箱密码，token 是站点 JWT）。

**C. 服务层直接返回明文密码 + N+1 查询**

- `arena_accounts.py:142-165` `get_account()` 无条件解密并返回 `password` 字段；`arena_routes.py:40` 靠路由层 `_strip_password` 兜底。防御位置错了一层——任何新调用方（抽卡引擎、导出、日志）都可能把明文密码带出去。
- `arena_accounts.py:129-140` `list_accounts()` 每行调用 `get_account()` **两次**（一次过滤、一次取值），N 条账号 = 2N 次查询 + 2N 次解密。

---

## 2. 参考实现提炼（逐条对照源码核实）

### 2.1 注册：纯协议 6 步（`reference/ArenCard/arena_core.py:443-495`）

| # | 步骤 | 关键细节（源码位置） |
|---|---|---|
| 1 | 取临时邮箱 | `GET https://10minutemail.one/zh` 从 HTML 正则提 JWT（`arena_core.py:250-262`，有效期 23h，失败重试 3 次）；本地名 = 随机 10 位 `[a-z0-9]`，域名从 `MAIL_DOMAINS`（`:36`，`dbwot.com`/`ygwpr.com`/`imxwe.com`）轮换，catch-all 免注册（`new_address:276`） |
| 2 | 创建用户 | `POST /nextjs-api/sign-up`，body `{recaptchaToken:"", provisionalUserId:<uuid4>}` → `access_token`（`create_user:340`）。**服务端不校验 reCAPTCHA**，所以注册不需要 token 窗口 |
| 3 | 发验证邮件 | `POST /nextjs-api/sign-up/magic-link`，body `{email, fullName:"Arena User", shouldLinkHistory:false, marketingConsent:false, registeredCountryCode:"US"}`（`send_magic_link:352`） |
| 4 | 收信取链接 | 轮询 `GET {MAIL_API}/mailbox/{email}`，headers 必带 `Authorization: Bearer <JWT>` + `X-Request-ID`(uuid4 hex) + `X-Timestamp` + Origin/Referer（`_headers:266`）；401 → 刷 JWT 重试一次（`fetch_mails:283`）；正文按 `https://arena\.ai/nextjs-api/callback\S+` 提取，并做 `\u0026`→`&`、去反斜杠清洗（`wait_for_link:300-322`）；随后 `GET` 该链接跟随重定向，从最终 URL 正则 `token=([^&]+)` 取 set-password token（`confirm_link:368`） |
| 5 | 设密码 | `POST /nextjs-api/auth/set-password` `{password, token}`；密码规则 ≥8 位且含大写+小写+数字+特殊符（`validate_password:420`、`gen_password:428`，14 位、`SystemRandom`、4 类字符保底后洗牌） |
| 6 | 验证 + 查额度 | `POST /nextjs-api/sign-in/email` 登录；**失败则用同一 token 重设一次密码再登录**（`register_one:474-482`）；`GET /api/me` 取 user id；`GET /api/billing/balance` 取 `creditsRemaining`（4 次 × 3s 重试，`get_balance:388`） |

### 2.2 抽卡：纯协议 8 步（`reference/ArenCard/arena_draw.py`）

模型是**对话级**分配的，所以「一抽 = 一个新会话」。

| # | 步骤 | 细节 |
|---|---|---|
| 1 | 登录 | `POST /nextjs-api/sign-in/email`；`DrawClient.logged` 会话内复用，不重复登录（省限流额度） |
| 2 | 取 V3 token | 常驻真浏览器加载 `https://arena.ai/agent/`，`grecaptcha.enterprise.execute("6LeTGMcsAAAAALuIlkVwIxaAuZA8VledA6d3Nnb0", {action:"agentic_chat_submit"})`（`token_server.py:28-44`）。token 约 2 分钟内可复用 |
| 3 | 建会话 | `POST /nextjs-api/stream/create-chat`，body `{message:{id:uuid4, role:"user", parts:[{type:"text",text:"1+1="}]}, timezone:"Asia/Shanghai", recaptchaV3Token}` → `{id}` = sid（`DRAW_TEXT:34`） |
| 4 | 取会话凭据 | `POST /api/chat/trigger-token` `{sessionId}` → JWT |
| 5 | 订阅输出流 | `GET /ai-proxy/realtime/v1/sessions/{sid}/out`（SSE，`Authorization: Bearer`、`Accept: text/event-stream`、`x-trigger-source: sdk`、`x-trigger-realtime-streams-version: v2`）→ 帧内 `records[].headers` 的 `public-access-token`（`read_run_token`，90s 超时，按 `\n\n` 切帧） |
| 6 | 读模型名 | `run_id` 从 JWT `scopes` 的 `read:runs:<id>` 取（`run_id_from_token`）；`GET https://api.trigger.dev/api/v1/runs/{runId}/events`（8 次 × 3s，401/403/404 立即停止）；`message=="ai.streamText.doStream"` 的事件里 `style.icon="ai-provider-<provider>"` 得供应商、`style.accessory.items[icon=="tabler-cube"].text` 得官方模型名；**内部配置名**从整段 JSON 正则 `"modelName"\s*:\s*"([^"]{2,80})"` 提取（`parse_models`），可再拆档位 `low/medium/high/max`（`_TIER_RE:282`） |
| 7 | （可选）思考强度 | `GET /api/v1/runs/{runId}/spans/{spanId}`：`token.usage.recorded` span 的 properties 顶层有 `modelName/provider/inputTokens/outputTokens/reasoningTokens/cacheReadTokens`（`USAGE_TOP:266`）；`ai.streamText.doStream` span 是点号路径（`STREAM_KEYS:270`），作为弱证据兜底；最多读 8 个 span、间隔 0.25s、遇 429 立即停止（`read_usage`）。**usage 比模型名晚落盘**，所以要档位/推理量时必须 `want_internal=True` 多等（`fetch_run_events`） |
| 8 | 处置 | 命中（官方名或内部名任一匹配正则，`model_matches`；`require_reasoning` 时零推理 token 视为不命中）→ `PATCH /api/history/agentic/{sid} {title}` 改名为 `内部名·r<reasoningTokens>`（截断 100 字）并保留；未命中 → 归档 `POST /api/chat/{sid}/archive`（失败自动退化为 `DELETE /api/chat/{sid}`）/ 直接删除 / 保留 |

### 2.3 限速门闸与换 IP（必须原样继承的经验值）

- **双层节奏**：全局最小请求间隔 `base_gap`（所有账号共用）+ 每账号独立退避。等待顺序固定为「本账号 429 退避 → 全局间隔 → 本账号被抬高的间隔」（`throttle:86`）。
- **每账号门闸**（key = 邮箱本地名，`gate_key:164`）：阶梯 `GATE_LADDER=(15,30,60,90)`（`:134`）；每次 429 抬一级并把该账号建会话间隔抬到 `min(60, 5*(level+1))`；`GATE_DECAY_AFTER=240`（`:135`）秒内无新 429 自动降一级（`note_rate_limited:192`、`gate_wait:217`）。
- **Cloudflare 挑战识别**：429 响应体前 800 字含 `just a moment` / `cf-chl` / `attention required`，或（含 `cloudflare` 且是 HTML）→ **等待无效，必须换 IP**；命中后 `CF_HOLD=180`（`:109`）秒内该出口视为已死（`_is_cf_challenge:181`）。
- **轮内换 IP**：`set_switch_level(n)`（`:113`）——阶梯到第 n 档（或命中 CF）就中止本轮，`draw_once` 返回 `switch=True`，上层重绑代理后**整轮重跑且不计失败**。
- **reCAPTCHA 拒绝**：每号 + 全局双计数（`note_recaptcha_reject:121`、`rej_count:129`）；被拒 → 等 10s 换新 token；429 → 等 20s 换新 token；建会话 backoff 序列 `(0,15,30,60)`，**同一轮内复用同一 token**（token 2 分钟有效）；全局拒绝数超阈值 → 换 token 浏览器的出口 IP。
- **一号一 IP**：注册时用的代理即该账号绑定 IP，抽卡默认沿用；`proxy_sid` 从代理 URL 提 `sid-XXXX`（辣酱会话 ID），代理池续期后按同 sid 找回同一条实现「重绑同 IP」（`proxy_sid`、`rebind`）。
- **出口探测刻意宽容**：`proxy_alive` 双端点轮试（ipify + ifconfig.me）、8s 超时——旧版单端点 6s 会把可用 IP 判死（源码注释明确记录）。

### 2.4 代理子系统

- **本地 CONNECT 中转（关键专利点，`proxy_relay.py`）**：辣酱类代理**CONNECT 只要带 Host 头就拒绝**（最小 CONNECT → 200；+Host → 拒；+UA → 200；+Proxy-Connection → 200），而 libcurl/curl_cffi 的 CONNECT 必带 Host → 直连必败。解法：curl_cffi → `127.0.0.1:<本地端口>`（自建 relay，用 `CONNECT host:port HTTP/1.0` + 可选 `Proxy-Authorization`，**绝不带 Host**，`proxy_relay.py:116-119`）→ arena.ai，TLS 端到端所以指纹不丢。
- **端口必须 bind 0 交系统分配**（`proxy_relay.py:45-66`）：Windows `SO_REUSEADDR` 允许多进程重复绑定同一固定端口，实测 11 个进程同听 20000，导致实例间 IP 隔离彻底失效。
- **动态代理 API**（`arena_core.py:47-110`）：`api.haiwaidaili.net/abroad` 风格，params `token/num=1/format=2/protocol/country/sep=1/csep=""`，返回 `{data:[{ip,port}]}`，兼容 dict/list/str 三种行形态，输出统一 `scheme://host:port`。
- **粘贴代理池**（`arena_core.py:112-233`）：`split_credentials:139` 用「哪段像端口 + 哪段像主机」启发式兼容 4 种格式（`host:port:user:pass`、`user:pass:host:port`、`user:pass@host:port`、`host:port@user:pass`）；按 `[\r\n,;\t ]+` 切分、去重、错误带行号；顺序/随机轮转（线程安全）。

### 2.5 token 服务（`token_server.py`）的三个硬坑

1. **无头浏览器出 V3 token → 100% 被 arena 拒**；有头浏览器/playwright 可过但依赖重；WebView2 可过且系统自带（文件头注释记录的实测结论）。→ **sage 用 Electron 隐藏 BrowserWindow 等价替代**，但 Chromium 106 的通过率必须实测（§8 S0）。
2. **离屏/隐藏窗口会被节流**：窗口放屏幕外被 Chromium 判为"被遮挡"→ 定时器节流 → grecaptcha 长时间不回调。参考用 4 个开关关闭节流：`--disable-background-timer-throttling`、`--disable-backgrounding-occluded-windows`、`--disable-renderer-backgrounding`、`--disable-features=CalculateNativeWinOcclusion`（`token_server.py:239-247`）。Electron 侧需 `app.commandLine.appendSwitch` + `webPreferences.backgroundThrottling:false`。
3. **就绪判定不能只看 readyState**：必须再探一次 `window.grecaptcha?.enterprise`；出票失败要重载页面重试一次（`ensure_alive:73`、`mint_token:105-123`）。源码注释明确记录"之前写错了导致启动后第一次必失败"。
4. （附带）走代理时 Chromium 忽略 `--proxy-server` 里的账号密码 → 统一经本地 relay；并加 `--disable-quic`（UDP 443 过不了代理）。

### 2.6 实测纪律清单（移植时逐条继承）

1. **TLS 指纹是生死线**：原生 requests 被 Cloudflare 判脚本（403）；必须 curl_cffi `impersonate="chrome131"`。
2. **绝不手写 User-Agent**：交给 impersonate 统一管理，否则出现「Windows UA + Mac Chrome 指纹」矛盾组合（`arena_core.py:330-334` 注释）。
3. **邮箱服务永远直连**：10minutemail 会拉黑部分机房/代理 IP（实测 10 条约 4 条 TLS 被断）；只有 arena 侧需要代理且 IP 要一致。
4. **注册并发 3~5**：瓶颈是邮件到达速度；10minutemail 100 并发查询无速率限制。
5. **单账号注册 15~30s**，额度约 15000 credits/天。
6. **每账号独立 HTTP session**（cookie 隔离）。
7. **arena.ai 偶发读超时**（实测一天 4 次）→ 统一 3 次重试、退避 `1.5*(i+1)`。
8. **登录态复用**：同一账号一轮任务内只登录一次。
9. **`public-access-token` 只用于读 trace，绝不落库/落日志**（与 spec §7.2 一致）。
10. **失败归因要保护**：CHANGELOG 记录过一次"回收风暴"（95 次回收 → 47 次 reCAPTCHA 拒 → 0 命中），修复方式是加 120s 冷却 + 失败归因保护。抽卡引擎必须有等价的熔断（§5.8）。

---

## 3. 总体架构

```
┌─ 前端 src/features/arena（三页签：注册 / 抽卡 / 账号）─────────────────┐
│  src/pages/Arena.tsx（lazy 路由 /arena）                              │
│  src/shared/api/arenaApi.ts ── backendRequest 漏斗（Electron 中继）    │
│  任务日志：listen('arena-job-{jobId}-seq-{n}')  ← NDJSON 中继          │
└───────────────┬───────────────────────────────┬──────────────────────┘
                │ REST /api/v1/arena/*          │ IPC（次级窗口控制）
┌───────────────▼───────────────┐   ┌───────────▼──────────────────────┐
│ FastAPI backend               │   │ Electron main                    │
│  api/arena_routes.py（扩展）   │   │  arenaTokenWindow.ts（新）        │
│  ── 任务层 ──                  │   │   隐藏 BrowserWindow              │
│  arena_jobs.py（JobStore+seq） │   │   loadURL(arena.ai/agent/)       │
│  arena_registration.py         │◄──┤   grecaptcha.enterprise.execute  │
│  arena_draw_engine.py          │推 │   POST /arena/token-window/push  │
│  ── 支撑层 ──                  │送 │   GET  /arena/token-window/state │
│  arena_protocol.py（注册+抽卡） │tok│   （轮询，2s；驱动按需出票/换 IP） │
│  arena_token_cache.py          │en │  生命周期随 app；partition 隔离    │
│  arena_proxies.py + proxy relay│   └──────────────────────────────────┘
│  arena_http.py（curl_cffi/httpx）
│  temporary_mail/tenminmail.py
│  ── 既有地基 ──
│  arena_accounts.py（+迁移）  run_trace_resolver.py（复用解析）
│  arena_adapter.py + arena_observation.py（浏览器兜底路径）
└───────────────┬───────────────┘
                │ 出口
   直连 ──或── arena_proxy_relay（127.0.0.1:bind0，最小 CONNECT）──► 上游代理 ──► arena.ai
   邮箱请求恒直连（纪律 3）
```

数据流（抽卡一轮）：`throttle/门闸` → 取 token（缓存，缺失则等待 Electron 推送）→ `create-chat` → `trigger-token` → SSE `/out` → `public-access-token` → `run_id` → `runs/{id}/events` → 解析模型（复用 `run_trace_resolver`）→（可选）`spans/{id}` 读推理量 → 命中改名 / 未命中处置 → 写 `arena_draws` + 追加 job 事件（NDJSON 推 UI）。

---

## 4. 关键设计决策

**D1 · 复用 `run_trace_resolver` 而非重写解析（对草案的修正 1）**
抽卡协议 4~6 步的解析逻辑 sage 已有且有单测。协议路径只新增「取数」与「扩展解析」：

- 复用：`parse_sse_frame` / `extract_public_access_token` / `decode_jwt_payload` / `validate_jwt_claims` / `extract_run_id_from_claims` / `extract_models_from_trace` / `parse_token_count`。
- 新增（放 `arena_trace_ext.py`，纯函数，便于单测）：`extract_internal_names(trace_json)`（`"modelName"` 正则）、`parse_tier(name)`（档位拆分）、`extract_usage(span_detail)`（`USAGE_TOP` 顶层优先、`STREAM_KEYS` 点号路径兜底）。
- 注意两处语义差异，需在实现时对齐并补测试：① `extract_run_id_from_claims:109` 要求 `run_` 前缀，参考实现 `run_id_from_token` 只按 `read:runs:` 前缀切；② resolver 的 `fetch_trace` 是注入式（浏览器路径经 CDP 取数，spec §7.3），协议路径要注入自己的 HTTP fetch（走 `arena_http`，可能经代理）。
- 收益：避免两套解析器漂移；抽卡结果与既有 `model_probe_py/idmap` 归一化天然对齐。

**D2 · token 通道方向：Electron 推、backend 缓存（对草案的修正 2）**
草案写的是"backend 经现有 backend↔Electron 通道取 token"——**该通道不存在**：现有架构里 HTTP 方向恒为 Electron→backend（`electron/invoke.ts`、`electron/relay.ts`），backend 从不调用 Electron。因此：

- Electron 主进程持有隐藏窗口与出票循环；出票成功 `POST /api/v1/arena/token-window/push`（带 `SAGE_LOCAL_AUTH_TOKEN`）。
- backend `arena_token_cache.py` 存 `{token, received_at, exit_ip, ua}`，`get(max_age≈110s)`；抽卡线程取不到时按条件变量等待新推送（最长 `token_wait_sec`），超时即本轮失败并提示"token 窗口不可用"。
- 按需出票与换 IP 由 Electron 轮询 `GET /api/v1/arena/token-window/state`（2s）驱动，返回 `{enabled, needed, reject_count, want_proxy, proxy_url, last_push_age}`。
- 好处：零新增通信方向、backend 无本地 HTTP 客户端依赖 Electron、窗口生命周期随 app、无本地端口暴露；`state` 轮询天然容忍后端重启。

**D3 · curl_cffi 走可选依赖 + 懒加载双后端**
`backend/requirements-optional.txt` 新增一节（注释态 + 「为什么单独放」说明，与 pywin32/pytesseract 同待遇）：curl_cffi 含二进制轮子、仅 main 通道需要、Win7(py38) 通道不装。`arena_http.py` 提供 `make_session()`：优先 `curl_cffi.requests.Session(impersonate="chrome131")`，ImportError 回退 httpx（HTTP/2 + 固定 Chrome UA，接受指纹降级）。能力探测结果通过 `GET /api/v1/arena/capabilities` 暴露给 UI（`fingerprint: "curl_cffi"|"httpx"`），httpx 态下 UI 明示"403 风险高，建议安装 curl_cffi 或改用浏览器路径"。**绝不手写 UA**（纪律 2）。

**D4 · CONNECT relay 原样重写为 sage 模块**
`backend/services/arena_proxy_relay.py`，纯 stdlib（socket/threading/base64/urllib.parse），保留三条实测纪律：最小 CONNECT 不带 Host、`bind(("127.0.0.1", 0))` 系统分配端口、同上游复用同端口。单测用本地 fake 上游断言「收到的 CONNECT 报文里没有 Host 头」。

**D5 · 任务事件走 NDJSON + Electron 中继，不复用 EventHub（对草案的修正 3）**
`backend/orchestration/event_hub.py` 是 orchestration 专用：事件类型固定为 `backend/domain/orch_events.py` 的 `RunEvent`、按 `run_id` 分桶、带 seq 与持久化 repository。把 arena 日志塞进去会污染编排域模型。改为：

- `backend/services/arena_jobs.py`：`JobStore` 持有 job 元数据 + append-only 事件环（`seq` 自增、`deque(maxlen)`），线程安全（任务在线程池里跑）。
- `GET /api/v1/arena/jobs/{job_id}/events?after_seq=N` → `StreamingResponse(media_type="application/x-ndjson")`，完全照 `backend/api/orch_run_control.py:91` 的续传语义。
- Electron：`electron/eventRouting.ts` 增 `parseArenaJobEventName`（`arena-job-{jobId}-seq-{n}`），`electron/relay.ts` 增通用 NDJSON 中继复用（现有 `relayOrchEventsStream:247` 已是同构实现，抽公共函数即可）。

**D6 · 密钥与机器指纹落地（对草案的修正 4，修 §1.3-A）**
新增 `backend/utils/machine_id.py`（spec §7.1 定义：Windows 注册表 `MachineGuid` / Linux `/etc/machine-id` + hostname + username → sha256）与 `backend/services/arena_keystore.py`：

- 主密钥 = `${SAGE_USER_DATA_DIR}/arena/master.key`（32 字节随机，首次创建，权限 0600；Windows 可选用 DPAPI `CryptProtectData` 包裹）。
- Fernet key = `derive_arena_key(token=master_key_b64, machine_id=machine_id())`（沿用既有函数，480k 迭代不变）。
- 明确记录对 spec §7.1 的偏离原因（进程级令牌不稳定），并在 spec/审计文档增补。
- 迁移负担为零：全仓无 `arena.sqlite`（§1.2）。

**D7 · 门闸与账号状态机联动**
429 门闸（阶梯/衰减/CF_HOLD/switch_level）原值移植到 `arena_draw_engine.py` 的 per-account gate；同时：门闸 level ≥ 2 或命中 CF → `record_failure(account_id, reason="rate_limited")`（触发既有失败隔离，阈值 3）；换 IP 成功 → `gate_reset` + 视情况 `release_account`。既有隔离语义不被绕过。

**D8 · 邮箱 ABC 向后兼容扩展**
`base.py` 增 `wait_for_link(mailbox, pattern, timeout_sec, poll_interval_sec)`（默认实现基于 `_fetch_messages` + 正则，子类可覆盖）与 `Mailbox.password`/`provider_token` 改为可空默认值；`__init__.py` 增 `get_provider(name)` 注册表（`tenminmail` 先落地，`mailtm` 保留占位）。`config` 默认值从 `mailtm` 改为 `tenminmail`（因为 mailtm 无实现）。

**D9 · 同步线程模型**
参考实现是线程模型，curl_cffi 也是同步库。协议客户端与任务 worker 全部同步，跑在 `ThreadPoolExecutor`（每类 job 一个池，容量 = `max_concurrent_sessions` / `registration.concurrency`）；FastAPI 路由用 `def`（FastAPI 自动线程池）或 `run_in_executor`。停止 = `threading.Event`，所有 sleep 走可打断封装（对齐 `_sleep_cancellable:74`），等邮件/等流/等 token 三处必须有 cancel 检查点。

**D10 · 数据库加法式迁移**
启动时幂等 `ALTER TABLE ... ADD COLUMN`（吞 `OperationalError` 兼容旧库）+ `CREATE TABLE IF NOT EXISTS arena_draws` + 索引。新增列：`proxy_url / proxy_sid / exit_ip / credits / last_draw_at / draw_count / source`。同时修 §1.3-C：`get_account(..., include_secret=False)` 默认不返回密码，`list_accounts` 单查询完成。

**D11 · Win7 通道零新增**
`requirements-py38.txt` 不加任何依赖；协议路径（curl_cffi）在 py38 通道不可用 → `capabilities` 报 `protocol_path: false`，UI 只提供浏览器路径（既有 `ArenaAdapter` + `ModelObservationService`）。Chromium 106 在两个通道都是上限（`package.json:89` electron `^21.4.4`），所以 S0 尖峰的结论对全平台有效。

**D12 · 移植纪律**
按 `docs/technical/50-arena-source-license-audit.md`：`reference/ArenCard` 无 LICENSE 文件 → **只借鉴逻辑与实测常量，从零重写，不逐字拷贝**；审计文档增补一节记录该新源与处理方式。协议常量集中在 `arena_protocol.py` 顶部常量区（带来源注释），单点维护（附录 A）。

---

## 5. 详细设计

### 5.1 配置层

`backend/config/arena_automation.py` 扩展（保持 pydantic v1 兼容写法、`extra=forbid`）：

```python
class RegistrationConfig(BaseModel):
    enabled: bool = False
    concurrency: int = Field(default=3, ge=1, le=5)   # 纪律 4：3~5
    mail_timeout_sec: int = 90
    domains: List[str] = Field(default_factory=list)  # 空 = 参考默认三域轮换

class DrawConfig(BaseModel):
    enabled: bool = False
    keep_pattern: str = ""            # 空 = 全保留
    require_reasoning: bool = False
    want_reasoning: bool = True       # 读 span 详情（关掉快很多）
    miss_action: str = "archive"      # archive | delete | keep
    rename_hit: bool = True
    base_gap_sec: float = 3.0
    switch_level: Optional[int] = None   # None = 轮内死等
    stream_wait_sec: float = 90.0
    captcha_retries: int = 2
    token_wait_sec: int = 75
    rounds_per_account: int = 10
    reject_threshold: int = 20        # 全局 reCAPTCHA 拒绝熔断（纪律 10）
    cooldown_sec: float = 120.0       # 熔断后冷却

class ProxyConfig(BaseModel):
    enabled: bool = False
    api_url: str = ""
    api_token: str = ""
    country: str = ""
    protocol: str = "http"            # http | socks5
    rotation: str = "per_account"     # per_account | per_wave
    pool_text: str = ""               # 粘贴池，优先于 API
    order: str = "sequential"         # sequential | random

class TokenWindowConfig(BaseModel):
    enabled: bool = False
    use_proxy: bool = False
    poll_interval_sec: float = 2.0
    max_age_sec: float = 110.0
```

`ArenaAutomationConfig` 增 `registration/draw/proxy/token_window` 四个子模型 + `data_dir: Optional[str]`；新增 `load_arena_config(path="backend/config/arena_automation.yaml") -> ArenaAutomationConfig`，完全照 `backend/main.py:185-220` 的 ghm 模式：文件缺失 → 默认（全关）；解析失败 → warning + 默认；`extra=forbid` 保证拼错的 key 会响。

新文件 `backend/config/arena_automation.yaml`：默认全关，逐行中文注释（内容见 §6.4）。

### 5.2 密钥与机器指纹

- `backend/utils/machine_id.py`：`machine_id() -> str`（sha256 hex；Windows `winreg` 读 `HKLM\SOFTWARE\Microsoft\Cryptography\MachineGuid`，Linux 读 `/etc/machine-id`，失败回退 `uuid.getnode()`；拼 hostname + username）。结果进程内缓存。
- `backend/services/arena_keystore.py`：`load_or_create_master_key(data_dir) -> str`（0600、原子写、已存在则读；Windows 可选 DPAPI 包裹，失败降级为裸文件 + warning）、`arena_fernet_key(data_dir) -> bytes`（= `derive_arena_key(master_key, machine_id())`）。
- 单测：machine_id 稳定性、key 文件权限、二次加载得到同一 Fernet key、旧库用错 key 时给出可读错误（而不是 traceback）。

### 5.3 数据层（`backend/services/arena_accounts.py` 增量）

```sql
ALTER TABLE arena_accounts ADD COLUMN proxy_url    TEXT;
ALTER TABLE arena_accounts ADD COLUMN proxy_sid    TEXT;
ALTER TABLE arena_accounts ADD COLUMN exit_ip      TEXT;
ALTER TABLE arena_accounts ADD COLUMN credits      INTEGER;
ALTER TABLE arena_accounts ADD COLUMN user_id      TEXT;
ALTER TABLE arena_accounts ADD COLUMN last_draw_at TEXT;
ALTER TABLE arena_accounts ADD COLUMN draw_count   INTEGER NOT NULL DEFAULT 0;
ALTER TABLE arena_accounts ADD COLUMN source       TEXT;   -- manual | registered

CREATE TABLE IF NOT EXISTS arena_draws (
  id               TEXT PRIMARY KEY,
  account_id       TEXT NOT NULL REFERENCES arena_accounts(id) ON DELETE CASCADE,
  model            TEXT,
  internal         TEXT,
  provider         TEXT,
  tier             TEXT,
  reasoning_tokens INTEGER,
  input_tokens     INTEGER,
  output_tokens    INTEGER,
  cache_read_tokens INTEGER,
  session_id       TEXT,
  run_id           TEXT,
  kept             INTEGER NOT NULL DEFAULT 0,
  miss_action      TEXT,
  error            TEXT,
  created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_arena_draws_account ON arena_draws(account_id, created_at);
```

新方法：`update_binding(id, proxy_url, proxy_sid, exit_ip)`、`update_credits(id, credits, user_id)`、`record_draw(id, draw_row)`、`list_draws(account_id=None, limit=100)`、`draw_stats(account_id)`。
安全修复：`get_account(account_id, include_secret=False)`、`list_accounts` 单查询（不再 N+1）、新增 `get_secret(account_id) -> str` 专供抽卡/注册引擎内部使用（调用点写注释说明为何需要明文）。

### 5.4 HTTP 指纹层（`backend/services/arena_http.py`）

```python
def curl_cffi_available() -> bool
def make_session(proxy_url: str = "", impersonate: str = "chrome131") -> SessionLike
def arena_headers(origin: str = ARENA, referer: str | None = None, extra: dict | None = None) -> dict
```

- `SessionLike` 是最小 duck-type 协议（`get/post/patch/delete/request` + `proxies`），curl_cffi 与 httpx 两个实现都满足；httpx 侧包一层适配器统一 `r.text/r.json()/r.status_code/r.url` 与 `stream=True` + `iter_content` 语义（httpx 用 `client.stream()` 上下文，需要小适配类）。
- 代理入参一律先过 `arena_proxy_relay.local_proxy()`。
- 统一超时与 3 次重试（纪律 7）封装为 `request_with_retry(session, method, url, **kw)`。

### 5.5 协议层（`backend/services/arena_protocol.py` + `arena_trace_ext.py`）

常量区见附录 A。两个客户端类 + 一组纯函数：

```python
class ArenaRegisterClient:      # 每账号一个 session（纪律 6）
    def create_user(self) -> str
    def send_magic_link(self, email: str, full_name: str = "Arena User") -> None
    def confirm_link(self, link: str) -> str          # 跟随重定向取 set-password token
    def set_password(self, token: str, password: str) -> None
    def sign_in(self) -> bool
    def get_me(self) -> dict
    def get_balance(self, retries: int = 4, delay: float = 3.0) -> dict

def gen_password(length: int = 14) -> str             # 对齐 arena_core.py:420-441
def validate_password(p: str) -> bool
def register_one(mail_provider, proxy: str = "", log=None, cancel=None,
                 mail_timeout: int = 90, domain: str | None = None) -> RegisterResult

class ArenaDrawClient:
    def login(self, force: bool = False) -> bool
    def create_chat(self, recaptcha_v3_token: str, text: str = DRAW_TEXT, cancel=None) -> str
    def session_token(self, sid: str) -> str
    def read_run_token(self, sid: str, token: str, wait: float = 90.0, cancel=None) -> str
    def rename_chat(self, sid: str, title: str) -> bool
    def archive_chat(self, sid: str, archive: bool = True) -> bool
    def delete_chat(self, sid: str) -> bool
    def fetch_run_events(self, run_token, run_id, want_internal=False, retries=8, delay=3.0) -> dict
    def fetch_span_detail(self, run_token, run_id, span_id) -> dict
```

- `read_run_token` 内部：按 `\n\n` 切帧 → 复用 `run_trace_resolver.parse_sse_frame` + `extract_public_access_token`；拿到后 `decode_jwt_payload` + `validate_jwt_claims` + `extract_run_id_from_claims`（不通过则继续等下一帧，而不是直接失败）。
- `fetch_run_events` 复用 `extract_models_from_trace`；`want_internal=True` 时循环直到 `extract_internal_names` 非空或重试耗尽（保留 best-effort 返回）。
- `arena_trace_ext.py`：`extract_internal_names`、`parse_tier`、`extract_usage(span_detail, kind)`、`model_matches(model, internal, pattern)`（正则非法时退化为 `re.escape` 字面量，与参考一致）。

### 5.6 代理层（`arena_proxy_relay.py` + `arena_proxies.py`）

```python
# arena_proxy_relay.py（纯 stdlib）
class Relay:  add(upstream) -> int ; local_url(upstream) -> str ; close_all()
def local_proxy(upstream: str) -> str        # 空/本地地址原样返回；异常回退原值

# arena_proxies.py
class ProxyPool:   split_credentials(raw) ; items() ; next() ; count()
class ProxyApi:    fetch() -> str           # haiwaidaili 风格，dict/list/str 三形态兼容
def proxy_exit_ip(proxy, timeout=12) -> str # ipify → ifconfig.me → 回退显示代理主机
def proxy_alive(proxy, timeout=8) -> bool   # 双端点、刻意宽容（§2.3）
def proxy_sid(url) -> str
def rebind(current_url, fresh_pool) -> str  # 同 sid 优先（IP 续期）
class ProxyProvider:  # 门面：pool 优先于 api；rotation=per_account|per_wave；sid 黑名单
    def acquire(self, exclude_sids: set[str]) -> str
```

`ProxyProvider` 增加参考实现里的 **sid 黑名单**（`arena_register.py:2135-2152`）：某条代理连续失败即拉黑 N 分钟，避免反复挑到同一条死代理。

### 5.7 邮箱层（`temporary_mail/`）

- `base.py`：`Mailbox.password`/`provider_token` 改 `= ""` 默认；新增 `wait_for_link(mailbox, pattern, timeout_sec=90, poll_interval_sec=4) -> Optional[str]`（默认实现：轮询 `_fetch_messages` → 正则 → `\u0026`/反斜杠清洗）；`wait_for_code` 保持不变（向后兼容既有测试）。
- `tenminmail.py`：`TenMinMailProvider(TemporaryMailProvider)`，`name="tenminmail"`；`create_mailbox()` = 刷 JWT + 随机本地名 + 域名轮换；`_fetch_messages()` = mailbox 列表 + 逐封取正文（401 刷 JWT 重试一次）；`destroy_mailbox()` = no-op（catch-all 无需销毁）；**恒直连**（纪律 3，构造时显式忽略 proxy 配置并注释原因）。async 接口内部用 `asyncio.to_thread` 包同步 HTTP（保持与 ABC 一致，且不阻塞 event loop）。
- `__init__.py`：`PROVIDERS = {"tenminmail": ..., "mailtm": ...}` + `get_provider(name, **kw)`；未实现 provider 抛可读错误。

### 5.8 任务层

`backend/services/arena_jobs.py`：

```python
@dataclass class JobEvent: seq:int; ts:str; level:str; kind:str; message:str; data:dict
@dataclass class Job: id; kind:"registration"|"draw"; status:"running"|"stopping"|"done"|"failed";
                      created_at; total; done; ok; failed; params; results:list; events:deque
class JobStore: create/get/list/append_event/finish/stop_requested ; 每 job 一个 threading.Event
```

`backend/services/arena_registration.py`：`start_registration_job(count, concurrency, proxy_mode, ...)` → job_id；worker 流程 = 建 mailbox（直连）→ 分配代理（`ProxyProvider.acquire` → `local_proxy`）→ `register_one`（带 cancel 检查点）→ 成功 `create_account(...)` + `update_binding` + `update_credits`，失败记事件继续；结果导出 `export_accounts(job_id)` → `${SAGE_USER_DATA_DIR}/arena/accounts_YYYYMMDD_HHMMSS.txt`，格式 `邮箱----密码----额度`（与参考一致，**安全约束见 §10**）。

`backend/services/arena_draw_engine.py`：

- per-account `Gate`（阶梯 15/30/60/90、衰减 240、CF_HOLD 180、间隔抬高 `min(60,5*(lvl+1))`）+ 全局 `Throttle`（base_gap）；`gate_status()` 供 UI 展示每号剩余等待。
- `draw_once(account, deps) -> DrawResult`：登录 → 取 token（`arena_token_cache.get`，缺失等待/超时失败）→ `create_chat`（backoff 0/15/30/60、同轮复用 token、CF 或到 switch_level → `RateLimited(switch=True)` 上抛）→ `session_token` → `read_run_token` → `run_id` → `fetch_run_events(want_internal=want_reasoning)` → `extract_usage`（可选）→ `model_matches` → 命中改名保留 / 未命中按 `miss_action`（归档失败自动退删除）→ 写 `arena_draws` + `record_draw` + 追加 job 事件。
- job 层循环：`switch=True` → `ProxyProvider.acquire(exclude_sids)` → `proxy_alive` → `update_binding` → `gate_reset` → 整轮重跑（不计失败）；无代理时退化为纯门闸等待。
- 熔断（纪律 10）：全局 reCAPTCHA 拒绝数 ≥ `reject_threshold` → 暂停 `cooldown_sec`、推事件建议"更换 token 窗口出口 IP"（`token_window.want_proxy` 置位让 Electron 重开窗口走新代理）；连续 N 轮 0 命中且拒绝率高 → 自动停止 job 并给出归因摘要（区分"token 被拒"/"429 限流"/"账号被判"），避免重演参考项目的回收风暴。

### 5.9 token 窗口（`electron/arenaTokenWindow.ts`）

```ts
export function registerArenaTokenWindow(deps: {
  register: (channel: string, h: IpcMainInvokeHandler) => void;  // 同 skillsIpc 模式
  getBackendUrl: () => string; getAuthToken: () => string | undefined;
}): void
```

- 窗口：`new BrowserWindow({ show:false, width:1100, height:800, webPreferences:{ contextIsolation:true, nodeIntegration:false, sandbox:true, backgroundThrottling:false, partition:'persist:arena-token' } })`，`loadURL('https://arena.ai/agent/')`。参照 `electron/main.ts:1583` 的次级窗口写法；`partition` 隔离 cookie/proxy，避免污染主窗口会话。
- 反节流：`app.commandLine.appendSwitch` 四个开关（§2.5-2），在 `app.whenReady()` 之前调用；`backgroundThrottling:false` 双保险。
- 就绪：轮询 `document.readyState === 'complete' && !!(window.grecaptcha?.enterprise)`（90s）；出票前再探一次，失败 `reload()` 重试一次（`ensure_alive` 语义）。
- 出票：`webContents.executeJavaScript(JS_MINT)` → 轮询 `window.__tok`（0.15s，30s 超时）→ `POST {backend}/api/v1/arena/token-window/push`（`node-fetch` + `Authorization: Bearer <backendAuthToken>`，同 `electron/invoke.ts` 惯例）。
- 轮询 `GET .../token-window/state`（2s，仅 `enabled` 时）：`needed` → 立即出票；`want_proxy` 变化 → `session.fromPartition('persist:arena-token').setProxy({proxyRules})`（代理走本地 relay 地址，因为 Chromium 忽略代理 URL 里的凭据）+ 重载窗口；`enabled=false` → 关窗停止。
- 诊断：`GET .../token-window/health` 返回 `{ready, count, error, exit_ip, ua, uptime}`，`exit_ip` 由窗口内 `fetch(ipify)` 实测（对齐 `token_server.py` 的 `/ip`）。
- IPC（renderer 可控，`isTrustedRenderer` 守卫）：`sage:arena-token:status` / `:start` / `:stop` / `:reload` / `:pick-proxy`。
- 生命周期：`app.on('before-quit')` 销毁窗口；后端不可达时指数退避重试推送，不崩主进程。
- backend 侧 `arena_token_cache.py`：`push(token, exit_ip, ua)`、`get(max_age)`（条件变量等待）、`health()`、`mark_rejected()`（累加拒绝数，供 state 轮询与熔断）、`request_proxy_change(proxy_url)`。

### 5.10 API 层（`backend/api/arena_routes.py` 增量）

沿用既有约定：`prefix="/api/v1/arena"`、模块级单例、`_check_enabled()` 403 门控；子能力再各自校验 `registration.enabled` / `draw.enabled` / `proxy.enabled`（未开 → 403 + 明确 detail）。所有阻塞调用在 `def`（非 async）路由里执行，交给 FastAPI 线程池。

```
# 能力与配置
GET    /api/v1/arena/capabilities        → {enabled, protocol_path, fingerprint, mail_providers,
                                            token_window:{available,ready}, proxy:{enabled},
                                            browser_path:true, config_snapshot(脱敏)}
GET    /api/v1/arena/config              → 当前生效配置（api_token/pool_text 脱敏）

# 账号（既有）+ 扩展
GET    /api/v1/arena/accounts            → 列表（含 credits/exit_ip/draw_count/proxy_sid，不含密码）
POST   /api/v1/arena/accounts/{id}/rebind    {pool_refresh?:bool} → {proxy_url,exit_ip,proxy_sid}
GET    /api/v1/arena/accounts/{id}/draws     → 抽卡历史

# 注册任务
POST   /api/v1/arena/registration/jobs   {count,concurrency,proxy_mode} → {id}
GET    /api/v1/arena/registration/jobs / /jobs/{id} / /jobs/{id}/results
POST   /api/v1/arena/registration/jobs/{id}/stop
GET    /api/v1/arena/registration/jobs/{id}/export → FileResponse(accounts_*.txt)

# 抽卡任务
POST   /api/v1/arena/draw/jobs           {account_ids|all, rounds_per_account, keep_pattern,
                                          require_reasoning, want_reasoning, miss_action,
                                          rename_hit, base_gap_sec, switch_level} → {id}
POST   /api/v1/arena/draw/jobs/{id}/stop
GET    /api/v1/arena/draw/jobs/{id}      → 含 gate 状态、拒绝计数、每号进度
GET    /api/v1/arena/draws?account_id=&limit=

# 代理
POST   /api/v1/arena/proxies/parse       {pool_text} → {count,items(脱敏),errors}
POST   /api/v1/arena/proxies/test        {proxy_url} → {exit_ip,alive}
POST   /api/v1/arena/proxies/fetch       {country,protocol} → {proxy_url,exit_ip}

# 任务事件流（NDJSON，after_seq 续传；照 orch_run_control.py:91）
GET    /api/v1/arena/jobs/{job_id}/events?after_seq=N

# token 窗口（Electron 专用，需 local-auth）
POST   /api/v1/arena/token-window/push   {token, exit_ip?, ua?} → {ok, age_sec}
GET    /api/v1/arena/token-window/state  → {enabled, needed, reject_count, want_proxy, proxy_url}
GET    /api/v1/arena/token-window/health → {ready, count, error, exit_ip, uptime, last_push_age}
```

### 5.11 前端（`src/features/arena/**` + 页面/路由/i18n）

- `src/pages/Arena.tsx`：顶层 Radix Tabs 三页签；`src/App.tsx` 增 lazy import + `<Route path="arena" .../>`（与 `model-catalog` 同形态，`App.tsx:44-47,211`）。
- `src/features/arena/`（遵守 `src/features/README.md` 依赖规则：不可 import app/processes/widgets）：
  - `RegisterTab.tsx`：数量 / 并发（1-5）/ 代理子模式（API 与粘贴池 + 「解析」「测试代理」按钮）/ 开始-停止 / 实时日志（NDJSON）/ 结果表（邮箱、密码可点显、额度）/ 导出下载。
  - `DrawTab.tsx`：目标模型正则（空=全保留，附常用预设）/ 只留推理开关 / 读思考强度开关 / 未命中策略 / 请求间隔 / 换 IP 档位 / token 窗口状态卡（ready、出票计数、出口 IP、拒绝数）/ 账号多选 / 开始-停止 / 抽卡卡流（官方名、内部名、档位、推理量、会话名、kept、耗时）。
  - `AccountsTab.tsx`：账号表（状态、额度、绑定代理/出口 IP、抽卡次数、最近抽卡）/ 行展开看抽卡历史 / 单个与批量重绑 / 手动添加账号（复用既有 `POST /accounts`）/ 隔离与启用。
  - `arenaJobStream.ts`：`listen('arena-job-{id}-seq-{n}')` 订阅封装（照 `orchEventStream.ts` 的重连与 buffer 上限）。
  - `__tests__/`：Vitest + jsdom，桩 `desktopInvoke`/`backendRequest`（与 `src/widgets/orchestration/__tests__` 同一套 seam）。
- `src/shared/api/arenaApi.ts`：走 `backendRequest` 漏斗（`src/shared/api/backendRequest.ts:20-25`，浏览器环境 fail-closed）。
- `src/widgets/command/commandItems.ts`：增 `{ type:'nav', path:'/arena', label:'Arena', icon:... }`（沿用"高级入口先走命令面板"的 U10 约定，`:40-42`）。
- i18n：`src/shared/lib/i18n/{zh,en}.ts` 同步补全（仓库有 translations 测试，漏 key 会红）。

### 5.12 浏览器兜底路径

不改既有实现，只在 UI 显式提供「浏览器路径抽卡」开关：`ArenaAdapter.submit_message`（发 `1+1=`）+ `ModelObservationService` 观测判模型 → 同一张 `arena_draws` 表、同一套命中/处置策略（处置动作改由 CDP 在页面内执行或调用协议 client 的 archive/delete —— 这两个接口不需要 reCAPTCHA token，可安全复用）。适用场景：Chromium 106 出票被拒、curl_cffi 缺失、Win7 通道。

---

## 6. 接口契约补充

### 6.1 NDJSON 任务事件

```json
{"seq":12,"ts":"2026-09-19T03:11:07","level":"info","kind":"log","message":"[*] 邮箱: ab12cd34ef@dbwot.com","data":{}}
{"seq":13,"ts":"...","level":"info","kind":"draw_result","message":"抽到 gpt-6-astra-low","data":{"account_id":"...","model":"...","internal":"gpt-6-astra-low","tier":"low","reasoning_tokens":0,"session_id":"...","kept":true,"duration_ms":8123}}
{"seq":14,"ts":"...","level":"warn","kind":"gate","message":"429 退避 30s（账号 ab12cd34ef）","data":{"account_id":"...","level":2,"left_sec":30,"cf":false}}
{"seq":15,"ts":"...","level":"info","kind":"progress","message":"3/10","data":{"done":3,"total":10,"ok":2,"failed":1}}
```

`kind` 取值：`log | progress | register_result | draw_result | gate | switch_ip | token | error | done`。前端按 `kind` 分流到日志区/结果表/卡流；`level=error` 高亮。

### 6.2 IPC 通道

| 通道 | 方向 | 用途 |
|---|---|---|
| `arena-job-{jobId}-seq-{n}` | renderer `listen` → main 中继 NDJSON | 任务事件流 |
| `sage:arena-token:status` / `:start` / `:stop` / `:reload` / `:pick-proxy` | renderer `invoke` → main | token 窗口控制 |

### 6.3 错误码约定

沿用既有风格（HTTPException + 中文 detail）：`403 arena automation is disabled` / `403 arena registration is disabled` / `409 max_accounts (N) reached` / `503 arena service not initialized` / `503 token window unavailable`（抽卡时 token 缓存空且等待超时）/ `424 proxy exit unreachable`（可议，或统一 400 + detail）。

### 6.4 `backend/config/arena_automation.yaml`（默认全关）

```yaml
# Arena 自动化（默认全部关闭；开启前请阅读 docs/mcp-aren-card-port-plan.md §10 安全与合规）
enabled: false
max_accounts: 5
max_concurrent_sessions: 2
mail_provider: tenminmail        # tenminmail（已实现）| mailtm（占位）
account_idle_timeout_sec: 300
failure_isolation_threshold: 3
probe_backend: python
registration:
  enabled: false
  concurrency: 3                 # 参考实测建议 3~5（瓶颈是邮件到达）
  mail_timeout_sec: 90
  domains: []                    # 空 = dbwot.com / ygwpr.com / imxwe.com 轮换
draw:
  enabled: false
  keep_pattern: ""               # 正则；空 = 全部保留
  require_reasoning: false
  want_reasoning: true
  miss_action: archive           # archive | delete | keep
  rename_hit: true
  base_gap_sec: 3.0
  switch_level: null             # 429 阶梯到第几档换 IP；null = 轮内死等
  stream_wait_sec: 90
  captcha_retries: 2
  token_wait_sec: 75
  rounds_per_account: 10
  reject_threshold: 20
  cooldown_sec: 120
proxy:
  enabled: false
  api_url: ""
  api_token: ""
  country: ""
  protocol: http
  rotation: per_account
  order: sequential
  pool_text: ""
token_window:
  enabled: false
  use_proxy: false
  poll_interval_sec: 2.0
  max_age_sec: 110
```

---

## 7. 文件清单

**新增（后端）**

| 文件 | 说明 | 估行 |
|---|---|---|
| `backend/utils/machine_id.py` | 机器指纹（spec §7.1 定义） | 60 |
| `backend/services/arena_keystore.py` | 持久化主密钥 + Fernet key 派生 | 90 |
| `backend/services/arena_http.py` | curl_cffi/httpx 双后端 session 工厂 + 重试 | 160 |
| `backend/services/arena_protocol.py` | 注册/抽卡协议原语 + 常量区 | 520 |
| `backend/services/arena_trace_ext.py` | 内部名/档位/usage 解析（扩展 run_trace_resolver） | 130 |
| `backend/services/arena_proxy_relay.py` | 本地最小 CONNECT 中转（纯 stdlib） | 180 |
| `backend/services/arena_proxies.py` | ProxyPool / ProxyApi / ProxyProvider / 探测 / rebind | 260 |
| `backend/services/temporary_mail/tenminmail.py` | 10minutemail.one provider | 170 |
| `backend/services/arena_jobs.py` | JobStore + 事件 seq + NDJSON 序列化 | 180 |
| `backend/services/arena_registration.py` | 批量注册编排 + 导出 | 220 |
| `backend/services/arena_draw_engine.py` | 抽卡引擎 + 门闸 + 换 IP + 熔断 | 480 |
| `backend/services/arena_token_cache.py` | token 缓存/等待/拒绝计数/换 IP 请求 | 130 |
| `backend/config/arena_automation.yaml` | 配置（默认全关） | 45 |

**新增（Electron / 前端）**

| 文件 | 说明 | 估行 |
|---|---|---|
| `electron/arenaTokenWindow.ts` | 隐藏窗口 + 出票 + 推送/轮询 + IPC | 320 |
| `src/pages/Arena.tsx` | 页面骨架（三页签） | 90 |
| `src/features/arena/RegisterTab.tsx` | 注册页签 | 320 |
| `src/features/arena/DrawTab.tsx` | 抽卡页签 | 380 |
| `src/features/arena/AccountsTab.tsx` | 账号页签 | 300 |
| `src/features/arena/arenaJobStream.ts` | NDJSON 订阅封装 | 120 |
| `src/features/arena/arenaStore.ts` | zustand store（与既有 store 惯例一致） | 140 |
| `src/shared/api/arenaApi.ts` | REST client（backendRequest 漏斗） | 180 |

**新增（测试）**

| 文件 | 覆盖 |
|---|---|
| `backend/tests/unit/services/test_arena_trace_ext.py` | 内部名/档位/usage 解析（真实抓包 fixture） |
| `backend/tests/unit/services/test_arena_protocol_parse.py` | 密码规则、CF 挑战识别、SSE 帧→run_id 全链路（fixture） |
| `backend/tests/unit/services/test_arena_draw_gate.py` | 阶梯/衰减/CF_HOLD/switch_level/间隔抬高 |
| `backend/tests/unit/services/test_arena_proxies.py` | 4 格式解析、轮转、去重、rebind 同 sid、sid 黑名单 |
| `backend/tests/unit/services/test_arena_proxy_relay.py` | fake 上游断言 CONNECT 报文无 Host、端口 bind 0 |
| `backend/tests/unit/services/test_tenminmail.py` | httpx MockTransport 全链路（JWT 刷新、401 重试、链接清洗） |
| `backend/tests/unit/services/test_arena_keystore.py` | key 稳定性、权限、错 key 可读错误 |
| `backend/tests/unit/services/test_arena_token_cache.py` | max_age、等待唤醒、拒绝计数 |
| `backend/tests/unit/api/test_arena_jobs_api.py` | 注册/抽卡 job CRUD + stop + NDJSON 续传 |
| `backend/tests/integration/test_arena_registration_protocol.py` | 协议 + 邮箱双 mock，断言入库字段与导出内容 |
| `backend/tests/integration/test_arena_draw_protocol.py` | SSE/trigger.dev 录制 fixture，断言命中改名与未命中归档 |
| `electron/__tests__/arenaTokenWindow.test.ts` | state 轮询决策、推送重试（BrowserWindow 桩） |
| `src/features/arena/__tests__/*.test.tsx` | 三页签渲染与交互（桩 backendRequest / listen） |

**修改**

| 文件 | 改动 |
|---|---|
| `backend/main.py` | lifespan 接线：`load_arena_config` → `init_arena_service(db_path=${SAGE_USER_DATA_DIR}/arena/arena.sqlite, key=arena_fernet_key(...), config=...)`；shutdown `close()` + `relay.close_all()` + 停 job；沿用 `_startup_mark("arena")` 埋点 |
| `backend/api/arena_routes.py` | §5.10 全部新路由 |
| `backend/services/arena_accounts.py` | schema 迁移 + 新方法 + §1.3-C 安全/性能修复 |
| `backend/config/arena_automation.py` | 四个子配置 + `load_arena_config` |
| `backend/services/temporary_mail/base.py` | `wait_for_link` + Mailbox 字段放宽 |
| `backend/services/temporary_mail/__init__.py` | provider 注册表 |
| `backend/services/run_trace_resolver.py` | 仅放宽 `extract_run_id_from_claims`（兼容无 `run_` 前缀）+ 补测试；不改既有行为 |
| `backend/requirements-optional.txt` | curl_cffi 一节（注释态 + 为什么单独放 + 验证命令） |
| `electron/main.ts` | 注册 token 窗口模块（照 `registerSkillsIpc` 形态）、`app.commandLine.appendSwitch` 反节流、`before-quit` 清理 |
| `electron/eventRouting.ts` / `electron/relay.ts` | `arena-job-*` 通道路由 + NDJSON 中继公共函数抽取 |
| `electron/preload.ts` | 暴露 arena token 窗口控制 API（`contextBridge` 增量） |
| `src/App.tsx` / `src/widgets/command/commandItems.ts` / `src/shared/lib/i18n/{zh,en}.ts` | 路由、入口、文案 |
| `docs/technical/50-arena-source-license-audit.md` | 增补 `reference/ArenCard` 源（无 LICENSE → 仅借鉴逻辑，从零重写） |
| `docs/superpowers/specs/2026-09-16-arena-automation-model-probe-design.md` | §1.4 非目标修订（注册需显式授权）+ §7.1 密钥来源修订（持久化主密钥） |
| `CHANGELOG.md` | 按既有格式记录（含"默认关闭 + 用户显式授权"说明） |

---

## 8. 阶段划分（每阶段独立可验收）

| 阶段 | 内容 | 验收标准 | 估时 | 依赖 |
|---|---|---|---|---|
| **S0 可行性尖峰** | 临时脚本：Electron 21 隐藏窗口出 V3 token（反节流开关齐备），用参考实现的 `create-chat` 手工验证 token 是否被接受；同时验证 curl_cffi 在本机安装与 `impersonate=chrome131` 打通 arena（非 403） | ① token 出票成功且 `create-chat` 返回 200 → 协议抽卡路径成立；② 若被拒：记录拒绝率与响应体，走 §11 R1 备选（系统默认浏览器/WebView2 子进程/仅浏览器路径）；③ curl_cffi 可用 | 0.5~1 天 | 无（**必须最先做**） |
| **P0 接线与密钥** | `machine_id` + `arena_keystore` + `load_arena_config` + yaml + lifespan 接线 + `arena_accounts` 安全/性能修复 + `capabilities` 端点 + `temporary_mail` 扩展与 `tenminmail` | `GET /api/v1/arena/capabilities` 返回真实能力；`POST /api/v1/arena/accounts` 不再 503；**重启后端后既有账号仍可解密**（回归测试）；tenminmail 单测绿（MockTransport，不连网）；默认全关时行为与现状一致（既有 arena 测试全绿） | 1.5 天 | S0 |
| **P1 协议注册** | `arena_http` + `arena_protocol`（注册部分）+ `arena_jobs` + `arena_registration` + 注册 API + 导出 | 解析/流程单测绿；集成测试（协议+邮箱双 mock）绿；真实冒烟：3 个账号注册成功、额度与 user_id 回写、导出格式 `邮箱----密码----额度`；并发 3 时无邮箱超时 | 2.5 天 | P0 |
| **P2 代理子系统** | `arena_proxy_relay` + `arena_proxies` + DB 迁移（binding 列）+ rebind + `/proxies/*` | relay 单测断言 CONNECT 无 Host、端口系统分配；`/proxies/test` 返回真实出口 IP；4 种粘贴格式解析用例全绿；rebind 同 sid 场景测试绿；注册任务可选走代理且邮箱恒直连（日志可证） | 2 天 | P0（可与 P1 并行） |
| **P3 token 窗口** | `electron/arenaTokenWindow.ts` + main.ts/preload 接线 + `arena_token_cache` + `/token-window/*` | `health.ready=true` 且 `exit_ip` 与本机出口一致；连续出票 20 次无失败；后端重启期间窗口自动重连推送；`state.needed` 触发按需出票（<3s）；反节流有效（隐藏 5 分钟后仍能出票） | 2 天 | S0、P0 |
| **P4 抽卡引擎** | `arena_draw_engine` + `arena_trace_ext` + `arena_draws` 表 + 抽卡 API + 门闸 + 换 IP + 熔断 | 门闸/解析单测绿；集成测试（录制 fixture）绿；真实冒烟 10 轮：命中改名（标题 `内部名·r<推理量>`）、未命中按策略归档/删除、429 触发阶梯退避、（有代理时）到档换 IP 整轮重跑且不计失败；拒绝计数与熔断可观测 | 3 天 | P1、P2、P3 |
| **P5 前端** | `/arena` 路由 + 三页签 + NDJSON 日志流 + i18n + 命令面板入口 | 三页签可完整操作两类 job（启动/停止/实时日志/结果/导出/重绑/手动加号）；断流后 `after_seq` 续传不丢事件；Vitest 组件测试绿；`npm run lint`/`typecheck` 绿 | 3 天 | P4（可在 P4 后期并行开工） |
| **P6 收口** | e2e（Playwright 既有 `test:pr` 通道）+ 审计/spec 修订 + CHANGELOG + 本文归档 + 真实冒烟记录 | `npm run test:pr` 与 `backend` pytest 全绿；`docs/verification/2026-09-19-aren-card-port.md` 记录冒烟数据（注册 ×3、抽卡 ×10、换 IP ×1、token 拒绝率）；spec §1.4/§7.1 修订落地；审计文档增补 ArenCard 源 | 1.5 天 | P5 |

合计约 **16 个工作日**（S0 结论若否定协议抽卡，P3/P4 缩减为浏览器路径适配，约省 3 天）。

---

## 9. 测试策略

- **原则**：`backend/pytest.ini` 单测 120s 超时 → 任何单测不得真连网、真等邮件、真出票。所有网络边界用 mock/fixture。
- **fixture 采集**（一次性人工，存 `backend/tests/fixtures/arena/`，**必须脱敏**：token 截断、账号替换为 example 域）：`sign-up.json`、`magic-link.json`、`mailbox-list.json`、`verify-mail.html`、`create-chat.json`、`create-chat-429-cf.html`、`trigger-token.json`、`out-stream.sse`、`run-events.json`、`run-events-with-internal.json`、`span-usage.json`。
- **单元**：解析纯函数（内部名/档位/usage/模型匹配/密码规则/CF 识别/SSE→run_id）、门闸状态机（用可注入时钟，避免真 sleep）、代理池 4 格式与轮转、relay CONNECT 语义（本地 fake 上游 socket）、keystore 稳定性、token 缓存时效与唤醒、tenminmail（httpx MockTransport）。
- **集成**：注册 job（协议 + 邮箱双 mock，断言 `create_account` 入参、binding 列、导出内容）、抽卡 job（fixture 驱动，断言命中改名 / 未命中归档 / switch=True 触发 rebind / 熔断触发）、NDJSON `after_seq` 续传、flag 关闭时全路由 403。
- **前端**：Vitest + jsdom，桩 `backendRequest` 与 `listen`（与 `src/widgets/orchestration/__tests__` 同 seam）；覆盖三页签渲染、日志追加、停止按钮、导出下载。
- **Electron**：`electron/__tests__/arenaTokenWindow.test.ts` 桩 `BrowserWindow`/`node-fetch`，覆盖 state 决策（needed/want_proxy/enabled=false）与推送失败重试。
- **e2e**：Playwright `electron-stub-*` 通道跑 UI 流程（后端 mock），不进 `electron-live-*`（避免真连 arena）。
- **真实冒烟**：人工执行，小批量（注册 3、抽卡 10），记录到 `docs/verification/2026-09-19-aren-card-port.md`（含 token 拒绝率、429 次数、换 IP 次数、命中率）。
- **回归红线**：`test_arena_accounts.py`、`test_arena_routes.py`、`test_arena_adapter.py`、`test_arena_observation.py`、`test_run_trace_resolver.py`、`integration/test_arena_registration_flow.py` 全绿不回退。

---

## 10. 安全与合规

1. **凭据**：密码只存 Fernet 密文；服务层默认不返回明文（§1.3-C 修复）；任何日志/事件/异常消息都不得含密码、token、`public-access-token`（对齐 spec §7.2）；job 事件里邮箱本地名可展示，密码仅在 UI 显式点击"显示"时经专用端点取（或直接从导出文件读）。
2. **导出文件**：`accounts_*.txt` 含明文密码 → 写入 `${SAGE_USER_DATA_DIR}/arena/`（**绝不写仓库目录**），确认 `.gitignore` 覆盖；导出必须由用户显式点击触发；UI 二次确认 + 明文风险提示；提供"导出为密文/仅邮箱"选项。
3. **本地鉴权**：所有新路由继承 `local_auth` 中间件；token 窗口 push/state 端点额外要求 `Authorization: Bearer <SAGE_LOCAL_AUTH_TOKEN>`（Electron 已持有）。
4. **网络边界**：relay 只监听 `127.0.0.1`；token 窗口 `partition` 隔离，不与主窗口共享 cookie；`session.setProxy` 仅作用于该 partition。
5. **默认关闭**：master flag + 三个子 flag 全默认 false；yaml 缺失/损坏 → 保持关闭（不 fail-open）。
6. **spec 非目标冲突（需用户拍板）**：spec §1.4 明确 "No unauthorized account creation — only accounts explicitly added by the user/org are managed"，而批量注册与之冲突。本方案的处理：注册是**用户在本机 UI 显式发起**的 job（非自动、非后台、独立 flag、默认关），并同步修订 spec §1.4 措辞为"不做未经用户显式发起的账号创建"，在审计文档与 CHANGELOG 中明示。**若用户不批准，P1 整段砍掉，账号池仅保留手动录入，其余阶段不受影响。**
7. **平台条款风险**：批量注册与自动抽卡属于对 arena.ai 的自动化使用，很可能违反其服务条款，存在账号封禁与 IP 封锁风险；参考项目自身 CHANGELOG 也记录过大规模"回收风暴"导致 0 命中。本方案通过门闸/一号一 IP/并发上限/熔断把风险降到参考实现同等水平，但**风险不可消除，需用户知情**（UI 首次启用时展示一次性告知）。
8. **移植纪律**：`reference/ArenCard` 无 LICENSE → 只借鉴逻辑与实测常量，代码从零重写（D12）；不把参考项目的可执行文件、账号数据、`config.json` 带入仓库。

---

## 11. 风险与回退

| # | 风险 | 概率 | 影响 | 缓解 / 回退 |
|---|---|---|---|---|
| R1 | **Chromium 106（Electron 21）出 V3 token 被拒**（参考用的是常青 WebView2） | 中高 | 协议抽卡不可用 | S0 先验证。备选梯度：① `webPreferences.backgroundThrottling:false` + 反节流开关 + 真实窗口尺寸（已含）；② 窗口临时 `show:true` 移到屏幕外/最小化（实测有头可过）；③ 保留参考形态——独立 WebView2 子进程（pywebview，可选依赖，仅 Windows）；④ 退回浏览器路径抽卡（`ArenaAdapter` + 观测，既有能力，慢但可用）。注册路径不受影响（步骤 2 不校验 reCAPTCHA） |
| R2 | curl_cffi 安装失败/平台无轮子 | 低 | 指纹降级 → 403 | 懒加载回退 httpx + `capabilities` 明示 + UI 建议；Win7 通道本就不走协议路径 |
| R3 | 10minutemail 域名/接口波动或被拉黑 | 中 | 注册失败 | provider 可插拔（mailtm 占位）；域名列表可配；失败账号可手动补录；邮箱恒直连 |
| R4 | arena 端点/事件结构变更 | 中 | 协议路径失效 | 常量单点区（附录 A）+ fixture 回归；`capabilities` 增自检探针；浏览器路径不受端点变更影响 |
| R5 | 主密钥文件丢失/机器指纹变化 | 低 | 账号密码不可解 | 启动时自检：若有账号且解密失败 → 明确 warning + UI 横幅（而不是静默 500）；文档告知备份 `master.key` |
| R6 | 429/CF 封锁导致 0 命中 | 中 | 抽卡无效 | 门闸 + 一号一 IP + switch_level 换 IP + 拒绝熔断 + 冷却（纪律 10）；UI 展示归因摘要 |
| R7 | 账号被封 | 固有 | 账号损失 | 并发上限、注册与抽卡同 IP、失败隔离（既有）、保留手动入口 |
| R8 | NDJSON 中继在长任务下断流 | 低 | 日志丢失 | `after_seq` 续传 + 前端重连（照 orchEventStream 既有实现） |
| R9 | 与既有 arena 测试冲突（`get_account` 签名变更） | 中 | CI 红 | 用默认参数保持向后兼容（`include_secret=False` 为默认，既有断言若依赖 password 字段则同步更新测试并在 PR 说明） |

---

## 12. 待用户确认的决策点

| # | 决策 | 选项 | 建议 |
|---|---|---|---|
| Q1 | 批量注册是否纳入范围（与 spec §1.4 非目标冲突） | A. 纳入（独立 flag + 修订 spec）／B. 不纳入（仅手动录入账号） | A，但需你明确授权；若 B，砍 P1，省 2.5 天 |
| Q2 | 明文导出 `accounts_*.txt` 是否保留 | A. 保留（用户显式触发 + 二次确认）／B. 只导出邮箱+额度／C. 不导出 | A（与参考一致，便于外部使用），默认目录在 userData |
| Q3 | token 窗口形态 | A. Electron 隐藏窗口（本方案）／B. 独立 WebView2 子进程（参考形态，仅 Windows，新增可选依赖） | 先 A；S0 失败再退 B |
| Q4 | 抽卡未命中默认策略 | A. 归档（参考默认）／B. 删除／C. 保留 | A |
| Q5 | 本方案与上一轮草案 `docs/mcp-aren-card-implementation.md` 的关系 | A. 保留两份，本文为准（本文已含差异表）／B. 用本文覆盖旧文 | A（保留可追溯性） |

---

## 附录 A · 协议常量单点区（`arena_protocol.py` 顶部，带来源注释）

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
DRAW_TIMEZONE = "Asia/Shanghai"
GATE_LADDER = (15.0, 30.0, 60.0, 90.0)
GATE_DECAY_AFTER = 240.0
CF_HOLD = 180.0
CREATE_CHAT_BACKOFFS = (0, 15, 30, 60)
CF_MARKERS = ("just a moment", "cf-chl", "attention required")
PROXY_SID_RE = r"sid-([A-Za-z0-9]+)"
TIER_RE = r"^(?P<base>.+?)[.-](?P<tier>low|medium|high|max)(?:[.-](?P<date>\d{6,8}))?$"
MODEL_NAME_RE = r'"modelName"\s*:\s*"([^"]{2,80})"'
ECHO_URLS = ("https://api.ipify.org?format=json", "https://ifconfig.me/ip")
SSE_HEADERS = {"x-trigger-source": "sdk", "x-trigger-realtime-streams-version": "v2"}
```

## 附录 B · 端点速查

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
| 归档/取消归档 | POST | `/api/chat/{sid}/archive` \| `/unarchive` |
| 删会话 | DELETE | `/api/chat/{sid}` |
| 临时邮箱列表 | GET | `web.10minutemail.one/api/v1/mailbox/{email}` |
| 临时邮箱正文 | GET | `web.10minutemail.one/api/v1/mailbox/{email}/{mailId}` |
| run 事件 | GET | `api.trigger.dev/api/v1/runs/{runId}/events` |
| span 详情 | GET | `api.trigger.dev/api/v1/runs/{runId}/spans/{spanId}` |

## 附录 C · 与上一轮草案（`docs/mcp-aren-card-implementation.md`）的差异

| # | 草案 | 本文（核实后） | 依据 |
|---|---|---|---|
| 1 | 新建 `arena_protocol.py` 自己实现 `parse_models` 等解析 | 复用 `run_trace_resolver.py` 既有纯函数，只新增 internal/tier/usage 扩展 | `backend/services/run_trace_resolver.py:55-271`，已有单测 |
| 2 | 任务事件走 EventHub（`arena:registration-log` 等主题） | 改为 `arena_jobs.py` + NDJSON `?after_seq=` + Electron `arena-job-*` 中继 | `backend/orchestration/event_hub.py` 绑定 `RunEvent`/`run_id` 域模型；`backend/api/orch_run_control.py:91` 已有同构 NDJSON 通道 |
| 3 | backend 经"现有 backend↔Electron 通道"取 token | 改为 Electron 推送 + backend 缓存 + state 轮询 | 现有 HTTP 方向恒为 Electron→backend（`electron/invoke.ts`、`electron/relay.ts:245`），无反向通道 |
| 4 | `init_arena_service(encryption_key=derive_arena_key(machine_token, machine_id))` | 新增持久化 `master.key` + `machine_id()` 实现；指出 spec §7.1 的 token 来源不稳定 | `electron/main.ts:465` 每次重启重新 `randomBytes(32)`；全仓无 machine_id 实现 |
| 5 | 配置文件路径 `config/arena_automation.yaml` | 修正为 `backend/config/arena_automation.yaml` | 仓库既有惯例 `backend/config/ghm.yaml` + `backend/main.py:199` |
| 6 | token 窗口在 P3、抽卡在 P4（S0 缺失） | 新增 **S0 可行性尖峰**前置（Chromium 106 出票 + curl_cffi 打通） | `package.json:89` electron `^21.4.4`；参考用的是常青 WebView2（`token_server.py` 头注释） |
| 7 | 邮箱 provider 直接实现 ABC | 指出 ABC 需扩展 `wait_for_link` 且 `Mailbox` 字段需放宽；config 默认 `mailtm` 需改 | `backend/services/temporary_mail/base.py:27-60`；`backend/config/arena_automation.py:16` |
| 8 | 未涉及账号服务的安全/性能问题 | 明确 `get_account` 明文密码外泄面与 `list_accounts` N+1，列入 P0 | `arena_accounts.py:129-165`、`arena_routes.py:40` |
| 9 | 未提熔断 | 增加全局拒绝阈值 + 冷却 + 归因摘要 | 参考 `CHANGELOG.md:24-29` 回收风暴实测事故 |

## 附录 D · 落地检查清单（PR 自检）

- [ ] `npm run lint` / `npm run typecheck` / `npm run typecheck:electron` 全绿
- [ ] `backend` pytest 全绿，且既有 6 个 arena 相关测试文件无回退
- [ ] `npm run test:run`（Vitest）与 `npm run test:pr`（Playwright stub 通道）全绿
- [ ] 默认配置（全关）下启动：无 arena 后台线程、无窗口、路由 403、`capabilities` 可读
- [ ] 开启后重启后端：账号仍可解密（密钥稳定性回归）
- [ ] 日志/事件/异常中 grep 不到密码、`public-access-token`、代理凭据
- [ ] `accounts_*.txt` 只落在 `${SAGE_USER_DATA_DIR}/arena/`，仓库 `git status` 干净
- [ ] 新增文档 LF 行尾、无行尾空白；spec/审计/CHANGELOG 已同步
