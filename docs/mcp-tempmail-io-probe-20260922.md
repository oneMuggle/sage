# temp-mail.io 可用性探测（2026-09-22）

结论：**可用，已端到端验证**。arena.ai 接受其域名并发送验证邮件，邮件秒级到达，
链接形状与现有 `VERIFY_LINK_RE` 一致。作为继 10minutemail 之后的第二个邮箱线路成立。

## 探测环境

- 探测方 A：本沙箱（海外出口）；探测方 B：用户 Windows 主机（ShunCode MCP）。
- 两处均直连成功，无 Cloudflare 拦截、无人机验证。

## API 契约（内部 API，站点自用，免鉴权）

基址 `https://api.internal.temp-mail.io/api/v3`，裸 HTTP 即可（无 cookie / JWT / captcha）：

1. `GET /domains` → `{"domains":[{"name":"ozsaip.com","type":"public",...}, ...]}`（本次 7 个公共域名）
2. `POST /email/new`，body `{"min_name_length":10,"max_name_length":10}`
   → `{"email":"b83q1ela1i@ooynib.com","token":"sMchKLRnVu2Ci1H382T4"}`
   服务端生成 local 部分；域名由服务端挑选。`token` 读信用不到（疑似删除/转发用）。
3. `GET /email/{email}/messages` → 消息数组（**列表即全文**，无需逐封再取）：
   `id / from / to / cc / subject / body_text / body_html / created_at / attachments`。
   空箱返回 `[]`；未创建过的地址返回 400 `{"code":101,"message":"Email not found"}`。

另有官方付费 API（`docs.temp-mail.io`，`api.temp-mail.io` + `X-API-Key`），本探测未使用；
内部 API 与现行 10minutemail「抠页面 JWT」属同一类做法，且更干净（连 JWT 都不用抠）。

## 与 10minutemail（`TenMinMailProvider`）的差异

| 维度 | 10minutemail.one | temp-mail.io |
|---|---|---|
| 建邮箱 | 页面抠 JWT + 自造 local（catch-all） | `POST /email/new`，服务端起名（**非 catch-all**） |
| 读信 | 列表取 id → 逐封取正文 | 列表直接带 `body_text`/`body_html` |
| 鉴权 | Bearer JWT（约 23h 过期，401 刷新） | 无 |
| 域名 | dbwot.com / ygwpr.com / imxwe.com | 轮换，本次 7 个（ozsaip.com 等） |
| arena 验证邮件 | 已验证可用 | **已验证可用**（team@everify.arena.ai，约 5s 到） |

## 端到端证据（2026-09-22，沙箱直连）

1. `POST /email/new` → `c4cfelwz04@lnovic.com`
2. `POST arena.ai/nextjs-api/sign-up`（recaptchaToken 空，方案 §2 实测不校验）→ 200 `access_token`
3. `POST arena.ai/nextjs-api/sign-up/magic-link`（email=上述地址）→ 200 `{"success":true,...}`
4. 轮询 `GET /email/.../messages` → **5 秒**后收到 `Confirm Your Signup`，
   `body_text` 含 `https://arena.ai/nextjs-api/callback/email?token=pkce_...\u0026type=email\u0026signup_intent_id=...`
   —— 与 `RegisterClient.VERIFY_LINK_RE` 匹配；`\u0026`/`\/` 转义由现有 `sanitizeLink` 处理。

## 集成注意点 / 风险

- **非 catch-all**：每次注册必须先 `/email/new`（失败重试=再建一个新地址，local 不可自选）。
- **域名轮换**：域名列表会变，provider 不应硬编码域名（`/email/new` 返回什么用什么）。
- **内部 API 无 SLA**：路径/行为可能变（对照 10minutemail 的 JWT 抠取风险同级）。
- **限流未公布**：Web 端每 5~10s 轮询一次；保持现有 `pollIntervalMs=5s` 量级，勿加速。
- 邮件 TTL：公共邮箱约 90 天（`forward_max_seconds≈7.77e6`），远超注册流程所需。

## 建议的接入设计（下一批实现）

- `TempMailIoProvider : MailProvider`（core/register）：`createMailbox` = `POST /email/new`；
  `waitForLink` = 轮询 `GET /email/{email}/messages`，对每封消息的 `body_text`+`body_html` 跑同一个
  `pattern`，命中后走 `sanitizeLink`。无 JWT 状态，无 401 分支。
- `TaskSettings.mailProvider`（`tenminmail` 默认 | `tempmailio`），设置页邮箱线路单选
  （与 engineGroup 同款交互）；`RegisterActivity` / `DrawActivity.protocolRegister` 的 `mailFactory` 按设置分流。
- 两条线路共用 `MailHttp`（邮件流量依旧不走代理）。
