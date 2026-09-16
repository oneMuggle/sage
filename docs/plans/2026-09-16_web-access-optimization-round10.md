# 网页访问能力优化 Round 10：AU5 渲染池 ↔ 凭据档案双向互通（2026-09-16）

- **日期**：2026-09-16
- **上游文档**：Round 5 §2.4（AU5 提案，本方案落地并超集）、Round 5 B3（AU1/AU2/AU4 已交付）、Round 15（credential-vault RFC 6265 加固，已交付）
- **范围**：main 与 release/win7 双分支（后端 only，零新依赖，py3.8 纪律不变）
- **方法**：基于 B3/B4 合并后 main 的 `web_render` / `browser_cdp` / `credential_vault` / `web_tool` 勘察（附 `file:line`），避免与 Round 1–9、Round 15 已交付项重复

## 0. 结论速览

Round 5 B3 交付了 cookie 桥（vault）与静态通道的互通，但 **JS 渲染通道仍是登录态孤岛**：`render_page` 签名不接收凭据、全仓无 `Network.setCookies`，`web_fetch credential_domain=` 命中 JS 壳或反爬升级走渲染时，渲染标签页永远是"未登录"身份——登录后 SPA 页面在渲染分支必然拿登录墙。当前唯一的替代路径（`web_access_config.render_persistent` + 用户预先在 `render-default` profile 里手动登录）要求用户理解 profile 概念并手工操作，与"cookie 桥一次导出"的体验断裂。

本方案把 vault cookie 经 **`Storage.setCookies`（浏览器级 CDP，免 attach）** 注入渲染浏览器、渲染完成后经 **`Storage.getCookies`** 按域取回并回写档案，让"一次导出，三条通道（静态 httpx / 渲染池 / 交互浏览器）共用"成立。

| 项 | 内容 | 批次 |
| --- | --- | --- |
| AU5a | vault 侧：`resolve_credential` 带出可注入 cookie 清单；新增 `merge_cdp_cookies` | 批次 1 |
| AU5b | CDP 侧：`Storage.*` 纳入浏览器级方法（免 attach） | 批次 1 |
| AU5c | 渲染侧：`render_page(credential_domain=)` 注入 + 回写 | 批次 1 |
| AU5d | web_tool 接线：`_render_dynamic` / `_escalate` 透传凭据域 + note | 批次 2 |
| T | 单测三处 + CHANGELOG + 文档回填 | 批次 2 |

## 1. 现状勘察（附证据）

- `web_render.render_page(url, network_policy, wait_for)`（web_render.py:314）无凭据参数；导航前仅 `apply_stealth`（:337）+ `Page.navigate`（:338）。
- 全仓无 `setCookies` 调用；`cdp_command` 仅把 `Target.*` / `Browser.*` 视为浏览器级（browser_cdp.py:461），`Storage.*` 会被错误 attach 到页面目标。
- vault 侧 `resolve_credential`（credential_vault.py:411）只返回拼好的 `Cookie` 头字符串，**丢弃逐条 cookie 的 domain/path/secure/expires** ——注入需要逐条原样回放（浏览器的域匹配比 RFC 6265 头匹配更严格，host-only cookie 无法从头串重建）。
- AU2 的 `merge_set_cookies`（:564）吃的是 `Set-Cookie` 头串；`Storage.getCookies` 返回的是 CDP cookie dict（`expires` epoch 秒、session 为 `-1`），复用会丢精度，需要平行的 dict 入口（同一套守卫）。
- `web_tool.execute` 两处渲染入口：`_should_render` 命中 → `_render_dynamic`（web_tool.py:626）；`_AntibotBlocked` → `_escalate`（:634）。两处都不传 `credential_domain`。
- 渲染分支拿到登录墙时无 AU2 语义（`_detect_login_wall` 只覆盖静态 hop），凭 `rendered_status` 只能看到 200 的登录墙页——注入后此缺口自然缓解（登录态真的带上了）。

**安全口径**（沿用既有约定）：

- 注入只在调用方显式传 `credential_domain` 时发生（与静态 attach 同门禁）；`resolve_credential(url=)` 已按过期 / secure / path 过滤。
- `Storage.setCookies` 只作用于渲染浏览器实例自己的 profile（临时 profile 随池回收、持久 profile 即 `render-default`），与用户日常浏览器进程完全隔离。
- 回写沿用 `merge_set_cookies` 的两条守卫：**host affinity**（请求主机必须落在 cookie 归属域内，fail closed）与**归属域 ∈ 档案域**（第三方 cookie 不混入）。
- header 型凭据（AU4）渲染通道不支持（`Page.navigate` 无自定义头机制），显式跳过不报错——静态通道已覆盖该场景。

## 2. 方案设计

### 批次 1：vault 基建 + CDP 通道 + 渲染注入/回写

**`credential_vault.py`**

- `CredentialResolution` 增加 `cookies` 槽：cookie 档案 `ok` 时携带过滤后的逐条 cookie dict（与 `headers` 同源同过滤），供渲染通道逐条注入。
- 新增 `merge_cdp_cookies(domain, cookies, request_url, repo=None) -> List[str]`：与 `merge_set_cookies` 同守卫（host affinity、归属域 ∈ 档案域、name+path 替换、过期删除、清空删档），输入为 `Storage.getCookies` 的 cookie dict。`session=True` 或 `expires<=0` 视为 session cookie（不落 `expires`）。

**`browser_cdp.py`**

- `cdp_command` 浏览器级前缀 `("Target.", "Browser.")` → `("Target.", "Browser.", "Storage.")`（Chrome 97+，覆盖 win7 的 109）。

**`web_render.py`**

- `render_page(url, network_policy, wait_for="", credential_domain="")`：
  1. **注入**：`credential_domain` 非空 → `resolve_credential(credential_domain, url=url)`；`ok` 且 `kind=cookie` 且 `resolution.cookies` 非空 → 组 CookieParam（name/value/domain/path + 可选 secure/httpOnly/sameSite/expires）经 `Storage.setCookies` 注入。注入失败（BrowserCDPError）→ `RenderError`（显式给了凭据却建立不了，宁失败不静默降级为"未登录渲染"）。`kind=header` / `not_found` / `expired` → 跳过注入不报错（web_tool 静态阶段已报过）。
  2. **回写**：页面 info 读取后（关标签页前、同 try 内）`credential_domain` 非空 → `Storage.getCookies` → 按 `cookie_domain_matches(hostname(final_url), c.domain)` 过滤 → `merge_cdp_cookies(credential_domain, filtered, final_url)`。changed 非空 → `rendered["credential_refreshed"] = sorted(set(changed))`。回写任何异常静默（与 AU2"回写失败不影响本次请求"同口径）。

### 批次 2：web_tool 接线 + 文案 + 测试 + 文档

**`web_tool.py`**

- `_render_dynamic(..., credential_domain="")` / `_escalate(..., credential_domain="")` → 透传 `render_page`；execute 两处调用传 `credential_domain.strip()`。
- 渲染结果带 `credential_refreshed` → `content["note"]` 追加 `credential_refreshed: 渲染通道续期了 cookie，档案已回写（…）`（escalate 路径此前无 note 字段，一并补齐）。
- schema `credential_domain` 描述补"JS 渲染降级 / 反爬升级时同样注入"。

**测试**

- `test_credential_vault.py`：`merge_cdp_cookies` 守卫全表（host affinity 拒绝、第三方域拒绝、过期删除、session 保留、name+path 替换、清空删档、无效名值跳过）；`resolve_credential.cookies` 与 headers 同过滤。
- `test_web_render.py`：`_install_render` 假体扩展 `Storage.setCookies` / `Storage.getCookies`——注入先于导航、CookieParam 形态（domain/path/expires 原样、session 不带 expires）、注入失败 → RenderError、回写落库（_MemRepo）、无凭据不触发 `Storage.*`、header 档案跳过注入。
- `test_web_tool.py`：`_render_dynamic` / `_escalate` 透传断言 + note 拼接。

## 3. 双分支实施策略

| 文件 | 状态 | 冲突预测 |
| --- | --- | --- |
| backend/tools/{credential_vault, browser_cdp, web_render, web_tool}.py | 与 release/win7 同源（B1–B4 保持零漂移） | 零冲突 |
| backend/tests/unit/{test_credential_vault, test_web_render, test_web_tool}.py | 同源 | 零冲突 |

py3.8 纪律：`from __future__ import annotations` + `typing.*`；不引入新语法；交付前 `ast.parse(feature_version=(3,8))` 抽查。

## 4. 未纳入本方案（记录到后续轮）

- **AU3 自动刷新回路**（login_required → 持久 profile 静默重导）：vault 需先记录 `source_profile`，渲染池需支持按请求换 profile——独立成轮。
- 渲染分支的 AU2 登录墙检测（渲染后页面密码框 → `login_required`）：注入后触发面大幅缩小，观察后再定。
- 截图视觉回传 / 凭据管理 UI：前端系列，另行立项。
