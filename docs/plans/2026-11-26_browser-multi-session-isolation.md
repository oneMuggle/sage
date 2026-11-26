# 浏览器多会话隔离（P0）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 让浏览器资源按聊天会话归属、按租约保护、按 profile 互斥，消除多会话并发时的串台、互杀与审计不可归因。

**Architecture:** 保留现有"纯 CDP + 进程级 `BrowserSessionManager`"架构不变，在会话对象上补 `owner`（聊天会话 id）与 `lease_count`；所有浏览器工具经统一的 `_resolve_session` 按调用方 `ToolExecutionContext.session_id` 解析归属；工具执行期间持租约，LRU/上限淘汰跳过被租用实例；持久 profile 增加进程内占用互斥；审计写入 `conversation_id`。

**Tech Stack:** Python 3.10（main）/ py3.8 兼容写法（`from __future__ import annotations` + typing），FastAPI 后端，纯 CDP（无 Playwright），pytest。

**Spec:** 本文件 §"背景与方案"（2026-11-26 会话评审结论）+ `docs/technical/159-controlled-browser-use.md`。

## Global Constraints

- 后端命令一律使用 `/home/fz/anaconda3/envs/sage-backend/bin/python`（conda 环境 `sage-backend`）。
- py3.8 兼容：新代码沿用 `from __future__ import annotations` + `typing.*` 泛型，不使用 `str | None`。
- 无上下文（`current_tool_context() is None`，如单测/REST 设置页）时保持旧解析语义（`owner == ""`），不得让既有调用方行为回退。
- 不动前端、Electron、渲染池分区与事件路由（属 P1）；不在本阶段改 `browser_action_log` 表结构（`conversation_id` 列已存在）。
- 提交信息遵循 Conventional Commits；文档编号申请前先 `ls docs/technical` 确认当前最大号（避免并发 PR 抢占）。

## 背景与方案（设计摘要）

当前隔离单位是 `browser_id` 而非聊天会话：`BrowserSessionManager` 为进程级单例，`browser_*` 不传 id 时回退"唯一用户实例/用户共享标签页"，导致两个会话共用同一浏览器、同一活动标签页、同一 ref 缓存，且任一会话可 `browser_close` 掉对方的实例；LRU 淘汰不感知 in-flight；持久 profile 无互斥；审计 `conversation_id` 恒 NULL。

P0 方案四点：

1. **归属（owner）**：`BrowserSession.owner` 记录启动它的聊天会话 id（`ToolExecutionContext.session_id`）。工具缺省解析只返回本会话拥有的实例；跨会话显式指定 id 报错（`external` 共享标签页除外）。
2. **租约（lease）**：工具执行期间对解析到的实例 `lease_count += 1`，结束释放；`register()` 的上限/LRU 淘汰与渲染池让位都跳过 `lease_count > 0` 的实例，无可回收时报错而不是杀 in-flight。
3. **profile 互斥**：持久 profile 目录在进程内登记占用者 `browser_id`；他人在用时显式命名 profile 直接报错，隐式 `default` 自动后缀 `default-2`；`browser_login` 复用固定 `login-default` 前校验归属；Firefox 启动前检查同端口活动实例并给出明确错误。
4. **可归因与落盘隔离**：审计写 `conversation_id`；无工作区时下载目录落到 `browser-downloads/<browser_id>/`；截图默认文件名带 `browser_id`。

非目标（P1/P2，另行计划）：内嵌浏览器 per-conversation 分区、前端"唯一存活会话/无过滤确认"回退、下载事件按会话路由、external 全局操作锁、渲染池并发 cookie 串味、并行多账号实例池。

## 文件清单

| 文件 | 责任 |
|---|---|
| `backend/tools/browser_cdp.py` | `BrowserSession` 字段；`BrowserSessionManager` 归属解析/租约/淘汰；`launch_browser(owner, profile 锁)`；`_terminate_session` 释放 profile；`get_status` 增 owner/busy |
| `backend/tools/browser_tool.py` | `_current_owner`、租约域与 `@_leased` 装饰器、`_resolve_session` 改造、`_has_usable_browser_session`、auto-launch 归属、`_apply_download_behavior`/截图命名、审计 `conversation_id`、`browser_login` 归属、`browser_switch_account` 传 owner |
| `backend/services/browser_account_service.py` | `switch_account(..., owner="")` 按归属解析会话 |
| `backend/tests/unit/test_browser_session_ownership.py` | 新增：归属解析、租约淘汰保护、profile 锁、审计归因、auto-launch owner |
| `backend/tests/unit/test_browser_tool.py` | 仅在旧断言与新语义冲突时调整（旧调用无上下文 → 行为不变，预期不改） |
| `docs/technical/159-controlled-browser-use.md` | 新增"会话归属与租约（2026-11-26）"小节 + 已知限制更新 |
| `docs/user-manual/54-browser-use.md` | 用户可见语义：每个对话默认独立浏览器；并发登录串行 |

### Task 1: BrowserSession 归属与租约字段

**Files:**
- Modify: `backend/tools/browser_cdp.py:345-391`（dataclass）、`:394-626`（manager）
- Test: `backend/tests/unit/test_browser_session_ownership.py`

**Interfaces:**
- Produces: `BrowserSession.owner: str = ""`、`BrowserSession.lease_count: int = 0`、`BrowserSession.is_leased() -> bool`；`BrowserSessionManager.acquire_lease(session) -> None`、`release_lease(session) -> None`

- [x] **Step 1: 写失败测试**
- [x] **Step 2: 运行确认失败**（`AttributeError: ... 'owner'`）
- [x] **Step 3: 实现字段与方法**（管理器方法持 `self._lock`；release 不抛错、计数不低于 0）
- [x] **Step 4: 运行确认通过**
- [x] **Step 5: 提交** `feat(browser): 会话归属与租约字段`

### Task 2: 管理器归属解析

**Files:**
- Modify: `backend/tools/browser_cdp.py:394-626`
- Test: `backend/tests/unit/test_browser_session_ownership.py`

**Interfaces:**
- Produces:
  - `BrowserSessionManager.owned_sessions(owner: str) -> List[BrowserSession]`（过滤保留池，`owner == ""` 返回空列表）
  - `BrowserSessionManager.resolve_owned(owner: str) -> BrowserSession`（1 个返回；0 个或 >1 个抛 `BrowserCDPError`，>1 时提示传 `browser_id`）
  - `BrowserSessionManager.require(browser_id: Optional[str], owner: str = "") -> BrowserSession`（显式 id 时校验归属；无 id 且 `owner` 非空时走 `resolve_owned` → 无自有实例则回退 `external`；`owner == ""` 保持旧逻辑）
  - `BrowserSessionManager.get_status()` 的 sessions 项新增 `"owner"`、`"busy"` 字段

- [x] **Step 1: 写失败测试**：两个会话分别 owner=A/B；`require(None, owner="A")` 返回 A 的；`require("B的id", owner="A")` 抛错；`require(None, owner="C")` 无实例且无 external 时抛"没有运行中的浏览器实例"；`owner=""` 仍返回唯一实例
- [x] **Step 2: 运行确认失败**
- [x] **Step 3: 实现**（`resolve_owned`、`require` 分支、`get_status` 字段）
- [x] **Step 4: 运行确认通过**
- [x] **Step 5: 提交** `feat(browser): 浏览器会话按归属解析`

### Task 3: 工具层接线（owner + 租约 + 自动拉起）

**Files:**
- Modify: `backend/tools/browser_tool.py:163-165`（`_resolve_session`）、`:337-352`（`_has_user_browser_session` → `_has_usable_browser_session`）、`:1442-1458`（navigate 自动拉起）、`:1273-1376`（launch 传 owner）、全部 `execute` 方法加 `@_leased`
- Test: `backend/tests/unit/test_browser_session_ownership.py`

**Interfaces:**
- Produces:
  - `_current_owner() -> str`（读 `current_tool_context()`，异常/无上下文返回 `""`）
  - `_browser_lease_scope()` 上下文管理器 + `_leased(fn)` 装饰器（线程本地栈；`_resolve_session` 内 acquire，作用域退出统一 release）
  - `_resolve_session(browser_id)` 内部 `manager.require(browser_id or None, owner=_current_owner())` 并登记租约
  - `_has_usable_browser_session(owner) -> bool`（自有实例 / external / 旧语义）
  - auto-launch 改用 `_owner_launch_lock(owner)` 包住"复查 + launch"，`launch_browser(..., owner=owner)`

- [x] **Step 1: 写失败测试**：`set_tool_context` 绑定 A 后，`BrowserNavigateTool.execute(url=...)` 在已注册 A 实例时不调用 `launch_browser`；无 A 实例时调用 `launch_browser(owner="A")`（monkeypatch 捕获参数）；显式传 B 的 id 返回 `success=False` 且错误文案含"另一个会话"
- [x] **Step 2: 运行确认失败**
- [x] **Step 3: 实现**（装饰器逐类加到 12 个 `execute`；navigate 自动拉起改造）
- [x] **Step 4: 运行确认通过 + `test_browser_tool.py` 全绿**
- [x] **Step 5: 提交** `feat(browser): 工具按调用方会话归属解析并持有租约`

### Task 4: 关闭/切号/登录的归属

**Files:**
- Modify: `backend/tools/browser_tool.py:2524-2605`（close 随 `_resolve_session` 生效，补显式错误文案测试）、`:3528-3548`（login 解析）、`:3972-3974`（switch_account 传 owner）
- Modify: `backend/services/browser_account_service.py:371-411`
- Test: `backend/tests/unit/test_browser_session_ownership.py`

**Interfaces:**
- Produces: `BrowserAccountService.switch_account(target_account_id, browser_id=None, owner="")`；login 复用 `login-default` 前用 `manager.require(_LOGIN_PROFILE_NAME, owner=...)`（归属不符时回可读错误）

- [x] **Step 1: 写失败测试**：B 会话显式 `browser_close(A 的 id)` 返回失败且 A 实例仍在；`switch_account(..., owner="A")` 在仅 B 实例存在时返回失败
- [x] **Step 2: 运行确认失败**
- [x] **Step 3: 实现**
- [x] **Step 4: 运行确认通过**
- [x] **Step 5: 提交** `feat(browser): 关闭/切号/登录校验会话归属`

### Task 5: 持久 profile 互斥与 Firefox 单实例

**Files:**
- Modify: `backend/tools/browser_cdp.py:965-1125`（`launch_browser` 签名与持久分支）、`:629-679`（`_terminate_session` 释放 profile）
- Test: `backend/tests/unit/test_browser_session_ownership.py`

**Interfaces:**
- Produces:
  - `launch_browser(headless=True, browser_id=None, persistent=False, profile_name: Optional[str] = None, owner: str = "")`
  - 模块级 `_claim_profile(profile_dir, browser_id, allow_suffix: bool) -> str`、`_release_profile(profile_dir, browser_id)`（`_profile_lock` 保护）
  - 行为：显式 `profile_name` 被他人占用 → `BrowserCDPError`（文案含"持久 profile ... 正被另一个浏览器会话使用"）；`profile_name is None` → 基名 `default` 被占用时自动取 `default-2..default-10`
  - Firefox：`_assert_firefox_single_instance(browser_id)` — 已有存活 FIREFOX 会话时抛"同一时刻只能有一个 Firefox 调试实例"

- [x] **Step 1: 写失败测试**：同一 profile 两个不同 browser_id 依次 `_claim_profile` 第二次抛错；`allow_suffix=True` 返回 `-2` 后缀；`_release_profile` 后可再次占用；Firefox 第二次启动前检查抛错（直接调内部检查，不真启动进程）
- [x] **Step 2: 运行确认失败**
- [x] **Step 3: 实现**（所有失败路径释放已占用 profile）
- [x] **Step 4: 运行确认通过**
- [x] **Step 5: 提交** `feat(browser): 持久 profile 互斥与 Firefox 单实例守卫`

### Task 6: 审计归因与落盘隔离

**Files:**
- Modify: `backend/tools/browser_tool.py:601-634`（audit）、`:355-373` + `:1323-1345`（下载目录）、`:2435-2462`（截图命名）、`:2899-2907`（browser_downloads 回退目录）
- Test: `backend/tests/unit/test_browser_session_ownership.py`

**Interfaces:**
- Produces: `_download_dir_for(session, workspace_root) -> Path`（有工作区 → `<root>/downloads`；否则 → `browser_downloads_root()/<sanitize(browser_id)>/`）；`_record_browser_audit` 写 `conversation_id=_current_owner() or None`；截图缺省名 `browser_screenshot_<browser_id>_<ts>.png`

- [x] **Step 1: 写失败测试**：绑定上下文后 `_record_browser_audit` 捕获 `conversation_id`；`_download_dir_for` 两条分支路径正确；截图默认文件名包含 browser_id（monkeypatch CDP/文件写入）
- [x] **Step 2: 运行确认失败**
- [x] **Step 3: 实现**
- [x] **Step 4: 运行确认通过**
- [x] **Step 5: 提交** `feat(browser): 审计归因与下载/截图按实例隔离`

### Task 7: 文档更新

**Files:**
- Modify: `docs/technical/159-controlled-browser-use.md`（会话配置一节后新增"多会话归属与租约（2026-11-26）"：owner 语义、解析顺序、租约淘汰、profile 互斥、Firefox 单实例、审计 conversation_id、已知 P1 限制）
- Modify: `docs/user-manual/54-browser-use.md`（每个对话默认自己的浏览器；多会话并发登录串行；未绑定工作区时下载在数据目录按实例分目录）
- README 索引仅在新增章节时需要更新（本任务不新增编号）

- [x] **Step 1: 更新两处文档**
- [x] **Step 2: 文档自检**（与代码一致）
- [x] **Step 3: 提交** `docs(browser): 多会话归属与租约说明`

### Task 8: 回归与交付

- [x] `pytest backend/tests/unit/test_browser_session_ownership.py backend/tests/unit/test_browser_session_settings.py backend/tests/unit/test_browser_tool.py backend/tests/unit/test_browser_cdp_external.py backend/tests/unit/test_render_pool.py -q`
- [x] `ruff check backend/tools/browser_cdp.py backend/tools/browser_tool.py backend/services/browser_account_service.py backend/tests/unit/test_browser_session_ownership.py`
- [x] 更新本计划勾选状态
- [ ] 推送分支并创建 PR（body 附验收清单与已知 P1 限制）

## 风险评估

| 风险 | 缓解 |
|---|---|
| 破坏"单实例免传 id"便利 | 无 `ToolExecutionContext` 的调用方保持旧语义；聊天内每会话自动拉起新实例，模型无需记 id |
| 内嵌浏览器仍共享 cookie 分区，P0 只解决实例归属 | 计划与 PR 明示"内嵌登录态隔离属 P1"，避免误以为已完全隔离 |
| 持久 profile 自动后缀改变登录目录名 | 仅当同名被他人占用时触发；单人使用行为不变 |
| `browser_login` 并发被拒 | 错误文案引导"另一个会话正在登录，请稍后"；与单登录窗口语义一致 |
| win7 分支后续同步 | 新代码全部 py3.8 兼容写法，后续 cherry-pick 仅需 pydantic 无关验证 |

## 验收标准

1. 两个聊天会话（不同 `ToolExecutionContext.session_id`）并发调用 `browser_*`：缺省解析各自落到自己的浏览器实例，互不覆盖页面/ref/活动标签页。
2. 会话 B 无法通过显式 id 关闭、暂停、切账号或登录到会话 A 的实例（`external` 共享标签页保留显式可用）。
3. 长任务执行期间（持租约），另一会话触发上限/LRU 不会终止该实例；无可回收时报"所有实例都在使用中"。
4. 持久 profile 同名双开被拒或自动后缀；Firefox 第二次启动收到明确单实例错误。
5. `browser_action_log.conversation_id` 写入当前会话 id。
6. 既有浏览器相关单测全绿；新增归属/租约/互斥测试覆盖上述语义。
