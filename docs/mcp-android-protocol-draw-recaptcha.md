# 安卓协议抽卡 · create-chat 403 `recaptcha validation failed` 归因与修复

日期：2026-09-22。现象来自真机日志：两个账户并发协议抽卡，`1/8 登录` 通过、`2/8` WebView 出票成功
（token 长度 2617 / 2660），`3/8 建会话` 均返回 `create-chat HTTP 403: {"error":"recaptcha validation failed"}`，
池随即 `结束 draws=2 hits=0 新号=0`。

## 1. 这个 403 是什么

不是 Cloudflare（登录 200、响应体是 arena 自己的 JSON），而是 arena 后端拿着 `recaptchaV3Token`
去 reCAPTCHA Enterprise 做 assessment 后**分数不够 / token 无效**。参考侧对同一错误的既有结论：

- `docs/mcp-arena-p4-draw-engine.md` §Recaptcha frontier diagnosis：桌面端逐一排除出口 IP 不一致、UA 自动化标记、
  token 新鲜度后，仍 403；残余变量是**出口 IP 信誉**（数据中心段一律低分），参考 ArenCard 是在住宅代理上跑通的。
- `docs/mcp-android-device-test-20260921.md` T4：同一台安卓真机上，**页面抽卡**（token 由 arena 页面自己出、
  请求由同一 WebView 发，UA / IP / Cookie 完全一致）的 `create-chat` 也 5/5 403。

所以代码层能做的，是把安卓协议路径与参考实现之间**确实存在的 parity 缺口**补齐（每一条都会拉低评分或直接判无效），
然后用日志把剩下的环境变量（出口 IP）暴露出来，而不是宣称某一条改动就能让它通过。

## 2. 对照参考实现找到的缺口

| # | 参考实现 | 安卓（修前） | 影响 |
|---|---|---|---|
| 1 | `backend/services/arena_draw_engine.py` `DrawClient.ua`：把出票窗口**实测** `navigator.userAgent` 转发到所有 arena 请求（「reCAPTCHA Enterprise 的评分会比对解题浏览器与呈现请求的 UA 一致性」）；ArenCard 用 curl_cffi `impersonate=chrome131`，与 WebView2 同为桌面 Chrome UA | `UrlConnectionTransport` 不设 UA → 安卓默认送 `Dalvik/2.1.0 (Linux; U; Android …)`；token 却由 `Chrome/1xx Mobile Safari` UA 的 WebView 出 | 解题 UA 与呈现 UA 明显矛盾 |
| 2 | `reference/ArenCard/arena_draw.py` `draw_once` `captcha_retries=2`：被 reCAPTCHA 拒 → 等 10 s 换**新 token** 再试一次；429 阶梯打满 → 等 20 s 换新 token；`arena_draw_engine.py` 同值 | `drawOnce` 第一次被拒即抛出，整轮结束 | V3 单次拒绝样本参考侧早有记录（`docs/mcp-arena-p1-protocol.md` §3.3），没有第二次机会 |
| 3 | `reference/ArenCard/token_server.py`：出票浏览器用 `--proxy-server` 接到与账号**同一条**本地中继，token 与请求同一出口 | 出票 WebView 直连，账号 transport 走 `ProxyRelay`；配了 HTTP 代理时两者出口必然不同 | 出口不一致直接低分（桌面 P4 把它列为第一嫌疑并专门验证） |
| 4 | 桌面 P3：把 Electron 的 UA 规范成 plain Chrome（去掉自动化 / 宿主标记） | 只删了 `; wv)`，留下第二个 WebView 标记 `Version/4.0`（Google 文档明示的 WebView 识别字段） | UA 仍可被识别为 WebView |

## 3. 本批改动

### core（纯 JVM，可单测）

- `register/HttpTransport.kt`：`UrlConnectionTransport(userAgent = "")` 新参数。非空时对每个请求（含 SSE `streamGet`）
  设置 `User-Agent`；调用方 `extraHeaders` 里显式给了 UA 则以调用方为准；空串保持平台默认。只允许传**测量值**，
  文件头注释写明这是「不手写 UA」纪律的唯一例外及原因。
- `register/DrawClient.kt`：`DrawOnceConfig` 新增 `captchaRetries = 2`、`recaptchaPauseMs = 10_000`、`rateLimitPauseMs = 20_000`。
  `drawOnce` 的 2/8–3/8 改成「取 token → 429 阶梯内复用同一 token → 被 reCAPTCHA 拒则 10 s 后换新 token 重试 →
  429 阶梯打满则 20 s 后换新 token 重试」，与 `arena_draw.py:659-715` 同构。非 reCAPTCHA 的协议错误不重试（换 token 无意义）；
  CF 挑战 / `shouldSwitch` 仍立即抛出交给上层换 IP；最终失败时 `DrawResult.recaptcha` 语义不变（`ProtocolLoop` 的暂停 / 换号逻辑不受影响）。
- `register/RecaptchaSite.kt`：`normalizeWebViewUa()` 只删除 `; wv` 与 `Version/x.y `，其余（Android 版本、机型、Chrome 版本）保留实测值；
  新增 `JS_UA` / `JS_IP_START` / `JS_IP` / `IP_ECHO_URL`（对 `token_server.py` 的 `/ip` 诊断）。

### app

- `app/RecaptchaWebViewMinter.kt`：用 `normalizeWebViewUa` 写回 WebSettings，暴露 `userAgent`；新增 `measuredUserAgent()`
  （页面里实测 `navigator.userAgent`，页面未起时退回设置值）与 `probeExitIp()`（best-effort，失败返回 null，绝不影响抽卡）。
- `app/DrawActivity.kt`：
  - 开抽前 `prepareTokenWindow()`：所选账户若配置 HTTP / Mixed 代理，用 `ProxyGate`（与协议 transport **共用同一个 `ProxyRelay`**，
    同一本地端口）把出票 WebView 对齐到同一出口；代理不可达按 `ProxyGate` 语义直接不开始，不回退直连。
    多条不同代理时只能跟随第一条（`ProxyController` 是进程级）并明确告警；SOCKS5 无法经 CONNECT 中继，告警后按原样继续。
  - 日志新增 `[i] 出票 UA：…` 与 `[i] 出口 IP：出票页 a.b.c.d / 协议 e.f.g.h`，两者不一致时 `[!]` 提示。
  - 协议 transport 改为 `buildArenaTransport(proxy, ua)`，`ua` 为出票页实测值；注册路径仍留空（保持原行为）。
  - `onDestroy` 关闭 `ProxyGate`（清 override）。

### 测试

- `HttpTransportTest` +2：实测 UA 原样转发；显式 `User-Agent` 头优先。
- `DrawClientTest` +4：被拒 → 10 s 换新 token 重试成功（两次 create-chat 分别带 `tok-1` / `tok-2`）；两次都被拒 → `recaptcha=true`、
  恰好消耗 2 个 token；非 reCAPTCHA 错误不消耗第二个 token；429 阶梯打满 → 20 s 换新 token。
- `RecaptchaSiteTest`（新）+4：reduced UA / 带 Build 的旧 UA 规范化、plain Chrome 原样、空输入。
- `JAVA_HOME=jdk17 ./gradlew --offline :core:test`：**277 tests, 0 failures**（改前 268）。

## 4. 真机复测怎么读日志

1. `[i] 出票 UA：` 应形如 `Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/1xx.0.0.0 Mobile Safari/537.36`，
   **不含** `wv` / `Version/4.0`。
2. `[i] 出口 IP：` 两个值必须相同。不同 → 先解决代理配置（HTTP / Mixed 模式、账户级与全局配置是否一致），别急着看别的。
3. 两者都对、仍然是 `[!] 被 reCAPTCHA 拒，等 10 秒换新 token 重试` 后再 403 → 剩下的就是桌面 P4 的结论：出口 IP 信誉。
   验证办法：关掉代理 / VPN，让手机走**蜂窝数据**直连再抽一次（蜂窝出口是运营商 NAT 池，reCAPTCHA 信誉通常最好）；
   或换住宅代理。如果蜂窝直连能过而代理不能，就是 IP 的问题，与安卓代码无关。
4. 若蜂窝直连也 403，且页面抽卡同样 403，则 reCAPTCHA 判的是设备 / WebView 指纹。下一步候选（本批未做，避免过度伪装）：
   `WebSettingsCompat.setUserAgentMetadata`（webkit 1.12.1 已在依赖里，`WebViewFeature.USER_AGENT_METADATA`）把
   UA Client Hints 的 brands 里的 `Android WebView` 换成与 UA 字符串一致的 Chrome 品牌；以及让出票 WebView 保留 Google Cookie
   （`_GRECAPTCHA`）跨次复用而不是每次冷启动。

## 5. 未改动 / 有意保留

- 注册路径（`registerOne`）的 transport 仍不带 UA：注册用的是另一套 token 流，真机已跑通，不动。
- `HostCookieJar`、`Origin` / `Referer`、`timezone` 字段与参考一致，未改。
- 没有在 Kotlin 里拼写任何固定 UA 字符串；所有 UA 都来自 WebView 实测（纪律 2）。
