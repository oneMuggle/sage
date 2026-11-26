# 浏览器多会话隔离 P1 实施计划（前端归属作用域 + 下载事件路由 + 渲染/共享标签页串行）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 在 P0（实例归属/租约/profile 互斥）之上，消除前端跨会话的 UI 串台、内嵌下载事件的跨会话广播，以及渲染池凭据与 external 共享标签页的并发交错。

**Architecture:** 前端不再猜测"唯一存活会话"，一切控制/确认只看 `/browser/status.owner === 当前对话` 的实例；Electron 桥把下载按 `browser_id` 路由到对应 WS 客户端并按实例分目录落盘；后端对同一渲染池实例上的凭据渲染加 per-instance 串行锁，对 external 共享标签页加全局动作锁。

**Tech Stack:** React 18 + zustand + vitest（前端）；Electron 21 + node:test/vitest（Electron）；Python 3.10/3.8 + pytest（后端）。

**Spec:** 已合并的 P0 计划 `docs/plans/2026-11-26_browser-multi-session-isolation.md` §"非目标（P1）" + `docs/technical/159-controlled-browser-use.md`。

## Global Constraints

- 后端命令用 `/home/fz/anaconda3/envs/sage-backend/bin/python`；前端/Electron 用 `npx vitest run <file>`。
- 不改变"内嵌浏览器全窗口共享登录分区"的现有语义（per-conversation 分区属 P2，需产品决策与真机验收）。
- 不新增用户可见的跨会话操作入口：任何暂停/接管/确认只能作用于当前对话名下实例。
- 文档不新开编号章节，更新现有 `docs/technical/159-*` 与 `docs/user-manual/54-*`（win7 为 162/55，cherry-pick 时改号）。
- 架构棘轮按 `split('\n')` 计行；改动后本地跑 `node scripts/architecture-check.mjs` 并按需补基线。

## 非目标（P2）

- 内嵌浏览器 per-conversation Electron 分区（`persist:sage-agent-<conversation>`）与手动面板按会话分区。
- 确认项服务端按 conversation 过滤/校验（本次以浏览器归属+前端作用域消除串台；服务端仍按 browser_id 隔离）。
- 并行多账号实例池（多账号 spec 的未来演进）。

## Task 1: 前端按归属作用域（不再猜测其他会话的浏览器）

**Files:**
- Modify: `src/shared/api/browserSettingsClient.ts`（`BrowserSessionInfo` 增 `owner?`/`busy?`）
- Modify: `src/features/browser/BrowserPanel.tsx:252-381`（删除 discoveredSession 与无过滤回退）
- Modify: `src/features/browser/BrowserSessionStatus.tsx:121-175`（只允许绑定本对话/无归属实例）
- Modify: `src/shared/lib/i18n/locales/{zh,en}/...`（新增"其他对话"标签 key）
- Test: `src/features/browser/__tests__/BrowserPanel.test.tsx`、`BrowserSessionStatus.test.tsx`

**Interfaces:**
- Produces: `fetchBrowserStatus()` 在面板内 2s 轮询；`ownedIds: Set<string>`（`alive && owner === conversationId`）。
- 解析规则：`target = (toolSessionId ?? remembered) if owned or ownedIds 未加载 else ownedSessionIds[0] ?? null`；`ownedIds` 已加载且候选不在其中 → 丢弃候选，绝不回退到其他会话。
- 只以 `target` 调 `fetchBrowserControl` / `fetchPendingConfirmations(target)`；target 为空时清空 pending/控制态，**不**调用无过滤 `/browser/confirmations`。
- `BrowserSessionStatus`：`owner` 非空且 `!== currentSessionId` 的实例显示"其他对话"、禁用绑定。

- [x] Step 1: 更新类型与测试 mock（`fetchBrowserStatus`），先改/加失败断言：其他 owner 的唯一存活会话不会被认领；本对话实例能恢复控制按钮；无过滤确认项不再渲染。
- [x] Step 2: `npx vitest run src/features/browser/__tests__/BrowserPanel.test.tsx src/features/browser/__tests__/BrowserSessionStatus.test.tsx` 确认失败。
- [x] Step 3: 实现解析与轮询收敛；新增 i18n key（zh/en 同步）。
- [x] Step 4: 测试通过；`npx tsc --noEmit` 通过。
- [x] Step 5: 提交 `feat(browser): 面板按会话归属限定控制与确认`。

## Task 2: Electron 下载按浏览器实例路由

**Files:**
- Modify: `electron/agentBrowserBridge.ts:68-96,176-196,233-237,544-611`（`createWindow(visible, session)`、`setDownloadPath(path, session)`、事件客户端按 session 过滤）
- Modify: `electron/agentBrowserHost.ts:37-149`（webContents→session 映射、下载目录 Map、事件带 session）
- Test: `electron/__tests__/agentBrowserBridge.test.ts`（+ 如存在 host 测试同步更新）

**Interfaces:**
- `BridgeDeps.createWindow(visible: boolean, session?: string)`
- `BridgeSession.setDownloadPath?(path: string, session?: string)`
- `BridgeDeps.onDownload?(handler: (method: string, params: Record<string, unknown>, session?: string) => void)`
- `AgentBrowserBridge.attachEventClient(send, session?)`：有 session 的事件只发给 `client.session === session` 或未限定 session 的客户端；无 session 的事件保持广播（兼容旧路径）。
- `agentBrowserHost`：`Map<webContentsId, session>`；`will-download` 第三参 `webContents` 反查 session；目录 `Map<session, dir>`，未命中用最后一次设置的目录兜底。

- [x] Step 1: 写失败测试：分别以 `s1`/`s2` 订阅事件，`downloadWillBegin(session=s1)` 只到 s1；无 session 事件广播到两者；`createTarget(session=s1)` 时 `createWindow` 收到 s1；`setDownloadBehavior` 携带 session 传到 `setDownloadPath`。
- [x] Step 2: `npx vitest run electron/__tests__/agentBrowserBridge.test.ts` 确认失败。
- [x] Step 3: 实现桥与 host 改造。
- [x] Step 4: 测试通过。
- [x] Step 5: 提交 `feat(browser): 内嵌下载目录与事件按浏览器实例隔离`。

## Task 3: 渲染池凭据渲染串行化

**Files:**
- Modify: `backend/tools/web_render.py`（新增 per-browser 凭据锁；`render_page` 在带凭据时持锁）
- Test: `backend/tests/unit/test_web_render.py` 或新增 `test_render_credential_lock.py`

**Interfaces:**
- Produces: `_credential_render_lock(browser_id) -> threading.Lock`（同 id 同锁、不同 id 不同锁）；`render_page` 在 `credential_cookies or credential_origins` 非空时，从 `Target.createTarget` 到 `Target.closeTarget` 全程持锁，其余分支不持锁。

- [x] Step 1: 失败测试：同 id 返回同一锁对象；两个线程各持锁时第二个阻塞/串行（用事件计数验证不重叠）。
- [x] Step 2: 运行确认失败。
- [x] Step 3: 实现锁与 `render_page` 持锁路径（finally 释放）。
- [x] Step 4: `pytest backend/tests/unit/test_web_render.py -q` 全绿。
- [x] Step 5: 提交 `fix(browser): 渲染池凭据注入按实例串行`。

## Task 4: external 共享标签页全局串行

**Files:**
- Modify: `backend/tools/browser_tool.py`（`_lease_session` 对 EXTERNAL 加全局锁；`_browser_lease_scope` 释放）
- Test: `backend/tests/unit/test_browser_session_ownership.py`

**Interfaces:**
- Produces: 模块常量 `_EXTERNAL_LOCK_TIMEOUT_SECONDS = 120.0`；`_external_action_lock`；`_lease_session` 在 EXTERNAL 时 `acquire(timeout=...)`，超时抛 `BrowserCDPError("共享标签页正被另一个会话操作，请稍后重试")`；作用域退出时逆序释放锁与租约。

- [x] Step 1: 失败测试：预先持有 `_external_action_lock`，`_browser_lease_scope` 内解析 external 会话抛可读错误；释放后可正常进入；普通 CHROME 会话不受影响。
- [x] Step 2: 运行确认失败。
- [x] Step 3: 实现（租约与锁的登记/释放都在作用域内）。
- [x] Step 4: 归属套件全绿。
- [x] Step 5: 提交 `fix(browser): 共享标签页动作全局串行`。

## Task 5: 文档与回归

**Files:**
- Modify: `docs/technical/159-controlled-browser-use.md`（"多会话归属与租约"补 P1：前端作用域、下载事件路由、渲染/external 串行；P2 非目标）
- Modify: `docs/user-manual/54-browser-use.md`（面板只看本对话实例；下载落在本实例目录）
- [x] `npx vitest run src/features/browser/__tests__ electron/__tests__/agentBrowserBridge.test.ts`
- [x] `pytest backend/tests/unit/test_browser_session_ownership.py backend/tests/unit/test_web_render.py backend/tests/unit/test_render_pool.py backend/tests/unit/test_browser_tool.py -q`
- [x] `ruff check` 改动文件；`node scripts/architecture-check.mjs`
- [x] 更新本计划勾选
- [ ] 推送并创建 PR；CI 绿后由用户合并

## 验收标准

1. 对话 B 的浏览器面板不会再显示/控制对话 A 的实例或待确认项；A 的唯一存活实例不会被 B 认领。
2. 内嵌浏览器并发下载：每个 `browser_id` 只收到自己的下载事件，文件落在各自目录。
3. 同一渲染池实例上的两个不同账号凭据渲染不会交叉注入 cookie。
4. external 共享标签页上的两个会话动作串行；等待超时给出可读错误。
5. 现有浏览器/面板/Electron 测试全绿，CI 通过。
