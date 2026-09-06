# 动态渲染网页访问支持：web_fetch 渲染降级 + 浏览器通路补洞（2026-09-06）

- **状态**：方案完成，未实施
- **上游文档**：[2026-09-06_coding-agent-parity.md](./2026-09-06_coding-agent-parity.md)（第一轮 G7 浏览器自动化已交付）、[2026-09-06_coding-agent-parity-round2.md](./2026-09-06_coding-agent-parity-round2.md)、[2026-09-06_coding-agent-parity-round3.md](./2026-09-06_coding-agent-parity-round3.md)——本文是 G7 之后的定向增强，不重复其内容
- **范围**：main 与 release/win7 双分支均需交付（见 §3 双分支策略）
- **编号约定**：W = Web 访问项；PF = 前置项；与 G7（browser_* 工具组）互引
- **方法**：代码勘察（web_tool / browser_tool / browser_cdp / browser_ws / profiles / html_extract / network_policy，附 `file:line`）+ 双分支 diff 对勘

## 0. 结论速览

**现象**：`web_fetch` 对 SPA（React/Vue 等 CSR 页面）只返回空壳——httpx 拉一次静态 HTML（web_tool.py:268）后用 stdlib HTMLParser 抽正文（html_extract.py:237），全程不执行 JS。

**实质**：渲染能力已存在（G7 的 CDP 浏览器工具组直驱本机 Chrome/Edge），但"读网页"场景到不了它，四处断点：

1. 模型被引导反方向走——browser_* 只注册在 coder（profiles.py:143），系统提示词把网页访问统一导向 web_fetch/只读子代理（profiles.py:316-323）；primary/researcher 无 browser 工具。
2. 无降级信号——web_fetch 拿到 JS 壳返回"成功 + 空内容"，模型不会自发切 browser_launch→navigate→snapshot 三连。
3. 成本高——即便走通，一次动态抓取 = launch(EXEC 审批) + navigate(EXTERNAL 审批) + snapshot 三次调用 + 3-5s 冷启动。
4. SPA 等待逻辑不对——`_wait_page_settled` 只等 readyState（browser_tool.py:208-218），React hydrate 发生在这之后，拿到半空页是大概率。

**策略**：给 web_fetch 加 JS 渲染自动降级（复用 G7 CDP 基建），模型侧零学习成本；同时补 G7 自身的两个洞（settle 等待、导航门禁）。

**双分支关键发现（对勘结论）**：

- `browser_tool.py` / `browser_cdp.py` / `browser_ws.py` / `html_extract.py` / `tool_names.py` / `network_policy.py` **两分支完全一致**——渲染基建主体若落新文件 + 这些文件，cherry-pick 天然干净。
- `web_tool.py` **已漂移**：win7 有 PR #397 硬化（手动多跳重定向 + 响应字节上限 + IPv4-mapped 解包 + `_validate_target_url`），main 没有（main 最新只到 #396）。渲染分支恰好要改这个文件，不先消除漂移则双分支要各做一遍。
- `profiles.py` 有小漂移（win7 的 researcher 多 `memory_save` + 注释格式差异），cherry-pick 时手工处理，量小。

## 1. 差距与证据（W）

| # | 差距 | 证据 | 价值 | 优先级 |
| --- | --- | --- | --- | --- |
| W1 | **web_fetch 无渲染降级**：SPA 拿到空壳当成功返回，无检测、无降级、无提示 | web_tool.py:268（静态 get）、html_extract.py:237（纯静态抽取） | 动态页面"开箱即读"，一次调用一次审批 | **P0** |
| W2 | **SPA settle 等待错误**：只等 readyState=complete/interactive，hydrate 后内容未等到 | browser_tool.py:208-218 | browser_navigate/snapshot 与 W1 共用，修一次两处受益 | **P0** |
| W3 | **web_search 伪造结果**：解析失败时返回"关于 {query} 的搜索结果"+ example.com 占位条目，success=True——幻觉源；且解析器拿不到真实 URL（代码自述） | web_tool.py:125-133、:116 | 比不支持更糟，必修 | **P1** |
| W4 | **browser_navigate 绕过 NetworkPolicy**：只校验 scheme（browser_tool.py:303-305）；web_fetch 有 check_host（web_tool.py:254-257）。OFFLINE 模式 web_fetch 不注册但浏览器可导航任意 URL，门禁可被绕过 | browser_tool.py:295-336；tool_names.py:20、:44 | 安全口径统一 | **P1** |
| W5 | **模型引导缺位**：提示词无"动态页面"语义；researcher 无 browser 工具；web_fetch description 未说明渲染行为 | profiles.py:316-323、:335-339、:175；web_tool.py:213-217 | 有 W1 后模型需要知道何时直接 web_fetch、何时 browser_* | **P1** |
| W6 | 渲染增强 backlog：渲染后 outerHTML（links/tables 复用现有抽取）、渲染结果短 TTL 缓存 | web_tool.py:314-320 | P2，按需 | P2 |

## 2. 方案设计

### 2.1 W1 web_fetch 渲染降级（主体）

**新模块 `backend/tools/web_render.py`（新文件 = 双分支零冲突）**：

- `render_page(url, network_policy, timeout) -> RenderedPage`：`check_host` 前置 → `Page.navigate`（browser_cdp.cdp_command）→ settle 等待（复用 W2）→ `Runtime.evaluate` 取 `JSON.stringify({url, title, text: innerText.slice(0, 30KiB)})`（上限对齐 SNAPSHOT_TEXT_CAP）→ 组装与 `_render` 同构的 content dict（加 `rendered: true` 标记）。
- **渲染实例池**：模块级单例 + `threading.Lock` 懒初始化（工具在 executor 线程执行）。专用保留 browser_id（如 `render-pool`），`BrowserSessionManager.get(None)` 的"唯一实例"解析排除保留 id（browser_cdp.py 小改，两分支一致文件）。空闲超时（5 分钟）或进程死亡时重建；后端退出随既有 `close_all` 一并回收（main.py lifespan 钩子已有）。避免每次渲染 3-5s 冷启动。
- headless 固定 true；整体渲染预算 ~30s（单命令沿用 CDP_TIMEOUT_SECONDS=20s），超时返回明确错误并提示手动 browser_* 路径；失败结果不缓存。

**JS 壳判定（auto 模式，纯函数放 web_render.py 便于单测）**：

- 触发条件（同时满足）：content-type 为 HTML；静态抽取正文 < 500 字符；且 script 标签字节占比 > 0.25 或存在空根挂载点（`<div id="root|app|__next">` 内无文本）。
- `render` 参数：`auto`（默认）/ `always` / `never`。静态站零开销不回退。

**门禁语义（不放宽）**：web_fetch 风险等级保持 EXTERNAL，渲染分支同样过 `check_host` + TLS 策略口径（network_policy.py 两分支一致，含 allows_insecure_tls）；OFFLINE 模式渲染分支同样拒绝。工具 description 写明"渲染分支内部会启动受控 headless 浏览器"，保持审批透明。

**web_tool.py 改动压到最小**（= 压 cherry-pick 冲突面）：schema + render 参数透传 + 壳判定调用 + 渲染分支组装，其余逻辑全在 web_render.py。

### 2.2 W2 settle 等待修正

`_wait_page_settled`（browser_tool.py:208-218）：readyState 达标后追加内容稳定检测——每 400ms 取 `body.innerText.length`，连续 2 轮不变或累计 3s 即返回；BrowserCDPError 提前返回保留现状语义。browser_navigate 与 web_render 共用。

### 2.3 W3 web_search 修复

- 删除伪造占位（web_tool.py:125-133）：解析为空返回 `success=True, results=[], note="搜索源无结果或解析失败"`（搜索本身成功、无结果是合法状态；异常仍走 success=False）。
- URL 解析：DDG html 版 `result__a href` 实为 `//duckduckgo.com/l/?uddg=<编码后真实URL>`，parse_qs + unquote 解码；失败可回退 `lite.duckduckgo.com`。

### 2.4 W4 browser_navigate 门禁补齐

BrowserNavigateTool.execute（browser_tool.py:295-336）scheme 校验后加 `load_network_policy().check_host(url)`，new_tab（Target.createTarget）分支同样校验；拒绝文案与 web_fetch 同口径。

### 2.5 W5 模型引导接线

- researcher profile tools 加 `*BROWSER_TOOLS`（profiles.py:175；研究代理是浏览场景主消费者）。
- 系统提示词两处补语义：委派指引（profiles.py:316-323）与 primary 直取说明（profiles.py:335-339）——"动态页面（SPA/需交互/需登录）用 web_fetch（自动渲染）或 browser_* 工具"。
- web_fetch description（web_tool.py:213-217）说明 render=auto 行为。

## 3. 双分支实施策略（main + release/win7）

### 3.1 前置项

| # | 事项 | 说明 |
| --- | --- | --- |
| PF-1 | **本地 main 同步 origin/main** | 本地 main 落后 origin 6 提交（批次 A/B/C-1 在 origin，round3 文档已记录同问题）。不先同步则后续 cherry-pick 基线错位 |
| PF-2 | **#397 web_tool 硬化反向同步 win7 → main**（推荐决策项） | win7 的 web_tool.py 多出多跳重定向/字节上限/IPv4-mapped 解包（PR #397，950aceb4），属通用加固而 win7-only。先反向同步 main（代码已是 `from __future__ import annotations` + typing.* 兼容写法，可直接落）→ 两分支 web_tool.py 归同源 → 渲染分支一次实现 cherry-pick 干净。**若不做 PF-2**：渲染分支要在两套 execute 流程各接一遍（main 的单跳 `_check_redirect` vs win7 的 `_get_with_redirects`），+0.5-1 天且漂移永续。main 顺带白得多跳重定向（原 main 侧 P2 愿望） |

### 3.2 冲突点预测与规避

| 文件 | 两分支状态 | 规避手段 |
| --- | --- | --- |
| backend/tools/web_render.py（新） | 均不存在 | **零冲突**；第一行起按 py3.8 写法 |
| backend/tools/browser_tool.py / browser_cdp.py（W2、保留 id、W4） | 完全一致 | **零冲突** |
| backend/tools/web_tool.py（W1 接线、W3） | **已漂移**（#397） | PF-2 先归同源；改动压最小（§2.1） |
| backend/agents/profiles.py（W5） | 小漂移（researcher memory_save 等） | cherry-pick 手工合并，量小已知 |
| 测试文件 | test_web_tool / test_browser_tool 均存在且同构 | respx 两分支 dev 依赖均已具备 |

### 3.3 流程与纪律

- 沿用 round2 §4 惯例：main 特性分支 → PR → 落地后 cherry-pick `release/win7`，commit message `cherry(win7): ...`；冲突解决后跑 win7 侧测试。
- **py3.8 纪律（win7）**：新代码一律 `from __future__ import annotations` + `typing.Dict/List/Optional/Tuple`；禁 PEP 604（`X | Y`）、PEP 585（`set[...]`）、3.9+ API（`str.removeprefix`、`dict |`）。browser_cdp/browser_ws 已是此风格，沿用。
- 网络代码不改 browser_ws（阻塞 socket 已验证）；不新增第三方依赖（零新依赖纪律，与 G7 一致）。

## 4. 实施批次与工作量

| 批次 | 内容 | 工作量 |
| --- | --- | --- |
| 前置 | PF-1 同步 main；PF-2 #397 反向同步（PR + CI） | 0.5 天 |
| 批次 1（P0） | W1 渲染降级 + W2 settle 修正 + 单测 | ~2 天 |
| 批次 2（P1） | W3 web_search 修复 + W4 导航门禁 + W5 提示词接线 | ~1 天 |
| 双分支收尾 | cherry-pick win7 + 冲突处理 + win7 侧测试 | ~0.5 天 |
| backlog | W6 渲染后 links/tables、渲染 TTL 缓存 | 按需 |

## 5. 测试与验收

- **单测**（backend/tests/unit/）：
  - `test_web_render.py`（新）：壳判定纯函数（静态页 False / CRA 壳 True / 空挂载点 True）；实例池生命周期（fake session：懒建、复用、空闲重建、保留 id 不参与唯一实例解析）；渲染流程 mock cdp_command 断言导航→settle→innerText 取值链。
  - `test_web_tool.py`：auto 模式不触发渲染（静态页）、always 强制渲染（mock web_render）、never 关闭、OFFLINE 渲染拒绝、W3 空结果语义 + uddg URL 解析（DDG HTML fixture）。
  - `test_browser_tool.py`：W2 稳定检测（注入 evaluate 序列）；W4 门禁（OFFLINE/白名单外 URL 拒绝，new_tab 分支同验）。
- **验收场景**：真实 SPA 页面 web_fetch 返回非空正文（rendered=true）；example.com 静态路径不触发渲染（无性能回退）；OFFLINE 模式 browser_navigate 被拒。

## 6. 安全口径与已知限制

- **审批语义**：渲染分支内部的浏览器启动不单独走 EXEC 审批，安全边界由 web_fetch 的 EXTERNAL 门禁 + check_host + headless 临时 profile（无扩展、独立 user-data-dir）覆盖；此语义写入工具 description 保持透明。
- **已知限制（明示不解决）**：浏览器内重定向与页面 JS 的二次请求不受逐跳 check_host——CDP 短连接丢弃事件帧、无拦截点。与既有 browser_* 工具同等风险口径，靠临时 profile + 仅回连缓解；ONLINE 模式下接受。
- **py3.11 对齐**：#397 的 IPv4-mapped 解包修复（::ffff: CGNAT 判定）随 PF-2 到 main，两分支 SSRF 防护同强度。

## 7. 实施补记（2026-09-06 实施时新增）

- **PF-2 范围修正**：#397 实为 25 文件的 win7 大 PR，其中 network_policy.py / html_extract.py / download_tool.py 等在 main 已同内容存在（#396 主线落地）。反向同步只取 `backend/tools/web_tool.py` + `backend/tests/unit/test_web_tool.py` 两个文件（多跳重定向逐跳校验 / 4MiB 响应上限 / IPv4-mapped 解包），见特性分支首提交。
- **W5 范围修正**：实施勘察发现子代理委派走 `SUBAGENT_TOOL_WHITELIST` 硬只读白名单（agent_tool.py:83，browser_* 不在其中）——给 researcher profile 加 browser 工具是死信，且 researcher 的动态页需求已由 W1（web_fetch 自动渲染）直接覆盖。故 W5 收敛为：web_fetch 工具 description 说明渲染语义（模型侧主通道，DB 无关、即时生效）+ 渲染失败错误文案给出手动路径指引（经 coder 的 browser_*）。primary 提示词两处补语义暂缓——改常量需为存量 DB prompt 升级链新增迁移段，边际价值低，留待后续批次。
- **架构收口**：就绪/稳定等待逻辑统一收口在 `web_render.wait_page_ready`（W2），browser_navigate 与渲染分支共用；渲染实例池用保留 browser_id（`RESERVED_BROWSER_ID`），`BrowserSessionManager` 的"唯一实例"解析跳过它；每次渲染独立标签页，并发渲染互不干扰。
- **测试基线**：本机 conda sage-backend（py3.11）下 web/browser 三测试文件 93 项全过、ruff 全绿；tests/unit 全量跑出现的 chat_dispatcher / skill / memory 等失败在未改动的工作树上同样复现（存量环境问题，与本次无关），以 CI 为准。
