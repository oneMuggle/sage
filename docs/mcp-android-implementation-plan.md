# Sage Arena 安卓版实现方案（独立 App / 高保真复现）

日期：2026-09-20（2026-09-20 第二版，替换首版）
范围：独立安卓 App，不连接 PC 或其他应用，最大程度复现 `reference/` 参考产品特征。
基线：main / 673548b9。
性质：静态分析 + 平台 API 核对形成的方案，**未在真机/模拟器验证**。所有"可行"均为待验证假设，落地前须过第 9 节门槛。

首版差异：首版把 ArenCard 的纯协议链路当主线、瘦客户端当 Phase 0。按"独立 App + 最大保真"重新定位后，**主线换成 C# 模型助手的 UI 自动化链路**，瘦客户端整条删除。这个调整同时消掉了首版最大的技术风险，见 §2。

## 1. 两套参考是两种产品，必须先选血统

| | C# Arena模型助手 | ArenCard |
|---|---|---|
| 形态 | 有头浏览器 UI 自动化 | 纯 HTTP 协议 |
| 核心 | `RetryController` 阶段机驱动真实页面 | 6 步注册 + 抽卡协议链 |
| 模型识别 | 页面内探针 `__MODEL_PROBE__` | 解析 trigger.dev run 事件 |
| 产出 | 模型归档、会话导出、多实例 | `accounts_*.txt` |
| reCAPTCHA | 页面自己出，不需要合成 | 需 `token_server.py` 常驻 WebView 造 token |
| 规模 | 7459 行 / 44 文件 | 5834 行 / 6 文件 |

"最大程度复现参考代码特点"指向 **C# 模型助手**：多实例、模型归档、会话管理、暂停/继续、指纹与代理设置这些用户可感知的产品特征全在它那边；ArenCard 只有一个批量注册命令行形态，且其产品定位落在 §8 排除项内。

**决策：安卓版以 C# 模型助手为蓝本，ArenCard 仅贡献"单账号注册"这一条能力，且从 sage 已收敛的 `backend/services/arena_protocol.py` 取行为，不从 ArenCard 原始代码取。**

## 2. 选 C# 血统直接消掉首版的头号风险

首版 S0 列了四项探测，其中第 3 项（Android WebView 能否产出被 arena 接受的 reCAPTCHA V3 token）是生死线——拿不到则抽卡链路整体不成立。

走 C# 路线后这个问题**不存在**：

- 抽卡 = 在真实已登录页面上点 New Chat、填提示词、发送。token 由页面自己的 `grecaptcha` 在正常用户流里生成，App 从不接触。`token_server.py` 整个模块不需要移植。
- 注册链路按 `reference/ArenCard/README.md` 第 32 行的实测记录，sign-up 端点 `recaptchaToken` 传空串即可，服务端不校验。

首版的 §4.4（TLS 指纹 / curl_cffi 对等物）同样消解：自动化路径所有请求都是页面自己发的，天生真实 Chrome 指纹 + 真实 Cookie。只有注册链路需要 App 自己发 HTTP，而那条链路本就不敏感。

代价是自动化路径**必须前台可见**（§7），这与移动端形态本来就吻合。

## 3. 必须逐行复现的参考行为

以下不是"参考实现"而是**规格**。每条都是参考作者踩出来的，Kotlin 侧不得简化或"顺手优化"。

### 3.1 阶段机（`RetryController.Tick.cs`，318 行 — 最高保真优先级）

```
inspect → new → waitNew → fill → send → confirm → observe → model → rename → [collect] → roundPause → new …
```

必须原样带过的细节：

- **epoch 守卫**：每次 await 后校验 `epoch != currentEpoch` 则丢弃本次结果。防止暂停/恢复期间的陈旧异步结果污染状态。安卓协程更容易出这个问题，不能省。
- **`snapshotConsistent` 闸门**：原生地址与 DOM 不一致时直接 return 等下一次稳定快照，不做任何判断。
- **读取失败指数退避**：`min(20, 2^min(4, failures))` 秒；连续失败满 120 秒才暂停。注释写明流式渲染时主线程繁忙导致读超时是正常现象——安卓 WebView 上只会更频繁。
- **条款弹窗（termsPending）的先后顺序**：必须在 `main`/`promptConfirmed` 可见性判断**之前**处理，且只尝试一次（`termsAttempted`），20 秒未关闭则暂停且明确"不会重复点击同意或重发消息"。
- **各阶段超时**：非 observe/model 阶段 120 秒 → 暂停；inspect/waitNew/new 各 20 秒 → 暂停。
- **New Chat 入口唯一性**：`newLinks != 1` 时，>1 直接暂停（避免误操作），==0 先尝试展开侧栏一次（`sidebarExpansionAttempted`），再超时暂停。
- **人机验证**：`blocker == "需要人机验证"` 走 `PauseForVerification`，验证通过后 `epoch++` 自动续跑，**不重发**。
- **所有失败都是"暂停 + 可读原因 + 等人工"**，没有一处自动重试有副作用的操作。这是整个参考产品最重要的安全气质。

### 3.2 会话身份（`ConversationIdentity.cs`）

URL 规范化是幂等性的地基，必须 1:1：

- 只认 `https` + 443 端口 + 空 UserInfo + host ∈ {`arena.ai`, `arena-demo.local`}。
- 路径必须匹配 `^/agent/[0-9a-fA-F]{8}-...-[0-9a-fA-F]{12}$`（严格 UUID），并 `ToLowerInvariant()`。
- `Same(a,b)` 比较规范化结果而非原始字符串；`Created()` 只认 arena.ai 真实会话；`IsTransition()` 判断 `/agent` → `/agent/<uuid>`。
- `arena-demo.local` 分支保留——它是参考的离线演示/测试通道，安卓上同样需要一个不打真网的 E2E 路径。

### 3.3 手动收集的双读稳定性校验（`ManualCollection.cs`）

37 行，但是整个归档正确性的核心。流程不可简化：

```
read → Validate → probe(before) → delay(500ms) → probe(after) → read → Validate
→ 比对 url / generationStamp / responseSignature / api / runId / name 全部一致
→ 任一不一致：抛「读取期间发生变化，未写入」
```

外加 `Active()` 在每一步之间复查收集条件，条件改变立即 `OperationCanceledException`。

`Validate` 的拒绝条件全列：非一致快照、非具体会话 URL、非 main、非 conversation、generating、activity、failed、termsPending、有 blocker、无 response、无 generationStamp、无 responseSignature。

**模型归属判定（`ManualCollectionModel`）四段式**，防止把上一轮的模型安到这一轮：
1. URL 与 `expectedUrl` 不同 → `未识别`
2. `completedGenerationStamp` 命中且有 `LastModel` → 用 `LastModel`
3. `promptConfirmed` 为假 → `未识别`
4. 探针 `api && runId && runId != baselineRunId && name` → 用 `name`，否则 `未识别`

### 3.4 模型保留策略（`ModelRetention.cs`）

- `Key()` = `Trim()` + NFC 规范化；异常返回空串。
- `Excludes()` 四个条件缺一不可：key 非空 **且** 不以 `未识别` 开头 **且** 在 catalog 里 **且** 在 exclusions 里。
- 注释明写：**exclusions 是精确模型名，永不做 family/prefix 匹配**。未知模型默认保留。
- 策略是 per-run 不可变快照（`runRetention`），运行中改设置不影响本轮。

### 3.5 限流追踪（`RateLimitTracker.cs`）

- 只对 `https://arena.ai/nextjs-api/stream/create-chat` 的 429 生效，别的 429 一律不记。
- `Retry-After` 解析两种形态：纯数字秒（钳到 `[1, int.MaxValue]`）、HTTP-date（若有 server `Date` 头则用差值，否则用绝对时间，且不早于 now+1s）。
- **跨页面槽共享的只有 deadline，不共享 response id**——注释明写"一个槽的 429 绝不能被误认为另一个槽的失败提交"。
- 持久化到 `rate-limit.json`，重启后恢复 deadline；写入走 tmp + Replace 原子替换。

### 3.6 任务设置（`TaskSettings.cs`）

- 默认提示词 **`1+1=`**（最短、只为触发一次真实模型调用）。旧默认 `hi` 在读取时自动跟随新默认；用户改过则原样保留。这个迁移逻辑要带。
- 附件：SHA256 内容寻址目录 `Attachments/<hash>/<name>`，复制后**重新哈希校验**，`Verify()` 检查存在性 + 字节数 + 哈希，附件名不得重复。
- 轮次间隔 `StepPauseSeconds=3` + 抖动 `StepPauseJitterSeconds=2`，间隔从**本轮重命名/本地保存/网站归档确认完成后**起算，首轮不等待（`使用说明.md` 第 55 行）。

### 3.7 实例管理（`InstanceManager.cs` / `InstanceContext.cs`）

- 实例名校验 `^[\p{L}\p{N}_ -]{1,40}$` 且不含首尾空格。
- 重命名前：确认自身未运行、**确认没有其它运行中实例的归档引用该路径**（`EnsureReferenceOwnersStopped`），否则报"实例 X 正在使用引用该账号的归档"。
- 重命名 = 移动目录 + 重写所有引用（task-settings.json、各实例候选图集、归档记录.json），**任一步失败全部回滚**（目录移回 + 文件内容还原）。
- 仅大小写变更走中间临时目录两步移动。
- 所有 JSON 写入走 tmp + `File.Replace` 原子替换。

### 3.8 归档存储（`ArchiveStore.cs`）

落盘结构原样保留（安卓改为 App 私有目录 + SAF 导出）：

```
<归档根>/
  记录.json      全量记录
  汇总.md        每模型一行
  <模型目录>/
    清单.md      该模型每会话一行
    <标题>.<入口>
```

- 同会话重复归档**幂等**：补写缺失入口，不重复记录。
- 模型目录名为空时用 `未识别`。
- 文件名把 `:` 换成 `-`，截断 100 字符，为空则用 entry.Id。
- 归档根可改，偏好存偏好文件；便携树内存相对路径，树外存绝对路径（`PortablePaths.Store`）。

### 3.9 探针（`ProbeInjection.cs` / `ProbeReader.cs`）

- document-start 注入（注释明写：必须在页面脚本之前接管 fetch/XHR，否则漏掉首个对话请求）。
- 只在 `location.hostname === 'arena.ai'` 运行。
- `window.__MODEL_PROBE_OPTIONS__ = {showHUD:false}`——页面内悬浮面板会挡住自动点击。
- **注入失败静默降级**，只在状态栏提示，不影响任何其他功能。
- 探针脚本从资源文件读取而非内嵌，便于单独更新。
- `runState()` 的 `modelHistory` 按当前 `runId` 反向查找归属，不用 `realModel()`（会跨轮残留）。

## 4. 安卓平台映射

| 参考机制 | 安卓对等物 | 状态 |
|---|---|---|
| WebView2 `UserDataFolder` 多实例 | `ProfileStore.getOrCreateProfile` + `WebViewCompat.setProfile` | API 存在（webkit 1.9.0，feature `MULTI_PROFILE`） |
| `AddScriptToExecuteOnDocumentCreatedAsync` | `WebViewCompat.addDocumentStartJavaScript(view, js, setOf("https://arena.ai"))` | API 存在（feature `DOCUMENT_START_SCRIPT`），document-start 语义严格对等，覆盖 iframe |
| `BrowserScript.Execute`（CDP evaluate）轮询 | `addWebMessageListener` 探针主动 push + `evaluateJavascript` 兜底 | 改进：消掉 `ProbeReader.cs` 注释里那三个坑（IIFE、runId 残留、引号转义） |
| `PageState` 读取 | 注入的 `PageBridge.js` 对等脚本，一次性返回整个快照对象 | 必须保持"单次快照"语义，不能拆成多次 evaluate（会撕裂 `snapshotConsistent`） |
| `Mutex` 判定实例运行中 | 单进程内实例注册表 + 文件锁 | 简化：安卓单进程，不需要跨进程 mutex |
| `.cmd` / `.lnk` 会话入口 | deep link `arena-companion://open?instance=X&url=Y` | 形态变化，语义保留（双击/点击用本 App 打开该会话） |
| 回收站删除 | App 内 `.trash/` 暂存目录 + 定期清理 | 安卓无系统回收站 |
| DPAPI 账号加密 | Android Keystore + EncryptedSharedPreferences / SQLCipher | 对等或更强（硬件绑定） |
| `PortablePaths` 便携树 | App 私有目录为根；导出走 SAF | 相对/绝对存储规则保留 |
| `ProxySettings` 每实例代理 | **做不到**，见下 | 受限 |

### 4.1 代理：进程级限制是唯一的硬降级

`ProxyController.setProxyOverride()` 官方措辞是 *"used by all WebViews in the app"*——进程级，不是 WebView 级。C# 版给每个实例发独立 `--proxy-server` 的模型在安卓上无法复现。

采用**串行化**：同一时刻只有一个"活动实例"，切换实例时重设 proxy override 并重建 WebView。移动端前台单任务本来就是自然形态，UI 上表达为顶部"当前实例"切换器。多进程方案（`android:process=":instN"`）不采用：与 Profile API 语义重叠，且 Cookie 跨进程同步行为不确定。

`ProxyConfig` **不支持 user:password 认证**，而参考的代理基本都带认证。因此 `reference/ArenCard/proxy_relay.py` 的本地中继从可选变为**必需**：App 内起 localhost 中继，上游带认证，向 WebView 暴露无认证的 `127.0.0.1:port`。

失败语义照抄且不得放松：**节点不可用时阻止启动，不回退直连**（`使用说明.md` 第 72 行）。

### 4.2 Clash 节点运行时：不移植

`ClashNodeRuntime.cs` 依赖拉起 Mihomo 子进程读取本机 Clash 配置。安卓上非 root 无法拉起任意二进制、也没有"本机 Clash 配置目录"这一概念。代理配置退化为：手填 HTTP/SOCKS5（经 §4.1 中继）或跟随系统。这是参考特征在安卓上的合理丢失，需在 UI 明示。

## 5. 模块结构

```
app/
  ui/                      Compose
    InstancePicker         对 InstancePicker.cs（启动选实例）
    MainScreen             WebView + 侧栏（探针信息/阶段/日志）
    GalleryScreen          对 GalleryWindow.cs（模型归档 + 多选删除）
    ConversationScreen     对 SavedConversationWindow.cs
    SettingsScreen         对 EnvironmentSettingsDialog / TaskSettings
  automation/
    RetryController.kt     ★ 对 RetryController*.cs 四文件（阶段机）
    PageBridge.kt          对 WebPage.cs + PageBridge.js（Read/Act）
    PageState.kt           对 PageState（单次快照 DTO）
    ManualCollection.kt    对 ManualCollection.cs（双读校验）
    RateLimitTracker.kt    对 RateLimitTracker.cs
    ModelRetention.kt      对 ModelRetention.cs
  webview/
    ProfileManager.kt      ProfileStore 封装，实例↔Profile
    ProbeBridge.kt         document-start 注入 + WebMessageListener
  data/
    Room: instances / accounts / archive / conversations / attachments / job_state
    KeystoreVault.kt       对 AccountStore.cs（+ Android Keystore）
    ArchiveStore.kt        对 ArchiveStore.cs（含 汇总.md / 清单.md 生成）
    PathPolicy.kt          对 PortablePaths.cs
  register/
    RegisterClient.kt      对 backend/services/arena_protocol.py（单账号）
    MailProvider.kt        临时邮箱 provider 接口
  net/
    ProxyRelay.kt          对 proxy_relay.py（本地认证中继）
  service/
    AutomationService.kt   前台服务 + 通知控制
  identity/
    ConversationIdentity.kt  对 ConversationIdentity.cs
```

`RetryController.kt` 是全项目最高保真要求的文件，建议逐段对照 C# 源码写，并在每个方法上标 `// ref: RetryController.Tick.cs:L88-L120`。

## 6. 数据模型

Room 取代参考的 JSON 文件树，但**保留其全部语义**：

| 表 | 对应参考文件 | 关键约束 |
|---|---|---|
| `instances` | 实例目录 | name 唯一，校验正则同 3.7 |
| `accounts` | `账号.json` | 密码字段 Keystore 加密 |
| `archive_entries` | `记录.json` | `(instance, canonicalUrl)` 唯一 → 幂等 |
| `attachments` | `Attachments/<hash>/` | sha256 主键，引用计数 |
| `rate_limit` | `rate-limit.json` | per-instance，持久 deadline |
| `task_settings` | `task-settings.json` | per-instance |
| `job_state` | 无（参考是内存态） | **新增**，见 §7 |

`汇总.md` / `清单.md` 不进数据库，作为导出产物按需生成——它们是给人看的，参考里也是派生物。

## 7. 安卓特有约束：后台执行

这是与桌面端差异最大、也最容易翻车的地方。

- Doze、后台进程回收、`WorkManager` 最短 15 分钟周期、Android 14+ 前台服务需声明 `foregroundServiceType`、厂商 ROM（小米/华为/OPPO）额外杀后台。
- **WebView 在后台无法可靠运行**，而自动化链路完全依赖 WebView。

对策：

1. 自动化跑在**前台服务 + 常驻通知**里，通知直出阶段/轮次/暂停/停止。
2. 屏幕常亮用 `FLAG_KEEP_SCREEN_ON`（任务运行时），不申请 `WAKE_LOCK` 长持有。
3. **任务状态持久化到 `job_state` 表**。参考的 `RetryController` 是纯内存态，桌面端能忍（进程不会被随机杀），安卓上不行。这同时修掉 `docs/mcp-reference-inventory-20260919.md` R2 记录的问题（`arena_jobs.py` 无 paused 状态、重启不恢复）。
4. 崩溃恢复后**一律进入 paused 状态等人工确认**，禁止自动重放任何有副作用的操作。这与 §3.1 "所有失败都暂停等人工"的气质一致。
5. 引导用户为本 App 关闭电池优化，并在 ROM 杀后台时给出明确诊断而非静默失败。

## 8. 明确不做

| 项 | 理由 |
|---|---|
| 指纹伪装（`FingerprintProfile.cs`） | C# 版自己承认"页面脚本级模拟，不保证不可识别，可能影响图像/音频/网站兼容性"。安卓 WebView 可注入面更窄、副作用更大 |
| Clash 节点运行时 | §4.2 |
| `token_server.py` reCAPTCHA 合成 | §2，走 C# 路线后不需要 |
| Chaquopy 内嵌 Python 后端 | 首版结论保留：`pydantic==2.5.0`（pydantic-core 无 Android wheel）、`cryptography==50.0.1`（Chaquopy 索引最新 42.0.8）、hnswlib/PyMuPDF/pandas 全部卡死 |
| 批量注册、每账号换 IP、验证码绕过 | 见下 |

关于最后一项：不上架 Google Play 确实移除了商店政策约束，但 `docs/mcp-reference-inventory-20260919.md` §3 把"验证码绕过、批量滥用账号、通过更换 IP 或指纹规避平台限制"列为项目自身的既定边界，并要求"遇到挑战或限流应停止/退避"。**本方案继续沿用该边界**——它也正是 §3.1 阶段机"所有失败都暂停等人工"气质的来源，两者是一套设计。ArenCard 的批量注册形态因此不进安卓版，只保留单账号注册。若要变更这条项目级边界，应作为独立决策记录，而不是在安卓方案里顺带改掉。

## 9. S0 探测（落地前必做）

首版四项去掉 reCAPTCHA（§2 已消解），剩三项 + 两项新增：

1. **WebView 版本矩阵**：目标机型 `MULTI_PROFILE` / `DOCUMENT_START_SCRIPT` / `PROXY_OVERRIDE` 实际支持率。三者均为 webkit 1.9.0 API，老设备大概率缺。不支持 `MULTI_PROFILE` 时**禁止多实例并明确告知**，绝不退回共享 CookieManager 假装隔离。
2. **后台存活**：前台服务 + WebView 在小米/华为 ROM 息屏 30 分钟存活率。
3. **arena.ai 页面可自动化性**：New Chat 入口、编辑器、发送按钮在移动端布局/移动 UA 下是否存在且可点。**参考全部基于桌面端布局**，这是移动端最大的未知数。若移动版页面结构差异过大，`PageBridge.js` 需要一套独立选择器，工作量可能翻倍。
4. **探针在 Android WebView 的兼容性**：`arena-model-probe.inject.js` 能否正常接管 fetch/XHR 并产出 `__MODEL_PROBE__`。
5. **注册链路**：OkHttp 直连 arena.ai 是否被 Cloudflare 403（`arena_http.py` 的 D3 记录了桌面端 curl_cffi 被 403、httpx 反而通过的反直觉结果）。若 403，注册请求改走 WebView 页面上下文 fetch。

第 3 项风险最高，建议最先做，**且只需一台设备 + 一个手工账号即可验证**。

## 10. 分阶段计划

| 阶段 | 内容 | 验收 |
|---|---|---|
| S0 | 上述五项探测，独立 spike module，不进产品代码 | 产出 `docs/mcp-android-s0-probe.md`，含精确版本与失败基线 |
| A 地基 | Room schema、Keystore 保险库、Profile 管理、实例 CRUD | 合成账号跨重启可读；Keystore 解不开时报可恢复错误且**不覆盖**；多 Profile 实测 Cookie 不串；实例重命名回滚有效 |
| B 页面桥 | `PageBridge.js` + `PageState` + 探针注入 | 单次快照语义成立（`snapshotConsistent` 可信）；探针 document-start 时机可断言；注入失败静默降级 |
| C 阶段机 | `RetryController` 全量移植 + 限流 + 保留策略 | 用 `arena-demo.local` 离线通道跑通全阶段；epoch 守卫、各超时、暂停语义逐条对齐 C# |
| D 归档 | ArchiveStore + 手动收集 + 多选删除 + SAF 导出 | 双读校验拒绝不稳定写入；同会话幂等；**本地删除不触发网站删除**；未识别不沿用旧会话模型；附件引用计数安全 |
| E 前台服务 | 服务化 + 通知控制 + 状态持久化 + 崩溃恢复 | 息屏 30 分钟不丢；恢复后为 paused 且不自动重放 |
| F 注册 | 单账号注册 + 邮箱 provider | 无真实账号批量写入；失败退避不重试风暴 |
| G 发布 | minSdk 26 / target 35；arm64-v8a + x86_64；侧载 APK | 导出包不含凭据、Cookie、浏览器状态；WebView 版本下限有降级提示 |

## 11. 与桌面端的关系

**不共享代码，共享规格。** Kotlin 侧每个移植类头部标注来源，双向可追溯：

```kotlin
// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/RetryController.Tick.cs
// spec: backend/services/arena_draw_engine.py (429 ladder)
```

桌面端未决的 R1（账号库/密钥双份来源分叉）、R2（任务内存态不持久）在安卓上是全新开始，**必须一次做对**，不要等价移植错误。

---

依据文档：docs/mcp-reference-inventory-20260919.md、docs/mcp-aren-card-port-plan.md、docs/mcp-arena-p3-token-window.md、docs/mcp-arena-p4-draw-engine.md。
