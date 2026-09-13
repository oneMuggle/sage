# 网页访问能力优化 Round 1：搜索多源化 + 登录态持久化 + 渲染深度（2026-09-13）

- **状态**：方案完成，未实施
- **上游文档**：[2026-09-06_web-dynamic-render-access.md](./2026-09-06_web-dynamic-render-access.md)（W1-W5 已交付，W6 backlog 由本文 R1 关闭）、[2026-09-06_coding-agent-parity.md](./2026-09-06_coding-agent-parity.md)（G7 浏览器工具组）
- **范围**：main 与 release/win7 双分支均需交付（见 §3 双分支策略）；前端部分 win7 侧另行评估（§3.4）
- **编号约定**：PF = 前置项；S = 搜索多源；PX = 代理；A = 登录态；R = 渲染深度
- **方法**：代码勘察（web_tool / download_tool / browser_tool / browser_cdp / web_render / network_policy / profiles / settings_repo / secret_box，附 `file:line`）+ 双分支 diff 对勘（2026-09-13 @ 44ff4a59）

## 0. 结论速览

**三大结构性缺口**（对标 ChatGPT/Claude/Perplexity/Tavily 等主流 AI 工具的网页通路）：

1. **搜索单源且大陆不可达**：`web_search` 唯一源是 `html.duckduckgo.com`（web_tool.py:80），大陆用户不开代理直接不可用；无重试、无备用引擎、无 API 引擎接入。代码自认"可能被限流"（web_tool.py:93）但无任何对策。
2. **登录态不可持久**：browser 每次启动 `tempfile.mkdtemp` 临时 profile、关闭 `rmtree`（browser_cdp.py:240/:208）；渲染池 5 分钟空闲重建（web_render.py:60）；CDP cookie 无法导出给 httpx，`web_fetch`/`http_download` 无凭据参数——**订阅源文献 PDF 下载（核心场景）走不通**。浏览器交互触发的下载落在临时 profile 目录，随 close 一起删掉（下载黑洞）。
3. **渲染结果只给纯文本**：渲染分支仅取 `innerText`（web_render.py:246），渲染后页面的 links/tables 拿不到（W6 backlog），对文献列表页是硬伤；无 wait_for 选择器等待；懒加载长列表只抓首屏。

**双分支对勘结论（2026-09-13）**：

- `web_tool.py` / `web_render.py` / `browser_tool.py` / `browser_cdp.py` / `browser_ws.py` / `html_extract.py` / `network_policy.py` / `network_config.py` / `secret_box.py` / `tool_policy.py` **两分支完全一致**——本方案主体文件零冲突，cherry-pick 天然干净。
- `download_tool.py` **win7 领先**：#397（950aceb4）的加固（手动 5 跳重定向逐跳 check_host + POSIX `O_NOFOLLOW` 独占写盘 + `_validate_target_url`）只在 win7，main 仍是 `follow_redirects=True` 只查初始 URL（download_tool.py:118/:186）——正是 2026-09-06 方案 PF-2 对 web_tool.py 做过的同类反向同步，漏了 download_tool.py。**PF-1 先归同源**。
- `profiles.py` 小漂移（win7 的 researcher 多 `memory_save`，本方案不碰该文件，见 §3.3）。
- `settings_repo.py` 小漂移（41 行 diff），加 KEYS 白名单条目时 cherry-pick 手工处理。
- 前端大漂移（win7 精简版，182 文件 -15440 行），但两分支都有 `NetworkTab.tsx` 锚点；win7 侧前端改动按 §3.4 收敛。

## 1. 差距与证据

| # | 差距 | 证据 | 价值 | 优先级 |
| --- | --- | --- | --- | --- |
| PF-1 | download_tool.py #397 加固未反同步 main：重定向不逐跳校验（INTRANET 模式白名单 host 可重定向出白名单） | main download_tool.py:118（`follow_redirects=True`）、:186（仅初始 URL check_host）；win7 #397 已修 | 安全口径统一 + 双分支归同源 | **P0（前置）** |
| S1 | **web_search 单源**：仅 DDG HTML，大陆被墙，无限流对策、无备用引擎 | web_tool.py:80、:93 | 大陆环境搜索从"不可用"变"可用" | **P0** |
| S2 | 无 API 搜索引擎接入（Tavily/智谱等），key 无处存 | web_tool.py 全文 | 对齐主流工具的搜索质量 | P1 |
| PX1 | **无用户级代理配置**：出网工具仅 `trust_env`（web_tool.py:199），无设置界面；浏览器通道也绕不开 | web_tool.py:196-201、download_tool.py:116-120、browser_cdp.py:241-251 | 代理用户全通道解锁 | **P0** |
| A1 | **浏览器 profile 即焚**：每次 `mkdtemp`、关闭 rmtree，无持久化选项；登录态无法跨会话保留 | browser_cdp.py:240、:208 | 登录态保持的前提 | **P0** |
| A2 | **下载黑洞**：页面交互触发的浏览器下载无 `Browser.setDownloadBehavior` 配置，落临时目录随 close 删除 | browser_cdp.py:241-251（无 downloadPath 配置） | 浏览器下载可用 | P1 |
| A3 | **cookie 不打通**：CDP cookie 无法导出；web_fetch/http_download 无凭据参数，登录墙后资源（知网/图书馆 PDF）不可达 | browser_cdp.py 全文（无 Network.getCookies 调用）、download_tool.py schema（无凭据参数） | 订阅源下载核心场景 | **P0** |
| R1 | **渲染只取 innerText**：渲染页无 links/tables（W6 backlog 未关闭） | web_render.py:246-247、web_tool.py:505-507（"渲染页暂不支持 links/tables"） | 文献列表页可用性 | **P1** |
| R2 | 无 wait_for：点击后异步加载的内容只能盲等 3s settle | web_render.py:107-146（wait_page_ready 无选择器等待） | 动态页可靠性 | P1 |
| R3 | 懒加载只抓首屏：渲染取值前不滚动 | web_render.py:243-247 | 长列表完整性 | P2 |
| B1 | 403/429 无路由指引：硬反爬站点报错后模型不知该转 browser 通道 | web_tool.py:333-334 | 模型引导 | backlog |
| B2 | researcher 无 browser 工具，登录态任务无法委派子代理 | profiles.py:185、agent_tool.py:89 | 涉 profiles.py 漂移，缓行 | backlog |
| B3 | 无抓取缓存：同 URL 重复抓取无 TTL 缓存 | web_tool.py 全文 | 限流缓解 + 省 token | backlog |

## 2. 方案设计

### 2.1 PF-1 download_tool.py #397 反向同步（前置）

复刻 2026-09-06 方案 PF-2 的手法：win7 #397 的 `backend/tools/download_tool.py` + `backend/tests/unit/test_download_tool.py` 两个文件原样复制到 main（代码已是 `from __future__ import annotations` + typing.* 风格，直接落地）。落地后 main 的 http_download 获得：手动 5 跳重定向 + 逐跳 `check_host`/`_validate_target_url`、POSIX symlink 防护独占写盘、响应上限校验。**此后 S/PX/A/R 各批次的 download_tool.py 改动双分支零冲突。**

### 2.2 S1+S2 搜索多源化

**新模块 `backend/tools/search_engines.py`（新文件 = 双分支零冲突）**：

- `SearchEngine` 协议：`name` + `search(query, limit) -> list[dict]`（title/url/snippet，与现 schema 同构）。
- `BingEngine`：`https://www.bing.com/search?q=` HTML 端点 + 正则解析（`b_algo` 结果锚点，复用 DDG 引擎同款正则手法与 `_resolve_result_url` 思路）；大陆可达，**默认首选**。
- `DuckDuckGoEngine`：现有 DDG 解析逻辑原样迁入（`_RESULT_ANCHOR_RE` / `_SNIPPET_ANCHOR_RE` / `_resolve_result_url`，web_tool.py:101-158），作后备。
- `TavilyEngine` / `ZhipuEngine`（可选启用）：httpx JSON API，api_key 来自 SecretBox 加密的设置值（见下）；未配 key 时引擎不进链。
- `resolve_engine_chain() -> list[SearchEngine]`：读设置 `search_config`（JSON `{"order": ["bing","ddg"], "tavily_key": "enc:...", "zhipu_key": "enc:..."}`），非法/缺省回退 `["bing","ddg"]`。

**配置加载 `backend/tools/search_config.py`（新文件）**：照抄 `network_config.py` 的 fail-safe 模式（惰性 import SettingsRepository、任何解析失败回退默认链）。`SettingsRepository.KEYS` 白名单加 `"search_config"`（settings_repo.py:34 旁）。

**WebSearchTool 接线**（web_tool.py，改动面小）：`execute` 沿链遍历，首个返回非空结果的引擎胜出；全链空/失败 → 保持 W3 语义（`success=True, results=[], note` 附各引擎失败原因，不伪造）。超时沿用 30s；引擎级失败不重试（fallback 即重试）。

**零新依赖**：全部 httpx + 正则/JSON。

### 2.3 PX1 代理设置

**配置**：settings KV 新 key `"web_proxy"`（JSON `{"http": "", "https": ""}`，空 = 不启用、保持现 `trust_env` 行为），白名单加条目，加载器并入 `search_config.py` 同款 fail-safe 模式。

**注入点**：新辅助模块 `backend/tools/http_factory.py`（新文件）：`build_client(**kwargs) -> httpx.Client`，内部读 `web_proxy` 配置填 `httpx.Proxy`。三个出网工具统一改走它：

- `WebSearchTool` / `HttpDownloadTool` 的长驻 client 改为每次 execute 现建（或配置版本号失效重建），保证设置改动即时生效（WebFetchTool 的 `_get_with_redirects` 本就逐跳新建 client，天然即时生效）。
- `trust_env` 语义保持：manual 代理优先于环境变量；subagent_only 的 `trust_env=False` 口径不变（SSRF 姿态不放宽）。

**浏览器通道**：`launch_browser`（browser_cdp.py:241-251）读同一配置，非空时追加 `--proxy-server=<url>` 启动参数——否则 headless 渲染/browser 工具绕过代理，大陆用户 DDG 渲染依旧不通。

### 2.4 A1+A2 持久 profile 与下载黑洞

**A1 持久 profile**：

- `browser_launch` schema 加 `persistent: bool = false`、`profile_name: str = "default"`（browser_tool.py:226-241）。
- 持久目录：后端数据根下 `browser-profiles/<profile_name>/`（与数据库同级的既有数据目录解析机制），**首次创建后不删**；`_terminate_session`（browser_cdp.py:198-208）对持久 profile 只关进程、保留目录（`headless=false` 时用户可手动登录，登录态随 profile 存续）。
- 启动结果 content 增加 `profile_dir` 与 `persistent` 字段，模型/用户可见登录态存续位置。
- 渲染池（web_render.py:168-213）：新增设置 `web_access_config.render_persistent`（默认 false 保持现状）；开启后渲染实例用持久 profile `render-default`。**5 分钟空闲重建与持久 profile 兼容**——重建后 cookie 从磁盘重载，登录态不丢。

**A2 下载黑洞修复**：

- `launch_browser` 握手完成后发一条浏览器级 `Browser.setDownloadBehavior`（`behavior="allowAndName"`，`downloadPath=<工作区>/downloads/`；未绑定工作区时用后端数据目录 `browser-downloads/`）——CDP 短连接发浏览器级命令无需 sessionId，与现架构兼容。
- `browser_launch` 返回 content 附 `download_dir`；A3 的 cookie 桥落地后，下载文件由 http_download 场景或 file_tool 直接消费。

### 2.5 A3 cookie 桥（登录态 → httpx）

**导出侧**：browser_tool.py 追加 `BrowserCookiesTool`（`browser_cookies`，WRITE_LOCAL 门禁；同文件追加一个类 + `__all__` 一行，cherry-pick 冲突面小）：

- `action="export"`：CDP `Network.getCookies`（经既有 `cdp_command` attach 当前页）取**当前 URL registrable domain** 的 cookie，JSON 打包后经 `secret_box.encrypt_secret(…, account="browser-cookie:<domain>")` 加密，存 settings KV `"browser_credential_vault"`（`{domain: {cookies_enc, saved_at}}`，白名单加条目）。返回脱敏预览（cookie 名列表 + 数量，不给值）。
- `action="delete"`：删除某 domain 档案。

**消费侧**：`web_fetch` / `http_download` schema 加 `credential_domain: str = ""`：设置该参数时从 vault 解密对应 cookie，以 `Cookie` 头附加。**重定向口径**：仅当 hop 的 host 与档案 domain 同 registrable domain 才续附（防止白名单 host 重定向把订阅 cookie 带去第三方）；跨域 hop 静默剥离并在结果 note 中明示。`credential_domain` 必须命中 `check_host` 放行的同一 URL host，不存在独立出网面。

**复用 SecretBox**（secret_box.py:204/:224 encrypt/decrypt_secret），静态加密口径与 API Key 一致；`llm_trace.redactor` 已对 Cookie 头脱敏，日志面无新增泄漏。

### 2.6 R1-R3 渲染深度

**R1 渲染页 links/tables（关闭 W6）**：`render_page` settle 完成后取 `document.documentElement.outerHTML`（上限 `RENDER_HTML_CAP = 512 KiB`，新常量），喂给既有 `wiki/html_extract.extract()` 产出 title/text/links/tables——与静态分支同一抽取器，模式语义完全对齐。`web_tool._render_dynamic`（web_tool.py:486-508）删除"渲染页暂不支持 links/tables"的 note，links/tables 照常按 mode 返回。innerText 链路保留给 settle 判定（等待逻辑不变）。raw 模式直接返回 outerHTML 截断。

**R2 wait_for**：`web_fetch` schema 加 `wait_for: str = ""`（CSS 选择器）；`wait_page_ready`（web_render.py:107）签名扩展 `wait_for=""`——readyState 达标后轮询 `document.querySelector(wait_for) !== null`（沿用 `_READY_POLL_INTERVAL`，上限 READY_TIMEOUT_SECONDS），超时返回已渲染内容 + `wait_for_timeout` note（不失败：半截内容好过没有）。`browser_navigate` 透传同参数（browser_navigate 与渲染分支共用该函数，修一次两处受益）。

**R3 懒加载滚动**：渲染分支 settle 后、取值前：最多 3 轮 `window.scrollTo(0, document.body.scrollHeight)` + 400ms 等待，`scrollHeight` 连续两轮不增长即提前结束——纯 `Runtime.evaluate` 实现，兼容 CDP 短连接架构（不依赖事件帧）。

## 3. 双分支实施策略

### 3.1 文件级对勘结论（改动面清单）

| 文件 | 两分支状态 | 涉及批次 | 冲突预测 |
| --- | --- | --- | --- |
| backend/tools/download_tool.py + test | **win7 领先**（#397） | PF-1 先归同源 → 后续零冲突 | PF-1 本身是复制 |
| backend/tools/search_engines.py / search_config.py / http_factory.py（新） | 均不存在 | S1/S2、PX1 | **零冲突** |
| backend/tools/web_tool.py | 完全一致 | S1（搜索接线）、A3（credential_domain）、R1（note 删除）、R2（wait_for） | 零冲突（改动压到接线层） |
| backend/tools/web_render.py | 完全一致 | R1/R2/R3 | 零冲突 |
| backend/tools/browser_tool.py / browser_cdp.py | 完全一致 | A1/A2、A3（browser_cookies 追加）、PX1（--proxy-server） | 零冲突 |
| backend/tools/network_config.py | 完全一致 | 不改（新配置走新文件） | 零冲突 |
| backend/data/settings_repo.py | 小漂移（41 行） | KEYS 白名单加 3 条（`search_config`/`web_proxy`/`browser_credential_vault`）+ `web_access_config` | cherry-pick 手工处理，量小 |
| backend/agents/profiles.py | 小漂移 | **不碰**（B2 researcher browser 授权移入 backlog） | 规避 |
| src/pages/settings/NetworkTab.tsx 等 | 大漂移（两分支同锚点不同内容） | S/PX/A 设置 UI | 见 §3.4 |

### 3.2 前置项

| # | 事项 | 说明 |
| --- | --- | --- |
| PF-1 | #397 download_tool 反向同步 win7 → main | 两个文件原样复制 + main 侧 CI；0.5 天。不做则 A3/A2 批次要在两套 download_tool 流程各接一遍，漂移永续 |

### 3.3 流程与纪律

- 沿用 round 系列惯例：main 特性分支（本文档所在 `feat/web-access-round1`）→ PR → 落地后 cherry-pick `release/win7`，commit message `cherry(win7): ...`；冲突解决后跑 win7 侧测试。
- **py3.8 纪律（win7）**：新代码一律 `from __future__ import annotations` + `typing.Dict/List/Optional/Tuple`；禁 PEP 604/585、3.9+ API。win7 #397 的 download_tool.py 已是该风格。
- **零新依赖纪律**：S/PX/A/R 全部 httpx + stdlib + 既有 SecretBox/CDP 基建实现；不引入 curl_cffi/Playwright（前者 Win7 轮子不可得，后者破坏零依赖——硬反爬站点的逃生舱是 browser 通道 + 真实 Chrome 指纹，见 §6）。

### 3.4 win7 前端收敛

两分支前端大漂移，设置 UI 不做跨分支同源假设：main 侧在 NetworkTab 扩展搜索引擎/代理/凭据档案三个区块；win7 侧 cherry-pick 后**仅保后端**（配置全走 preferences KV，win7 用户可经 API 或暂缓 UI），前端区块按 win7 现状单独评估，量小则手写、量大则该分支先不上 UI（后端默认链 `["bing","ddg"]` 保证无 UI 也可用）。

## 4. 实施批次与工作量

| 批次 | 内容 | 工作量 |
| --- | --- | --- |
| PF-1 | download_tool #397 反向同步（PR + CI） | 0.5 天 |
| 批次 1（P0） | S1+S2 搜索多源（search_engines/search_config + 接线 + 单测） | 1 天 |
| 批次 2（P0） | PX1 代理（http_factory + 三工具 + browser 启动参数 + 设置 UI） | 1 天 |
| 批次 3（P0/P1） | A1 持久 profile + A2 下载黑洞 | 1 天 |
| 批次 4（P0） | A3 cookie 桥（vault + browser_cookies + 消费接线 + UI） | 1.5 天 |
| 批次 5（P1） | R1+R2+R3 渲染深度 | 1.5 天 |
| 双分支收尾 | cherry-pick win7 + settings_repo 冲突处理 + win7 测试 | 1 天 |
| backlog | B1 路由指引、B2 researcher browser 授权、B3 TTL 缓存、Playwright MCP 外挂（main-only） | 按需 |

## 5. 测试与验收

- **单测**（backend/tests/unit/）：
  - `test_search_engines.py`（新）：Bing/DDG 解析（fixture HTML）、链式 fallback（首引擎空→次引擎）、API 引擎 mock httpx（key 未配不进链）、fail-safe 配置回退。
  - `test_web_tool.py` 扩展：引擎链空结果 W3 语义、`credential_domain` 附加/跨域剥离、`wait_for` 超时 note。
  - `test_http_factory.py`（新）：manual 代理注入、空配置不注入、subagent_only trust_env 不变。
  - `test_browser_tool.py` 扩展：persistent 路径不删、setDownloadBehavior 参数、browser_cookies 导出脱敏 + vault 加密落库、--proxy-server 透传。
  - `test_web_render.py` 扩展：outerHTML→html_extract 链（渲染页 links/tables）、wait_for 轮询序列、懒加载滚动提前收敛。
  - `test_download_tool.py`：PF-1 反同步后 291 项全过 + `credential_domain` 接线用例。
- **验收场景**：① 大陆无代理环境 `web_search` 返回 Bing 结果；② 配置代理后 `web_fetch`/`browser_navigate` 均走代理；③ headless=false 登录知网 → `browser_cookies export` → `http_download(credential_domain=...)` 拉回订阅 PDF；④ SPA 文献列表页 `web_fetch mode=links` 返回渲染后链接列表；⑤ 浏览器内点击触发下载，文件落在 `<工作区>/downloads/` 且 close 后仍在。

## 6. 安全口径与已知限制

- **门禁不放宽**：所有新参数（credential_domain/wait_for/引擎链）仍走 EXTERNAL 风险类 + `check_host`；cookie 仅附加到 check_host 放行且同 registrable domain 的请求；INTRANET/OFFLINE 模式行为不变。
- **cookie 静态加密**：SecretBox（DPAPI/keychain），脱敏预览不回显值；`llm_trace.redactor` 已覆盖 Cookie 头日志脱敏。诊断导出（electron diagnosticExport / write_diagnostics）需排除 `browser-profiles/` 与 vault key——实施时显式核对。
- **持久 profile 风险明示**：登录态落本机磁盘（用户数据目录），工具 description 与设置 UI 明示；不随备份/诊断外带。
- **代理信任明示**：manual 代理可见全部抓取流量，用户自配即自担（设置 UI 提示）。
- **已知限制（明示不解决，沿用 2026-09-06 §6 口径）**：CDP 短连接无事件帧——渲染分支内 JS 二次请求不受逐跳 check_host；cookie 桥不能过 JS 人机挑战（该场景走 browser 通道 headless=false 人工介入）；`--headless=new` 指纹不做隐身处理（硬反爬站点明确指引 browser 人工通道，即 B1 backlog 的路由指引）。
