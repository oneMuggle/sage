# Sage 网页访问与文件下载能力分析及优化方案（Round 5 候选）

- **日期**：2026-09-14
- **状态**：方案完成，**B1 已实施**（分支 `feat/web-access-round5-b1`，基于 origin/main），**B2 已实施**（分支 `feat/web-access-round5-b2`，基于 B1），**B3 已实施**（分支 `feat/web-access-round5-b3`，基于 B2）；B4–B6 待排期
- **勘察范围**：`backend/tools/{web_tool,download_tool,browser_tool,browser_cdp,browser_ws,web_render,web_cache,credential_vault,http_factory,network_config}.py`、`backend/domain/network_policy.py`、`docs/plans/2026-09-*_web-access-*.md`（Round 1–4）
- **方法**：只读代码勘察（附 `file:line`），对照 Round 1–4 已交付项，避免重复提案
- **编号约定**：AB = 反爬；AU = 登录态；SN = 嗅探；DL = 下载稳定性/续传；X = 横切

---

## 0. 结论速览

Round 1–4 已把"能不能用"打通：多引擎搜索、用户级代理、持久 profile、cookie 桥、JS 渲染池、TTL 缓存、UA 现代化、设置 UI。**当前最大的结构性短板集中在下载链路**——`http_download` 是一次性 GET、零重试、零续传、不发浏览器头、不校验完整性；而浏览器通道触发的下载则完全没有完成跟踪。反爬侧的短板是 **httpx TLS 指纹 + 单调请求头** 在 Cloudflare/Akamai 类风控前必然被识别，目前只能"报错后指引模型转浏览器通道"，缺少自动升级。

| 维度 | 现状评级 | 核心缺口 |
| --- | --- | --- |
| 网页访问（普通站） | ★★★★☆ | 无重试/退避；每跳新建 client 无连接复用 |
| 反爬网页访问 | ★★☆☆☆ | httpx 指纹裸奔；403/429 只给文案不自动降级到浏览器；无 Retry-After 处理 |
| 登录态保持 | ★★★☆☆ | cookie 快照无过期/刷新；仅 cookie 一种凭据；渲染池与 http 通道登录态不互通 |
| 文件嗅探 | ★☆☆☆☆ | 没有嗅探能力：web_fetch 遇 PDF 直接当文本；不解析 `<a download>`/meta refresh/JS 跳转；不监听浏览器网络流 |
| 下载稳定性/续传 | ★★☆☆☆ | 无重试、无 Range 续传、无 `.part` 原子落盘、无完整性校验、无进度/取消、无并发 |

---

## 1. 现状勘察（附证据）

### 1.1 网页访问通道

三条通道：

| 通道 | 实现 | 门禁 | 备注 |
| --- | --- | --- | --- |
| 静态 httpx | `WebFetchTool._get_with_redirects` web_tool.py:462-540 | 逐跳 `check_host` + subagent 公网 IP 校验 + 4 MiB 上限 | `Accept-Encoding: identity`、手动 5 跳重定向、每跳**新建** client |
| headless 渲染池 | `web_render.render_page` + `_RendererPool`（单实例、300s 空闲回收） | 与静态同口径 | `auto` 模式靠 `looks_like_js_shell` 启发式（正文<500 字 或 script 占比>25%） |
| 交互式浏览器 | `browser_launch/navigate/snapshot/interact/screenshot/cookies` | `validate_url` + `check_host` | 真 Chrome 指纹，`--headless=new`；启动参数 browser_cdp.py:269-284 |

**观察**：
- 静态通道已有 `_ANTIBOT_GUIDANCE`（web_tool.py:47-55），但**只是文案**，没有代码级自动升级。
- 请求头固定 3 个（UA/Accept/Accept-Language），缺 `Sec-CH-UA*`、`Sec-Fetch-*`、`Upgrade-Insecure-Requests`、`Referer`——这是比 UA 版本更"廉价"的 bot 信号（Chrome 126 一定会带 Client Hints）。
- httpx 0.26 不启用 HTTP/2（`http2` 无引用），Cloudflare 的 JA3/JA4 + ALPN 指纹判定下几乎必然落入 challenge。
- 没有任何重试/退避：一次 `ConnectError`/`ReadTimeout`/5xx 即失败。
- Chrome 启动没有 `--disable-blink-features=AutomationControlled`，`navigator.webdriver === true` 直接暴露（新 headless 下仍为 true）。
- 渲染池的 `Page.navigate` 结果里 HTTP 状态不可见（未监听 `Network.responseReceived`），Cloudflare 5 秒盾页会被当成"渲染成功的正文"返回给模型。

### 1.2 登录态保持

已交付（Round 1 A1/A3）：
- 持久 profile：`browser_launch persistent=true profile_name=…`，落 `_profiles_root()/<name>`。
- cookie 桥：`browser_cookies export` → `credential_vault.save_credential`（SecretBox 加密，按 cookie domain 分组）→ `web_fetch/http_download credential_domain=` 附 Cookie 头，跨域重定向剥离。
- 渲染池可选持久 profile（`web_access_config.render_persistent`）。

**缺口**：
- **cookie 是一次性快照**：`save_credential` 只存 name/value/domain/path，丢弃 `expires`/`httpOnly`/`secure`/`sameSite`（credential_vault.py:85-92）。过期 cookie 照样发送，站点 302 到登录页时模型只看到"正文变短"，无明确 `credential_expired` 信号。
- **单向同步**：httpx 收到的 `Set-Cookie`（会话续期、CSRF token 轮换）被丢弃，不写回 vault；也不回写浏览器 profile。
- **无自动刷新**：没有"检测到登录失效 → 用持久 profile 静默重新导出"的回路。
- **凭据类型单一**：只支持 Cookie，不支持 `Authorization: Bearer`、自定义头（如 API key）、HTTP Basic。学术 API（Semantic Scholar、CrossRef polite pool）、企业内网 SSO 常见此类。
- **secure cookie 越 http 发送**：不检查 `secure` 标志，`http://` 目标也会附带（信息泄露面）。
- 交互浏览器与 http 通道的登录态需要模型手动 `browser_cookies export` 桥接，没有"web_fetch 命中登录墙时自动查 vault"的便捷路径。

### 1.3 文件嗅探

**当前基本为零**：
- `web_fetch` 对非 HTML 直接 `text[:max_length]`（web_tool.py:558-560），PDF 会以乱码返回；没有"这是二进制，请改用 http_download"的引导，也不返回 `Content-Length`/`Content-Disposition`。
- `http_download` 完全信任传入 URL，不能处理：
  - 落地页 → 真实文件（`<a download>`、`<meta http-equiv="refresh">`、`window.location=` JS 跳转、`<iframe src=*.pdf>`、`<embed>`、`citation_pdf_url` meta）；
  - 需要点击才触发的下载（`POST` 表单、JS 生成的 blob URL）；
  - HTML 错误页伪装成 200（Content-Type 为 text/html 却带 .pdf 后缀）。
- 浏览器通道虽已 `Browser.setDownloadBehavior allow`（browser_tool.py:286-295），但**没监听 `Browser.downloadWillBegin/downloadProgress`**：模型点击后不知道文件名、不知道是否完成、无法拿到最终路径；`browser_ws` 是短连接（"CDP 短连接丢弃事件帧"，web_render.py 文档注释），结构上收不到事件。
- 无 MIME 嗅探/魔数校验：下载完成后不校验 `%PDF-`、`PK\x03\x04` 等，HTML 登录页存为 `paper.pdf` 无感知。

### 1.4 下载稳定性与续传

`HttpDownloadTool._stream_to_disk`（download_tool.py:270-388）：

| 能力 | 现状 |
| --- | --- |
| 重试 | **无**。`httpx.HTTPError` 直接包成失败 |
| 断点续传 | **无**。不发 `Range`，不读 `Accept-Ranges`/`ETag`/`Last-Modified` |
| 原子落盘 | **无** `.part` + rename；异常时 `unlink` 已写文件——中断即全丢 |
| 完整性 | 不比对 `Content-Length` vs 实际字节（只查"超限"，不查"不足"）；无 hash 校验 |
| 请求头 | 只有可选 Cookie，**无 UA/Accept**（web_tool 的 `_DEFAULT_HEADERS` 没复用）——文献站/网盘对无 UA 请求 403 是常态 |
| 超时 | 单一 `timeout_seconds=30`（读/连/写同值），大文件慢速链路易 ReadTimeout |
| 进度/取消 | 无进度事件、无取消句柄；100 MiB 上限内同步阻塞 executor 线程 |
| 并发 | 单线程串行；多文件靠模型多次调用 |
| 压缩 | 未设 `Accept-Encoding: identity`，服务器若 gzip，`Content-Length` 与落盘字节不可比 |
| 文件名 | ✅ RFC 5987 + 去路径 + 冲突加后缀 + O_EXCL/O_NOFOLLOW（做得好） |
| Electron 侧 | `modelDownloadIpc.ts` 有 `.part`+rename 但同样无 Range 续传（仅模型下载用，与后端工具不共享） |

对比：Round 1 §PF-1 说明 download_tool 的安全加固已到位，但"可靠性"从未被任何一轮列入范围。

---

## 2. 优化方案

优先级：P0 = 直接影响核心场景（文献 PDF 下载）；P1 = 显著提升成功率；P2 = 体验/成本。

### 2.1 DL：下载可靠性（P0）

**DL1 重试 + 退避 + 续传（核心）**

```
http_download(url, filename?, max_bytes?, credential_domain?,
              retries: int = 3, resume: bool = true, expected_sha256?: str)
```

- 落盘走 `<name>.part`，成功后 `os.replace` 到最终名；`.part` 旁存 `<name>.part.json`（url、etag、last_modified、total、written、saved_at）。
- 失败可重试异常集合：`ConnectError/ReadTimeout/RemoteProtocolError/ReadError`、5xx、429（尊重 `Retry-After`，上限 60s）。指数退避 `1s·2^n + jitter`，最多 `retries` 次。
- 续传：重试或再次调用时若 `.part` 存在且服务器上次响应 `Accept-Ranges: bytes` → 发 `Range: bytes=<written>-` + `If-Range: <etag|last-modified>`；收到 206 追加写，收到 200 则丢弃 `.part` 重下，收到 416 视为已完成。
- 完整性：结束后若 `Content-Length` 已知且 `written != total` → `incomplete_download` 失败并**保留 `.part`** 供续传；`expected_sha256` 给定则校验。
- 超时拆分：`httpx.Timeout(connect=10, read=60, write=30, pool=10)`，读超时按块计而非整文件。
- 请求头复用 `_DEFAULT_HEADERS`（UA/Accept/Accept-Language）+ `Accept-Encoding: identity`（保证 Content-Length 可比）+ `Referer`（默认取 URL 的 origin，可参数覆盖——很多文献站校 Referer）。
- 返回值增加 `resumed: bool, attempts: int, sha256, total_bytes, elapsed_ms, speed_bps`。

安全口径不变：`.part` 与 `.json` 同样经 `_open_exclusive`；Range 续传的每一跳仍走 `check_host`；`If-Range` 不匹配一律重下（防止拼接不同版本）。

**DL2 后台任务化 + 进度 + 取消（P1）**

- 新 `download_job` 状态机（pending/running/paused/done/failed），落 SQLite `downloads` 表；`http_download` 增 `background: bool = false`，true 时立即返回 `job_id`，走 `report_progress`/RunEvent 流投影进度（复用子代理事件投影通道，不新增通道）。
- 新工具 `download_status(job_id?)`、`download_cancel(job_id)`。大于 20 MiB 时 schema 描述建议模型使用 background。
- 并发上限：全局信号量 3，同 host 1（避免触发限流）。

**DL3 MIME 嗅探与内容校验（P0，见 SN2 复用）**

- 落盘前读首块做魔数判定；若 URL/`Content-Disposition` 暗示 PDF/ZIP/DOCX 而首块是 HTML → 立即中止并返回 `html_instead_of_file`，附前 2 KB 文本摘要（登录页 / 验证码 / 反爬盾）与路由指引（`credential_domain` 或浏览器通道）。这条直接堵住"下载了一个 12 KB 的 paper.pdf 其实是登录页"的高频故障。

### 2.2 SN：文件嗅探（P0/P1）

**SN1 `web_fetch` 二进制感知（P0，改动最小）**

- 非 HTML 且 Content-Type 属二进制族（`application/pdf|zip|octet-stream|msword|vnd.openxmlformats*|x-*`）或首 512 B 含 NUL/魔数 → 不返回乱码正文，改返 `{"kind":"binary","content_type","content_length","suggested_filename","hint":"请用 http_download 下载"}`。
- 走 `HEAD` 不可靠（很多站禁 HEAD），沿用现有流式 GET 读首块即关闭。

**SN2 `sniff_download_links` / `web_fetch mode=files`（P1）**

- `web_fetch` 新 mode `files`：从（静态或渲染后）DOM 抽取候选文件链接并打分：
  - `<a href>` 后缀 `.pdf/.zip/.docx/.xlsx/.pptx/.epub/.csv/...`、`download` 属性、`type=application/pdf`；
  - `<meta name="citation_pdf_url">`、`<link rel="alternate" type="application/pdf">`（学术站标准）；
  - `<iframe|embed|object src>`；`<meta http-equiv=refresh>`；
  - 锚文本/aria-label 含 `download|PDF|全文|下载|附件`。
- 输出 `[{url, text, source:"anchor|meta|iframe", ext, score}]`，并对 top-N 做轻量探测（流式 GET 首块 → content_type/length/magic）；结果直接可喂 `http_download`。
- 对 `render=auto/always` 的页面，在渲染标签页内额外监听 `Network.responseReceived` 抓取 `application/pdf` 等响应 URL（需要 SN3 的长连接基础）。

**SN3 浏览器下载跟踪（P1）**

- `browser_ws` 增"事件订阅"模式：在 `browser_launch` 后维持一条常驻 WS（每 session 一个线程），订阅 `Browser.setDownloadBehavior{eventsEnabled:true}` 的 `downloadWillBegin/downloadProgress`，落到 `session.downloads[guid] = {url, suggestedFilename, state, receivedBytes, totalBytes, path}`。
- 新工具 `browser_downloads(browser_id?, wait_for_complete: bool, timeout)`：列出/等待下载完成，返回最终路径并 `_record_artifact`。
- 同一条 WS 顺带解决 1.1 的"渲染页不知道 HTTP 状态"（订阅 `Network.responseReceived` 主帧），让 Cloudflare 403/503 盾页在渲染分支也能触发 AB 指引。

### 2.3 AB：反爬访问（P1）

**AB1 自动升级链（P1，收益最大）**

把 `_ANTIBOT_GUIDANCE` 从"文案"变"代码"：`web_fetch` 增 `escalate: bool = true`（默认）。静态请求命中 403/429/503 **或** 正文命中盾页特征（`cf-browser-verification`、`__cf_chl_`、`Just a moment`、`验证码`、`Access Denied` + `akamai`、`_Incapsula_`、`aliyun waf` 等）→ 自动经渲染池重放一次（真 Chrome 指纹 + 用户代理配置 + 可选持久 profile）；渲染仍失败才返回指引。结果标 `escalated: "render"`。

- 门禁：升级到渲染仍受 `check_host`；OFFLINE/INTRANET 不注册渲染时跳过。
- 成本控制：只对 HTML 目标升级；429 先按 `Retry-After` 退避一次再升级。

**AB2 请求头拟真（P1，一处常量）**

`_DEFAULT_HEADERS` 补齐 Chrome 126 实际发送的头，并保持自洽：
```
Sec-CH-UA: "Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"
Sec-CH-UA-Mobile: ?0
Sec-CH-UA-Platform: "Windows"
Sec-Fetch-Dest: document / Sec-Fetch-Mode: navigate / Sec-Fetch-Site: none / Sec-Fetch-User: ?1
Upgrade-Insecure-Requests: 1
```
UA 版本号改为**每次启动从已发现的本地 Chrome 版本读取**（`discover_browser_executable` 已有路径，`--version` 一次即可），保证 UA 与真浏览器通道一致且永不过期。

**AB3 TLS/HTTP2 指纹（P2，可选依赖）**

- 最低成本：`httpx[http2]`（h2）开启 HTTP/2——ALPN 与 SETTINGS 帧更接近浏览器，能过一部分低档风控。
- 进阶：可选依赖 `curl_cffi`（impersonate="chrome"），在 `http_factory.build_client` 增 `impersonate` 开关；未安装时透明回退 httpx。**win7 分支不引入**（保持 stdlib+httpx 纪律），main 作为 `web_access_config.tls_impersonate` 可选项。

**AB4 Chrome 启动去自动化痕迹（P1，两行）**

`_build_launch_command` 增 `--disable-blink-features=AutomationControlled`；渲染池/交互浏览器 `Target.createTarget` 后 `Page.addScriptToEvaluateOnNewDocument` 注入最小 stealth（`navigator.webdriver` 置 undefined、`navigator.languages`、`window.chrome` 占位）。不追求完整 stealth 库，只堵最廉价的三项。

**AB5 请求级重试与 Retry-After（P1）**

`web_fetch`/`web_search` 对 `ConnectError/ReadTimeout` 与 5xx 做 2 次退避重试；429 读 `Retry-After`（≤30s）。同 host 加简单令牌桶（默认 2 req/s），防止子代理并发把站点打限流——这是缓存 C1 之外的另一半限流对策。

**AB6 连接复用（P2）**

`_get_with_redirects` 每跳新建 client 使 TLS 握手翻倍且失去 keep-alive；改为**一次 execute 一个 client**（`verify` 仍可按跳判断：多数场景 `allows_insecure_tls` 对整个 execute 一致；若跳间不一致再新建）。对代理用户尤其明显。

### 2.4 AU：登录态（P1）

**AU1 cookie 元数据与过期判定（P1）**

- `save_credential` 保留 `expires/httpOnly/secure/sameSite`；`cookie_header_for(domain, url)` 按 `expires` 过滤已过期、按 `secure` 拒绝 http、按 `path` 匹配。
- 全部过期 → 返回 `credential_expired`（区别于 `credential_not_found`），指引重新登录导出。
- `browser_cookies list` 显示 `expires_in` 最短项，让模型/用户预知失效。

**AU2 Set-Cookie 回写 + 登录墙检测（P1）**

- `web_fetch/http_download` 带凭据的请求收到 `Set-Cookie` 且 domain 命中档案域 → 合并回 vault（续期 token 不丢）。
- 登录墙启发式：带凭据请求被 302 到含 `login|signin|sso|auth|passport` 的 URL，或最终页面含密码输入框 → 返回 `login_required` 并附 `credential_domain`，而非普通正文。

**AU3 自动刷新回路（P2）**

`web_access_config.auto_refresh_credentials=true` 时，AU2 触发 `login_required` 且存在同域**持久 profile** → 用渲染池（persistent）静默访问一次原 URL，若页面已登录（无密码框）则自动 `Network.getCookies` 重新导出并重放请求。用户只需在持久 profile 里登录过一次。

**AU4 头部凭据（P1）**

vault 增 `kind: "cookie" | "header"`；`browser_cookies` 之外新增 `credential_set(domain, header_name, value)`（EXTERNAL 风险，值不回显）。`credential_domain` 命中 header 型档案时附 `Authorization`/自定义头，同样跨域剥离。覆盖 API key / Bearer / Basic 场景。

**AU5 渲染池 ↔ vault 双向（P2）**

`render_persistent` 开启时，`web_fetch credential_domain=` 走渲染分支前用 `Network.setCookies` 注入 vault cookie（无需用户先在 render profile 里登录）；反向：渲染完成后 domain 命中时回写。让"一次导出，三条通道共用"。

### 2.5 X：横切

- **X1 统一网络 helper**：`http_factory` 增 `default_headers()`、`retrying_send(client, request, policy)`、`sniff_first_chunk(response)`，web_tool/download_tool/search_engines 三处共用，避免下一轮再出现"download 没 UA"这种漂移。
- **X2 可观测**：出网工具结果统一附 `net: {attempts, escalated, resumed, elapsed_ms, bytes}`；`metrics_routes` 暴露 per-host 成功率/403 率，为后续调优提供数据。
- **X3 模型侧引导**：schema 描述明示决策树——"先 `web_fetch mode=files` 嗅探 → `http_download`（自动重试/续传）→ 失败按 `error` 前缀（`html_instead_of_file`/`login_required`/`http_403`）选 `credential_domain` 或浏览器通道"。

---

## 2.6 B1 实施记录（2026-09-14）

| 项 | 落点 | 说明 |
| --- | --- | --- |
| DL1 重试/退避 | `download_tool.py` `execute` 重试环 + `_RetryableError` | 可重试：`Connect/Read/Write/PoolTimeout`、`ConnectError/ReadError/WriteError/RemoteProtocolError`、408/425/429/5xx；`Retry-After` ≤60s；401/403 不重试给指引；404 等 4xx 不重试。`_sleep` 模块级钩子供单测替换 |
| DL1 `.part` + 续传 | `_PartState`（`.part` / `.part.json`）、`_attempt` 发 `Range`/`If-Range`、`_consume` 处理 206/200、`_attempt` 处理 416 | 文件名可预知（显式 `filename` 或 URL 末段）时跨调用续传；Content-Disposition 决定的名字首次中断后不可续传（明示限制，见 `_DownloadContext.part_for`）。`_unique_path` 同时避让 `.part` |
| DL1 完整性 | `_consume` 末尾长度比对 → `incomplete_download`；`_finalize` sha256 | 续传路径的 sha256 走整文件重算 |
| DL1 头/超时 | `_hop_headers`、`_timeout` | `Accept: */*`、`identity`、`Referer` 默认 origin |
| DL3/SN1 嗅探 | 新模块 `content_sniff.py`；`_consume` 首块 `sniff().mismatch` → `html_instead_of_file`；`web_tool._render` → `_binary_result` | 魔数表覆盖 pdf/zip(ooxml)/ole/gz/bz2/xz/7z/rar/png/jpeg/gif/exe/elf/sqlite/mp4/mp3/ogg/flac；Content-Type 明示文本时不按二进制 |
| X1 共用头 | `http_factory.DEFAULT_HEADERS` / `default_headers()` | `web_tool._DEFAULT_HEADERS` 保留为别名 |

测试：`test_download_tool.py` +26 用例（重试次数 / 退避序列 / Retry-After 及上限 / 403 不重试 / HTML 伪装 PDF / Content-Type 撒谎 / 无期望不拦 / 不足保留 .part / 无 Range 重下 / 遗留 .part 续传 / resume=false / 服务器忽略 Range / 416 完成 / sha256 / 分段超时 / 流中断续传 / 首块前中断干净重试），`test_content_sniff.py` 新增 14 组，`test_web_tool.py` +5（binary hint / octet-stream+disposition / raw 模式 / json+text 仍为文本 / 不渲染）。

双分支：所有改动文件在 main 与 origin/release/win7 上**同源**（`git diff` 为空，仅 `test_download_tool.py` 有 4 行 win7-only 差异），新模块 stdlib+httpx、`from __future__ import annotations` + `typing.*`，py3.8 `ast.parse(feature_version=(3,8))` 通过——cherry-pick 到 win7 预期零冲突。

## 2.7 B2 实施记录（2026-09-14）

| 项 | 落点 | 说明 |
| --- | --- | --- |
| AB1 自动升级链 | `web_tool.py` `_AntibotBlocked` / `looks_like_antibot_page` / `WebFetchTool._escalate` | 触发：`_get_with_redirects` 任一跳 403/429/503（先于 `raise_for_status` 返回未读体响应）或 2xx 但正文 ≤1200 字且命中 `_ANTIBOT_PAGE_MARKERS`；升级走 `render_page`，检查 `rendered_status` 与盾页特征后按 `mode` 组装结果（`escalated`/`escalated_from`）；`escalate=false`、`render="never"`、`mode="raw"` 不升级，直接返回 `_ANTIBOT_GUIDANCE` |
| AB2 头拟真 | `http_factory._HEADER_TEMPLATE` / `_probe_chrome_major` / `chrome_major_version` / `default_headers()` | `DEFAULT_HEADERS` 改为惰性 dict 代理（首次访问才探测 Chrome，避免 import 期 I/O）；探测源：`discover_browser_executable()` 同目录的 `NNN.x.y.z` 版本目录（Windows），POSIX 回退 `--version`；探测值低于 `FALLBACK_CHROME_MAJOR=126` 则弃用（win7 Chrome 109 仍报 126，避免"老浏览器"被区别对待） |
| AB4 去自动化痕迹 | `browser_cdp._build_launch_command` 新增两 flag；`STEALTH_SCRIPT` / `apply_stealth()`；`web_render._render_once` 导航前调用 | 仅覆盖三个最廉价的信号（webdriver / window.chrome / languages），不做 canvas/WebGL 指纹伪装；`apply_stealth` 吞 `BrowserCDPError` 返回 False；页面脚本新增从 `performance.getEntriesByType("navigation")[0].responseStatus` 取状态码 → `rendered_status` |
| AB5 重试/限速 | `http_factory.parse_retry_after` / `HostRateLimiter` / `get_host_rate_limiter()` / `retrying_send` / `_RETRYABLE_STATUS`；`web_tool._RetryingClient` | web_fetch 逐跳 `retrying_send(stream=True)`；web_search 通过 `build_client(client_class=_RetryingClient)` 让引擎代码零改动获得重试；退避 `0.8·2^n + jitter`（≤8s），`Retry-After` ≤30s；状态码耗尽重试返回最后一个响应交上层处理（403/429 → 升级链）；`_sleep` 为模块级钩子供单测替换 |

测试：`test_web_tool.py` +15（403/429/503/盾页升级、升级后仍盾页给指引、`escalate=false` / `render=never` / `raw` 不升级、links/tables 升级、5xx / 连接错误重试、429 `Retry-After` 后升级、请求头含 Sec-CH-UA / Sec-Fetch、web_search 引擎请求重试）、`test_http_factory.py` +15（头模板 / 版本探测与回退 / `parse_retry_after` 各格式与上限 / `retrying_send` 状态码与异常路径 / `HostRateLimiter` 令牌桶 / `client_class`）、`test_web_render.py` +4（stealth 注入顺序、`rendered_status`、注入失败不阻断）、`test_browser_tool.py` +4（启动 flag / stealth 脚本 / `apply_stealth`）；`test_web_cache.py` 的"失败不缓存"用例按 AB5 语义更新为 `2 × (1 + DEFAULT_FETCH_RETRIES)` 次真抓。

双分支：改动文件 `http_factory.py` / `browser_cdp.py` / `web_render.py` / `web_tool.py` 在 main 与 win7 同源；无新依赖，py3.8 `ast.parse(feature_version=(3,8))` 通过。

## 2.8 B3 实施记录（2026-09-14）

| 项 | 落点 | 说明 |
| --- | --- | --- |
| AU1 元数据/过期 | `credential_vault._clean_cookie` 保留 `expires`（epoch 秒，≤0 视为 session）/ `secure` / `httpOnly` / `sameSite`；`_split_cookies` → (可发送, 已过期)；`cookie_header_for(domain, repo, url, now)`；`cookie_path_matches`；`resolve_credential()` 统一入口返回 `CredentialResolution(status ∈ ok/not_found/expired, headers, expired_names, expires_in)` | web_tool / download_tool 的 `credential_domain` 解析改走 `resolve_credential`，全部过期 → `credential_expired`；`list_credentials` 增 `kind` / `expires_in_seconds` / `expired`；旧档案无 `kind` 字段按 cookie 处理（向后兼容） |
| AU2 回写 | `parse_set_cookie`（stdlib 手写，Domain/Path/Max-Age/Expires/Secure/HttpOnly/SameSite）、`merge_set_cookies(domain, values, url)`；web_tool `_writeback_set_cookies`（`headers.get_list("set-cookie")`，仅凭据实际附加的 hop）；download_tool 同 | 归属域必须落在档案域内（第三方 cookie 不混入）；同名同 path 覆盖；`Max-Age≤0` / 过期 `Expires` 删除；档案清空则删条目；回写失败静默不影响本次请求；web_fetch 结果 `note` 追加 `credential_refreshed` |
| AU2 登录墙 | `looks_like_login_url`（host 前缀 `login./sso./passport./auth./idp./accounts.` 或 path 片段 `login/signin/sso/passport/authenticate/authorize/oauth/cas/idp`）、`looks_like_login_html`（`<input type=password>`）；web_tool `_detect_login_wall`；download_tool 302 到登录 URL 即返回、首块 HTML 含密码框 → `login_required` | 仅在**携带凭据**时判定（无凭据的登录页就是普通页面）；密码框页面还需"登录类 URL 或去标签后 <250 词"，避免误伤带登录小组件的正文页；起始 URL 本身就是登录页不判定 |
| AU4 头部凭据 | `save_header_credential(domain, headers, repo, ttl_seconds)`（`kind=header` / `headers_enc` / `expires_at`）；`BrowserCookiesTool action=set_header`（`header_name` / `header_value` / `ttl_seconds`） | 头名须合法 token 且不在 `Cookie/Host/Content-Length/Transfer-Encoding/Connection/Accept-Encoding` 内，头值拒 CR/LF；`resolve_credential` 对 header 档案返回原样头；`cookie_header_for` / `load_credential` 对 header 档案返回 `None`（cookie 视角接口语义不变）；web_tool / download_tool 用 `hop_headers.update(credential_headers)` 附加，跨域剥离逻辑与 cookie 共用 |

> 未新增工具名（`credential_set` 并入 `browser_cookies action=set_header`），`tool_names.py` / profiles / win7 settings KEYS 白名单均无需改动 —— 方案 §3 预计的"settings KEYS 白名单需手工 cherry"不再成立。

测试：`test_credential_vault.py` +38（元数据保留 / 过期不发 / 全过期 expired / secure+path 过滤 / path 匹配表 / 旧档案兼容 / list 时效 / web_fetch & http_download `credential_expired` / Set-Cookie 解析两组 / merge 更新-删除-忽略第三方 / 无档案 noop / web_fetch 回写 & 跨域不回写 / download 回写 / 登录 URL 判定 9 组 / 密码框判定 / web_fetch 302 登录页 & 密码框页 & 带登录小组件的正文页不误判 & 无凭据不判定 / download 302 SSO & 登录页代替 PDF / header 存取 / 非法头拒绝 / TTL 过期 / web_fetch 附头 + 跨域剥离 / download 附头 / header 过期 / `set_header` 存档脱敏 & 校验 / export 时效）。

双分支：改动文件 `credential_vault.py` / `web_tool.py` / `download_tool.py` / `browser_tool.py` 在 main 与 win7 同源；stdlib only（`email.utils.parsedate_to_datetime`），py3.8 `ast.parse(feature_version=(3,8))` 通过。

## 3. 实施批次建议

| 批次 | 内容 | 预估 | 双分支 |
| --- | --- | --- | --- |
| **B1（P0）** ✅ | DL1 重试/续传/`.part`/完整性 + DL3/SN1 魔数嗅探 + download 复用默认头 | 已交付 | main + win7（stdlib+httpx，零新依赖） |
| **B2（P1）** ✅ | AB1 自动升级链 + AB2 头拟真 + AB4 去自动化痕迹 + AB5 重试/限速 | 已交付 | main + win7 |
| **B3（P1）** ✅ | AU1 cookie 元数据/过期 + AU2 Set-Cookie 回写/登录墙检测 + AU4 header 凭据 | 已交付 | main + win7（未新增 settings key / 工具名，零手工 cherry） |
| **B4（P1）** | SN3 浏览器事件长连接 + `browser_downloads` + SN2 `mode=files` | 2 天 | main + win7 |
| **B5（P2）** | DL2 后台任务/进度/取消 + AU3/AU5 自动刷新与渲染池互通 + AB6 连接复用 | 2–3 天 | main 优先（涉前端进度 UI） |
| **B6（P2，可选）** | AB3 HTTP/2 / curl_cffi 指纹伪装 | 0.5 天 | main only |

每批验收要点：
- B1：断网/杀连接中途 → 再次调用同 URL 命中 `.part` 并以 206 续传完成；服务器不支持 Range 时重下；HTML 伪装 PDF 被 `html_instead_of_file` 拦截；`Content-Length` 不足报 `incomplete_download` 且 `.part` 保留。
- B2：模拟 403 + 盾页特征 → 自动渲染成功且结果标 `escalated`；`navigator.webdriver` 在渲染页为 undefined；429 按 `Retry-After` 等待。
- B3：过期 cookie 不发送并返回 `credential_expired`；302 到 `/login` 返回 `login_required`；Bearer 档案附头且跨域剥离。
- B4：`browser_interact click` 触发下载后 `browser_downloads wait_for_complete=true` 返回最终路径；`mode=files` 在 arXiv/期刊页抽出 `citation_pdf_url`。

---

## 4. 安全口径与已知限制

- 所有新增出网路径保持 EXTERNAL 风险类与逐跳 `check_host`；续传/升级/自动刷新不放宽 subagent 公网 IP 约束。
- `.part` 元数据不含 cookie 值，只含 etag/length；vault 仍为唯一凭据存储。
- 指纹伪装（AB3）与 stealth（AB4）只做"不主动暴露自动化"，不做验证码破解、不绕过明确的 robots/ToS 拒绝；403 升级链失败后仍以指引结束，不无限重试。
- 浏览器内二次请求与页面 JS 发起的下载仍不受逐跳 `check_host`（与 Round 1 §6 口径一致）。
- win7 分支 Chrome 109 的 Client Hints 与 UA 126 不一致——AB2 的"从本地 Chrome 读版本"同时解决这一点。
