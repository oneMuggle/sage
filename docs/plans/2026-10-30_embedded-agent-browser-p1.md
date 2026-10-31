# 内置 Agent 浏览器（P1）实施计划

> 堆叠在 `feat/web-access-login-ux`（PR #2683）之上；完成 P0 合并后 rebase 到 release/win7。
> 目标：Win7 无可用系统浏览器的机器也能完成网页登录/抓取；登录窗口由 Sage 自有 Chromium 承载，
> 会话（cookie + localStorage）与渲染池共享同一持久分区。

## 1. 背景

P0 已让「登录一次、三通道复用」成立，但浏览器通道仍依赖系统 Chrome/Edge/Firefox：
纯净 Win7 常只有 IE，Chrome/Edge 最高 109、Firefox ESR 115，`browser_*` 直接不可用。

**Spike 事实（Electron 21.4.4 / Chromium 106）**：

- `--remote-debugging-port` 的浏览器端点可连，但 `Target.getTargets` 恒为空、
  `Target.createTarget` 返回 `Not supported` → 不能把 Electron 当外部 Chrome 直接接现有 CDP 客户端。
- 主进程 `webContents.debugger.attach()` 后支持：`Page.enable/navigate/addScriptToEvaluateOnNewDocument/captureScreenshot`、
  `Runtime.evaluate`、`Network.enable/getCookies`。
- `Storage.getCookies/setCookies` 返回 “Browser context management is not supported.” →
  cookie 改用 Electron `session.cookies` API；截图改用 `webContents.capturePage()`。

## 2. 架构

```
backend browser_cdp.cdp_command
  └─ session.browser_type == embedded
       └─ HTTP POST http://127.0.0.1:<port>/command  (X-Sage-Bridge-Token)
             └─ Electron 主进程 agentBrowserBridge
                  ├─ 目标注册表（headless / visible 两套模式）
                  ├─ BrowserWindow(partition: persist:sage-agent-browser)
                  ├─ webContents.debugger → Page/Runtime/Network 命令
                  └─ session.cookies → Storage/Network cookie 命令
```

- **隔离**：headless（web_fetch 渲染池）与 visible（登录/交互）各自独立目标表，
  避免渲染池复用登录标签页；两者共享持久分区，登录后 localStorage/cookie 天然对渲染可见。
- **启用条件**：Electron 仅在 Win7（`os.release()` 以 `6.1` 开头）或
  `SAGE_FORCE_EMBEDDED_BROWSER=1` 时向 backend 注入环境变量；其它平台行为不变。
- **不在本 P1**：应用内右栏浏览器面板（BrowserView bounds 同步）——登录窗口本身就是可见
  Sage BrowserWindow，已满足接管；面板留 P2。

## 3. 文件

| 文件 | 动作 |
|---|---|
| `electron/agentBrowserBridge.ts` | 新建：HTTP bridge、目标注册表、命令分发（依赖注入便于测试） |
| `electron/__tests__/agentBrowserBridge.test.ts` | 新建：命令分发/目标隔离/cookie 映射/鉴权 单测 |
| `electron/main.ts` | 启动 bridge、把 port/token/开关注入 spawnBackend env、退出时关闭 |
| `backend/tools/browser_cdp.py` | `BrowserType.EMBEDDED`、`EmbeddedLauncher`、`_embedded_command`、launch 分支、事件通道跳过 |
| `backend/tools/browser_launcher.py` | 环境发现：`SAGE_EMBEDDED_BROWSER/PORT/TOKEN` 优先于系统浏览器 |
| `backend/tools/browser_tool.py` | 下载跟踪对 embedded 降级为目录扫描 |
| `backend/tools/web_render.py` | 渲染池事件通道对 embedded 返回 False（轮询兜底） |
| `backend/api/diagnostic_routes.py` | 浏览器健康：embedded 时报告「Sage 内置浏览器」 |
| `backend/skills/skill_md/shipped/cnki-research/SKILL.md` | 新建：知网检索/登录/PDF 下载 playbook |
| `backend/skills/builtin/academic_adapters.py` | CNKI URL 切到 kns8s 检索页 + 说明 |
| `docs/user-manual/18-web-access.md` | 内置浏览器说明（Win7） |
| `backend/tests/unit/test_browser_cdp_embedded.py` | 新建：launcher 发现 / 命令路由 / 错误映射 |
| `backend/tests/unit/test_academic_adapters.py`（如存在则扩展） | 新 URL 断言 |

## 4. 全局约束

- py3.8 语法（typing.*、无 PEP604/585）；ruff 双引号；测试沿用 `_MemRepo`/monkeypatch 风格。
- Electron 21 / Node 16：无全局 fetch，使用 `http` 模块；无 `WebSocketServer`，本方案只用 HTTP。
- bridge 只监听 `127.0.0.1`，随机端口 + 随机 token；无 token → 401；body 上限 8 MiB。
- BrowserWindow 安全基线：`sandbox: true`、`contextIsolation: true`、`nodeIntegration: false`、
  `partition: 'persist:sage-agent-browser'`、UA 归一化复用 `plainChromeUa`。
- 站点数据不得成为命令：bridge 只接受已定义命令；拒绝未知方法。

## 5. 任务

### Task 1：Electron bridge（纯模块 + 单测）
- [x] `agentBrowserBridge.ts` 定义 `BridgeDeps`（createWindow/closeWindow/getSession/now）与 `dispatch(request)`；
      命令：`Target.getTargets/createTarget/closeTarget/attachToTarget`、`Browser.getVersion/setDownloadBehavior`、
      `Network.getCookies/enable`、`Storage.getCookies/setCookies`、`Page.*`/`Runtime.*`（debugger 透传）、
      `Page.captureScreenshot`（capturePage）。
- [x] 单测：模式隔离（headless 看不到 visible 目标）、attach 返回 sessionId、cookie 映射 CDP↔Electron、
      未知方法报错、缺少 token 401（HTTP 层另测）。
- [x] 提交。

### Task 2：main 集成 + env
- [x] `startAgentBrowserBridge()` 在 `spawnBackend()` 前启动；env 注入 `SAGE_EMBEDDED_BROWSER=1`（仅 Win7/force）、
      `SAGE_EMBEDDED_BROWSER_PORT`、`SAGE_EMBEDDED_BROWSER_TOKEN`。
- [x] `before-quit` 关闭 server 与窗口；日志只打端口不打印 token。
- [x] `npm run typecheck:electron` 通过；提交。

### Task 3：后端 Embedded 启动器与命令路由
- [x] `BrowserType.EMBEDDED` + `EmbeddedLauncher`（build_command 空、wait_for_cdp 复用 env 端口/路径）；
      `launch_browser` 走嵌入式分支（dummy process、persistent、profile_name="embedded"）。
- [x] `_discover_from_env` 优先 embedded（`SAGE_EMBEDDED_BROWSER=1` 且 port/token 齐全）。
- [x] `cdp_command` 顶层分流 `_embedded_command`（urllib + token + `X-Sage-Headless`）；页面方法缺 target 时由 bridge 选首个/新建。
- [x] `browser_events.start_event_channel`/`start_download_tracking` 对 embedded 直接返回 False；
      `web_render._ensure_pool_channel` 同理。
- [x] 单测：env 发现优先级、launch 不 spawn、命令 POST 形状/错误映射、embedded 跳过事件通道。
- [x] 提交。

### Task 4：健康检查与降级
- [x] `diagnostic_routes.get_browser_health`：embedded 时 `browserFound=true, executable="Sage 内置浏览器"`。
- [x] `browser_downloads` 在 embedded 无 tracker 时扫描下载目录（现有 fallback 已覆盖，补测试）。
- [x] 提交。

### Task 5：CNKI playbook + 适配器
- [x] `cnki-research/SKILL.md`：登录（个人/机构/校园网）→ 检索 → 结果解析 → 详情 → 点「PDF下载」
      （禁 CAJ）→ `browser_downloads` 等待 → `%PDF-` 校验 → 5–12s 限速、单批 ≤20。
      `allowed-tools: browser_launch browser_navigate browser_snapshot browser_interact browser_downloads browser_login web_fetch http_download`
- [x] `academic_adapters.CNKIAdapter` 改用 `https://kns.cnki.net/kns8s/defaultresult/index?kw=<query>&korder=SU` 形态；
      保留旧模板说明。更新/新增单测断言 URL 含 `kns8s` 与编码关键词。
- [x] 手册补充「知网等登录站点的推荐流程」。
- [x] 提交。

### Task 6：验证
- [x] 后端：新增/相关测试 + `test_browser_tool/test_web_render/test_diagnostic_routes` 回归。
- [x] Electron：`npm run typecheck:electron` + `npx vitest run electron/__tests__/agentBrowserBridge.test.ts`。
- [x] `scripts/check_py38_compat.py`、ruff、architecture check。
- [ ] 推送 + PR（stacked on #2683），CI 绿。

## 6. 风险

- **bridge 是本地高权限接口**：token + 127.0.0.1 + 命令白名单；不实现任意 debugger 透传。
  若本地进程拿到 token 可控制内置浏览器——与现有本地后端同信任边界。
- **Chromium 106 老化**：内置浏览器定位 Win7 兜底；main/新系统仍优先外部新版浏览器。
- **事件通道缺失**：embedded 下渲染就绪等待回到轮询、下载走目录扫描；可接受，P2 再补 WS 事件。
- **CDP 差异**：Storage 域不可用已用 session.cookies 替代；若后续发现其它域缺失，按同一模式补映射。
