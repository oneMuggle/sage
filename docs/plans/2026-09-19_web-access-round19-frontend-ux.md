# 网页访问能力增强 Round 19：前端可视化 + 凭据管理 + Playwright MCP（2026-09-19）

- **状态**：批次 1（R19-W1）已交付（#1225）；**批次 2（R19-W2 + R19-W3）已完成并验证（2026-09-19）**；批次 3（R19-W4/W5/W6）**未实现**，待排期
- **上游文档**：Round 1（路由指引 backlog B1-B3）、Round 2（G1 反爬路由指引）、Round 5（AB1-AB5 反爬韧性）
- **范围**：main 优先；release/win7 按双分支策略按需同步
- **背景**：用户反馈"动态页面抓取不到，也没法访问需要登陆的页面"。勘察发现 Round 2/5 已实现自动升级链（static→render）、反爬检测（20+ 标记）、stealth 反检测（AB4）、结构化错误指引（G1）——**后端能力已完备，痛点在前端可视化、凭据管理 UX、模型主动引导**。

## 0. 结论速览

**已实现能力（Round 2/5，零新增）**：
- ✅ 反爬自动升级链：static fetch → antibot 检测 → render fallback（AB1）
- ✅ 20+ 反爬标记检测（Cloudflare/Akamai/Incapsula/中文验证码）
- ✅ stealth 反检测：webdriver flag、Chrome 指纹、语言列表（AB4）
- ✅ 结构化错误指引：`suggested_next_actions` 字段 + 文案提示用 browser 通道或配置代理（G1）
- ✅ 凭据桥：`credential_domain` 参数 + `credential_vault` 加密存储（Round 2）
- ✅ 浏览器 8 工具：launch/navigate/interact/cookies 等（G7）

**真正缺失的能力**：
- ❌ **前端无法感知拦截**：用户/模型不知道被反爬/登录墙拦截，错误只返回文本
- ❌ **凭据管理无 UI**：`credential_vault` 只有 CLI/API，用户无法直观管理已存 cookies/headers
- ❌ **模型不主动转通道**：错误消息有提示，但 system prompt 没引导，模型不会自发切 browser
- ❌ **无 Playwright 级自动化**：headless 浏览器只能手动 8 步操作，无法脚本化批量登录

## 1. 差距分析

| # | 差距 | 证据 | 价值 | 优先级 |
|---|---|---|---|---|
| R19-W1 | **前端无拦截可视化**：web_fetch 返回 `success=False` + 文本错误，用户看不到"为什么失败"、"该怎么做" | `web_tool.py` `_ANTIBOT_GUIDANCE`（纯文本常量）；前端无解析 `suggested_next_actions` | 用户感知"系统能帮我登录"而非"又失败了" | **P0** |
| R19-W2 | **凭据管理无 UI**：用户不知道存了哪些 cookies/headers，无法查看/删除/导出 | `credential_vault.py` 仅 CLI API（`resolve_credential`/`store_credential`）；无前端入口 | 凭据过期用户无法自助修复，只能手动 CLI | **P1** |
| R19-W3 | **模型不主动转通道**：error message 有提示，但 primary/researcher prompt 没引导"遇到反爬/登录墙用 browser 工具" | `profiles.py` primary/researcher prompt 无"antibot/login"语义；只有错误后才见提示 | 减少用户干预，模型自动升级 | **P1** |
| R19-W4 | **无 Playwright 级脚本化**：browser_* 8 工具只能手动逐步操作，无法写"登录→抓取→导出"脚本 | `browser_tool.py` 8 工具无批量/编排能力；无 Playwright MCP | 高频登录场景效率低 | **P2** |
| R19-W5 | **无多策略 retry**：单次 403/429 后不自动换 UA/代理/延迟重试 | `web_tool.py` `_get_with_redirects` 无 retry 逻辑（Round 5 AB5 只 retry 渲染分支） | 限流站成功率低 | **P2** |
| R19-W6 | **无"一键登录"入口**：用户需 4 步手动登录（browser_launch → navigate → 手动登录 → browser_cookies） | 无 UI 入口；workflow 散落在工具文档 | 登录流程复杂，用户不知从何开始 | **P2** |

## 2. 方案设计

### 2.1 R19-W1 前端拦截可视化（P0）

**方案**：解析 `suggested_next_actions` 字段，渲染为可点击卡片。

**前端改动**：
- `src/components/chat/ToolResultCard.tsx`：识别 `web_fetch` 失败结果，解析 `suggested_next_actions`，渲染为卡片：
  ```
  ┌─ ⚠️ 网页访问被拦截 ─────────────────────┐
  │ 目标：https://example.com              │
  │ 原因：Cloudflare 反爬验证                │
  │                                         │
  │ 建议操作：                                │
  │ [🌐 用浏览器打开] [🔑 配置登录凭据]       │
  │ [⚙️ 配置代理]     [📖 查看文档]          │
  └─────────────────────────────────────────┘
  ```
- 卡片按钮点击后触发对应 action（deeplink 到凭据管理/代理设置/浏览器工具）。

**后端改动**：
- `web_tool.py` 错误返回标准化 `suggested_next_actions`（已有，零改动）。
- 新增 `block_reason` 枚举：`antibot_cf` / `antibot_other` / `login_wall` / `http_4xx` / `http_5xx` / `timeout` / `dns`。

**工作量**：~1 天（前端 0.7 天 + 后端 0.3 天枚举标准化）。

### 2.2 R19-W2 凭据管理 UI（P1）

**方案**：**复用既有 `NetworkTab/CredentialsSection` 组件与 `/api/v1/web-access/credentials` 路由族**（list / delete / header 入口早已存在），零新页面、零重复路由；本批次仅新增 **cookie 导入**。

**实际交付（批次 2，2026-09-19）**：

- 后端：`POST /api/v1/web-access/credentials/cookie`（`backend/api/web_access_routes.py`），沿用既有 `credential_vault.save_credential` 做校验 + 加密存储（不引入新存储路径）；保留 `_origin_guard` Origin 守卫；校验失败统一返回固定文案 `invalid_cookie_credential`，**不回显提交值**。
- 前端：`CredentialsSection` 内新增 cookie 表单（域名 + `document.cookie` 文本），解析器 `src/pages/settings/credentialCookieParser.ts` 按首个 `=` 切分、不解码、不在成功/失败态回显值。

**工作量**：已交付（复用既有能力，实际约 0.7 天）。

### 2.3 R19-W3 模型主动引导（P1）

**方案**：primary/researcher system prompt 补"反爬/登录墙"语义，模型见到错误后主动切 browser。

**实际交付（批次 2，2026-09-19）**：

- `backend/agents/profiles.py` 新增 `_WEB_ACCESS_ROUTING_GUIDANCE`，并派生 `PRIMARY_SYSTEM_PROMPT_WITH_WEB_ACCESS_ROUTING`（= `PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT` + 引导段）与 `RESEARCHER_SYSTEM_PROMPT_WITH_WEB_ACCESS_ROUTING`（= 旧字面量常量 `_RESEARCHER_SYSTEM_PROMPT_BEFORE_WEB_ACCESS_ROUTING` + 引导段）。
- 存量 DB 迁移按**精确字符串匹配**：primary 链 `BEFORE_DELEGATION → WITH_DELEGATION → WITH_FETCH_DIRECT → WITH_WEB_ACCESS_ROUTING` 一气呵成；researcher 旧默认字面量 → 新常量。任一段非精确命中（即用户自定义 prompt）一律跳过，**字节级不动**。
- `web_fetch` 工具 description 追加引导段（**纯描述性，不改运行时行为**）：仅当 `success=False` 且结果 JSON 含 `metadata.blockReason`（`antibot_cf` / `antibot_other` / `login_wall`）时才转 `browser_navigate` + `browser_snapshot`，必要时经 `credential_domain` 提供登录态，不反复重试 `web_fetch`。字段名取模型实际可见的失败信封（`backend/core/legacy/agent.py` 失败分支产出的 `metadata.blockReason`），而非内部载荷键 `block_reason`。

**工作量**：~0.2 天（改常量 + 测试）。

### 2.4 R19-W4 Playwright MCP 外挂（P2，main-only）

**方案**：通过 MCP 协议接入 Playwright，提供脚本化浏览器自动化。

**架构**：
```
Sage backend (MCP client) ←→ Playwright MCP server (独立进程)
                                   ↓
                          Playwright (Node.js)
                                   ↓
                          Chromium/Firefox/WebKit
```

**实现**：
- `backend/mcp/playwright_server.py`（新文件）：MCP server，暴露 `playwright_*` 工具：
  - `playwright_navigate(url, wait_for)` → 导航 + 等待
  - `playwright_fill(selector, value)` → 填写表单
  - `playwright_click(selector)` → 点击
  - `playwright_evaluate(js)` → 执行 JS
  - `playwright_screenshot()` → 截图
- 依赖：`playwright` (Node.js) + `@playwright/mcp` (官方 MCP adapter)。
- **main-only**：Playwright 不支持 Win7（py3.9+ 要求 + Chromium 2024 后不支持 Win7），release/win7 不同步。

**工作量**：~2 天（MCP server 1 天 + 测试 0.5 天 + 文档 0.5 天）。

### 2.5 R19-W5 多策略 retry（P2）

**方案**：403/429 后自动换 UA、延迟重试、换代理（如已配置）。

**后端改动**：
- `web_tool.py` `_get_with_redirects` 增加 retry 逻辑：
  ```python
  for attempt in range(3):
      response = httpx.get(url, headers=_pick_ua(attempt))
      if response.status_code not in (403, 429, 503):
          break
      await asyncio.sleep(2 ** attempt)  # 1s, 2s, 4s
  ```
- UA 池：5 个主流浏览器 UA，每次 retry 换一个。
- 代理切换：如已配置多代理，round-robin 切换（无配置则跳过）。

**工作量**：~0.5 天（后端 0.3 天 + 测试 0.2 天）。

### 2.6 R19-W6 一键登录入口（P2）

**方案**：Settings → Integrations → 网站卡片，"登录"按钮启动浏览器流程。

**前端改动**：
- 新增 `src/components/settings/WebsiteIntegrationsTab.tsx`：
  - 卡片列表：预设 10 个高频网站（GitHub/Twitter/知乎/微博等）
  - 每张卡片：图标 + 域名 + 状态（未登录/已登录/凭据过期）
  - "登录"按钮：自动 `browser_launch` → `browser_navigate(url)` → 等待用户手动登录 → `browser_cookies` 导出并存储
- 后端新增 API：
  - `POST /api/v1/integrations/{domain}/login` → 返回 `browser_session_id`
  - `POST /api/v1/integrations/{domain}/complete` → 导出 cookies 并存储

**工作量**：~1.5 天（前端 1 天 + 后端 0.5 天）。

## 3. 实施批次与工作量

| 批次 | 内容 | 工作量 | 优先级 | 状态 |
|---|---|---|---|---|
| **批次 1（P0）** | R19-W1 前端拦截可视化 | 1 天 | **必修** | ✅ 已交付（#1225） |
| **批次 2（P1）** | R19-W2 凭据管理（复用现有 + cookie 导入）+ R19-W3 模型主动引导 | 1.7 天 | **推荐** | ✅ **已完成并验证（2026-09-19）** |
| **批次 3（P2）** | R19-W4 Playwright MCP + R19-W5 多策略 retry + R19-W6 一键登录 | 4 天 | **可选** | ❌ **未实现**（待排期） |

**总计**：~6.7 天（批次 1-2 必修 = 2.7 天，均已完成；批次 3 按需 = 4 天，**未实现**）。

## 4. 测试与验收

> **交付状态**：批次 1-2 的测试已落地并通过（见 §7 交付记录）；**R19-W4 / R19-W5 / R19-W6 未实现**，其对应测试项（Playwright MCP / retry / 一键登录）尚未编写。

- **前端测试**：
  - R19-W1：拦截卡片渲染测试（mock `suggested_next_actions` 各类型）。
  - R19-W2：凭据列表/删除/导入测试（mock credential_vault API）。
  - R19-W6：一键登录流程测试（mock browser_* 工具链）。
- **后端测试**：
  - R19-W2：credentials API 单元测试（list/delete/import）。
  - R19-W3：profile prompt 测试（断言包含 antibot/login 语义）。
  - R19-W4：Playwright MCP server 集成测试（mock Playwright 进程）。
  - R19-W5：retry 逻辑测试（mock 403/429 响应序列）。
- **验收场景**：
  - 用户访问 Cloudflare 保护站点 → 前端显示拦截卡片 → 点击"用浏览器打开" → 自动启动 browser_navigate。
  - 用户凭据过期 → 凭据管理 UI 显示"过期" → 点击"重新登录" → 启动一键登录流程。
  - 模型收到 antibot 错误 → 主动切 browser 通道而非反复重试 web_fetch。

## 5. 安全口径

- **凭据存储**：沿用 credential_vault 加密（SecretBox + DPAPI/keychain），不引入新存储。
- **Playwright MCP**：main-only，明确标注"不支持 Win7"；release/win7 分支不同步。
- **代理切换**：仅切换已配置代理，不自动连接公共代理（避免数据泄露）。
- **一键登录**：浏览器流程沿用既有 browser_* 工具审批语义（launch=EXEC, navigate=EXTERNAL）。

## 6. 与已有 18 轮的关系

| 已有轮次 | 内容 | 本文关系 |
|---|---|---|
| Round 1 | B1-B3 backlog（路由指引/缓存/浏览器工具） | **已交付**（Round 2/5），本文不重复 |
| Round 2 | G1 反爬路由指引 + 凭据桥 | **已交付**，本文 R19-W1 是其前端可视化 |
| Round 3 | 下载工具 | 不相关 |
| Round 4 | 403/429 路由指引（同 G1） | **已交付** |
| Round 5 | AB1-AB5 反爬韧性 | **已交付**，本文 R19-W5 是其增强（多策略 retry） |
| Round 6-18 | 渲染/搜索/指标等 | 不相关 |

**本文定位**：不重复已有后端能力，聚焦前端 UX + 凭据管理 + 模型引导 + Playwright 外挂。

## 7. 实施补记

### 7.1 批次 2 交付记录（2026-09-19）

- **R19-W2**：**复用现有 `NetworkTab/CredentialsSection` 与 `/api/v1/web-access/credentials` 路由族**，仅新增 **cookie 导入**——后端 `POST /api/v1/web-access/credentials/cookie`（Origin 守卫保留、校验失败固定文案不回显值），前端 cookie 表单 + `credentialCookieParser.ts`。未新增 `CredentialVaultTab` 页面或 list/delete/import 端点。
- **R19-W3**：primary/researcher **精确匹配 prompt 迁移**（自定义 prompt 字节级不动）+ `web_fetch` schema 引导（纯描述，不改运行时）。
- **验证结果**：后端 focused 用例 255 passed（含迁移/路由/工具 schema）；前端 focused 用例 21 passed（解析器 3 + NetworkTab 18）；ruff 对全部改动后端文件全绿；迁移测试覆盖默认种子、一次性迁移、幂等与自定义 prompt 不覆盖。
- **既有构建阻断（非本批次引入）**：`npm run build` 因 `src/features/office/DocxNativePreview.tsx` 找不到 `docx-preview` 失败——该依赖在 `package.json` 已声明（0.3.5）但未安装进 `node_modules`，文件在 `origin/main` 已存在且本批次未触碰。`tsc --noEmit` 仅此 1 处报错，改动的前端文件类型检查干净。

### 7.2 设计说明

- **不重复造轮子**：Round 2/5 已实现 80% 后端能力，本文只补 20% 真正缺失的前端/UX。
- **Playwright 不替代现有 browser_***：两者定位不同——browser_* 是手动 8 步操作，Playwright MCP 是脚本化批量自动化。用户可根据场景选择。
- **Win7 约束**：Playwright MCP main-only（py3.9+ 要求 + Chromium 2024 后不支持 Win7）；其余 R19-W1/W2/W3/W5 可 cherry-pick 到 release/win7。
- **用户原话**：「现在是动态页面抓取不到，也没法访问需要登陆的页面」——动态页面 Round 2 已解决（web_render 自动升级）；登录页面本文 **R19-W2 已交付凭据管理（cookie 导入）**，R19-W6 一键登录入口**仍未实现**。
- **批次 3（R19-W4 / R19-W5 / R19-W6）明确未实现**：Playwright MCP 外挂、多策略 retry、一键登录入口三项本轮均未落地，仍为 P2 backlog，需另起批次排期。
