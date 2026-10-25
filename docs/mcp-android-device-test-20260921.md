# 安卓端真机测试记录与未完成项清单（2026-09-21，第三十四批）

- 目的：按 `android/` 目录现状做一次真机端到端，核对 `docs/mcp-android-implementation-progress.md` 里第二十八至三十三批的
  「真机复核清单」，列出仍未完成的事项；并按用户要求把桌面端「人机验证 → 更换邮箱 → 继续任务」的行为补齐到安卓端。
- 设备：HONOR PGT-AN10（`AD3JVB3921000413`），Android 16 / SDK 36，系统 WebView 138.0.7204.179，1312×2848（CSS 375×553 @ dpr 3.5）。
- 被测 APK：`android/app/build/outputs/apk/debug/app-debug.apk`，源码 `4d021a9d`（第三十三批），21:46 安装。
- 构建链：JDK 17 `/d/programmingSoftware/java/jdk17`，`cd android && ./gradlew :core:test :app:assembleDebug`；
  设备侧观察工具为本批新增的 `scripts/verification/android-cdp.mjs`（见 §6）。
- 结论一句话：**登录、探针注入、发送前的页面状态机在真机成立；发送被 arena 的 reCAPTCHA 拒绝（`create-chat` 403），
  而安卓端此前对人机验证只会「暂停等人工」且识别不到 Google 的挑战窗口。本批已按桌面端语义接上自动换号；
  换号闭环的真机复测因设备在 23:47 后从 adb 断开尚未完成（§5 给出步骤）。**

## 1. 真机测试结果

| # | 项目 | 结果 | 依据 |
|---|---|---|---|
| T1 | 三段桥注入：PageBridge / ModelRename / ModelArchive / 探针 | 通过。PageBridge **v4**、ModelRename v3、ModelArchive v1，探针 `__MODEL_PROBE__` 已装 | CDP `eval`；注意 docs 里第三十一批清单写的是 v3，应以 v4 为准 |
| T2 | 空白 `/agent` 快照 | 通过。`main/editor/sendReady/newLinks` 等与离线 fixture 一致；差异只有 `newLinks=0`（侧栏折叠，`canExpand=true`，阶段机会先 `expand`） | CDP 快照 |
| T3 | 自动登录 → 任务启动 | 通过。实例 `111` 已登录状态下点「开始」→ `第 1 轮 · inspect → fill → send` | uiautomator 状态文本 |
| T4 | 发送 → 回答 | **失败（站点侧）**。`POST /nextjs-api/stream/create-chat` 返回 **403 `{"error":"recaptcha validation failed"}`**，5 次（含真实触摸）全部相同；随后页面出现 Google reCAPTCHA 挑战 iframe（`bframe`，「验证任务将于 2 分钟后过期」） | `docs/evidence/android-e2e-20260921-create-chat-403-network.json`、`docs/evidence/android-e2e-20260921-recaptcha-challenge.png` |
| T5 | 人机验证识别 | **部分**。站点先弹「Security Verification … Protected by reCAPTCHA」对话框时 `blocker=需要人机验证`、阶段机正确暂停；对话框关闭后只剩挑战 iframe 时 `snapshot().blocker` 为空，阶段机随即误报「验证已通过，继续当前进度」 | `docs/evidence/android-e2e-20260921-observe-paused-cdp.json`、`-window.xml`、`.png` |
| T6 | 人机验证后的处置 | **不符合要求**。安卓端只会暂停等人工；`TaskSettings.pauseOnCaptcha` 被设置页强制写成 `true`，`MainActivity` 从不读取它，也没有任何调用 `AccountReplacement` 的自动路径。桌面端在复选框「人机验证不自动换号，手动验证」未勾选时会自动「更换邮箱并开始任务」 | 桌面端 `MainForm.Control.cs` L81-L89、`MainForm.AccountReplacement.cs` L61-L70 |
| T7 | B35 附件入口 | **失败（选择器）**。arena 的 `input[type=file][multiple]` 是隐藏的 1×1 元素，`attachmentEntry()` 返回 `count:1, trigger:true` 但触发目标就是这个隐藏 input，原生触摸打不开任何东西。真实入口是按钮 `Add files and connections` → 弹层里的 `Add files` | CDP 求值 |
| T8 | B33 探针噪声 | **缺陷**。`extractModelFromJson` 的 `"name"` 回退会匹配 RSC / HTML 载荷，产生 `run-<ts>` 假记录 | CDP 读取 `__MODEL_PROBE__.history`（数组） |
| T9 | 重命名桥在空白页 | 通过（预期报错 `无法确认待重命名会话身份`） | CDP |
| T10 | 进度持久化 | **缺陷**。暂停态 force-stop 后重开为空闲「开始」，`files/` 下没有 `job-state.json`，也没有 Room 数据库目录：`AutomationService`（负责每拍 `persist`）从未被 `MainActivity` 启动 | `run-as` 目录列表 |
| T11 | 息屏 / 后台存活（S0 探测 2） | 未测。应用不在 deviceidle 白名单，`BatteryOptimizationHelper` 只做提示 | `dumpsys deviceidle` |

发送被拒的根因不在安卓代码：同一账号在该 WebView 内所有 `create-chat` 都被 reCAPTCHA v3 判为低分。桌面端对此的产品语义是
**换一个邮箱重新注册再跑**，安卓端缺的正是这条路，因此本批不再对 `111` 重试发送，而是把换号路径补齐。

## 2. 本批代码变更：人机验证 → 自动换邮箱 → 登录后自动继续

逐条对照桌面端，安卓平台差异只在「单进程内换页面」这一点上。

| 桌面端 | 安卓端（本批） |
|---|---|
| `TaskSettings.PauseOnCaptcha` 默认 `true`，复选框「人机验证不自动换号，手动验证」（`MainForm.Advanced.cs:9`） | `TaskSettings.pauseOnCaptcha` **默认 `false`**（用户要求默认自动换号），新增 `captchaPolicyVersion`：旧文件里的 `true` 是设置页强制写入的、不代表用户选择，读到版本 0 一律回到 `false`；设置页显式保存后才保留用户的选择。设置页开关改为可用，文案与桌面端一致 |
| `HandleVerificationSignal(loginFlow)`（`MainForm.Control.cs` L81-L89）：`verificationSignalHandled` 闩锁，每个验证事件只处理一次；勾选时只记日志，否则 `changeAccount.PerformClick()` | `:core` 新增 `VerificationSignal.claim(waiting)`（同语义，2 个单测）；`MainActivity.handleVerificationSignal(loginFlow)` 在登录定时器（对 `MainForm.Control.cs:L64`）和任务定时器（对 `MainForm.cs:L279`）每拍调用；`pauseOnCaptcha` 读的是设置文件当前值（桌面端读的是复选框即时状态），开着就 toast「已按设置不自动换号」并留在原地 |
| `CreateReplacement`（`MainForm.AccountReplacement.cs` L61-L70）：`loginTaskStart.Cancel()` → 停登录 → 有任务则 `Pause("正在保存任务并更换邮箱…")` → 存设置 → `AccountReplacement.Create` → `ReplacementHandoff.Launch(--register --run-after-login)` → 350 ms 后关旧窗口 | `MainActivity.replaceAccountAndContinue()`：`loginTaskStart.cancel()` → `authFlow.stop("正在交接到新账号，原登录已停止")` → `AccountReplacement.replace(instance, pauseAndPersist = {暂停 + `JobStateStore(instanceDir()).save(capture(cleanShutdown = true))`}, activate = {})` → 交还活动权 → `finish()` 本页并 `startActivity(MainActivity, EXTRA_INSTANCE=新实例, EXTRA_RUN_AFTER_LOGIN=true, EXTRA_HANDOFF_DEPTH+1)`。任何一步失败：旧实例原样保留、本页留在暂停态并弹「自动换号未完成」 |
| `--run-after-login` → `ARENA_RUN_AFTER_LOGIN=1` → `LoginTaskStart(pending)`；`ARENA_AUTO_LOGIN` 自动 `BeginAutoLogin` | `EXTRA_RUN_AFTER_LOGIN`：新页面 `onCreate` 800 ms 后自动 `toggleRun()` → `startAuthThenAutomation`（无账号时 `AuthFlow` 自动申请临时邮箱注册；`AccountReplacement` 已把旧邮箱写入 `excludedEmails`）→ 登录 `complete` 后既有 `LoginTaskStart.take` 自动 `startAutomation`。仅在 `savedInstanceState == null` 时触发，进程被杀重建走 `offerRecovery` 的暂停路径 |
| 无 | 安全阀：`MAX_AUTO_REPLACEMENTS = 3`，连续自动换号 3 次仍遇验证则退回等人工；默认实例（无独立目录）与不支持 MULTI_PROFILE 的 WebView 不自动换号，给出原因 |
| 桌面端 `PageBridge` 只看提示文本 | `PageBridge.blockerOf` / `AuthBridge.read` 新增：可见的 `iframe[src*="/recaptcha/"][src*="/bframe"]`（api2 / enterprise 同形）即 `需要人机验证`，修 T5 的误报「验证已通过」。离线回归 +1 例（可见 / 隐藏 / enterprise 三态） |
| `InstancePicker` 的「更换邮箱」 | 结果对话框新增「打开并开始任务」（对桌面端按钮「更换邮箱并开始任务」），原「仅打开」保留 |
| `onNewIntent` 切实例 | 原实现直接改 `instance` 并 `bindProfile()`，但 `WebViewCompat.setProfile` 只允许在 WebView 使用前调用，真机上会抛异常；改为 `finish()` + 以新 intent 重开页面（与交接同一条路） |

涉及文件：`android/core/.../data/TaskSettings.kt`、`android/core/.../account/VerificationSignal.kt`（新）、
`android/core/.../automation/RetryController.kt`（仅文案「请在页面中完成」）、`android/app/.../app/MainActivity.kt`、
`SettingsActivity.kt`、`InstancePickerActivity.kt`、`res/layout/activity_settings.xml`、`data/room/TaskSettingsEntity.kt`（默认值同步）、
`assets/PageBridge.js`、`assets/AuthBridge.js`、`app/src/test/js/page-bridge.test.cjs`、
`core/src/test/.../VerificationSignalTest.kt`（新）、`TaskSettingsTest.kt`（+2 例）。

验证：

```text
node run-all.cjs                              PageBridge 39 / Rename 33 / Archive 29 checks passed
JAVA_HOME=jdk17 ./gradlew :core:test          208 tests, 0 failures（第三十三批 190 → +18，含本批 4 例；其余为同日 RegisterClient 批次）
JAVA_HOME=jdk17 ./gradlew :app:assembleDebug  BUILD SUCCESSFUL；APK 23:56，6,887,337 B，assets/PageBridge.js 含 challengeFrame
get_diagnostics android/                      0 error
```

**未安装到设备**：安装属需本地确认的操作，且设备已断开（§5）。

## 3. 未完成项清单（按优先级）

### P0 — 阻断主链路

1. **换号闭环真机复测**（本批新代码）：见 §5。需要确认 (a) 新实例自动注册拿到新邮箱并登录；(b) 登录后自动进入 `第 1 轮`；
   (c) 新账号的 `create-chat` 不再 403。若新账号同样 403，说明 reCAPTCHA 判的是设备 / WebView 指纹而非账号，换号策略对安卓无效，
   需回到方案 §2 重新评估（那一节假设 token 由页面自身产生、App 不接触）。
2. **B35 附件入口**（T7）：`PageBridge.attachmentEntry` 需增加「先打开 `Add files and connections` 弹层 → 再点 `Add files`」一级，
   并把隐藏 input 排除出可触摸目标；`WebViewAttachmentPage.deliver` 的坐标换算随之复核。
3. **任务进度持久化未接线**（T10）：`AutomationService` 没有被启动，`JobStateStore.capture` 只在本批换号路径里调用一次。
   需在 `startAutomation` 时启动前台服务并注入 `controller/stateStore/instanceName`，`onDestroy`/暂停时 `persist(clean=true)`。
   注意 `offerRecovery()` 读的是 `JobStateStore(filesDir)`，而本批换号落盘用的是 `JobStateStore(instanceDir())`，两处要统一到实例目录。

### P1 — 影响判定正确性

4. **B33 探针 `extractModelFromJson` 误报**（T8）：限制 `"name"` 回退只在真实 run JSON（有 `runId`/`modelId` 之类字段）中生效。
5. **`blockerOf` 未覆盖 4xx**：`create-chat` 403 后站点无提示文本、无挑战 iframe 的窗口期内，阶段机会以为已发送而等待回答，
   直到 2 分钟 `confirm` 超时；桌面端同样如此，但安卓端该窗口更常见。可选：把 `failed` 的 `[role=alert]` 范围外再加一条「草稿仍在、无用户气泡、发送按钮恢复可用」的重发保护提示。
6. **docs 与真机不一致的小项**：第三十一批清单写 PageBridge v3（真机 v4）；`RetryController.pauseForVerification` 文案原为「请在右侧完成」（本批已改）。

### P2 — 仍只有离线验证

7. B31 对话区选择器在真实回答上的复核（`promptConfirmed / response / completionConfirmed / generationStamp`）——依赖 P0-1 拿到一次真实回答。
8. B32 重命名菜单 / 对话框、B34 网站归档在真机会话页上的复核。
9. S0 探测 2：息屏 30 分钟后台存活；应用不在电池白名单，需要实测 `BatteryOptimizationHelper` 提示后的实际存活时间。
10. Room / instrumentation 测试（`ArenaDatabaseTest`、`WebViewAttachmentPage`）未在设备上跑过。
11. DemoArenaPage 多轮 E2E、限流重试路径的附件分支单测。
12. 工作树杂项：`android/window_dump.xml`、`main_dump_txt.xml`、`screen_*.png` 为本地抓取产物（已被 `.gitignore` 忽略，可删）；
    `scripts/verification/android-cdp.mjs` 尚未提交。

## 4. 真机取证过程摘要

1. `am start` 后 ≥ 9 s 再点「开始」（早于 1–2 s 的点击会被忽略），状态依次 `正在检查页面 → 第 1 轮 · fill → send`。
2. `android-cdp.mjs watch 40 'create-chat|recaptcha'` 抓到 `reload`（Google，200）与 `create-chat`（403）；重复 5 次含一次真实触摸 Send（1170, 2674）。
3. `Security Verification` 对话框出现时 `snapshot().blocker === '需要人机验证'`，状态栏显示暂停；对话框消失、只剩 `bframe` iframe（373×150 可见）时
   `blocker === ''`，阶段机 1 s 后「验证已通过，继续当前进度」，但草稿未重发、无回答，2 分钟后 `confirm` 超时暂停。
4. force-stop 后重开：`files/` 仅 `instances/` 与 `profileInstalled`，无 `job-state.json`。

## 5. 换号闭环真机复测步骤（待设备重新连接）

前置：设备 23:47 起 `adb devices` 为空（USB 断开或授权失效），需重新插线 / 允许调试；安装新 APK 需本地确认。

1. `adb install -r android/app/build/outputs/apk/debug/app-debug.apk`（23:56 构建）。
2. 打开实例 `111` → 设置 → 确认「人机验证不自动换号，手动验证」为**关**（默认）→ 保存。
3. 回到会话页点「开始」。预期时间线：
   - 发送被拒 → 页面出现 `Security Verification` 或 `bframe` → 状态「需要人机验证 … 已暂停」；
   - 1 s 内 toast「人机验证 → 已更换邮箱：新实例「111-2」正在打开并自动登录，本页关闭」，`instances/111-2/` 生成，
     `instances/111/job-state.json` 写入（`cleanShutdown: true`）；
   - 新页面标题 `111-2`，状态「换号交接：正在为新实例自动登录 / 注册新邮箱…」→ `登录 · mail/verification/...` → `complete` → `第 1 轮 · inspect`。
4. 取证：`screencap` 三张（暂停、交接 toast、新实例第 1 轮）、`run-as ls instances/`、`cat instances/111-2/account.vault` 存在性、
   `android-cdp.mjs watch 60 'create-chat'` 看新账号是否 200。
5. 反向用例：设置里把开关打开 → 再触发验证 → 应 toast「已按设置不自动换号」，且不生成新实例。
6. 安全阀用例：连续 3 次自动换号后第 4 次应停止并提示。

## 6. 本批新增工具

`scripts/verification/android-cdp.mjs`（node ≥ 18，无依赖）：

```bash
PID=$(adb shell pidof ai.arena.companion | tr -d '\r')
adb forward --remove-all; adb forward tcp:9222 localabstract:webview_devtools_remote_$PID
node scripts/verification/android-cdp.mjs pages
node scripts/verification/android-cdp.mjs eval '__ARENA_PAGE_BRIDGE__.snapshot("1+1=")'
node scripts/verification/android-cdp.mjs eval-in 1 'location.href'          # 指定页面序号（authWebView）
node scripts/verification/android-cdp.mjs watch 40 'create-chat|recaptcha'    # 抓匹配 URL 的请求 / 响应 / 响应体
```

`MSYS_NO_PATHCONV=1` 后再传 `/sdcard/...` 参数；主机上没有 python，`/tmp` 映射到不存在的 `E:\tmp`，临时文件放 `android/build/verify/`。

## 7. 证据文件

- `docs/evidence/android-e2e-20260921-observe-paused.png` / `-cdp.json` / `-window.xml`：人机验证暂停态的截图、CDP 快照、窗口树。
- `docs/evidence/android-e2e-20260921-recaptcha-challenge.png`：只剩 Google 挑战 iframe 时的页面。
- `docs/evidence/android-e2e-20260921-create-chat-403-network.json`：`reload`（200）与 `create-chat`（403 `recaptcha validation failed`）的网络记录（已脱敏）。
