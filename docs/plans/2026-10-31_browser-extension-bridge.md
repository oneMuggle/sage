# 外部日常浏览器扩展桥（Manus 模式）实施计划

## 背景与目标

Sage 现有的网页访问登录态方案要求用户在 Sage 打开的浏览器里重新登录，并保存 Cookie + localStorage。对已经在自己日常 Chrome/Edge 中登录知网、校内数据库、企业后台的用户来说，仍有额外一步；遇到扫码、短信、机构 CARSI 等场景也无法直接复用日常会话。

本方案新增 **外部浏览器扩展桥**：用户在日常浏览器中安装 Sage 扩展，点击「共享此标签页」后，Sage 的 agent 通过本机后端向该标签页转发 CDP 命令，直接使用用户已有的登录态、浏览器指纹与网络环境。密码、验证码、扫码始终只在用户自己的浏览器中完成，不经过 Sage 聊天或设置页。

**目标（P0）**：

1. 用户可在设置页生成一次性配对码，在扩展中粘贴完成配对；设备可查看、撤销。
2. 扩展只操作用户**显式共享的单个标签页**；标签页跨域跳转、关闭、用户停止共享时立即断开。
3. 共享期间，现有 `browser_navigate` / `browser_snapshot` / `browser_interact` / `browser_screenshot` / `browser_cookies export` 工具无需修改调用方式即可作用于该标签页。
4. 扩展提供「保存登录状态到 Sage」按钮，将当前站点的 Cookie + localStorage 加密写入现有凭据库，供之后静态抓取 / 渲染通道复用。
5. 默认拒绝多标签页、拒绝非共享标签页、拒绝未配对设备；所有操作在本机回环内完成。

**非目标（P0 不做）**：

- 远程/局域网暴露、云端中继。
- 自动接管用户所有标签页、后台静默读取 cookie。
- 验证码破解、反检测对抗。
- Chrome Web Store 上架；先以「加载已解压扩展」方式分发。

## 技术方案

### 总体架构

```
┌──────────────── 用户日常 Chrome/Edge ────────────────┐
│  Sage Browser Bridge 扩展 (MV3)                        │
│  popup: 配对 / 共享当前标签页 / 保存登录状态 / 停止     │
│  background: chrome.debugger 附着共享标签页            │
│  offscreen: 长轮询本机后端，转发命令与结果              │
└───────────────┬───────────────────────────────────────┘
                │ HTTP 127.0.0.1（配对码/设备 token）
┌───────────────▼───────────────────────────────────────┐
│  FastAPI 后端                                          │
│  /web-access/extension/*  扩展 I/O（设备 token 鉴权）   │
│  /web-access/browser-extension/* 设置页管理（本地能力） │
│  BrowserExtensionBridge                                │
│    · 设备注册 / 配对码 / 命令队列 / 结果 Future         │
│    · 共享标签页 → 注册 BrowserSession(EXTERNAL)         │
└───────────────┬───────────────────────────────────────┘
                │ 现有 cdp_command 分发
┌───────────────▼───────────────────────────────────────┐
│  BrowserType.EXTERNAL → _external_command              │
│  现有 browser_* 工具 / web_render.wait_page_ready 复用   │
└───────────────────────────────────────────────────────┘
```

### 为什么用「长轮询 + chrome.debugger」而不是 WebSocket / JS 注入

- **MV3 Service Worker 生命周期**：Chrome 109（Win7 末代版本）的 SW 空闲约 30 秒会被回收，WebSocket 无法可靠保活；长轮询（20 秒一请求）配合 offscreen 文档最稳，且在 Chrome 109 可用。
- **CDP 语义复用**：扩展用 `chrome.debugger.sendCommand` 转发原样 CDP 方法，后端只需把 `BrowserType.EXTERNAL` 接到现有 `cdp_command`，`browser_snapshot`、`browser_interact`、`wait_page_ready`、`browser_screenshot` 全部零改动。
- **可见与可撤回**：`chrome.debugger` 会显示「Sage Browser Bridge started debugging this browser」信息条；用户停止共享即 detach，隐私边界清晰。
- **避免 eval/CSP 问题**：`Runtime.evaluate` 由 CDP 执行，不受页面 CSP 影响；JS 注入方式在 MV3 与严格 CSP 站点上不可靠。

### 协议

扩展 → 后端（除 pair 外均带 `X-Sage-Extension-Token`）：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/v1/web-access/extension/pair` | 用配对码换设备 token（仅一次） |
| POST | `/api/v1/web-access/extension/poll` | 长轮询（≤20s），上报共享标签页，取一条命令 |
| POST | `/api/v1/web-access/extension/result` | 回传命令结果 / 错误 |
| POST | `/api/v1/web-access/extension/detach` | 主动停止共享 |
| POST | `/api/v1/web-access/extension/sync-session` | 保存当前标签页 Cookie + localStorage |

设置页 → 后端（本地能力，经 LocalAuthMiddleware）：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/v1/web-access/browser-extension/pairing-code` | 生成 10 位一次性配对码（5 分钟） |
| GET | `/api/v1/web-access/browser-extension/status` | 设备、在线状态、共享标签页、扩展目录 |
| DELETE | `/api/v1/web-access/browser-extension/devices/{id}` | 撤销设备 |

命令格式：

```json
{"id":"cmd-...","method":"Runtime.evaluate","params":{...}}
```

扩展回传：

```json
{"id":"cmd-...","ok":true,"result":{...}}
{"id":"cmd-...","ok":false,"error":{"message":"...","code":"..."}}
```

`Target.getTargets` 由扩展直接根据 `chrome.tabs.get(tabId)` 返回；其余方法原样发给 `chrome.debugger.sendCommand({tabId}, method, params)`。`Target.createTarget` / `Target.closeTarget` 在 P0 显式拒绝，防止 agent 操作共享标签页以外的页面。

### 共享标签页与 BrowserSession

- 后端固定浏览器 id `external`，同一时间**只允许一个**共享标签页；第二个设备共享时 `/poll` 返回 409 `another_tab_shared`，扩展自动停止共享并提示。
- 共享开始时注册：

```python
BrowserSession(
    browser_id="external",
    executable="(browser-extension)",
    browser_type=BrowserType.EXTERNAL,
    process=_ExternalProcess(),   # poll() 恒 None
    persistent=True,
    profile_name="browser-extension",
    external_device_id=device_id,
)
```

- 停止共享、设备被撤销、标签页跨域/关闭时从会话表移除；不关闭用户标签页。
- `_list_page_targets` 与 `_terminate_session` 增加 EXTERNAL 分支；`_terminate_session` 对 EXTERNAL 为 no-op（只清 Sage 会话，不碰用户页面）。

### 安全模型

1. **配对**：10 位 base32 码（约 50 bit），5 分钟有效、一次性；连续 5 次失败立即作废；设置页可重新生成。设备 token 仅返回扩展一次，后端只存 SHA-256。
2. **共享粒度**：扩展 popup 在用户点击时请求当前站点的 `optional_host_permissions`，随后才允许共享；background 每次命令前校验 `tabId`、URL origin 与共享记录一致，跨域跳转由 `chrome.tabs.onUpdated` 自动停止共享。
3. **命令白名单**：后端只允许 CDP 方法与扩展侧一致的白名单；拒绝 `Target.createTarget`、`Target.closeTarget`、`Browser.close` 等影响用户浏览器全局状态的方法。
4. **网络门禁**：`Page.navigate` 仍经过现有 `browser_navigate` 的 NetworkPolicy 校验；扩展桥不新增绕过路径。
5. **权限沿用**：agent 调用现有 `browser_*` 工具，风险等级与审批矩阵不变；`browser_navigate` 仍是 EXTERNAL，`read_only` 模式下不可导航。
6. **数据最小化**：`sync-session` 只接受与共享标签页 host 匹配的 cookie 域和当前 origin 的 localStorage；Cookie 值不返回设置页/聊天，只落加密凭据库。
7. **本地回环**：所有端点只监听 127.0.0.1；扩展 host_permissions 仅本机地址；不开放公网。

### 设置页体验

设置 → 网络 → 「日常浏览器扩展」：

- 未配对：三步引导（安装扩展 → 生成配对码 → 在扩展中粘贴）；
- 已配对：设备名称、最近在线时间、撤销按钮；
- 共享中：显示标签页域名/标题与「Sage 正在使用此标签页」；
- 扩展目录路径（开发态仓库路径 / 安装包 `resources/extension/agent-bridge`）可直接复制。

扩展 popup：

- 首次：后端地址（默认 `http://127.0.0.1:8765`）+ 配对码；
- 已配对：当前标签页信息 + 「共享此标签页 / 停止共享」+「保存登录状态到 Sage」；
- 持续显示共享状态徽标（toolbar badge `ON`），提示用户 agent 正在操作。

## 涉及文件

### 后端

| 文件 | 动作 | 说明 |
| --- | --- | --- |
| `backend/services/browser_extension_bridge.py` | 新增 | 设备/配对/长轮询/命令 Future/会话注册/CDP 转发/凭据同步 |
| `backend/api/browser_extension_routes.py` | 新增 | 扩展 I/O + 设置页管理端点 |
| `backend/api/local_auth.py` | 修改 |  `/api/v1/web-access/extension/` 前缀公开（端点内设备 token 鉴权） |
| `backend/main.py` | 修改 | 挂载新路由 |
| `backend/data/settings_repo.py` | 修改 | 新增 `browser_extension_devices` 白名单 key |
| `backend/tools/browser_cdp.py` | 修改 | `BrowserType.EXTERNAL`、`_ExternalProcess`、`_external_command`、目标列表/终止分支 |
| `backend/tests/unit/test_browser_extension_bridge.py` | 新增 | 配对、鉴权、队列、超时、会话注册、同步校验 |
| `backend/tests/api/test_browser_extension_routes.py` | 新增 | HTTP 契约、公开路径、设备管理、Origin |
| `backend/tests/unit/test_browser_cdp_external.py` | 新增 | EXTERNAL 命令映射、目标解析、终止 no-op |

### 扩展

| 文件 | 说明 |
| --- | --- |
| `extension/agent-bridge/manifest.json` | MV3；permissions: storage/tabs/scripting/cookies/alarms/offscreen/debugger；optional host 权限 |
| `extension/agent-bridge/background.js` | 配对、共享、debugger 附着、命令执行、保存登录态、撤销/通知 |
| `extension/agent-bridge/offscreen.html` + `offscreen.js` | 长轮询与结果回传，保持连接 |
| `extension/agent-bridge/popup.html` + `popup.js` + `popup.css` | 配对与共享 UI |
| `extension/agent-bridge/icons/*` | 复用现有图标 |
| `extension/agent-bridge/README.md` | 安装、授权、隐私说明、故障排查 |

### 前端

| 文件 | 动作 |
| --- | --- |
| `src/shared/api/webAccessClient.ts` | 新增扩展状态/配对/撤销 API |
| `src/pages/settings/BrowserExtensionSection.tsx` | 新增设置区 |
| `src/pages/settings/NetworkTab.tsx` | 挂载新设置区 |
| `src/pages/settings/settingsSearchEntries.ts` | 新增搜索条目（条目拆到 `settingsSearchEntriesBrowserExtension.ts`，守住 800 行门禁） |
| `src/shared/lib/i18n/locales/{zh,en}/chatAndSider.ts` | 新增文案（英文文案拆到 `en/chatAndSiderBrowserExtension.ts`，守住 800 行门禁） |
| `src/pages/settings/__tests__/BrowserExtensionSection.test.tsx` | 新增测试 |
| `src/shared/api/__tests__/webAccessClient.test.ts` | 补充 API 测试 |

### 文档与打包

| 文件 | 动作 |
| --- | --- |
| `docs/plans/2026-10-31_browser-extension-bridge.md` | 本文件 |
| `docs/user-manual/18-web-access.md` | 新增「日常浏览器扩展」章节 |
| `docs/technical/46-intranet-web-access.md` 或新增章节 | 记录协议与安全边界 |
| `electron-builder.yml` | `extraResources` 打包 `extension/agent-bridge` |

## 实施步骤

### 里程碑 M1：后端桥核心（可独立测试）

- [x] 编写 `test_browser_extension_bridge.py`：配对码生成/校验/过期/失败作废；token 只存哈希；轮询队列与结果 Future；命令超时；设备撤销；第二个共享被拒。
- [x] 实现 `BrowserExtensionBridge`（设备存储、配对、长轮询、命令分发、会话注册、共享状态）。
- [x] 在 `SettingsRepository.KEYS` 增加 `browser_extension_devices`。
- [x] 运行 `pytest backend/tests/unit/test_browser_extension_bridge.py`。

### 里程碑 M2：API 与鉴权

- [x] 编写 `test_browser_extension_routes.py`：pair 公开、poll 无 token 401、错误配对码 403、status 脱敏、撤销后 poll 401、Origin 守卫。
- [x] 实现 `browser_extension_routes.py`，挂载 `/api/v1`。
- [x] `local_auth.py` 增加扩展 I/O 公开前缀；补中间件测试。
- [x] 运行相关 pytest。

### 里程碑 M3：现有浏览器工具接入

- [x] 编写 `test_browser_cdp_external.py`。
- [x] `browser_cdp.py` 增加 EXTERNAL 分支与 CDP 方法白名单。
- [x] 验证 `browser_navigate/snapshot/interact/screenshot/cookies` 单测不回归。

### 里程碑 M4：Chrome 扩展

- [x] 实现 manifest、background、offscreen、popup。
- [x] 真实 Chromium 冒烟：扩展加载（Service Worker + offscreen）→ 配对 → 共享本地页面 → `chrome.debugger` 执行 `Runtime.evaluate` → 停止共享 → 后端状态清空。
- [ ] 真机验证跨域跳转自动停止、关闭标签页自动停止、DevTools 占用时的错误提示（逻辑已实现，待真实站点/Chrome 109 验证）。
- [x] 验证「保存登录状态」：真实 Chromium 中 Cookie + localStorage 落库为加密凭据（`source_profile=browser-extension`）。
- [ ] 验证保存后的登录态被 `web_fetch` / JS 渲染通道复用（沿用现有凭据库路径，待真实站点验证）。

### 里程碑 M5：设置页与文档

- [x] 实现前端组件、API 客户端、i18n、搜索条目。
- [x] 编写组件测试（配对码展示、设备撤销、共享状态、空状态）。
- [x] 更新用户手册与技术文档；README 安装说明。
- [x] `electron-builder.yml` 打包扩展目录。

### 里程碑 M6：回归与交付

- [x] 后端目标测试（166 项相关测试）+ 前端 vitest（设置/i18n/API 目标测试）/ tsc / eslint / architecture-check。
- [x] 真实 Chromium 扩展 + 真实后端端到端冒烟（配对 → 共享 → CDP 命令 → 保存登录态 → 停止共享）。
- [ ] 手动 Electron 冒烟：设置页生成配对码 → 扩展配对 → 共享 → agent 抓取。
- [ ] 提交 PR（main 分支），CI 全绿后合并；再按双分支策略评估同步到 release/win7。

## 风险评估与依赖

| 风险 | 影响 | 对策 |
| --- | --- | --- |
| Chrome 109 对 `chrome.debugger` + offscreen 的行为差异 | 连接不稳 | 长轮询超时 20s + 1 分钟 alarm 看门狗；attach 失败给出明确错误；真机 Chrome 109 验证 |
| 用户 DevTools 已附着同一标签页 | attach 失败 | 提示关闭 DevTools 后重试；不自动抢夺 |
| MV3 SW 被回收导致命令丢失 | 工具超时 | offscreen 文档承载长轮询；结果超时 30s；下次轮询自动恢复 |
| 多标签页共享冲突 | 会话歧义 | P0 单共享；第二个 409 并自动停止 |
| 扩展权限过宽 | 隐私顾虑 | 仅 optional host 权限按站点申请；只操作共享标签页；显示调试信息条；可随时停止/撤销 |
| 扩展分发 | 用户安装成本 | 提供设置页路径与安装引导；后续再评估商店上架 |

**依赖**：无新增 Python/npm 依赖；Chrome/Edge 109+（Win7 支持的最后一个大版本）；现有 `browser_ws` 不参与本方案。

## 验收标准

1. 设置页可生成/展示配对码，扩展粘贴后显示已连接；设备可撤销。
2. 用户共享知网标签页后，在 Sage 中让 agent 读取页面，无需重新登录即可拿到已登录内容。
3. 用户停止共享或切换标签页域名后，agent 的浏览器工具在 30 秒内报错而不是继续访问。
4. 扩展「保存登录状态」后，断开共享仍可通过 `web_fetch` 抓取该站点登录墙内容。
5. `read_only` 权限下，共享标签页仍不能执行 `browser_navigate`（沿用风险等级）。
6. 未配对请求、错误 token、非共享标签页的操作全部被拒绝，且不泄露设备 token。
