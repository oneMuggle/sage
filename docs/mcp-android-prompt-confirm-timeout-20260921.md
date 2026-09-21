# 安卓端「当前问题连续 20 秒无法确认」根因分析与继续方案

日期：2026-09-21
范围：`android/`（APK `android/app/build/outputs/apk/debug/app-debug.apk`，构建于 2026-09-21 00:19，包含同日 00:18 修改的 `android/app/src/main/assets/PageBridge.js`）
参照：`reference/Arena模型助手-源码-fyb-0.1.0`（C# 桌面端）、`reference/ArenCard`（纯协议注册/抽卡）
前序记录：`docs/mcp-android-implementation-progress.md`（第二十八批 S0 真机探测、第三十批真机烟测）

## 0. 结论速览

1. **根因是页面桥，不是阶段机。** `android/app/src/main/assets/PageBridge.js` 用 ChatGPT 风格的选择器 `[data-message-author-role="user"]` 来确认「我的问题已出现在页面上」（`promptConfirmed`）。arena.ai 当前前端（部署号 `dpl_8JFP6KSwW7PUGUCzKeAYEMTvMtDN`，2026-09-21 抓取）**全站 JS 中不存在** `data-message-author-role` / `data-message-role` / `data-message-id`，因此 `promptConfirmed` 在真机上恒为 `false`。
2. 阶段机 `RetryController.tick()` 在 `send` 之后进入 `confirm`，从第一次读到 `!promptConfirmed` 起计时，20 秒后按 C# 原语义暂停：`当前问题连续 20 秒无法确认，已暂停，不会自动重发`（`android/core/src/main/kotlin/ai/arena/companion/automation/RetryController.kt` 第 336-342 行、第 248-254 行）。这 20 秒里模型已经把「1+1=」答完了，所以用户看到的是「LLM 回复之后才报错」。
3. 同一组选择器还决定 `conversation` / `response` / `completionConfirmed` / `generationStamp` / `messageIdentity`，它们在真机上同样恒为空。**即使只把 `promptConfirmed` 修好，`observe` 阶段也拿不到回答、走不到 `model` / `rename` / `collect`。** 必须整体按真实 DOM 重映射。
4. 桌面端参考 `reference/Arena模型助手-源码-fyb-0.1.0/assets/PageBridge.js` 从来不依赖这些属性成立：它以 `main [role="log"]` 为对话区，角色属性只是「优先项」，缺失时回退到「日志文本以完整提示词开头」。安卓移植时把回退分支删掉了，而 `android/README.md` 与进度文档第一批 §5 早已写明「`PageBridge.js` 的选择器全是桌面端推测，S0 完成前不应视为可用实现」——第二十八批的 S0 只校准了输入框 / 发送 / 侧栏 / 条款弹窗，**没有校准对话区读取**，第三十批又被 429 挡在回复之前，于是这一段一直没被真机覆盖。
5. 继续方案分五批：B31 对话区选择器重映射 + jsdom 回归（P0）→ B32 `ModelRename.js` 同类修复（P0）→ B33 探针 model 阶段真机验证（P1）→ B34 阶段机已具备但 `MainActivity` 未接线的能力（模型取舍、网站归档、轮次上限）（P1）→ B35 附件上传与工程卫生（P2）。详见 §5。

## 1. 现象与时间线

用户报告：安装包在 LLM 回复后显示「当前问题连续 20 秒无法确认」。按代码推演的时间线：

| 时刻 | 阶段机 | 页面 | UI 文案 |
|---|---|---|---|
| t0 | `send`：`move("confirm")` 后 `page.act("send")`（`RetryController.kt:403-419`） | 发送按钮被 pointer 事件序列触发（第三十批修复） | 已提交第 1 次，等待网页确认… |
| t0+1s | `confirm`：`needsPrompt=true`，快照 `promptConfirmed=false` → `waitForReadableContent()` 记下 `contentMissingSince` 并 `return`（`RetryController.kt:336-342`, `248-254`） | URL 迁移到 `/agent/<uuid>`，用户消息与回答开始渲染 | 不变 |
| t0+2s ~ t0+10s | 每秒重复上一行；`snapshotConsistent` 为 true，`isAllowed('/agent/<uuid>')` 为 true，不会被别的分支截断 | 回答流式输出并完成 | 不变 |
| t0+21s | `secondsBetween(contentMissingSince, now) >= 20` → `pause(reason)` | 回答早已完成 | **当前问题连续 20 秒无法确认，已暂停，不会自动重发** |

如果是新账号首次发送，条款弹窗会先被 `termsPending` 分支处理并清零 `contentMissingSince`（`RetryController.kt:315-334`），此时报错时刻是「弹窗关闭后 20 秒」，表现一致。

第三十批「剩余阻塞」第 3 条（限流时文案仍优先显示「当前问题无法确认」）也是同一个原因：`promptConfirmed` 永远不为 true，任何发送之后的 blocker 都会被这 20 秒超时抢先。修好页面桥后，blocker 会按桌面端相同的顺序正常浮现，不需要调整阶段机顺序。

## 2. 代码路径核对

### 2.1 阶段机（与 C# 一致，无需改动）

`android/core/src/main/kotlin/ai/arena/companion/automation/RetryController.kt` 第 336-342 行：

```kotlin
val needsPrompt = phase == "observe" || phase == "confirm"
val readableReason = when {
    !v.main -> "页面内容连续 20 秒无法读取，已暂停；恢复后点“继续”"
    needsPrompt && !v.promptConfirmed -> "当前问题连续 20 秒无法确认，已暂停，不会自动重发"
    else -> null
}
if (waitForReadableContent(readableReason)) return
```

逐句对应 `reference/Arena模型助手-源码-fyb-0.1.0/src/RetryController.Tick.cs` 第 78-80 行。`waitForReadableContent` 的 20 秒累计、`contentMissingSince` 清零点也与 C# 相同。**阶段机不是问题所在，不要为了绕过现象去改它。**

### 2.2 安卓页面桥（问题所在）

`android/app/src/main/assets/PageBridge.js`（APK 内实际注入的版本）：

```js
conversationTurn: '[data-message-author-role], [data-testid^="conversation-turn"]',
assistantTurn: '[data-message-author-role="assistant"]',
userTurn: '[data-message-author-role="user"]',
...
var turns = all(SELECTORS.conversationTurn).filter(visible);
var assistants = all(SELECTORS.assistantTurn).filter(visible);
var users = all(SELECTORS.userTurn).filter(visible);
...
conversation: turns.length > 0,
promptConfirmed: !!prompt && users.some(function (u) { return text(u).indexOf(prompt) >= 0; }),
response: answer.length > 0,
completionConfirmed: !generating && answer.length > 0,
```

三个选择器在 arena.ai 上一个都匹配不到（证据见 §3），于是 `users` / `assistants` / `turns` 恒为空数组。

### 2.3 桌面端参考（正确语义）

`reference/Arena模型助手-源码-fyb-0.1.0/assets/PageBridge.js` 第 42-57 行：

```js
const main = [...document.querySelectorAll('main')].find(visible);
const log = main && [...main.querySelectorAll('[role="log"]')].find(visible);
const text = log?.innerText.trim() || '';
const messages=messageNodes(log), users=messages.filter(e=>roleOf(e)==='user');
const user=users.at(-1) ...
// Prefer actual message roles. Legacy DOM fallback must match a complete prompt prefix, not any substring.
const normalized=norm(text), expected=norm(prompt);
const promptConfirmed=!!expected&&(user?norm(user.innerText)===expected:
  normalized===expected||normalized.startsWith(expected+' '));
```

要点：对话区锚点是 `main [role="log"]`；角色属性缺失时用日志文本前缀回退；比较前做 `NFC + 空白折叠`；完成证据看 `Copy response` 类按钮；`failed` 只看回答范围内的 `[role="alert"]` / `data-state`。安卓版这四点全部丢失。桌面端离线演示页 `reference/Arena模型助手-源码-fyb-0.1.0/assets/demo.html` 也只有 `<div role="log">`，没有任何 `data-message-*` 属性。

## 3. arena.ai 真实 DOM 证据（2026-09-21 抓取）

抓取方式：以 Android Chrome 138 UA 请求 `https://arena.ai/agent` 与 `https://arena.ai/agent/<uuid>`，解析 HTML 里的 `_next/static/chunks/*` 以及 webpack 运行时 `s.u` 映射，共下载 62 个首屏 chunk、392 个懒加载 chunk、5 个 `/agent/[id]` 路由 chunk（约 28 MB JS）后全文检索。部署号 `dpl_8JFP6KSwW7PUGUCzKeAYEMTvMtDN`。

| 检索项 | 命中 | 结论 |
|---|---|---|
| `data-message-author-role` / `data-message-role` / `data-message-id` | 0 | 安卓桥的三组对话选择器永远不命中 |
| `Copy response` / `Regenerate` / `data-testid^="conversation-turn"` | 0 | 桌面端的备选完成证据在当前站点也不存在 |
| `role:"log","aria-live":"polite"` | 1（`ChatMessageList`，模块 61047） | 对话区容器 = `main div[role="log"]` |
| `data-agent-transcript-message` + `data-chat-message-id` | 路由 chunk `app/[locale]/(app)/(agent)/agent/[id]/page-6b064e914c7a512e.js` | **每条消息的外层包装**，user / assistant 都有 |
| `data-user-message-layout` / `data-user-message-body-row` / `data-user-message-action` | 模块 77628 | **仅用户消息**有此包装，是区分角色的唯一稳定属性 |
| `MessageBubble`（模块 39852） | 纯 `div`，只有 className | user：`bg-surface-raised rounded-lg w-fit max-w-[min(70%,768px)] ml-auto`；assistant：`bg-surface-primary rounded-xl border w-full`。**不输出任何 role/data 属性** |
| `"aria-label":"Stop generating"` | 路由 chunk，`"streaming"===x||"submitted"===x` 时替换发送按钮 | 生成中判定 = `main button[aria-label="Stop generating"]` 可见 |
| `"aria-label":"Send message"` | 首页与路由 chunk | 现有选择器 `button[aria-label*="Send" i]` 可用 |
| `"aria-label":"Copy"` | 助手消息动作条（非流式时渲染） | 完成证据 = 最后一条助手消息内出现 `button[aria-label="Copy"]` |
| `role:"alert"` | 错误横幅（含 `Retry` / `Refresh` 按钮）、`Plan unavailable`、文件未保存等琥珀色提示 | `failed` 必须限定在回答范围内，不能取全局 |
| `router.push(\`/agent/${id}\`)` | 路由 chunk（`type:"agentic"`） | agent 模式新会话落在 `/agent/<uuid>`，`ConversationIdentity.route()` 接受；`/c/<uuid>` 只用于非 agent 会话（第二十八批看到 `/c/` 是因为当时 `newChat` 选择器包含 `a[href="/"]`） |
| 侧栏 `"aria-label":"More options"` → 菜单项 `Rename` / `Archive` / `Unarchive`；重命名对话框提交按钮文案 `Rename`、`Cancel` | 侧栏 chunk 与菜单 chunk | 与桌面端 `ModelRename.js` 的 `label(e)==='More options'` / `'Rename'` 一致；安卓 `ModelRename.js` 用的 `aria-label*="menu"` 匹配不到（见 §5 B32） |

补充：消息渲染代码（路由 chunk）为

```js
<div data-agent-transcript-message data-chat-message-id={e.id}>
  {"user"===e.role
     ? <il.N attachments=... body={<MessageBubble variant="user" ...>}/>   // il.N = data-user-message-layout
     : <ChatMessage role={e.role} headerIcon=... headerLabel=...>          // → MessageBubble variant="assistant"
         <iU message=.../>                                                // 正文 parts
         {"assistant"===e.role && !streaming && <iD .../>}                // 动作条（含 aria-label="Copy"）
       </ChatMessage>}
  <ik isLast dagError liveError blockedError onRetry/>                   // 错误时渲染 div[role="alert"] + Retry
</div>
```

## 4. 修复方案（B31：对话区重映射）

原则：保持 §4「单次快照」语义不变；只改 `PageBridge.js` 的 `SELECTORS` 与 `snapshot()`；对齐桌面端 `view()` 的判定语义而不是发明新语义；所有判定限定在 `main` / `[role="log"]` 内。

### 4.1 选择器映射表

| 字段 | 现状（错误） | 改为 |
|---|---|---|
| 对话区 | 全局 `[data-message-author-role]` | `log = main [role="log"]`（取可见的那个） |
| 消息列表 | `conversationTurn` | `messages = log.querySelectorAll('[data-agent-transcript-message]')` 过滤可见 |
| 用户消息 | `[data-message-author-role="user"]` | `messages` 中含 `[data-user-message-layout]` 的项；`user = 最后一条` |
| 助手消息 | `[data-message-author-role="assistant"]` | `user` 之后、不含 `[data-user-message-layout]` 的最后一条 |
| `conversation` | `turns.length > 0` | `!!log && norm(log.innerText) !== ''`（与桌面端一致） |
| `promptConfirmed` | `text(u).indexOf(prompt) >= 0` | `user ? norm(text(user)) === expected \|\| norm(text(user)).startsWith(expected + ' ') : (logText === expected \|\| logText.startsWith(expected + ' '))`，其中 `norm = NFC + \s+→空格 + trim` |
| `generating` | `button[aria-label*="Stop" i]`（全局） | `main button[aria-label="Stop generating"]` 可见 |
| `activity` | `= generating` | `generating \|\| scope 内可见的 [aria-busy="true"],[role="progressbar"],.animate-spin`（排除 `pre,code`） |
| `response` | `answer.length > 0` | 助手正文文本非空，且不以 `finding/waiting/initializ/starting` 开头（桌面端规则） |
| `completionConfirmed` | `!generating && answer.length > 0` | `!!answer && promptConfirmed && !activity && answer 内存在 button[aria-label="Copy"]` |
| `failed` | 全局任意 `[role="alert"]` | `scope`（answer 或 log）内可见 `[role="alert"]` 且文案匹配 `/stopped\|error\|something went wrong\|failed\|rejected\|出错\|失败\|已停止/i`，排除 `pre,code` |
| `thinking` | 对空字符串做正则 | `scope` 内文本匹配 `/^Thinking\b\|思考/i` 的按钮或 `AgentThinkingIndicator` 文案 |
| `generationStamp` | `assistants.length + '#' + 首段指纹` | `users.length + ':' + user 的 data-chat-message-id + ':' + answer 的 data-chat-message-id + ':' + responseSignature`（可再加桌面端的 `__arenaGenerationTracker` 提交计数） |
| `messageIdentity` | 最后一 turn 指纹 | `user.getAttribute('data-chat-message-id')` |
| `sendReady` | 现状可用 | 追加 `aria-disabled !== 'true'` |
| `editor` / `draft` / `newLinks` / `canExpand` / `termsPending` / `blocker` | 第二十八至三十批已校准 | 不动；`blocker` 的限流判定建议改为只看 `[role="alert"]` / `[role="dialog"]` 文本而非整个 `body` |

### 4.2 `snapshot()` 草案

```js
var SELECTORS = {
  main: 'main',
  log: '[role="log"]',
  message: '[data-agent-transcript-message]',
  userLayout: '[data-user-message-layout]',
  editor: 'textarea[name="message"], textarea[data-testid="prompt-textarea"], [contenteditable="true"], textarea',
  sendButton: 'button[aria-label="Send message"]',
  stopButton: 'button[aria-label="Stop generating"]',
  copyButton: 'button[aria-label="Copy"]',
  newChat: 'a[href="/agent"]',
  alert: '[role="alert"]',
  busy: '[aria-busy="true"],[role="progressbar"],.animate-spin',
};

function norm(s) { s = s || ''; try { s = s.normalize('NFC'); } catch (e) {} return s.replace(/\s+/g, ' ').trim(); }
function within(root, sel) { return root ? Array.prototype.slice.call(root.querySelectorAll(sel)) : []; }
function notInCode(el) { return !el.closest('pre,code'); }

function snapshot(prompt) {
  var before = location.href;
  var mainEl = all(SELECTORS.main).filter(visible)[0] || null;
  var log = within(mainEl, SELECTORS.log).filter(visible)[0] || null;
  var logText = norm(text(log));
  var messages = within(log, SELECTORS.message).filter(visible);
  var users = messages.filter(function (m) { return !!m.querySelector(SELECTORS.userLayout); });
  var user = users.length ? users[users.length - 1] : null;
  var answer = null;
  for (var i = messages.length - 1; i > messages.indexOf(user); i--) {
    if (!messages[i].querySelector(SELECTORS.userLayout)) { answer = messages[i]; break; }
  }
  var expected = norm(prompt);
  var userText = norm(text(user));
  var promptConfirmed = !!expected && (user
    ? (userText === expected || userText.indexOf(expected + ' ') === 0)
    : (logText === expected || logText.indexOf(expected + ' ') === 0));
  var answerBody = answer ? answer.cloneNode(true) : null;
  if (answerBody) within(answerBody, 'button,[role="status"],[role="progressbar"],time').forEach(function (n) { n.remove(); });
  var response = answerBody ? norm(text(answerBody)) : '';
  var scope = answer || log;
  var stopBtn = within(mainEl, SELECTORS.stopButton).filter(visible)[0] || null;
  var generating = !!stopBtn;
  var activity = generating || within(scope, SELECTORS.busy).filter(visible).some(notInCode);
  var failed = within(scope, SELECTORS.alert).filter(visible).filter(notInCode).some(function (a) {
    return /stopped|error|something went wrong|failed|rejected|出错|失败|已停止/i.test(text(a));
  });
  var completionConfirmed = !!answer && promptConfirmed && !activity &&
    within(answer, SELECTORS.copyButton).filter(visible).length > 0;
  var responseSignature = generating ? '' : fingerprint(response);
  var sendEl = within(mainEl, SELECTORS.sendButton).filter(visible)[0] || null;
  var after = location.href;
  return {
    url: after, browserSourceBefore: before, browserSourceAfter: after, snapshotConsistent: before === after,
    main: !!mainEl,
    conversation: logText.length > 0,
    promptConfirmed: promptConfirmed,
    thinking: !!scope && /\bThinking\b|思考/i.test(text(scope)),
    generating: generating, activity: activity, failed: failed,
    response: response.length > 0 && !/^(finding|waiting|initializ|starting)/i.test(response),
    generationStamp: users.length + ':' + (user ? user.getAttribute('data-chat-message-id') || '' : '') + ':' +
      (answer ? answer.getAttribute('data-chat-message-id') || '' : '') + ':' + responseSignature,
    progressSignature: fingerprint(norm(text(scope))),
    responseSignature: responseSignature,
    completionConfirmed: completionConfirmed,
    messageIdentity: user ? user.getAttribute('data-chat-message-id') || '' : '',
    draft: draft(), editor: visible(one(SELECTORS.editor)),
    blocker: blockerOf(), termsPending: termsDialogVisible(),
    sendReady: !!sendEl && !sendEl.disabled && sendEl.getAttribute('aria-disabled') !== 'true',
    newLinks: newChatLinks().length, canExpand: !!sidebarOpener(),
    attachmentNames: [], conversationAttachments: [],
  };
}
```

`act()`、`click()`、`fill()`、`newChatLinks()`、`sidebarOpener()`、`termsButton()` 沿用现有实现（已在真机校准）。`android/core/src/main/resources/web/PageBridge.js` 是一份已经漂移的旧副本（215 行 vs app 256 行），修复时应删除或改成构建期从单一来源复制，避免再次分叉。

### 4.3 验证步骤

1. **离线回归（新增，必须）**：仿照 `reference/Arena模型助手-源码-fyb-0.1.0/tests/rename-bridge.test.cjs` 建 `android/app/src/test/js/page-bridge.test.cjs`（node + jsdom），fixture 按 §3 的真实结构手写：`main > div[role=log] > div[data-agent-transcript-message][data-chat-message-id] > (div[data-user-message-layout] | assistant bubble + button[aria-label=Copy])`，覆盖：空白新对话、已发送未回答（有 `Stop generating`）、回答完成（有 `Copy`）、回答出错（`role=alert` + `Retry`）、多轮对话取最后一组、含换行/全角空格的提示词。桌面端就是因为有这三个 `.test.cjs` 才没有出这类问题。
2. **真机 CDP 校验**（沿用第二十八批通道）：手工发一条「1+1=」后执行 `JSON.stringify(__ARENA_PAGE_BRIDGE__.snapshot("1+1="))`，期望 `promptConfirmed=true`、`conversation=true`、流式期间 `generating=true`，结束后 `response=true, completionConfirmed=true, responseSignature!=""`。
3. **阶段机 E2E**：`:core:test` 全绿 → `:app:assembleDebug` → 真机「开始」，期望 UI 依次出现 `第 1 轮 · confirm` → `observe`（第 N 次：等待回答…）→ `回答已完成，正在读取本轮的模型名…` → `model` → `rename` → `collect`。若卡在 `model`，进入 B33。
4. 证据落到 `docs/evidence/android-e2e-<date>-*.{png,xml,json}`，记录到进度文档新批次。

## 5. 对照两套参考的未完成项

统计口径：`android/` 相对 C# 桌面端（产品蓝本）与 ArenCard（仅贡献单账号注册、额度、429 门闸，见 `docs/mcp-android-implementation-plan.md` §1/§8）。「已移植」指代码存在且 `:core` 单测通过；「真机验证」以进度文档第二十八至三十批为准。

| # | 能力 | 参考来源 | 安卓现状 | 缺口 / 风险 | 优先级 |
|---|---|---|---|---|---|
| 1 | 对话区读取：`promptConfirmed` / `conversation` / `response` / `completionConfirmed` / `generationStamp` / `messageIdentity` | C# `assets/PageBridge.js` `view()` | `app/src/main/assets/PageBridge.js` 用 ChatGPT 风格选择器 | **本文根因**；阶段机无法越过 `confirm` / `observe` | P0 |
| 2 | 回答失败 / 活动判定 | 同上（`failed` 限定回答范围、`activity` 看 busy 指示） | `failed` 取全局 `[role="alert"]`；`activity = generating` | 任意提示横幅都会让本轮「作废」；思考中无 Stop 按钮的瞬间会被误判为停止 | P0（随 #1） |
| 3 | JS 桥回归测试 | `reference/.../tests/{archive,rename}-bridge.test.cjs`、`auth-sidebar.test.cjs` | 无 | 选择器错误只能靠真机发现；本次问题即由此漏出 | P0（随 #1） |
| 4 | 会话重命名 `ModelRename.js` | C# `assets/ModelRename.js` + `RenamePage.cs` | 选择器 `button[aria-label*="menu"]`（真实是 `More options`）；用 `links[0]` 而非当前会话链接；`el.click()`（第三十批已证明移动页需要 pointer 序列）；对话框不校验 `Rename chat` 标题 | 真机上打不开菜单；多会话时可能改错会话 | P0 |
| 5 | 模型探针 `arena-model-probe.inject.js` 在 `model` 阶段 | `ProbeInjection.cs` / `ProbeReader.cs` | 已移植；真机只验证过 `version=2` 注入成功 | 站点用 fetch + `ReadableStream` 拉 `realtime/v1/sessions/<sid>/out`，探针的 fetch 分流未在真机走过；失败时按 150 秒超时收为「未识别」 | P1 |
| 6 | 模型取舍（保留策略）接线 | `ModelRetention.cs` / `MainForm.ModelRetention.cs` | `TaskSettings.excludedModels` 与设置页存在；`MainActivity.startAutomation()` 未给 `RetryController.retentionPolicy` 赋值 | 设置无效，所有模型一律保留 | P1 |
| 7 | 未保留模型「仅网站归档」 | `WebPage.ModelArchive.cs` + `assets/ModelArchive.js` | 无 `ModelArchive.js`，`websiteArchive` 未注入 | 一旦 #6 接通，排除模型会在 `archiveExcludedModel` 抛「网站归档不可用」并暂停 | P1（与 #6 同批） |
| 8 | 轮次上限 / 任务参数 | `TaskSettings.cs` / `MainForm.TaskSettings.cs` | `c.start(settings.prompt, 0)` 写死不限次；`maximumNoProgressSeconds` / `modelWaitSeconds` 无入口 | 无法限定轮数 | P2 |
| 9 | 附件随消息上传 | `AttachmentUpload.cs` / `PageBridge.js attachmentsReady` / `prepare` 阶段 | 设置页可选附件、`TaskSettings.attachments` 落盘；`RequestPreparation` 未实现，`PageBridge` 的 `attachmentNames` 恒空，controller 未注入 `preparation` | 附件不会被发送，也不会阻止无附件发送 | P2 |
| 10 | 鹈鹕测试（向当前会话发固定提示词） | `MainForm.Pelican.cs` / `PelicanSend.js` | 无 | 手工辅助功能 | P3 |
| 11 | 离线演示页 | `assets/demo.html`（真实 `role=log` 结构） | `DemoArenaPage.kt`（Kotlin 假页，不经过 JS 桥） | 无法离线验证 JS 桥；由 #3 的 jsdom fixture 覆盖 | P1（并入 #3） |
| 12 | S0 剩余探测 | 方案 §9 | #1 WebView `MULTI_PROFILE` / `PROXY_OVERRIDE` 真机行为、#2 息屏 30 分钟存活、#5 注册直连是否 403 均未做 | 多实例隔离与后台存活尚无结论 | P1 |
| 13 | ArenCard：单账号注册（六步协议） | `arena_core.py` | `RegisterClient.kt` + `RegisterActivity` 已移植并单测；真机实际走的是 `AuthFlow` + `AuthBridge.js` 页面路线（第三十批已跑通） | OkHttp 直连路径未在真机验证（S0 #5） | P2 |
| 14 | ArenCard：额度查询 | `GET /api/billing/balance` | `AccountBalanceClient.kt` 已移植 | 未核对是否接入归档 `creditsRemaining` / UI | P3 |
| 15 | ArenCard：429 门闸 | `arena_draw.py` 阶梯 15/30/60/90 | `AccountRiskController.kt` + `RateLimitTracker.kt` | 已覆盖；换 IP / 批量注册 / 验证码绕过按方案 §8 不做 | — |
| 16 | ArenCard：账号管理（每号抽到过哪些模型） | 账号管理页签 | `ArchiveEntry.modelHistory` + `ConversationDetailActivity` | 未在真机核对 | P3 |
| 17 | 工程卫生 | — | `android/` 整个目录在 git 中为未跟踪（`?? ./`）；仓库根目录存在名为 `nul` 的文件，导致 ripgrep / `search_files` 在根目录报 `函数不正确`；`core/resources/web/PageBridge.js` 与 `app/assets/PageBridge.js` 分叉 | 丢失风险；工具链故障 | P2 |

明确不在范围（方案 §8 已决策，不重开）：指纹伪装、Clash 节点运行时、`token_server.py`、批量注册、每账号换 IP、验证码绕过。ArenCard 面向 Sage 桌面端的协议移植（P0-P5）另见 `docs/mcp-arena-p0-verification.md` 至 `docs/mcp-arena-p5-ui.md`，与安卓端无关。

## 6. 继续方案

| 批次 | 内容 | 验收 |
|---|---|---|
| B31（P0） | 按 §4 重写 `PageBridge.js` 的 `SELECTORS` / `snapshot()`；删除或单源化 `core/resources/web/PageBridge.js`；新增 node + jsdom 的 `page-bridge.test.cjs`（fixture 取自 §3） | jsdom 用例全绿；真机 CDP `snapshot("1+1=")` 各字段符合 §4.3 第 2 条；真机「开始」能从 `confirm` 走到 `model` |
| B32（P0） | `ModelRename.js`：菜单按钮改为当前会话链接同级的 `button[aria-label="More options"]`；会话链接按 `ConversationIdentity` 规范化后与当前 URL 精确匹配；菜单项 / 对话框 / 提交按钮按 `label === 'Rename'`、`/^Rename chat\b/` 判定；点击改用 `PageBridge.click()` 的 pointer 序列；补 `rename-bridge.test.cjs` | 真机一轮内完成重命名并在侧栏可见新标题；`ConversationRenamer` 的「标题已存在则不重复改」路径复验 |
| B33（P1） | 探针 `model` 阶段真机验证：抓 `trigger-token` → `realtime/.../out` → `api.trigger.dev/.../events` 的分流是否产出 `runId` / `name`；不行则改为在 fetch 分流中 `response.clone().body` 逐帧解析；同时核实助手消息头部 `headerLabel` 是否为模型名，仅作旁证不作归属依据 | 真机连续 3 轮模型名非「未识别」；`RetryControllerTest` 增加「探针晚于回答完成到达」用例 |
| B34（P1） | 接线缺口：`retentionPolicy` 由 `TaskSettings.excludedModels` 构造；移植 `ModelArchive.js` + `websiteArchive`（对齐 `WebPage.ModelArchive.cs` 的「生成状态未变才点归档」前置校验）；轮次上限 / 无进展 / 模型等待参数进设置页 | 排除某模型后一轮内完成「仅网站归档、不存本地」；限次到达后 `done` 文案正确 |
| B35（P2） | `RequestPreparation`（附件）+ `PageBridge.attachmentsReady`；`android/` 纳入 git；删除根目录 `nul`；进度文档补第三十一至三十五批记录与证据 | 附件出现在网页「Remove <name>」列表后才发送；`git status` 干净；`search_files` 根目录可用 |

S0 剩余项（#12）建议穿插在 B33/B34 的真机时段完成，不单独排期。

## 7. 证据与命令备忘

- 静态证据（本机不需要设备即可复现）：`curl -A "<Android Chrome UA>" https://arena.ai/agent` 与 `/agent/<uuid>`，从 HTML 收集 `_next/static/chunks/*.js`，再从 webpack 运行时的 `s.u=e=>...` 映射补齐懒加载 chunk，对 `data-message-author-role`、`role:"log"`、`Stop generating`、`aria-label":"Copy"`、`data-agent-transcript-message`、`data-user-message-layout`、`More options` 做全文检索。
- 动态证据（需设备）：`adb forward tcp:9222 localabstract:webview_devtools_remote_<pid>`，在页面上下文执行 `__ARENA_PAGE_BRIDGE__.snapshot("1+1=")`，并 `document.querySelectorAll('[data-agent-transcript-message]').length` 与 `document.querySelector('main [role="log"]')` 交叉验证。
- 构建：`cd android && JAVA_HOME=/d/programmingSoftware/java/jdk17 ./gradlew :core:test :app:assembleDebug`；安装：`adb install -r -t app/build/outputs/apk/debug/app-debug.apk`。
- 本次分析未修改任何产品代码；`android/` 内文件与 2026-09-21 00:19 的 APK 一致。

## 8. 实施记录（2026-09-21，第三十一批）

- B31 与 B32 已按 §4 / §6 实施，详见 `docs/mcp-android-implementation-progress.md` 第三十一批：
  `android/app/src/main/assets/PageBridge.js`（version 3）、`android/app/src/main/assets/ModelRename.js`（version 3）、
  `android/core/src/main/resources/web/PageBridge.js` 已删除，新增 `android/app/src/test/js/` 下的 jsdom 回归
  （`page-bridge.test.cjs` 29 例、`rename-bridge.test.cjs` 33 例）并挂到 `:app:preBuild`（任务 `bridgeJsTest`）。
- 与 §4.2 草案的差异：`promptConfirmed` 在用户消息内按「任一节点文本等于提示词或以提示词 + 空格开头」判定
  （动作条 sr-only 文本可能排在气泡前面）；`blocker` 的限流 / 验证判定按 §4.1 建议缩到 alert / status / dialog / toast
  与 main 中对话区以外的文本；`progressSignature` 覆盖用户消息之后的全部消息；新增 `act('stop')`。
- 验证：`:core:test` 165 通过；`:app:bridgeJsTest` 29 + 33 通过；`:app:assembleDebug` 产出 2026-09-21 19:57 的 APK，
  内含新脚本。**真机 CDP 复核（§4.3 第 2、3 条）与阶段机 E2E 尚未执行**，清单见进度文档第三十一批「验收状态」。
- §6 中 B33-B35 未动；第三十批剩余阻塞第 3 条（限流早于提示词出现时先报「无法确认」）与 C# 顺序一致，保持不变。

## 9. 实施记录（2026-09-21，第三十二批）

- B34 已实施：`retentionPolicy` 在 `MainActivity.startAutomation()` 接线（目录 = 本地归档模型名 ∪ `model-observed-names.json`），
  `ModelArchive.js` 逐句移植并由 `WebsiteArchiver.kt` 驱动接入 `websiteArchive`，轮次上限 / 无进展上限 / 模型名等待进设置页。
  证据：`archive-bridge.test.cjs` 29 例、`:core:test` 179 通过、`:app:assembleDebug` 通过（APK 2026-09-21 20:21）。**真机未验证**。
- B35 部分完成：`android/` 与 `docs/mcp-android-*.md`、`docs/evidence/` 收进 git（`android/.gitignore` 用 `!**/data/` 放回被根规则误忽略的源码目录），
  根 `nul` 删除，`WebViewArenaPage.parse()` 解析附件字段；附件上传本身仍未做。详见进度文档第三十二批。
- B33 仍需设备。
