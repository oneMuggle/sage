# mail.cx 可用性探测（2026-09-22）

结论：**可用，已端到端验证**。arena.ai 接受其域名（uqu.me），验证邮件约 3 秒到达，
链接形状与现有 `VERIFY_LINK_RE` 一致。作为第三条邮箱线路接入。

## 探测环境

- 探测方：本沙箱（海外出口）直连，无拦截、无人机验证。
- 前端逆向：mail.cx 是 Remix 应用，收件逻辑在 `MailboxWidget-*.js` / `mailbox-*.js` / `client-*.js`，
  接口为站点自用免鉴权 REST（注册用户另有 x-api-token / 自定义域 / SSE，本线路未使用）。

## API 契约（站点自用，免鉴权）

基址 `https://mail.cx/v1`，无需 cookie / token，带一个随机 `X-Client-ID` 头即可：

1. `GET /v1/config` → `{system_domains:[{domain,default}], local_part_rules:{min_length:2,
   max_length:20, pattern:"^[a-z0-9._-]+$", reserved:[38 个保留名]}, ttl_seconds:3600}`。
   本次域名：ddker.com / 9k3r.com / uqu.me（default）——会轮换，勿硬编码。
2. **无建箱请求**：catch-all，地址本地拼出即用（`local@domain`，遵守上面的规则与保留名）。
   官网「Get this address」也只是本地赋值，不发任何创建请求。
3. `GET /v1/inbox/{addr URL 编码}` 是**长轮询**：空箱挂住约 25s 后返回 `204`；
   有信立即 `200 {emails:[{id,subject,from_email,preview_text,size,created_at}], next_since}`
   —— 列表只有摘要（preview_text 截断），不含全文。
4. `GET /v1/email/{id}` → 全文 `{text_body, html_body, attachments, from, to, date, …}`（亚秒级）。
   另有 `/v1/email/{id}/raw`、`/v1/email/{id}/attachments/{index}` 未使用。
5. 免费箱 TTL 1 小时（`ttl_seconds:3600`），注册流程足够。

## 端到端证据（2026-09-22，沙箱直连）

1. 本地拼地址 `e8fece08d5dk@uqu.me`（未发过任何「创建」请求）
2. `POST arena.ai/nextjs-api/sign-up`（recaptchaToken 空）→ 200 `access_token`
3. `POST arena.ai/nextjs-api/sign-up/magic-link` → 200 `{"success":true,…}`
4. `GET /v1/inbox/e8fece08d5dk%40uqu.me` → **1.8s** 返回 `Confirm Your Signup`
   （`Arena <team@everify.arena.ai>`）
5. `GET /v1/email/{id}` → `text_body` 含
   `https://arena.ai/nextjs-api/callback/email?token=pkce_…&type=email&signup_intent_id=…`
   （方括号包裹、干净 &），匹配 `VERIFY_LINK_RE`；方括号与 `&amp;` 由共用 `cleanLink` 剥掉。

## 与另两条线路的差异

| 维度 | 10minutemail | temp-mail.io | mail.cx |
|---|---|---|---|
| 建邮箱 | 页面抠 JWT + 自造 local | `POST /email/new` 服务端起名 | **本地拼地址（catch-all，零请求）** |
| 读信 | 列表 id → 逐封取正文 | 列表即全文 | 列表摘要 → **逐封取全文** |
| 轮询 | 常规 5s | 常规 5s | **长轮询 ~25s（204=空）** |
| 鉴权 | Bearer JWT（401 刷新一次） | 无 | 无（X-Client-ID 即可） |
| 邮箱 TTL | 数小时 | ~90 天 | **1 小时** |
| arena 验证邮件 | 已验证可用 | 已验证（~5s） | **已验证（~3s）** |

## 集成注意点 / 风险

- **读超时**：长轮询挂 ~25s，邮件侧 transport 读超时须 ≥45s（`MailProviders` 已统一放宽）。
- **域名轮换**：每次 `GET /v1/config` 取默认域；拉不到回退内置 `uqu.me`。
- **保留名/规则**：local 2–20 位 `[a-z0-9._-]`，保留名列表随 config 下发（provider 内置快照兜底）。
- 限流：官网标 10 req/s（带 token）；匿名未公布。本线路一次注册约 3–5 个请求 + 长轮询，远低于此。
- 站点 API 无 SLA，路径/行为可能变（与 10minutemail 抠 JWT 同级风险）。
