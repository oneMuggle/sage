# Android vs ArenCard 对照与落地（2026-09-21）

日期：2026-09-21
参考：`reference/ArenCard`（批量注册 / 自动抽卡 / 账号管理）
安卓：`android/`（Arena Companion：C# 模型助手主线 + ArenCard 协议注册机）
方案边界：`docs/mcp-android-implementation-plan.md` §1；§8 批量/换 IP 已于 2026-09-21 由用户去掉

## 0. 一句话

ArenCard 是「纯协议批量注册 + 抽卡」。安卓 App 是「有头 WebView 自动化 + 归档」。两者不是同一产品。
对照 ArenCard 的能力清单，安卓先前只移植了**六步注册协议的纯逻辑**和 **CONNECT 中继**；邮箱、HTTP、注册页都是空的。
本会话 B36 接上单账号协议注册；B37 按用户决策去掉 §8 边界，补上批量 / 一号一 IP / `accounts_*.txt`。Companion「开始」仍走 WebView `AuthFlow`（已有账号登录），与注册机不是同一条路。

## 1. ArenCard 能力对照

| ArenCard 能力 | 参考位置 | 安卓现状（本会话前） | 本会话后 | 备注 |
|---|---|---|---|---|
| 协议 6 步注册 | `arena_core.py` | `RegisterClient.registerOne` 有，无 HTTP / 无邮箱 | **已接线** | 行为取自 sage `arena_protocol.py`，不抄 ArenCard 原文 |
| 10minutemail catch-all | 同上 | 只有 `MailProvider` 接口 | **`TenMinMailProvider` + `TempMailIoProvider` + `MailCxProvider`** | 三条线路设置页单选；邮件永不走代理；temp-mail.io / mail.cx 免鉴权（2026-09-22 端到端验证） |
| HTTP 传输 | curl_cffi / httpx | 无 | **`UrlConnectionTransport`** | 每实例 Cookie 罐；arena 与邮箱必须分实例 |
| 单账号 UI | Tk 页签一的简化 | `RegisterActivity` 占位 toast | **真跑 registerOne，写入 Keystore 保险库** | 入口：设置页 / 实例长按 / 会话菜单 |
| 批量 + 并发 | 页签一 | 明确不做 | **`registerBatch` + 注册页数量/并发/间隔** | 用户 2026-09-21 去掉 §8 |
| 动态代理池 / 一号一 IP | 页签一 | 单实例一份 `ProxySettings` | **`ProxyPool` 4 格式 + `ProxyProvider` sid 黑名单** | chili `sid-` 保证一号一 IP；无 sid 会复用。认证走 `ProxyRelay` |
| `accounts_*.txt` 导出 | 页签一 | 无 | **`email----password----credits----proxy`** | 写入 `register-output/`；UI 日志打码。数量=1 仍写入保险库 |
| 协议 8 步抽卡 | `arena_draw.py` | 无 | **`drawOnce` 8 步已接线** | Companion 主线仍是 WebView New Chat；本条是协议机 |
| reCAPTCHA V3 token 窗口 | `token_server.py` | 无 | **半接线** | 协议八步已移植；V3 目前由抽卡页粘贴，窗口未移植 |
| 429 换 IP / 重绑 | 抽卡自动行为 | 阶段机暂停等人工 | 注册路径：拉黑该 sid 30 分钟 | 抽卡引擎仍未移植 |
| 账号管理 / 体检 | 页签三 | `AccountBalanceClient` / `AccountRiskController` | 已有，未做成 ArenCard 页签 | 服务于 Companion 换号，不是批量池 |
| CONNECT 中继 | `proxy_relay.py` | **已有** `ProxyRelay` | 沿用 | 注册 HTTP 代理复用它 |
| 查额度 | `get_balance` | `RegisterClient.getBalance` + `AccountBalanceClient` | 沿用 | 4×3s，不重试风暴 |

粗算：ArenCard「注册机」功能（六步 + 批量 + 代理池 + 导出）代码约 85% 就绪（待真机）；协议抽卡 / token_server 仍 0%。

## 6. B38 协议抽卡 8 步（2026-09-22）

入口：设置页「协议抽卡」→ `DrawActivity`。账号取本实例保险库。

| 步 | 动作 | 实现 |
|---|---|---|
| 1 | 登录 | `POST /nextjs-api/sign-in/email` |
| 2 | V3 token | `RecaptchaTokenSource`（UI 粘贴；token_server 未移植） |
| 3 | 建会话 | `POST /nextjs-api/stream/create-chat` |
| 4 | 会话 JWT | `POST /api/chat/trigger-token` |
| 5 | SSE | `GET /ai-proxy/realtime/v1/sessions/{id}/out` → public-access-token |
| 6 | 模型 | `GET api.trigger.dev/api/v1/runs/{runId}/events` |
| 7 | 命中改名 / 未命中归档或删除 | PATCH history / POST archive / DELETE chat |
| 8 | 返回 `DrawResult` | 日志 `1/8`…`8/8` |

测试：`DrawClientTest`（JWT / SSE / parse / hit rename / miss archive / 空 token）。
Companion 自动化（阶段机、归档、附件、重命名）对 ArenCard 是另一条产品线，不在本表评分。

## 2. 为何注册是协议，登录却是 WebView

两条路不要混：

1. **注册 = 纯协议**（`RegisterActivity` → `registerBatch` / `registerOne`）。没有浏览器、没有 `AuthFlow`。这就是 ArenCard 的六步。B36 起就已经是这条路；之前方案 §8 只是不让它批量。
2. **Companion「开始」= WebView `AuthFlow`**。那是 C# 模型助手登录已有账号、把 Cookie 放进 WebView，再跑阶段机。协议注册成功后的账号，要用 Companion 自动化，才需要这条登录。

用户问「为什么不用纯协议注册」——**已经在用**。`AuthFlow` 不是注册。

2026-09-21 用户去掉 §8「不做批量」边界后，协议注册机补齐数量/并发/代理池/导出。验证码绕过与指纹伪装仍不做。

B36 已把 `registerOne` 跑起来：

1. `TenMinMailProvider`（sage `tenminmail.py` 的 Kotlin 版）
2. `UrlConnectionTransport`（Cookie + 自跟重定向，给 `confirmLink` 最终 URL）
3. 接线 `RegisterActivity`：邮件直连、arena 跟随实例代理、成功写入 `AccountVault`
4. 从设置 / 实例选择器 / 会话菜单进入，不再是死页面

真机未知数仍是方案 §9 第 5 项：OkHttp/UrlConnection 直连 arena.ai 是否 403。若 403，下一刀是 WebView 页面上下文 fetch，协议逻辑不动。

## 3. B36 交付

### `:core`

| 文件 | 作用 |
|---|---|
| `register/TenMinMailProvider.kt` | JWT / catch-all 域名轮换 / 401 刷新 / `waitForLink` 还原 `\u0026` |
| `register/HttpTransport.kt` | `UrlConnectionTransport` + `HostCookieJar` + `asMailHttp()` |
| `register/RegisterClient.kt` | `passwordOverride`：合法则用，非法失败且不碰 set-password |

### `:app`

| 文件 | 作用 |
|---|---|
| `RegisterActivity.kt` | 真跑六步；覆盖已有账号需确认；取消合作 `cancelled` |
| `activity_register.xml` | 邮箱只回填；日志可选中 |
| 设置页 `btnRegister` / 实例长按 / 会话菜单 | 三个入口都带 `EXTRA_INSTANCE` |
| `network_security_config.xml` | 仅 127.0.0.1/localhost 清文本，给 ProxyRelay |

### 测试

- `TenMinMailProviderTest` 8 例：域名轮换、JWT 重试、401 刷新、超时不抛、hiccup 吞掉、链接还原
- `HttpTransportTest` 4 例：POST JSON、Cookie、重定向 finalUrl、mail 不带 arena Origin
- `RegisterClientTest` +2：密码覆盖合法 / 非法

`JAVA_HOME=jdk17 ./gradlew :core:test --rerun-tasks` **BUILD SUCCESSFUL**。
`./gradlew :app:assembleDebug -PskipBridgeJsTest=true` **BUILD SUCCESSFUL in 24s**。
`get_diagnostics android` 0 条 error。

## 4. 真机复核（未做）

- [ ] 无代理：开始注册 → 日志出现邮箱 → 约 15–30s 成功 → 设置页账号摘要显示该邮箱、密码不出现在日志
- [ ] HTTP 认证代理：流量走 `ProxyRelay`；上游挂了必须报错停止，不得直连
- [ ] 429 / Cloudflare 挑战页：停止并提示，不换 IP
- [ ] 若 sign-up HTTP 403：不要放宽协议，改用 WebView fetch 实现 `ArenaTransport`

## 5. 仍未做

- token_server / 抽卡 8 步 / 协议机换号已接线；动态换出口 IP（代理池 sid 重绑）仍未接到抽卡循环
- 动态代理 API（haiwaidaili），目前只有粘贴池
- 自定义邮箱（自有邮箱 / IMAP；内置线路已可选 10minutemail、temp-mail.io 与 mail.cx）
- 验证码绕过、指纹伪装


## 7. B39 token window + DrawGate (2026-09-22)

- RecaptchaWebViewMinter: same JS as token_server.py (V3_KEY + agentic_chat_submit)
- DrawActivity mints via hidden WebView; paste field is optional override
- DrawGate: 429 ladder 15/30/60/90, CF hold 180s, create-chat backoff reuses token
- RecaptchaTokenCache consume-once (core)
- Tests: DrawGateTest 3 + DrawClientTest 6

## 8. 双线路（2026-09-22）

设置页「运行线路」二选一，写入 `TaskSettings.engine`。主界面「开始」按线路分流。

| | 页面自动化（webview，默认） | 协议机（protocol） |
|---|---|---|
| 注册 | WebView `AuthFlow` 自动申请临时邮箱 | HTTP `registerOne`（无账号时循环会先注册） |
| 登录 | WebView 填邮箱密码，Cookie 进主页面 | `POST /nextjs-api/sign-in/email` |
| 抽卡 | 阶段机 New Chat + 探针识别模型 | `drawOnce` 8 步，模型来自 Trigger.dev events |
| 换号 | 人机验证 → 新实例 + AuthFlow（`pauseOnCaptcha` 可改等人工） | 同一实例覆盖保险库；reCAPTCHA / CF / 429 / 登录失败触发，上限 3 次 |
| 仍要 WebView | 整条自动化 | 仅隐藏 WebView 出 V3 token（无头会被拒） |

入口：设置保存线路后，会话页点「开始」。协议机打开 `DrawActivity`（`EXTRA_LOOP`）自动开跑。
