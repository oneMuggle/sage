---
name: cnki-research
description: 在知网（CNKI）检索、阅读并下载学术论文，覆盖登录态、动态页面、PDF 下载与校验。当用户要在知网找文献、下载 PDF、或抓取需要登录的知网页面时使用。
license: Apache-2.0
compatibility: 需要 browser_launch/browser_navigate/browser_snapshot/browser_interact/browser_downloads/browser_login/web_fetch 工具
when_to_use: 当用户提到"知网""CNKI""下载知网 PDF""知网检索"，或明确要求在需要机构/个人登录的知网页面取全文时使用
allowed-tools: browser_launch browser_navigate browser_snapshot browser_interact browser_downloads browser_login browser_cookies web_fetch http_download
triggers: []
---

# 知网（CNKI）文献检索与下载

> 仅使用用户自己的合法账号与机构权限；不绕过付费墙、DRM 或双因素认证。
> 默认节奏：每篇间隔 5–12 秒，单批 ≤20 篇；遇到验证码/滑块交还用户处理。

## 0. 前置判断

1. 用户是**校园网/机构 IP** 访问 → 通常无需登录，直接检索。
2. 用户是**个人账号 / 机构账号（CARSI）/ 校外访问** → 需要登录：
   - 优先调用 `browser_login`，`url=https://kns.cnki.net/`；
   - 在可见浏览器窗口完成登录（账号密码/扫码/机构 SSO），Sage 会自动保存
     cookie + localStorage（双 token 站点）。
3. 如果 `web_fetch` 返回 `login_wall` / `login_required`，不要反复重试，按上面登录。

## 1. 检索

使用浏览器通道（知网是 Vue SPA，静态抓取拿不到结果）：

1. `browser_launch`（`headless=false` 便于观察与处理验证码）。
2. `browser_navigate` 打开：
   `https://kns.cnki.net/kns8s/defaultresult/index?kw=<关键词>&korder=SU`
   - **`wait_for=".result-list, .search-result-wrap, #result-table, .s-main"`**：
     搜索结果由 XHR 异步加载，加 `wait_for` 让导航等待结果容器出现再返回。
3. `browser_snapshot` 读取结果页；需要翻页时用 `browser_interact` 点击
   「下一页」，不要手工拼接带 `QueryID`/`v=` 的详情页 URL。
4. **点击搜索按钮后**：若首次 `browser_snapshot` 结果列表为空，
   不要立即判断失败——SPA 搜索请求可能还在进行，请等待 2–3 秒后重新
   `browser_snapshot`；或改用 `browser_navigate wait_for=...` 直接导航到
   结果 URL（见上方）。
5. **知网内网镜像库**部分版本把搜索结果放在 `<iframe>` 内，
   `browser_snapshot` 会自动扫描 same-origin iframe 内容并标注 `frame_url`；
   若 `elements` 中出现 `role: "iframe"` 且 `frame_url` 指向结果页，
   可用 `browser_navigate url=<frame_url>` 直接进入该 frame。
6. 热门/高频检索可能触发滑块验证码：停下来请用户在窗口中完成，
   不要自动破解。

## 2. 打开文献详情

- 在结果列表里按标题文本点击（`browser_interact action=click text=<标题>`），
  或从结果中提取详情链接后 `browser_navigate`。
- 详情页里用 `browser_snapshot` 确认：题名、作者、来源、年份、摘要、下载按钮。

## 3. 下载 PDF（禁止 CAJ）

1. 只点可见文本为「PDF下载」的入口；**不要**选择「CAJ下载」。
2. 知网下载链接是动态生成的短时效 token（≤60 秒、单次有效），必须在
   当前已登录的浏览器会话里点击，不要复制链接到 `http_download`。
3. 下载后用 `browser_downloads`（`wait_for_complete=true`）等待完成并登记 artifact。
4. 校验：
   - 文件头必须是 `%PDF-`；
   - 题名与用户请求一致（先做去空白/标点归一化）；
   - 打不开或不是 PDF → 报告失败，不要当作成功。
5. 若机构权限不足（403 或没有下载按钮）：如实告知用户需要机构订阅/登录，
   不要尝试绕过。

## 4. 输出

按用户要求整理：题名 / 作者 / 来源 / 年份 / 摘要要点 / 本地文件路径。
批量任务先给清单，再逐篇下载；失败项列出原因，不要静默跳过。

## 5. 合规与边界

- 仅用于个人学习/科研，遵守知网 robots 与机构协议；
- 不并发轰炸、不批量转售、不绕过登录/付费墙；
- 不把 cookie、令牌、账号密码写入聊天或文件。
