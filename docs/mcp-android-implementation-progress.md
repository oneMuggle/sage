# Sage Arena 安卓版实现进度（第一批：阶段 A/C 核心层）

日期：2026-09-20
基线：main / 673548b9
依据：docs/mcp-android-implementation-plan.md（下称"方案"）
性质：**已编译、已单测通过**的纯 JVM 代码；未在真机/模拟器验证，方案 §9 的 S0 五项探测仍未做。

## 0. 批次总览

| 批次 | 内容 | 测试 | 状态 |
|---|---|---|---|
| 第一批 | 阶段 A/C 核心：identity / PageState / retention / ratelimit / ManualCollection / RetryController / PageBridge.js | 31 | 完成 |
| 第二批 | 阶段 D 数据层：PathPolicy / AtomicFiles / ArchiveStore / TaskSettings | 50（累计） | 完成 |
| 第三批 | 阶段 E 任务持久化 JobState；阶段 A 实例管理 InstanceManager | 68（累计） | 完成 |
| 第四批 | 阶段 F 单账号注册 RegisterClient | 79（累计） | 完成 |
| 第五批 | 阶段 G 工程化：gradlew wrapper + `:app` 模块 + 探针注入 + 前台服务 | 79 + APK 构建通过 | 完成 |
| 第六批 | ConversationRenamer（rename 阶段的页面工作流） | 87（累计） | 完成 |
| 第七批 | ProxyRelay（localhost 认证中继） | 98（累计） | 完成 |
| 第八批 | 代理配置与闸门 + 账号保险库（Keystore） | 118（累计） | 完成 |
| 第九批 | ActiveInstanceGate（串行化单活动实例） | 128（累计） | 完成 |
| 第十批 | SessionLauncher（活动权 + 代理的唯一启动入口） | 128 + APK 构建通过 | 完成 |
| 第十一批 | ProfileManager（多实例登录态隔离） | 128 + APK 构建通过 | 完成 |
| 第十二批 | InstancePicker 界面 + 启动入口改为选择器 | 128 + APK 构建通过 | 完成 |
| 第十三批 | Gallery / Settings 界面 | 128 + APK 构建通过 | 完成 |
| 第十四批 | SAF 归档导出 | 128 + APK 构建通过 | 完成 |
| 第十五批 | 附件引用计数 + 附件选择 UI | 133（累计） + APK 构建通过 | 完成 |
| 第十六批 | 换号流程（AccountReplacement / LoginTaskStart） | 141（累计） + APK 构建通过 | 完成 |
| 第十七批 | 会话界面接线（RetryController / ProbeReader / 手工收集） | 141 + APK 构建通过 | 完成 |
| 第十八批 | 模型取舍界面 | 141 + APK 构建通过 | 完成 |
| 第十九批 | Room 持久化（app/data/room） | 141 + APK 构建通过 | 完成 |
| 第二十批 | 探针 document-start 加固（arena-model-probe.inject.js） | 141 + APK 构建通过 | 完成 |
| 第二十一批 | 会话重命名完整链路（ModelRename.js + WebViewRenameExecutor） | 141 + APK 构建通过 | 完成 |
| 第二十二批 | 排队状态可视化（QueueStatusActivity） | 141 + APK 构建通过 | 完成 |
| 第二十三批 | 会话详情与画廊增强（ConversationDetailActivity） | 141 + APK 构建通过 | 完成 |
| 第二十四批 | 单账号注册界面（RegisterActivity） | 141 + APK 构建通过 | 完成 |
| 第二十五批 | 电池优化引导（BatteryOptimizationHelper） | 141 + APK 构建通过 | 完成 |
| 第二十六批 | 刘海屏 / 系统栏 / 输入法 insets 适配（EdgeToEdgeInsets）+ 设置页顶栏 | 141 + APK 构建通过 | 完成 |
| 第二十七批 | 设置页 MD3 重做（静态 XML 表单 + 代理方式三选一 + 附件 chips）+ 实例对话框 TextInputLayout | 141 + APK 构建通过 | 完成 |

**当前状态：27 批全部完成，`:core` 141 项单测通过；`:app:assembleDebug` BUILD SUCCESSFUL（全量 1m23s / 第二十七批增量 27s），`:core:test --rerun-tasks` 59s 全绿。
真机只跑过界面走查（暴露了刘海遮挡，已在第二十六批修复）——方案 §9 的 S0 五项探测仍未做；余下均为真机验证或 Room/instrumentation 迁移。**

## 1. 第一批交付了什么

按方案 §10 的阶段划分，本批落地的是"不依赖设备就能做对、且风险最高"的那部分：
**阶段机与其全部判定规格**。理由是方案 §5 明写 `RetryController.kt` 是全项目最高保真要求的文件，
而它恰好不需要 Android API——把它做成纯 Kotlin 库，就能在没有真机的情况下用单测逐条对齐 C# 语义。

新增工程：`android/`，Gradle 8.13 + Kotlin 2.0.21，单模块 `:core`（纯 JVM，`jvmToolchain(17)`）。
Android application 模块留到阶段 G，本批刻意不引入 AGP——避免在 S0 探测出结论前锁死任何平台决策。

| 文件 | 对应参考 | 方案条目 |
|---|---|---|
| `android/core/src/main/kotlin/ai/arena/companion/identity/ConversationIdentity.kt` | `ConversationIdentity.cs` | §3.2 |
| `android/core/src/main/kotlin/ai/arena/companion/automation/PageState.kt` | `RetryController.cs` L11-L47 | §4「单次快照」 |
| `android/core/src/main/kotlin/ai/arena/companion/automation/ModelRetention.kt` | `ModelRetention.cs` | §3.4 |
| `android/core/src/main/kotlin/ai/arena/companion/automation/RateLimitTracker.kt` | `RateLimitTracker.cs` | §3.5 |
| `android/core/src/main/kotlin/ai/arena/companion/automation/ManualCollection.kt` | `ManualCollection.cs` | §3.3 |
| `android/core/src/main/kotlin/ai/arena/companion/automation/RetryController.kt` | `RetryController*.cs` 四文件 | §3.1 |
| `android/core/src/main/kotlin/ai/arena/companion/automation/DemoArenaPage.kt` | 新增（离线通道） | §3.2 末段 / §10 阶段 C |
| `android/core/src/main/resources/web/PageBridge.js` | `WebPage.cs` | §4 / §5 |

每个移植文件头部都带 `// ref:` 与 `// spec:` 双向追溯标注，符合方案 §11。

## 2. 逐条保真记录（方案 §3 的"规格"部分）

全部原样带过，未做任何简化：

- **epoch 守卫**：`tick()` 进入时取 `currentEpoch`，每个 `await` 之后校验 `epoch != currentEpoch` 即丢弃结果。
- **`snapshotConsistent` 闸门**：不一致直接 `return`，**不做任何判断、也不计入任何超时**——已有单测覆盖。
- **读取失败指数退避**：`min(20, 2^min(4, failures))` 秒，连续失败满 120 秒才暂停。
- **条款弹窗顺序**：在 `main` / `promptConfirmed` 可见性判断之前处理，`termsAttempted` 只尝试一次，20 秒未关闭暂停。
- **各阶段超时**：非 observe/model 阶段 120 秒；inspect/waitNew/new 各 20 秒。
- **New Chat 入口唯一性**：`>1` 直接暂停；`==0` 先尝试展开侧栏一次再超时暂停。
- **人机验证**：走 `pauseForVerification`，通过后 `epoch++` 自动续跑，**不重发**。
- **限流阶梯**：`5 * 2^min(4,completed)` + 20% 抖动，与服务端 deadline 取较大者；上限 5 次后 `finished=true` 并明确"不会自动换号或切换 IP"。
- **限流重试前的重读**：异步附件检查后必须重读页面，陈旧 DOM 绝不授权发送。
- **保留策略**：per-run 不可变快照 `runRetention`；`excludes()` 四条件；`未识别` 前缀永不排除；未知模型默认保留。
- **模型归属四段式**：`manualCollectionModel()` 原样，绝不把上一轮 trace 安到本轮。
- **双读校验**：`read → validate → probe → 500ms → probe → read → validate → 六字段比对`，每步之间复查 `active()`。

### 两处有意的平台适配（不是简化）

1. **`RateLimitTracker` 的持久化抽象成 `RateLimitStore` 接口**。C# 版直接写 `rate-limit.json` 并用
   `File.Replace` 原子替换；核心层不应该知道文件系统，Android 侧由 Room/文件实现，
   **原子写入的要求写在接口注释里，由实现方承担**。共享 deadline 的语义（只共享 deadline、
   绝不共享 response id）在核心层完整保留，并有单测锁死。
2. **`ConversationIdentity` 的端口判断**。C# `Uri` 对 https 缺省端口填 443，Java `URI` 给 `-1`，
   因此接受 `-1` 或 `443`，其余拒绝；`https://arena.ai:8443/...` 仍被拒。有单测。

## 3. 验证结果

```
gradle --no-daemon :core:test    →    BUILD SUCCESSFUL，31 tests PASSED
```

覆盖的关键行为（各一条以上用例）：

- URL 规范化：大小写、尾斜杠、显式 443、非 https、UserInfo、近似域名、demo 通道。
- 保留策略：精确匹配不做前缀/家族匹配、未知模型默认保留、`未识别` 永不排除、旧混合选择向保留迁移。
- 限流：只认 create-chat 的 429、`Retry-After` 数字钳位、HTTP-date 用 server Date 差值、过期日期不早于 now+1s、deadline 跨槽共享而 id 不共享。
- 阶段机：不一致快照被完全忽略、条款弹窗只点一次且超时暂停、多入口直接暂停且不发任何动作、侧栏只展开一次、人机验证通过后不重发、读超时退避到 120 秒才暂停、暂停后 tick 不推进（epoch 守卫）、标题截断只截模型段。
- 双读校验：回答变化/模型变化/生成中/非具体会话 URL 全部拒绝写入。

## 4. 环境记录（本机实测）

- `JAVA_HOME` 指向 jdk25，**Gradle 8.13 不支持 JDK 25**（报 `25.0.1` 后直接失败）。
  本工程用 `JAVA_HOME=D:\programmingSoftware\java\jdk17` 构建；Android Studio 自带 jbr 为 21，也可用。
- Gradle 无 wrapper 脚本，使用本机已缓存的 dist：`~/.gradle/wrapper/dists/gradle-8.13-bin/.../bin/gradle`。
  **待办**：补 `android/gradlew` wrapper，避免依赖本机缓存。
- Android SDK 在 `D:\Android\Sdk`（platforms 34/35/36，build-tools 34/35/36）。
  `ANDROID_HOME` 未设置，阶段 G 引入 AGP 时需要 `local.properties` 或环境变量。
- `dl.google.com/dl/android/maven2/` 根路径返回 404（正常，该仓库不允许目录列举），`repo1.maven.org` 200。

## 5. 已知缺口与下一步

按风险排序：

1. **`PageBridge.js` 的选择器全是桌面端推测**。方案 §9 第 3 项明写这是最大未知数，
   且只需一台设备 + 一个手工账号即可验证。选择器已集中在文件顶部 `SELECTORS` 常量，
   S0 出结论后整体替换即可，不需要动其余逻辑。**在 S0 完成前，这个文件不应被当作可用实现。**
2. **`generationStamp` / `responseSignature` 的构造方式是新设计**，C# 版由 `WebPage.cs` 决定。
   语义要求（"内容变了就一定变"）满足，但与桌面端的具体取值不兼容——两端不共享归档数据，可接受。
3. 尚未开始：Room schema、Keystore 保险库、ProfileManager、探针 document-start 注入、
   ArchiveStore、前台服务与 `job_state` 持久化、注册链路、本地代理中继。
4. `DemoArenaPage` 目前只覆盖顺利路径，尚未用它跑完整的多轮 E2E（阶段 C 验收项）。

（第一批结论：下一步不碰设备，先把落盘正确性锁死。已在第二批完成，见下。）

---

# 第二批：阶段 D 数据层（落盘正确性）

日期：2026-09-20
性质：纯 JVM，**已编译、单测累计 50 项全通过**；仍未上真机。

## D.1 交付内容

| 文件 | 对应参考 | 方案条目 |
|---|---|---|
| `android/core/src/main/kotlin/ai/arena/companion/data/PathPolicy.kt` | `PortablePaths.cs` | §4「便携树」 |
| 同上（`AtomicFiles`） | C# 各处 `tmp + File.Replace` | §3.7 / §3.8 |
| `android/core/src/main/kotlin/ai/arena/companion/data/ArchiveStore.kt` | `ArchiveStore.cs` + `ArchiveEntry.cs` | §3.8 |
| `android/core/src/main/kotlin/ai/arena/companion/data/TaskSettings.kt` | `TaskSettings.cs` | §3.6 |

落盘结构与桌面端保持一致：`记录.json` / `汇总.md` / `<模型目录>/清单.md` / `<标题>.<入口>`。

## D.2 逐条保真记录

- **同会话重复归档幂等**：按 `ConversationIdentity.same(url)` 查重，命中则替换记录、补写缺失入口，不新增记录。
- **模型目录名为空用 `未识别`**；模型名含 `/`（如 `zai-org/GLM-5.3-Flash`）净化为 `_`。
- **文件名规则**：`:` 换 `-`、截断 100 字符、为空用 `entry.id`。
- **删除只动本地**：删除记录与它**独占**的入口文件（仍被其它记录引用时不删）；模型目录空了才删。
  **绝不触碰 Arena 网站上的对话**，也不碰导出副本。
- **`deleteMany` 全有或全无**：请求集合与实际命中数不等时抛错且不删任何记录。
- **`markExported` 只改导出字段**，不重建入口、不改清单。
- **所有写入走 `AtomicFiles.write`**（tmp + rename），与 C# 的 `File.Replace` 对等。
- **便携路径**：树内存相对、树外存绝对、等于根存 `.`；`PathPolicy.contains()` 额外提供目录穿越检查，
  `tryDeleteArchiveFile` / `tryDeleteEmptyModelDirectory` 都先验证目标在归档根之内才动手。
- **`TaskSettings` 默认值迁移**：`prompt` 为空或仍是旧默认 `hi` 时跟随新默认 `1+1=`；用户改过则原样保留。
- **附件**：SHA256 内容寻址 `Attachments/<hash>/<name>`，复制后**重新哈希校验**；
  `verify()` 查存在性 + 字节数 + 哈希三项，附件名不得重复。

### 一处平台适配

`.cmd` / `.lnk` 会话入口换成 `.url` 文件承载 deep link（方案 §4：`arena-companion://open?...`）。
入口生成委托给 `deepLink` 回调，核心层不假设 scheme。C# 版「建 .cmd 失败退回 .url」的降级链在安卓上
不需要——只有一种入口形态——但「入口文件写不出不阻塞归档记录」这条保留了。

## D.3 验证结果

```
gradle --no-daemon :core:test    →    BUILD SUCCESSFUL，50 tests PASSED（新增 19）
```

新增覆盖：目录/清单/汇总生成、重复归档幂等、空模型名兜底、模型名净化、无效会话地址拒绝归档、
删除后空目录清理、有兄弟记录时保留目录、`deleteMany` 原子性、`markExported` 只动导出字段、
Markdown 表格竖线转义、默认提示词迁移三态（旧默认/空/用户自定义）、附件内容寻址与重校验、
空附件与缺失附件拒绝、重名附件拒绝、附件被篡改后校验失败、附件相对路径存储与读回。

### 一个测试期望被修正

初版断言「标题里的 `|` 出现在汇总表中且被转义」是错的：汇总表按**模型目录名**分组，而目录名
已被 `sanitizeSegment` 把 `|` 换成 `_`，所以竖线根本到不了汇总表。转义逻辑真正生效的位置是
**清单表的标题列**（标题不净化）。测试已改为断言该处，这是对参考行为的理解修正，不是放宽断言。

---

# 第三批：阶段 E 任务持久化 + 阶段 A 实例管理

日期：2026-09-20
性质：纯 JVM，**单测累计 68 项全通过**；仍未上真机。

## E.1 `JobState` / `JobStateStore`（方案 §7 第 3、4 条）

桌面端 `RetryController` 是纯内存态——桌面进程不会被随机杀，所以能忍。安卓上 Doze、
后台回收、厂商 ROM 杀后台让这个前提不成立，必须持久化。本模块同时修掉
`docs/mcp-reference-inventory-20260919.md` R2 记录的问题（无 paused 状态、重启不恢复）。

设计上最重要的一条是**不持久化任何"进行中的动作"**：没有 `pendingAct`，没有 `inFlightRequest`。
只存轮次、阶段、追踪地址、限流计数与 deadline。理由直接来自方案 §7 第 4 条与 §3.1 的气质——
恢复后一律 paused 等人工确认，**禁止自动重放任何有副作用的操作**。

`decide()` 返回四种结果，没有一种会自动继续：

| 结果 | 触发条件 | 行为 |
|---|---|---|
| `Fresh` | 无状态文件 | 全新开始 |
| `CleanExit` | `cleanShutdown=true` | 无需恢复提示 |
| `Interrupted` | 被杀 | **进入 paused**，附可读诊断；`canContinue` 只决定 UI 是否给"继续"按钮 |
| `Unusable` | 文件损坏或 schema 版本不认识 | 不猜，要求重新开始 |

限流 deadline 跨重启保留（存 ISO-8601），不清零重来——否则重启就能绕过网站要求的等待，
违反方案 §8 的项目边界。

## E.2 `InstanceManager`（方案 §3.7）

- 名称校验 `^[\p{L}\p{N}_ -]{1,40}$` 且不含首尾空格。
- 重命名前三道闸：自身未运行 → **没有其它运行中实例的归档引用该路径** → 目标名未被占用。
- 重命名 = 移动目录 + 重写所有引用（task-settings.json、各实例归档 记录.json），
  **重写任一步失败则目录移回原位 + 已改文件内容还原**。
- 仅大小写变更走中间临时目录两步移动。
- 所有 JSON 写入走 `AtomicFiles`。

### 两处平台适配

1. **运行中判定不用跨进程 Mutex**。安卓单进程，`isRunning: (File) -> Boolean` 由外部注入，
   核心层不假设实现（方案 §4 明确"简化：安卓单进程，不需要跨进程 mutex"）。
2. **删除走 App 内 `.trash/`**（方案 §4：安卓无系统回收站）。`.trash` 不计入 `list()`。

此外，引用重写除了 C# 的 `路径"` 与 `路径\\` 两种形态，额外处理了 `路径/`——
安卓路径分隔符是 `/`，不加这条会漏替换。仍然只替换"路径 + 分隔符/引号"的形态，
避免误伤同名前缀实例（如 `old` 与 `oldx`）。

## E.3 验证结果

```
gradle --no-daemon :core:test    →    BUILD SUCCESSFUL，68 tests PASSED（新增 18）
```

新增覆盖：无状态/干净退出/被杀/未知阶段/损坏文件/未知 schema 六种恢复分支、限流 deadline 跨重启、
状态清除；实例名校验六种非法形态、重命名重写引用、运行中拒绝重命名、
**其它运行中实例引用归档时拒绝重命名且不移动目录**、重名拒绝、同名拒绝、缺失实例拒绝、
删除移入 `.trash` 且不计入列表、运行中拒绝删除、重复创建拒绝。

---

# 第四批：阶段 F 单账号注册

日期：2026-09-20
性质：纯 JVM，**单测累计 79 项全通过**；未打过真实网络。

## F.1 交付内容

`android/core/src/main/kotlin/ai/arena/companion/register/RegisterClient.kt`

行为来源是 **`backend/services/arena_protocol.py`**，不是 ArenCard 原始代码——这是方案 §1 的明确决策。
移植的是 `ArenaRegisterClient` 六步流程与 `register_one` 编排，`ArenaDrawClient`（抽卡协议）
**不移植**：走 C# 血统后抽卡由页面自动化完成（方案 §2）。

两个注入点让协议逻辑与平台解耦：

- **`ArenaTransport`**：方案 §9 第 5 项明写 OkHttp 直连可能被 Cloudflare 403
  （`arena_http.py` D3 记录桌面端 curl_cffi 被 403 而 httpx 通过的反直觉结果）。
  若真机实测 403，换一个"WebView 页面上下文 fetch"的实现即可，**协议逻辑一行不动**。
- **`MailProvider`**：邮件流量绝不走代理（provider 自己拥有出口）。

## F.2 逐条保真记录

- **`recaptchaToken` 传空串**：方案 §2 / ArenCard README L32 实测服务端不校验。有单测断言。
- **set-password 抖动容错**：用**同一个 token** 重试**恰好一次**，仍失败即报错退出。
  单测断言 `setPasswordCalls == 2`，锁死"不是循环"。这是方案 §10 阶段 F 的验收项
  「失败退避不重试风暴」。
- **`registerOne` 永不抛出**，失败走 `error` 字段，由上层计数。
- **密码永不进日志/事件**：`redacted()` 把密码换成 `***`。有单测。
- **取消检查点**：建邮箱后、建用户后、等到链接后各一次；取消时不再发任何请求（单测断言
  取消后没有 magic-link 调用）。
- **429 → `ArenaRateLimitedException`**，并区分是否 Cloudflare 挑战（`cf` 标志）。
  方案 §8 的边界在此体现：**识别限流并上报，由上层停止/退避，绝不自动换 IP 或换号**。
- **查额度重试次数有界**（默认 4 次固定间隔），单测断言恰好 4 次调用。
- 密码生成保证四类字符齐全，50 次采样全部满足 arena 规则。

### 一处依赖决策

没有为了读几个顶层标量引入 JSON 解析依赖，用了受限的正则取值（`jsonString`）。
读的字段是 `access_token` / `id` / `creditsRemaining`，都是顶层标量，且读不到时一律按空处理、
不影响流程正确性。真正需要结构化解析的地方（归档记录、任务设置）用的是 kotlinx.serialization。

---

# 第五批：阶段 G 工程化

日期：2026-09-20
性质：**`:app:assembleDebug` 构建通过，产出 `app-debug.apk`（3.7 MB）**；未安装到设备运行。

## G.1 交付内容

| 文件 | 说明 |
|---|---|
| `android/gradlew` / `gradlew.bat` / `gradle/wrapper/` | Gradle wrapper，不再依赖本机缓存 dist |
| `android/app/build.gradle.kts` | minSdk 26 / target 35 / arm64-v8a + x86_64（方案 §10 阶段 G） |
| `android/app/src/main/AndroidManifest.xml` | 权限、前台服务 type、deep link |
| `app/.../ProbeBridge.kt` | document-start 注入（对 `ProbeInjection.cs`，§3.9） |
| `app/.../WebViewArenaPage.kt` | 单次快照读取（对 `WebPage.cs`，§4） |
| `app/.../AutomationService.kt` | 前台服务 + 通知 + 状态持久化（§7） |
| `app/.../MainActivity.kt` | WebView 宿主 + 崩溃恢复对话框骨架 |
| `android/README.md` / `local.properties.example` / `.gitignore` | 构建说明与环境要求 |

`settings.gradle.kts` 会在**找不到 Android SDK 时自动跳过 `:app`**，
这样在纯 JVM 环境（CI、无 SDK 的机器）上 `./gradlew :core:test` 依然可用。

## G.2 逐条保真记录

- **document-start 注入**：`WebViewCompat.addDocumentStartJavaScript` 与 WebView2 的
  `AddScriptToExecuteOnDocumentCreatedAsync` 语义严格对等。**必须在页面脚本之前接管
  fetch/XHR，否则漏掉首个对话请求。**
- **只在 `https://arena.ai` 运行**：注入时传 origin 白名单。
- **`showHUD:false`**：页面内悬浮面板会挡住自动点击，注入脚本开头就关掉。
- **注入失败静默降级**：`ProbeBridge` 捕获所有异常，`injected=false` + `lastError`，
  只在状态栏提示；阶段机随后走「未识别（探针未加载）」的正常降级路径。
  设备不支持 `DOCUMENT_START_SCRIPT` 时同样降级而非崩溃。
- **探针脚本从 assets 读取而非内嵌**，便于单独更新（§3.9）。
- **单次快照**：`WebViewArenaPage.read()` 一次 `evaluateJavascript` 拿回整个对象。
  超时抛 `PageReadTimeoutException` 交给阶段机指数退避，不自行重试。
- **前台服务**：`foregroundServiceType="dataSync"`，Android 14+ 要求；常驻通知直出
  轮次/阶段/暂停原因。
- **`START_NOT_STICKY`**：刻意不让系统自动重启服务。重启后的进程没有页面上下文，
  自动续跑等于盲目重放；恢复一律走 `JobStateStore` 的 paused 路径（§7 第 4 条）。
- **屏幕常亮用 `FLAG_KEEP_SCREEN_ON`**，不申请 `WAKE_LOCK` 长持有（§7 第 2 条）。
- **deep link `arena-companion://open`** 取代 `.cmd` / `.lnk` 会话入口（§4）。

## G.3 构建环境的三个坑（都已解决，记录备查）

1. **Gradle 8.13 不支持 JDK 25**，本机 `JAVA_HOME` 正指向 jdk25。构建须显式覆盖为
   jdk17（或 Android Studio 自带的 jbr 21）。已写进 `android/README.md`。
2. **`gradle wrapper` 任务无法联网校验 distribution URL**（`services.gradle.org` 返回 307
   且校验失败）。改为手工放置 wrapper jar/脚本（取自 GitHub `v8.13.0` tag）+ 手写
   `gradle-wrapper.properties`，`./gradlew` 实测可用。
3. **AGP 8.7.3 与 Kotlin 2.0.21 不兼容**：AGP 8.7 移除了
   `com.android.build.gradle.api.BaseVariant`，而 Kotlin android 插件仍依赖它，
   报 `Could not generate a decorated class for type KotlinAndroidTarget`。
   固定 AGP 8.5.2，且**两个插件版本必须都在根 build 文件声明**——
   只在 `pluginManagement` 里固定 AGP 时子模块仍会解析出不兼容组合。

---

# 第六批：会话重命名

日期：2026-09-20
性质：纯 JVM，**单测累计 87 项全通过**。

`android/core/src/main/kotlin/ai/arena/companion/automation/ConversationRenamer.kt`
对 `RenamePage.cs`，实现 `:core` 早先留下的 `RenamePage` 接口——阶段机的 `rename`
阶段此前一直注入 null（等于跳过重命名），现在这条链补齐了。

## 最关键的一条不变量

**`saveSubmitted` 必须在 dispatch 之前置位**（C# 源码第 63-64 行专门写了注释）。
保存请求的响应不确定时，用户点"继续"绝不能导致重复保存——宁可只去确认结果。
单测专门锁死这条：第一次调用超时后，第二次调用的 `saveCount` 不变。

其余逐条带过：标题比较做 NFC + 空白折叠、侧栏入口必须恰好一个、
`openMenu` 的 pending 重试 10 秒上限、`waitFor` 25 次 × 200ms、
确认循环 30 秒上限且区分"名称已更新但窗口未关"与"完全未确认"两种超时消息。

暂停（`active()` 返回 false）在每个动作前后都检查，取消时不再派发任何动作——
单测断言取消场景下 `actions` 为空。

## 待补

`:app` 侧还需要一个 `ModelRename.js` 对等脚本来实现 `RenameExecutor`
（找侧栏条目 → 打开菜单 → 点重命名 → 填入 → 保存）。它与 `PageBridge.js` 一样
依赖 arena.ai 的真实 DOM 结构，**同属 S0 第 3 项的验证范围**，所以先不写推测实现。

---

# 剩余工作

## 必做且必须有设备：方案 §9 的 S0 五项探测

| # | 探测 | 风险 | 当前占位 |
|---|---|---|---|
| 3 | **arena.ai 移动端布局可自动化性** | **最高** | `PageBridge.js` 选择器为桌面端推测，集中在文件顶部 `SELECTORS` |
| 4 | 探针在 Android WebView 的兼容性 | 高 | `app/src/main/assets/arena-model-probe.inject.js` 是**明确的空实现占位**，只返回"未加载" |
| 1 | WebView 版本矩阵（MULTI_PROFILE / DOCUMENT_START_SCRIPT / PROXY_OVERRIDE） | 中 | `ProbeBridge` 已对 `DOCUMENT_START_SCRIPT` 缺失做降级 |
| 2 | 后台存活（小米/华为息屏 30 分钟） | 中 | 前台服务已就位，存活率未测 |
| 5 | OkHttp 直连 arena.ai 是否被 Cloudflare 403 | 中 | `ArenaTransport` 是接口，403 时换 WebView fetch 实现即可 |

第 4 项的占位是**有意为之**：与其塞一个未经验证的脚本假装能用，不如让阶段机走它本来就
设计好的「未识别（探针未加载）」降级路径。这与 §3.1「所有失败都暂停 + 可读原因」一致。

# 第七批：本地认证代理中继

## 交付

| 文件 | 行数级别 | 对照来源 |
| --- | --- | --- |
| `android/core/src/main/kotlin/ai/arena/companion/net/ProxyRelay.kt` | 新建 | `reference/ArenCard/proxy_relay.py` + 方案 §4.1 |
| `android/core/src/test/kotlin/ai/arena/companion/ProxyRelayTest.kt` | 11 测试 | — |

`:core:test` **98 PASSED，BUILD SUCCESSFUL**（87 + 11）。

## 为什么在安卓上是必需的

安卓侧唯一能给 WebView 设代理的官方入口是 `ProxyController.setProxyOverride()`，
它的 `ProxyConfig` **不支持 user:password 认证**，而参考使用的代理基本都带认证。
所以中继不是优化，是**打通代理的唯一路径**：WebView 连一个本机无认证端口，
由中继向上游补 `Proxy-Authorization`。

## 逐条保真记录

1. **最小 CONNECT，绝不带 Host**。参考 `proxy_relay.py` 顶部记录了实测矩阵：
   最小 CONNECT → 200；**+Host → 被拒**；+User-Agent → 200；+Proxy-Connection → 200。
   `buildConnectRequest()` 因此只产出请求行 + 可选认证头，单测断言
   「除请求行与认证头外没有别的头」，并断言客户端即使带了 `Host`，
   发往上游的 CONNECT 里也没有。
2. **端口交给系统分配（`ServerSocket(0)`）**，不用固定基数。参考记录过一次真实事故：
   `SO_REUSEADDR` 允许多进程重复绑定 `127.0.0.1:20000`，实测 11 个进程同时监听而只有
   一个在收连接，导致所有实例都从同一条上游出去、**IP 隔离彻底失效**。
   单测断言端口非固定值且不同上游拿到不同端口。
3. **同一条上游复用同一端口**（`ConcurrentHashMap` + `putIfAbsent`，竞态下关掉多余 socket）。
4. **只监听回环**：`InetAddress.getByName("127.0.0.1")`，不暴露到局域网。
5. **认证凭据先 percent-decode 再 base64**，对齐 python 的 `unquote()`；
   单测用 `user%40mail:p%3Ass` 验证解出 `user@mail:p:ss`。
6. **失败语义（红线）**：上游连不上、或上游 CONNECT 非 200（如 407），
   一律回 `502 Bad Gateway` 并关闭连接，**绝不回退直连**。两条单测分别覆盖
   「上游端口已死」与「上游回 407」。这条对应方案 §4.1 的
   「节点不可用时阻止启动，不回退直连」——中继层面先保证不会"悄悄走本机 IP"。
7. **非 CONNECT 请求回 400**；单条连接的任何异常都被吞掉，不影响中继本身继续服务。
8. 超时对齐参考：客户端 30s、上游连接 20s、上游读写 30s。
9. `AutoCloseable`；`close()` 之后 `add()` 抛 `IllegalStateException`（单测覆盖），
   避免关闭后还有人以为拿到了可用端口。

## 尚未接线

`ProxyRelay` 本体完成且可单测，但**还没接到 `ProxyController.setProxyOverride()`**。
接线要在真机上验证两件事：`setProxyOverride` 是否对当前 WebView 版本全局生效、
以及 arena.ai 在代理下是否触发额外风控。这两项归入 S0。

# 第八批：代理闸门与账号保险库

## 交付

| 文件 | 内容 | 对照来源 |
| --- | --- | --- |
| `android/core/.../net/ProxySettings.kt` | 代理配置 + 校验 + 落盘 | `ProxySettings.cs` |
| `android/core/.../account/PasswordPolicy.kt` | `VaultPasswordPolicy` | `PasswordPolicy.cs:L5-L33` |
| `android/core/.../account/AccountVault.kt` | `AccountData` + 加密保险库 | `AccountData.cs`、`AccountStore.cs`、`PasswordSetupDialog.cs:L152-L164` |
| `android/app/.../KeystoreCipher.kt` | Android Keystore AES/GCM 后端 | 对 DPAPI `CurrentUser` |
| `android/app/.../ProxyGate.kt` | `setProxyOverride` 接线 + 启动闸门 | 方案 §4.1 |
| 测试 `ProxySettingsTest`(10) / `AccountVaultTest`(10) | — | — |

`:core:test` **118 PASSED**，`:app:assembleDebug` **BUILD SUCCESSFUL**。

## 逐条保真记录：ProxySettings

1. 端口 1–65535（ref: `ProxySettings.cs:L21`）、主机只许 IP 或主机名
   （**不带协议 / 端口 / 用户名 / 路径**，ref: L26-L27）、IPv6 补方括号（ref: L23-L25）。
   文案逐字沿用。
2. **`clash` 变成一条明确的拒绝**而不是当成 `system`。方案「明确不做 Clash 节点运行时」，
   但静默降级成跟随系统就等于回退直连，所以 `ProxyMode.parse("clash")` 直接抛并说明原因。
3. 新增 `username` / `password` 字段。桌面端靠浏览器认证弹窗，安卓走 ProxyRelay 注入，
   所以认证必须能存；`upstream()` 输出 percent-encoded 的 `scheme://u:p@host:port`。
4. **读和写都先跑一遍校验**（ref: L46 / L49）。损坏或缺 `mode` 的配置一律抛，
   不返回一个"能用"的默认对象——否则坏配置会无声变成直连。
5. 一个踩到的坑：IPv6 判定最初只做字符集匹配，导致 `1.2.3.4:8080`（其实是带端口的地址）
   被当成 IPv6 放过。已改为真正的 IPv6 字面量解析（`::` 压缩至多一处、分组 1-4 位十六进制、
   非压缩必须 8 组），单测覆盖。

## 逐条保真记录：AccountVault

1. `AccountData` 字段与 `AccountData.cs` 一一对应，含换号流程的
   `mailboxBeforeRefresh` / `mailboxRefreshRequested` / `mailboxChangeConfirmed` / `excludedEmails`。
   `nicknameError` 三条规则与文案逐字沿用（ref: `AccountData.cs:L5-L12`）。
2. `VaultPasswordPolicy` 与 `register.PasswordPolicy` **是两套规则，不能合并**：
   前者是 C# 对用户自设本地口令的要求（8 位 + 大写 + 符号），
   后者是 arena 服务端对注册密码的要求（大小写 + 数字 + 符号）。已在注释里写明。
3. **解密失败 = 可恢复错误且绝不覆盖**（方案 §10 阶段 A 验收项）。
   `load()` 失败置 `locked=true` 并抛 `VaultUnavailableException`；
   **锁定期间任何 `save()` 都被拒绝**，单测断言旧密文字节完全未变。
   唯一解锁入口是 `resetAfterUserConfirmation()`，只能由明确的用户动作调用。
4. **有意不复刻 `EnsurePassword`**（ref: `AccountStore.cs:L31-L44`）。C# 从随软件分发的
   `assets/account-defaults` 读一个内置密码；在移动分发下这等于把密码公开。
   改为 `needsSetup()`，由 UI 引导用户自设。
5. `validateSetup` 复刻 `PasswordSetupDialog.SavePassword` 的**校验顺序**
   （昵称 → 两栏留空则保留旧密码 → 强度 → 两次一致），`applySetup` 复刻 keepPassword 语义。
6. `redacted()` 永不输出密码，单测断言。

## 逐条保真记录：KeystoreCipher / ProxyGate

- `KeystoreCipher`：AES-256/GCM，密文 `[版本][12B IV][密文]`，
  **IV 每次随机并随密文存储**（GCM 下复用 IV 直接泄露明文）。
  密钥**不**设 `setUserAuthenticationRequired`——后台自动化在锁屏下也要读账号，
  否则熄屏即失败；硬件不可导出已挡住拷文件离线解密。
  密钥丢失（清除凭据 / 换机）映射成 `VaultUnavailableException`，接上第 3 条的不覆盖语义。
- `ProxyGate`：`setProxyOverride` 是**进程级**的，一个进程内所有 WebView 共享，
  所以多实例并行跑不同代理在安卓上做不到，上层必须**串行化到单个活动实例**。
  三道闸门，任一不过都抛 `ProxyUnavailableException` 并**阻止启动，不回退直连**：
  ① `PROXY_OVERRIDE` feature 不支持；② 上游 TCP 探测 8s 连不上；③ override 10s 未生效。
  `ProxyConfig` **不设任何 bypass 规则**——漏一条 URL 就等于暴露真实 IP。

# 第九批：串行化单活动实例

## 交付

| 文件 | 内容 |
| --- | --- |
| `android/core/.../data/ActiveInstanceGate.kt` | 活动权互斥 + FIFO 排队 |
| `android/core/.../ActiveInstanceGateTest.kt` | 10 测试（含 16 线程并发） |

`:core:test` **128 PASSED，BUILD SUCCESSFUL**。

## 为什么需要它

桌面端每个实例一个浏览器进程、各带各的 `--proxy-server`。安卓的
`setProxyOverride` 是**进程级**的，一个进程里所有 WebView 共用一份设置。
放任多实例并行的后果不是"代理不生效"，而是**第二个实例悄悄用着第一个实例的出口 IP**
——和 `proxy_relay.py` 注释里记录的那起端口复用事故同一类失效。
所以方案 §4.1 的降级是「串行化单活动实例」，本批把它变成可执行的闸门。

## 语义要点

1. **同一时刻至多一个持有者**；其余一律入队，不存在"先跑起来再说"的路径。
   16 线程并发申请的单测断言恰好 1 个 Granted、15 个在队列里。
2. **token 是单调递增的持有凭据，`release` 必须带对 token**。
   这条防的是：一个已被强制接管的旧持有者，在自己超时后把**新**持有者释放掉。
   单测专门覆盖了"迟到的 release 必须无效"。
3. **重入不换令牌**：持有者重复 `acquire` 沿用原 token，既不排队也不重发凭据。
4. **同名实例重复申请不会在队列里堆叠**。
5. **不做自动超时抢占**。`heldForMillis()` 只供 UI 显示"已运行 xx"；
   自动接管会让一个正在等页面的任务被无声打断，而方案要求一切异常停下等人工。
   接管只有 `forceTakeOver()` 一条路，且**只允许明确的用户动作触发**。
6. 闸门本身不启动任何东西：调用方拿到 `Granted` 之后才去 `ProxyGate.apply()`，
   两者的失败语义因此可以各自独立地"阻止启动"。

# 第十批：唯一启动入口

## 交付

`android/app/.../SessionLauncher.kt` —— 把第八批 `ProxyGate` 与第九批
`ActiveInstanceGate` 接成单一入口。`:core:test` 128 PASSED，`:app:assembleDebug` SUCCESSFUL。

## 顺序是有意的

1. **先抢活动权，再验代理**。反过来会出事：代理 override 是进程级的，
   没拿到活动权就去改，会把**正在跑的那个实例**的出口悄悄换掉。
2. 代理验证失败时**立刻交还活动权**，返回 `Blocked`。
   不能留下"拿着活动权但没代理"的半吊子状态——那正是回退直连的温床。
3. `release()` **不自动提升队首**。下一个实例必须重新走 `launch()`，
   因为它要重新验自己的代理，而不是继承上一个实例遗留的 override。

`LaunchOutcome` 三态里**只有 `Ready` 允许实例跑起来**，`Queued` 与 `Blocked` 都是停下等人工，
与方案「所有失败=暂停等人工」一致。

# 第十一批：多实例登录态隔离

## 交付

`android/app/.../ProfileManager.kt`。`:app:assembleDebug` **BUILD SUCCESSFUL**。

## 不支持就拒绝，不假装

桌面端靠"每实例一个用户数据目录"隔离。安卓的对等物是 `androidx.webkit` 的
Profile API，需要较新的系统 WebView。方案 §9 第 1 项要求：
**不支持时禁止多实例并明确告知，绝不退回共享 `CookieManager`**。

理由值得写下来：退回共享 Cookie 不是"隔离弱一点"，而是两个实例共用同一份登录态——
用户以为在操作两个号，实际全部落在同一个号上。这比"用不了多实例"糟糕得多，
而且**出错时用户看不出来**。所以 `requireMultiProfile()` 直接抛，文案说明后果。

## 其他决定

- **单实例例外**：只有一个实例时不存在串号风险，即使不支持 MULTI_PROFILE 也允许走默认
  Profile。`attach(..., isOnlyInstance = true)` 覆盖这条路径。
- **Profile 名做清洗 + 哈希**：只保留字母数字，其余换下划线，再拼一段实例名的稳定哈希。
  只清洗不哈希的话，"甲" 和 "乙" 会被清洗成同一个下划线串而互相串号。
- **删除实例要连 Profile 一起删**，且返回删除是否成功：残留 Profile 会在同名实例
  重建时把旧登录态带回来。

# 第十二批：实例选择器

## 交付

| 文件 | 内容 |
| --- | --- |
| `android/app/.../InstancePickerActivity.kt` | 对 `InstancePicker.cs`：列表 / 新建 / 重命名 / 删除 / 打开 |
| `android/app/.../MainActivity.kt` | 接收 `EXTRA_INSTANCE`、绑定 Profile、退出时交还活动权 |
| `android/app/src/main/AndroidManifest.xml` | LAUNCHER 改为选择器 |

`:app:assembleDebug` **BUILD SUCCESSFUL**。

## 为什么启动入口换成选择器

代理 override 和活动权都是**进程级**的（第八、九批）。直接进会话页面意味着
"先跑起来再说选哪个实例"，而正确顺序是**先选定唯一活动实例，再配代理，再开页面**。
所以 LAUNCHER 指向 `InstancePickerActivity`，`MainActivity` 只能带着实例名进入。

## 三条守卫

1. **已有实例时再新建，先过 `requireMultiProfile()`**。不支持隔离就弹窗说明后果并拒绝，
   不创建一个注定串号的实例。
2. **`MainActivity` 绑定 Profile 失败直接 finish**，绝不退回共享 Cookie 继续跑。
   只有一个实例时例外（无串号风险），走默认 Profile。
3. **删除实例时连 Profile 一起删**。只删目录会让同名实例重建时带回旧登录态。

运行中的实例在列表里标注「运行中」，`InstanceManager` 的 `isRunning` 回调接的就是
`SessionLauncher.holder()`，所以"正在运行不能改名/删除"这条桌面端约束自动成立。

# 第十三批：归档画廊与设置界面

## 交付

| 文件 | 对照来源 |
| --- | --- |
| `android/app/.../GalleryActivity.kt` | `GalleryWindow.cs` |
| `android/app/.../SettingsActivity.kt` | `MainForm.TaskSettings.cs`、`EnvironmentSettingsDialog.cs`、`PasswordSetupDialog.cs` |

选择器长按菜单扩为「打开 / 设置 / 归档 / 重命名 / 删除」。`:app:assembleDebug` **BUILD SUCCESSFUL**。

## GalleryActivity

- 按模型分组排序，**「未识别」排最后**，与 `ArchiveStore` 的未识别目录语义一致。
- **不提供「恢复归档」**。归档在 arena 侧不可逆，摆一个做不到的按钮比没有更糟；
  删除对话框明说「只删本地记录，网站上的归档无法撤销」。
- `renameError` 直接显示在列表项里。重命名未确认是需要人工介入的状态，
  躺在 JSON 里等于没有。
- 多选删除走 `ArchiveStore.deleteMany`（已有单测覆盖幂等与入口文件清理）。

## SettingsActivity

- **校验失败就不保存**，且**先把代理校验跑完再动任何文件**，任一非法则整体不落盘。
  桌面端 `ProxySettingsStore.Save` 也是先跑 `ProxyUri()` 再写——存下一份非法配置，
  下次启动要么崩、要么悄悄变直连。
- 代理配置**读失败不静默用默认值顶上**：弹窗说明，并把方式显示为「跟随系统」
  但**只有用户点保存后才真的改盘上的值**。
- 「遇到人机验证时暂停」**勾选框置灰且恒为真**。方案要求人机验证一律停下等人工，
  给一个能关掉的开关就是给一条违反红线的路径。
- 账号设置复用 `AccountVault.validateSetup` / `applySetup`，校验顺序与
  `PasswordSetupDialog.SavePassword` 一致（昵称 → 留空保留旧密码 → 强度 → 两次一致）。
- **保险库锁定时不直接写**：走 `promptVaultReset` 让用户明确确认"覆盖且旧数据无法找回"，
  这是第八批定下的「唯一解锁入口必须由用户动作触发」在 UI 上的落点。
- 加密后端接的是第八批的 `KeystoreCipher`（Android Keystore AES/GCM）。

# 第十四批：SAF 归档导出

## 交付

`android/app/.../ArchiveExporter.kt` + 画廊里的「导出归档到…」按钮。
新增依赖 `androidx.documentfile:documentfile:1.0.1`。`:app:assembleDebug` **BUILD SUCCESSFUL**。

## 设计取舍

安卓没有"随便往某个路径写文件"这回事，桌面端的「导出到文件夹」对应
`ACTION_OPEN_DOCUMENT_TREE` + `DocumentFile`（方案 §4 已定）。

1. **逐个文件记录失败，不中途抛出**。半途崩掉会给用户留下一份看起来完整、
   实则残缺的目录。全部尝试完再如实报告哪些没成功。
2. **`ExportReport.ok` 为假时标题就是「导出部分失败」**，不谎报成功。
3. **建带时间戳的子目录**（`arena-归档-yyyyMMdd-HHmmss`），
   绝不覆盖用户选定目录里已有的同名内容。

## 一个编译坑

`?: run { ...; return@try }` —— Kotlin 不允许给 `try` 块加标签返回
（`Label must be named`）。改成显式 `if (out == null)` 分支。

# 第十五批：附件引用计数与选择界面

## 交付

| 文件 | 内容 |
| --- | --- |
| `android/core/.../data/AttachmentGarbage.kt` | 引用计数 + 回收 |
| `android/core/.../AttachmentGarbageTest.kt` | 5 测试 |
| `android/app/.../SettingsActivity.kt` | 附件区块：添加 / 移除 / 清理 |

`:core:test` **133 PASSED，BUILD SUCCESSFUL**；`:app:assembleDebug` **BUILD SUCCESSFUL**。

## 为什么需要引用计数

附件按 `Attachments/<sha256>/<name>` **内容寻址**，所以两份内容相同的文件
共享同一个哈希目录。删除一条引用时顺手删目录，会把另一处仍在用的附件一起删掉。
`AttachmentGarbage` 只回收**当前没有任何设置引用**的哈希目录，单测专门覆盖了
"同内容被两处引用时一个都不能删"。

`collect(dryRun = true)` 先算出"将清理 N 项、释放 X"，由用户确认后才真删——
删除必须是用户明确同意的动作。

## 附件导入路径

安卓拿不到普通文件路径，SAF 只给 `Uri`。所以流程是
**content stream → 缓存临时文件 → `TaskSettingsStore.import`**，
由后者做内容寻址与**复制后重新哈希校验**（§3.6 原有语义不变）。
临时文件在 `finally` 里删除。同名附件先在 UI 挡掉，避免走到
`TaskSettingsStore.verify` 才报错。

# 第十六批：换号流程

## 交付

| 文件 | 对照来源 |
| --- | --- |
| `android/core/.../account/AccountReplacement.kt` | `MainForm.AccountReplacement.cs`、`ReplacementHandoff.cs`、`LoginTaskStart.cs` |
| `android/core/.../AccountReplacementTest.kt` | 8 测试 |
| `android/app/.../InstancePickerActivity.kt` | 长按菜单新增「更换邮箱」 |

`:core:test` **141 PASSED**，`:app:assembleDebug` **BUILD SUCCESSFUL**。

## 交接模型的平台差异

桌面端换号是**开第二个进程**：启动新 exe → 命名管道握手 → 等 45 秒就绪 →
确认 `pid` 与 `dataDirectory` 都对得上 → 才关旧窗口（`ReplacementHandoff.cs`）。

安卓是单进程，没有第二个窗口可开，所以交接退化为**进程内实例切换**。
管道握手与 45 秒超时不再需要，但**它们保护的那条语义必须原样保住**：

> 新实例没准备好之前，旧实例的数据一个字节都不能动。

落实成执行顺序：**先暂停旧实例并落盘 → 再读旧账号 → 再建新实例 → 全部成功才切换**。
任何一步失败都返回 `Failed` 且旧实例完好，文案对齐桌面端的
「新实例交接未完成，旧实例已保留，可重试换号」。
三条单测分别覆盖：暂停失败时**新实例根本没被创建**；切换失败时**半成品目录已回滚**；
成功路径下旧实例的 `account.vault` **字节完全未变**。

## 继承什么、不继承什么

| 字段 | 处理 | 理由 |
| --- | --- | --- |
| 密码、昵称 | **继承** | 桌面端同样沿用，换的是邮箱不是身份 |
| 邮箱 | **不继承**（置空） | 换号的目的就是换它 |
| `verified` | **不继承**（置 false） | 新邮箱当然未验证，继承会让流程跳过验证 |
| `mailboxBeforeRefresh` | 记旧邮箱 | 供"收件箱与原注册地址不一致"的判定 |
| `excludedEmails` | 旧列表 **+ 旧邮箱** | 避免新注册又撞回同一地址 |
| `task-settings.json` / `proxy-settings.json` | 复制 | 省得用户重配 |

## LoginTaskStart

逐条对 `LoginTaskStart.cs`：`take()` 三个条件缺一不可（pending、登录已停、phase 为
`complete`），**成功后立即清零**。这保证"登录后自动开始"只发生一次——
桌面端界面定时器会反复调用它，靠的正是这个一次性语义。

## 一条 UI 守卫

换号会产生第二个实例，所以在真正创建前先过 `ProfileManager.requireMultiProfile()`。
运行中的实例禁止换号（先停止）。

# 第十七批：会话界面接线

## 交付

| 文件 | 内容 |
| --- | --- |
| `android/app/.../WebViewProbeReader.kt` | 对 `ProbeReader.cs`，实现 `:core` 的 `ProbeReader` 接口 |
| `android/app/.../MainActivity.kt` | 开始/暂停/继续、tick 循环、手工收集、归档写入 |

`:app:assembleDebug` **BUILD SUCCESSFUL**。至此 `:core` 的阶段机第一次有了完整的
`ArenaPage` + `ProbeReader` 实现并被界面驱动。

## WebViewProbeReader

**读不到一律返回带 `lastError` 的空快照，绝不抛**。探针是可选增强，
注入失败时阶段机必须能以「未识别（探针未加载）」正常收尾（§3.9 静默降级），
而不是让整轮任务失败。超时、异常、解析失败三条路径都映射成空快照 + 原因。

一次 `evaluateJavascript` 取回整个探针状态，**不拆成多次读取**——
否则 `runId` 与 `name` 可能来自不同时刻，正是 `ProbeReader.cs` 注释里记录的坑。

## 启动路径

「开始」按钮不直接跑，而是先过 `SessionLauncher.launch()`：

- `Queued` → 提示"「X」正在运行，本实例排在第 N 位"，**不启动**。
- `Blocked` → 弹窗说明原因（代理不可用等），**不启动、不回退直连**。
- `Ready` → 才建 `RetryController` 并开始 tick。

代理配置读失败时同样**阻止启动**而不是当作"跟随系统"继续。

## 暂停与继续的区别

已有控制器时按钮是「继续」而非「开始」，调 `resume()` 而不是 `start()`。
这是方案的红线：**继续只推进当前进度，绝不重发已提交的问题**。
`onDestroy` 里也是 `pause()` 而非丢弃状态。

## 手工收集

直接走 `:core` 的 `ManualCollection.read()`，双读校验一步不省。
**任何不稳定都拒绝写入**——凑合存一条张冠李戴的记录，比不存糟糕得多。

# 第十八批：模型取舍界面

## 交付

`SettingsActivity` 新增「模型取舍」区块：多选要归档的模型，写入
`TaskSettings.excludedModels`。`:app:assembleDebug` **BUILD SUCCESSFUL**。

## 目录从哪来

**不硬编码模型清单**。硬编码会在 arena 上新模型时静默失效——用户以为勾全了，
实际上新模型在名单外，被默认保留。这里的目录从**归档记录里实际见过的模型名**生成
（`ArchiveStore.all().model`），经 `ModelRetentionCatalog` 规整。

还没观察到任何模型时**只提示、不自造列表**：
「还没有观察到任何模型名，先跑一轮或手工收集一次再来设置」。
给一个猜测的清单会让用户以为设置生效了。

## 界面文案承担的语义

界面明写「只按完整模型名精确匹配，不做系列或前缀推断；未出现在列表里的模型一律保留」。
这正是 `ModelRetentionPolicy.excludes()` 的四条件语义（§3.4），
用户必须知道勾选 `gpt-4` 不会连带排除 `gpt-4-turbo`。

## 第十九批后新增能力总览

第十九批后已补齐方案 §10 剩余的全部纯 JVM 可做项，不再有“缺口”清单：

- **Room 已落地**（第十九批）：`android/app/src/main/kotlin/ai/arena/companion/data/room/` 下 10 文件
  `ArenaDatabase`（v1，fallbackToDestructiveMigration）、`Converters`、`*Entity`、`RoomMappers`，
  kapt 生成通过，`:app:assembleDebug` 1m23s 绿。`:core` 的 JSON 落盘仍保留作对照与回滚基准，Room 为增量并存。
- **探针三件套**（第二十批）：`arena-model-probe.inject.js`（X-HR/fetch 劫持组装 `window.__arenaProbe`）、
  `PageBridge.js`（快照）、`ModelRename.js`（重命名 DOM）三资产在 `ProbeBridge` 中 `DOCUMENT_START` 注入，
  `SessionLauncher` 的 `gate` 字段已暴露供 `MainActivity` 直接显示排队位。
- **重命名端到端**（第二十一批）：`WebViewRenameExecutor`（`evaluateJavascript` 执行 `ModelRename.js`）+
  `MainActivity` 中 `ConversationRenamer` 接线（`rename` 阶段 `doRename`→`confirm`→`write`），失败进 `renameError` 人工重试。
- **排队可视化**（第二十二批）：`QueueStatusActivity`（轮询 `ActiveInstanceGate.snapshot()` 显示持有者/队列位/等待时长，
  “查看队列”入口已加入 `MainActivity` 与 `InstancePickerActivity`，`Queued` 分支可一键跳转）。
- **会话详情**（第二十三批）：`ConversationDetailActivity`（按 `entryId` 展示标题/链接/状态 + Markdown 预览），
  `GalleryActivity` 点击条目即打开详情，详情页失败时展示 `lastError` 而非崩溃。
- **注册界面**（第二十四批）：`RegisterActivity`（单账号 UI 框架：邮箱/密码输入 + 状态机 + 开始/取消），
  网络实现留空但文案已约束“不提供批量/换 IP/绕验证码，遇 429 停止不重试风暴”（方案 §10 阶段 F）。
- **电池优化**（第二十五批）：`BatteryOptimizationHelper`（`isIgnoringBatteryOptimizations` + `requestIgnore` 跳设置页）+
  `MainActivity` 首次启动提示 + `AndroidManifest` `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS` 权限，
  前台服务 `AutomationService` 的 Doze/杀后台风险已在 UI 层显性提示。
- **刘海屏 / 系统栏 / 输入法适配**（第二十六批）：`EdgeToEdgeInsets`（`enableEdgeToEdge()` + 逐视图 insets 施加）
  接入全部 7 个页面，设置页补齐 MD3 顶栏与返回键；见下文「第二十六批」。

# 第二十六批：刘海屏 / 系统栏 / 输入法 insets 适配

日期：2026-09-20
性质：UI 层修复。`:app:assembleDebug` **BUILD SUCCESSFUL**（增量 37s），`get_diagnostics` 0 条；遮挡是否消除仍需真机复核。

## 现象与根因

真机走查：每个页面的标题都顶进了前置摄像头（刘海 / 挖孔）区域。

根因不是"漏了一个刘海适配开关"，而是 **`targetSdk = 35` 之后 Android 15+ 强制 edge-to-edge**：
窗口内容直接铺到状态栏、导航栏与挖孔之下，`android:statusBarColor` 之类的主题项被系统忽略。
此前 7 个 Activity 没有任何 `WindowInsets` 处理，`AppBarLayout` 从 y=0 开始布局，标题自然落在状态栏 /
摄像头下面。同一根因还带出三处此前没暴露的问题：列表末尾、底部操作条与 FAB 压在手势导航条上；
横屏时内容被刘海侧边切掉；API 30+ 上键盘弹出后输入框被盖住（`adjustResize` 对不 fit system windows
的窗口已经不起作用）。

## 交付

| 文件 | 内容 |
| --- | --- |
| `android/app/src/main/kotlin/ai/arena/companion/app/EdgeToEdgeInsets.kt` | 新增：`install()` + `apply()`，全部页面唯一的 insets 入口 |
| `android/app/src/main/res/layout/activity_settings.xml` | 新增：设置页改为与其它页面同构的 AppBarLayout + NestedScrollView |
| `activity_main / instance_picker / gallery / conversation_detail / queue_status / register.xml` | 为根、顶栏、内容区、底部操作条补 id（`root` / `appBar` / `content`（详情页为 `scroller`）/ `bottomBar`） |
| 7 个 `*Activity.kt` | `onCreate` 首行 `EdgeToEdgeInsets.install(this)`；取到视图后 `EdgeToEdgeInsets.apply(root, topBar, contents, bottomBar, floating)` |
| `res/values/themes.xml` | 移除 `statusBarColor` / `navigationBarColor` / `windowLightStatusBar` |
| `AndroidManifest.xml` | Main / Settings / Register 三个有输入的页面加 `windowSoftInputMode="adjustResize"` |

## 设计取舍

1. **不退回、全版本统一开启。** `windowOptOutEdgeToEdgeEnforcement` 只是缓兵之计（已标废弃，SDK 36 起失效）。
   改为在 minSdk 26 起的所有版本上显式 `enableEdgeToEdge()`，Android 8～16 走同一条代码路径，
   而不是 15+ 一套、14- 另一套"碰巧不重叠"的布局。
2. **insets 只施加给点名的视图，且叠加在 XML 原值之上。** 顶栏吃 top + 左右（横屏时刘海在侧边），
   内容区 / 底部操作条吃 bottom + 左右，FAB 吃 bottom + 右侧 margin。`apply()` 在注册监听时先记下原始
   padding / margin，每次回调从原值重算——旋转、键盘反复弹出都不会累加。
3. **输入法高度加在根视图的底部 padding 上**，等价于旧 `adjustResize` 的"窗口变矮"：CoordinatorLayout 按
   padding 重新测量子视图，滚动容器 `onSizeChanged` 自动把焦点输入框滚到键盘之上。键盘弹出时它已盖住
   导航栏，此时内容区的导航栏避让量归零（`max(bars.bottom - ime.bottom, 0)`），不会在键盘上方留一条空带。
4. **系统栏图标深浅按 `colorSurface` 的实际亮度判定**，不按系统夜间模式。当前配色在 DayNight 两种模式下
   都是浅色表面（`colors.xml` 没有 night 变体）；若沿用 `enableEdgeToEdge()` 默认按夜间模式取值，
   深色模式下状态栏图标会被刷成白色而看不见；原主题里写死的 `windowLightStatusBar=true` 则是在
   将来真正引入深色配色时反过来出错。
5. **API 28+ 把刘海模式设为 `SHORT_EDGES`**（运行时设置，避免为一个属性再开 `values-v27`）。Android 15 对
   targetSdk 35 已强制 `ALWAYS`，这一步只是让 9～14 的横屏表现与之对齐；避让本身由 `displayCutout` insets 完成。
6. **不给 `AppBarLayout` / `CoordinatorLayout` 设 `fitsSystemWindows`。** 那条路径会让 CoordinatorLayout 自己
   画状态栏背景并消费 insets，不同 Material 版本行为有漂移，而且管不到导航栏、刘海侧边与输入法。
   所有避让集中在一个 object 里，可读、可搜、可改。

## 顺手修掉的一处

`SettingsActivity` 此前用 `title = …` 设标题，但主题是 `NoActionBar`，这个标题从来没显示过，页面也没有返回键。
现在与其它页面同构：`activity_settings.xml` 提供 MD3 顶栏 + 滚动内容，程序化构造的表单挂在 `@id/body` 下；
原来 `setPadding(32, 32, 32, 32)` 的裸像素值换成 XML 的 `16dp`。

## 一个编译坑

`activity_conversation_detail.xml` 里正文 `TextView` 已经占了 `@+id/content`，ViewBinding 的
`dataBindingGenBaseClassesDebug` 直接报同一布局内 id 冲突。该页滚动容器改用 `@+id/scroller`。

## 验证

- `:app:assembleDebug` BUILD SUCCESSFUL（增量 37s），`get_diagnostics` 0 条。
- 编译只能证明类型与资源引用正确；**遮挡是否消除、键盘是否把输入框顶起来，必须上真机看**。建议至少各验一台：
  Android 15+（系统强制 edge-to-edge 路径）与 Android 10～14（`enableEdgeToEdge()` 显式开启路径），
  带挖孔 / 刘海的机型横竖屏各一次，并在设置页 / 注册页弹出键盘确认输入框可见。

# 第二十七批：设置页 MD3 重做 + 实例对话框

日期：2026-09-20
性质：纯界面层，业务逻辑零变更。`:app:assembleDebug` **BUILD SUCCESSFUL**（增量 27s），`get_diagnostics` 0 条。

## 为什么只动这一页

第十二～二十四批的界面优化覆盖了实例选择器、画廊、会话、详情、队列、注册六个页面（MD3 卡片 / Chip / TextInputLayout），
**设置页是唯一还在用程序化裸控件的页面**：`TextView` 当分节标题、系统 `EditText` / `Button` / `CheckBox`、
`setPadding(32, 32, 32, 32)` 裸像素。另外还有两处小尾巴——「账号」分节下面挂着一个空 `TextView`，
「附件」分节标题写在「模型取舍」之前而内容排在其后，用户看到的分组是错位的。

## 交付

| 文件 | 内容 |
| --- | --- |
| `android/app/src/main/res/layout/activity_settings.xml` | 五张 `Widget.Arena.Card` 分节卡（任务 / 代理 / 附件 / 模型取舍 / 账号）+ 常驻底栏「保存」 |
| `android/app/src/main/res/layout/chip_attachment.xml` | 附件条目 Input chip（叉号移除单个附件，点击显示完整 SHA-256） |
| `android/app/src/main/res/layout/dialog_account_setup.xml` | 昵称 / 密码 / 再次输入三个 TextInputLayout（密码带可见性切换） |
| `android/app/src/main/res/layout/dialog_text_input.xml` | 单行输入对话框，供实例选择器新建 / 重命名复用 |
| `android/app/src/main/res/values/themes.xml` | 新增 `Widget.Arena.Card / TextInput / SectionTitle / HintText / BodyText` 五个复用样式 |
| `android/app/src/main/kotlin/ai/arena/companion/app/SettingsActivity.kt` | 改为 `findViewById` 接静态布局；删除 `section()` / `field()` 构造器 |
| `android/app/src/main/kotlin/ai/arena/companion/app/InstancePickerActivity.kt` | 新建 / 重命名对话框改用 `dialog_text_input.xml` |

## 设计取舍

1. **代理方式从自由文本改成三选一按钮组**（跟随系统 / HTTP·Mixed / SOCKS5）。`ProxyMode` 只有这三个值，
   让用户手敲 `socks5` 只会制造拼写错误；`clash` 之类的非法值在 UI 上就没有入口，`ProxyMode.parse` 的拒绝逻辑仍在
   保存路径上兜底。跟随系统时地址 / 端口 / 认证置灰但**不清空、保存时仍原样写盘**——与旧行为一致，切回代理不用重填。
2. **附件从一段多行文本改成 chips，并允许单个移除。** 原来只有「移除全部」，删一个要全删重加。移除只改内存列表，
   点「保存」才落盘，与「移除全部」走同一条路径，不引入新的写盘时机。
3. **「遇到人机验证时暂停」改成 `MaterialSwitch`，仍然常开且禁用**，并在下方明写"通过后自动续跑、不重发；此项不可关闭"。
   第十三批定下的"不给一条能关掉的路径"原样保留。
4. **「保存」放进常驻底栏**而不是滚动到最后：五张卡片的长度在小屏上超过两屏，保存按钮必须随时可见。
   底栏与画廊页同构，走第二十六批的 `EdgeToEdgeInsets.apply(bottomBar = …)` 避让手势条，内容区底部预留 88dp。
5. **校验与落盘逻辑一行未改。** `save()` 仍是先跑 `ProxySettings.proxyUri()` 再动文件、任一非法整体不保存；
   代理读失败仍弹窗说明并只在界面上回退「跟随系统」；保险库锁定仍走 `promptVaultReset` 由用户确认。
   `TextInputEditText.getText()` 标注可空，统一经 `str()` 收口成非空字符串，避免 `"null"` 被当成密码存进去。

## 验证

- `:app:assembleDebug` BUILD SUCCESSFUL（增量 27s），`get_diagnostics` 0 条。
- 真机复核项并入第二十六批的 insets 清单：设置页竖屏滚到底部时最后一张卡不被底栏遮住、键盘弹出时焦点输入框可见、
  代理三选一切换时下方字段的启用状态正确。

## 当前整体状态（第二十七批后）

- `:core:test --rerun-tasks` **BUILD SUCCESSFUL in 59s**，**141 项测试全通过**（分布见下）。
- `:app:assembleDebug` **BUILD SUCCESSFUL in 1m23s**（`kaptGenerateStubs` + `kaptDebugKotlin` + `compileDebugKotlin` 全绿），
  `android/app/build/outputs/apk/debug/app-debug.apk` 可产出（AGP 8.5.2，compileSdk 35，minSdk 26，arm64-v8a+x86_64）。
- 第二十六批（insets 适配）后 `:app:assembleDebug` 增量 **BUILD SUCCESSFUL in 37s**，`get_diagnostics` 仍为 0 条。
- 第二十七批（设置页重做）后 `:app:assembleDebug` 增量 **BUILD SUCCESSFUL in 27s**，`get_diagnostics` 仍为 0 条。
- `get_diagnostics` 0 条；`JAVA_HOME=/d/programmingSoftware/java/jdk17`（Gradle 8.13 不支持 JDK 25）。
- **Room 编译验证**：kapt 生成的 `*_Impl.java` 已在 `android/app/build/generated/source/kapt/debug/` 下产出 8 个 DAO 实现。

**141 项测试分布**：ConversationIdentity(6)、ManualCollection(5)、ModelRetention(6)、
RateLimitTracker(5)、RetryController(9)、ArchiveStore(10)、TaskSettings(9)、JobState(7)、
InstanceManager(9)、RegisterClient(11)、ConversationRenamer(8)、ProxyRelay(11)、
ProxySettings(10)、AccountVault(10)、ActiveInstanceGate(10)、AttachmentGarbage(5)、
AccountReplacement(8)。

**所有非设备依赖的方案条目均已实现（含 Room、探针三件套、重命名、排队可视化、详情页、注册 UI、电池引导）。**
余下工作均为**真机验证**：S0 五项探测（§9）、`ModelRename.js` 选择器真机校准、代理与 Profile 的 WebView 真机行为、
以及 Room 的 instrumentation 迁移验证（需设备上的 SQLite 真实行为）。

## 建议的下一步

1. **S0 第 3 项优先**——`PageBridge.js` / `ModelRename.js` 的选择器在真机 arena 页面上实测，
   探针 `window.__arenaProbe` 字段与桌面端对齐后，`:core` 已验证的阶段机即可端到端跑通。
2. **S0 第 1/5 项**——Profile 多实例隔离与代理 `PROXY_OVERRIDE` 在真机 WebView 上验证（是否为进程级、是否生效）。
3. **Room instrumentation**——在 `androidTest` 中跑通 `ArenaDatabase` 的 `(instance, canonicalUrl)` 幂等与迁移，
   再决定是否将 `:core` 的 JSON 存储切为 Room 主路径。
4. **真机回归**——`JobState` 的 Doze/杀后台恢复、`BatteryOptimizationHelper` 的免优化跳转、`QueueStatusActivity` 的排队提示。
5. **insets 真机复核**——带挖孔机型上逐页确认标题不再进入摄像头区域、列表末尾与 FAB 不被手势条遮挡、
   横屏刘海侧边留白正确、键盘弹出时输入框可见（第二十六批只做到了编译通过）。
6. **设置页真机走查**——代理三选一与字段置灰联动、附件 chip 移除后点保存确实落盘、底栏「保存」不遮住最后一张卡。

---

# 第二十八批：S0 真机探测（HONOR Magic5 Pro）与移动端选择器校准

日期：2026-09-20
性质：真机验证与页面桥接/探针修正。`:core:test` **141 项测试全通过**，`:app:assembleDebug` **BUILD SUCCESSFUL in 7s**，已在真机全链路实跑。

## 真机环境

- **测试机型**：HONOR PGT-AN10（Magic5 Pro）
- **系统版本**：Android 16（Vanilla Ice Cream 演进，API Level 36，Linux 6.6）
- **WebView 内核**：Chromium 138.0.7204.180
- **连接通道**：ADB 端口转发 `tcp:9222 -> @webview_devtools_remote_<pid>`，CDP WebSocket 控制台全量交互

## 真机实测发现的关键 DOM 差异与问题定位

1. **输入框（`editor`）差异**：
   - 移动版 `arena.ai` 渲染的是 `<textarea name="message" placeholder="Ask anything…">`，**不存在桌面版的 `data-testid="prompt-textarea"`**。
   - 旧选择器只能匹配 `[contenteditable="true"]`，移动端未能捕获到输入框，导致 `draft()` / `sendReady` 失效。
2. **React 受控输入与按钮状态追踪器（`_valueTracker`）**：
   - 现代 React 的受控 `textarea` 挂载了 `_valueTracker`。如果仅通过 `setter.call(e, value)` 或 `e.value = value` 赋值，React 的合成事件系统因 `tracker.getValue() === value` 认为值未改变，不会更新内部 state，底部的发送按钮会一直保持 `disabled: true`。
   - **修复**：赋值前取 `last = e.value`，调用原生 descriptor setter 后重置 `e._valueTracker.setValue(last)`，并连发 `input` 与 `change` 两个 bubbling 事件。实测后发送按钮立即从 `disabled: true` 转为 `disabled: false`。
3. **底部静态 reCAPTCHA 声明导致 blocker 误判**：
   - `arena.ai` 页面底部包含静态页脚：`"This site is protected by reCAPTCHA and the Google Privacy Policy..."`。
   - 原 `blockerOf()` 正则 `/captcha/i.test(document.body)` 会直接击中该页脚，导致正常页面一律被误判为 `"需要人机验证"`，阻断状态机推进。
   - **修复**：排除 `protected by reCAPTCHA` 静态文字，仅在命中 `Security Verification`、`verify you are human`、`complete this quick security check` 等真实弹窗时才触发阻断。
4. **服务条款弹窗（`termsDialog`）处理优化**：
   - 首发消息时会触发 `[role="dialog"]` 服务条款弹窗（`Terms of Use & Privacy Policy`）。
   - 弹窗内包含 `Agree` 和 `Close` 两个按钮。原 `PageBridge.act('terms')` 盲取 `all(SELECTORS.termsAccept).pop()`，在某些结构下会误点关闭按钮而非同意。
   - **修复**：在弹窗中精准匹配包含 `Agree / 同意 / Accept` 文案的按钮。
5. **移动端侧栏与「新建会话」（`newChat`）**：
   - 移动端默认隐藏侧栏抽屉（`canExpand: true, newLinks: 0`）。
   - 展开侧栏后出现 `a[href="/"]`（包含 `New Chat` 文本）。扩展 `newChat` 选择器与正则过滤以支持移动版首页路由。
6. **`ModelRename.js` 非标准 CSS 选择器修复**：
   - `ModelRename.js` 中原包含 `button:has-text(...)`。`:has-text` 是 Playwright 专有伪类，标准 Chromium `document.querySelector` 会抛出 DOMException `SyntaxError`。
   - 改用标准 CSS 选择器配合 DOM 文本属性安全过滤；增加移动端 `/c/<uuid>` 会话路径支持。

## 验证交付

| 文件 | 修改说明 |
| --- | --- |
| `android/app/src/main/assets/PageBridge.js` | 移动端多重选择器、React `_valueTracker` 重置、静态 reCAPTCHA 误报排除、精准 Agree 按钮 |
| `android/core/src/main/resources/web/PageBridge.js` | 与 app 端保持一致的单次快照桥接脚本（Version 2） |
| `android/app/src/main/assets/ModelRename.js` | 移除 `:has-text` 非标准选择器，支持 `/c/` 会话路径 |
| `android/app/src/main/kotlin/ai/arena/companion/app/MainActivity.kt` | 开启 WebView 调试模式与控制台日志桥接 |

## 验证结果

1. **JVM 单元测试**：
   - `./gradlew :core:test`：**141 项测试全部 PASSED**。
2. **真机编译与部署**：
   - `./gradlew :app:assembleDebug`：BUILD SUCCESSFUL in 7s。
   - `adb install -r -t` 成功安装并运行于 HONOR Magic5 Pro 真机。
3. **CDP 实测全自动化流程闭环**：
   - `window.__ARENA_PAGE_BRIDGE__.version` = 2（通过 `document-start` 成功自动注入）。
   - `act("fill", "What is 2+2?")` 成功填充并驱动 React 状态，`sendReady` 变为 `true`。
   - `act("send")` 成功发送，URL 迁移至 `https://arena.ai/c/<uuid>`。
   - `act("expand")` 成功展开侧栏抽屉，`newLinks` 从 0 变为 3，`canExpand` 翻转为 `false`。
   - `ModelRename.state()` 正常返回状态，无任何选择器报错。

---

依据文档：docs/mcp-android-implementation-plan.md、docs/mcp-reference-inventory-20260919.md

---

# 第二十九批：桌面端自动登录 / 账号保险库链路移植收口

日期：2026-09-20
性质：自动登录阻塞修复与桌面端回归用例迁移。`:core:test --rerun-tasks` **165 项测试全通过**，`:app:assembleDebug --rerun-tasks` **BUILD SUCCESSFUL in 29s**，`get_diagnostics android` 0 条。

## 背景

第二十八批已证明移动端页面桥可以把消息发出去，但剩余真阻塞是**页面未登录**：如果直接进入 `RetryController`，消息可能完成输入 / 发送动作，却没有已登录账号来确认、归档和续跑。桌面端对此已有完整链路：`AuthFlow.cs` 469 行状态机 + `assets/AuthBridge.js` + `AccountStore`；本批把这条链路在 Android 侧收口，并修正换号时账号保险库加密后端未贯通的问题。

## 补丁路径

| 文件 | 本批处理 |
| --- | --- |
| `android/core/src/main/kotlin/ai/arena/companion/account/AuthFlow.kt` | 保持对桌面端 `AuthFlow.cs` 的 Kotlin 状态机映射：登录前检查、邮箱注册/确认、人机验证暂停、1 秒动作延迟、epoch 取消保护、邮箱恢复与换号请求。 |
| `android/app/src/main/assets/AuthBridge.js` | 与桌面端 `assets/AuthBridge.js` 对齐，供 `WebViewAuthPages` 在 `arena.ai` / `10minutemail.one` 页面读取 stage 并执行受控动作。 |
| `android/app/src/main/kotlin/ai/arena/companion/app/WebViewAuthPages.kt` | Android WebView 执行桥：加载 `AuthBridge.js`、限制导航域名、15 秒超时、把 `bridgeError` 还原成 Kotlin 异常。 |
| `android/app/src/main/kotlin/ai/arena/companion/app/MainActivity.kt` | 「开始」现在先进入 `startAuthThenAutomation()`：登录 `complete` 后 `LoginTaskStart.take()` 一次性放行，才创建 `RetryController` 开始发消息。 |
| `android/core/src/main/kotlin/ai/arena/companion/account/AccountReplacement.kt` | 新增 `vaultFactory` 注入点，核心层默认仍用纯 JVM `AccountVault`，app 层可传 Android Keystore 后端。 |
| `android/app/src/main/kotlin/ai/arena/companion/app/InstancePickerActivity.kt` | 换号流程改为 `AccountReplacement(..., vaultFactory = { AccountVault(it, KeystoreCipher()) })`，避免读取设置页保存的加密 `account.vault` 时误用明文 cipher。 |
| `android/core/src/test/kotlin/ai/arena/companion/AuthFlowTest.kt` | 追加桌面回归：已有邮箱页不被重载、确认邮件先打开再校验链接、缺失 auth 页先恢复、延迟动作期间停止不会补点。 |
| `android/core/src/test/kotlin/ai/arena/companion/AccountReplacementTest.kt` | 追加加密保险库工厂测试，证明换号读旧 vault / 写新 vault 都走注入 cipher。 |

## 关键语义

1. **未登录不再直接跑任务**：`MainActivity` 先执行 `AuthFlow.start()`；只有 `phase == "complete"` 且登录已停时，`LoginTaskStart.take(loginRunning=false, phase="complete")` 才触发一次自动化启动。
2. **账号保险库端到端加密一致**：设置页与自动登录均使用 `AccountVault(instanceDir, KeystoreCipher())`；换号新实例现在也通过同一工厂读取旧账号、写入新账号，避免 Keystore 密文被 PlainTextCipher 当作损坏数据。
3. **桌面端反重复提交保护保留**：所有 UI 写动作前等待 1 秒；若用户在延迟期间停止，epoch 变化会取消后续点击，保留用户停止原因。
4. **邮箱链路不误刷新**：已有 `auth` 邮箱页可用时不重复导航到 `10minutemail.one`，防止临时邮箱站刷新地址；若页面缺失则只恢复一次并等待加载。
5. **注册邮箱强绑定**：未验证账号在提交邮箱 / 创建账号前必须确认 auth 页邮箱与 vault 中保存地址一致；不一致时停止并保留旧账号，必要时只暴露一次 `mailboxRecoveryPending`。

## 验证结果

```text
cd android && JAVA_HOME=/d/programmingSoftware/java/jdk17 ./gradlew :core:test --rerun-tasks
BUILD SUCCESSFUL in 15s
165 tests completed

cd android && JAVA_HOME=/d/programmingSoftware/java/jdk17 ./gradlew :app:assembleDebug --rerun-tasks
BUILD SUCCESSFUL in 29s
42 actionable tasks: 42 executed

get_diagnostics android
returned: 0
```

备注：构建仍有既有 AGP 提示（AGP 8.5.2 未正式声明支持 compileSdk 35）和 KAPT language-version fallback 提示，均非本批新增错误。

---

# 第三十批：Android 自动登录真机烟测与发送按钮移动端触发修复

- 日期：2026-09-20
- 性质：真机 E2E 烟测记录；登录链路已跑通并放行自动化，发送/回复闭环受 Arena 站点 429 限流阻断，未完成最终回复归档。

## 真机与安装

- 设备：`AD3JVB3921000413`，`PGT-AN10`，Android release `16` / SDK `36`。
- APK：`android/app/build/outputs/apk/debug/app-debug.apk`。
- 安装命令：`adb install -r -t app-debug.apk`，结果 `Success`。
- 实例：`111`；`files/instances/111/task-settings.json` 中 prompt 为 `1+1=`；代理为 `system`。

## 为真机烟测补充的调试 / 修复补丁

| 文件 | 处理 |
| --- | --- |
| `android/app/src/debug/AndroidManifest.xml` | 新增 debug-only `ai.arena.companion.DEBUG_SEED_ACCOUNT` receiver 声明，仅 debug 包可用。 |
| `android/app/src/debug/kotlin/ai/arena/companion/app/debug/DebugAccountSeedReceiver.kt` | 真机烟测用于通过 app 进程写入 `AccountVault(instanceDir, KeystoreCipher())`，避免生产入口暴露。 |
| `android/app/src/main/kotlin/ai/arena/companion/app/MainActivity.kt` | 增加 `AuthFlow` / `LoginTaskStart` / 自动化放行日志点（该机 logcat 仍未稳定输出 app tag，见下方限制）。 |
| `android/app/src/main/assets/PageBridge.js` | 修复移动端发送按钮触发：`HTMLElement.click()` 在 Arena 当前移动页不会实际提交；改为派发 pointer/mouse down/up/click 事件序列。 |
| `android/core/src/main/resources/web/PageBridge.js` | 与 app 端 `PageBridge.js` 同步 pointer/mouse click 修复。 |

## 账号保险库准备

1. 设置页账号弹窗路径已确认：`设置昵称和密码` → `昵称和密码设置`，字段为 `nickname` / `password` / `confirm`，本地 vault 密码策略为至少 8 位、含大写字母和符号。
2. 坐标填充保存两次未能稳定落库（`accountSummary` 仍显示“尚未设置昵称和密码。”，`account.vault` 缺失），故本次烟测改用 debug-only receiver 写入同一个 Keystore 后端：

```text
adb shell am start -n ai.arena.companion/.app.InstancePickerActivity
adb shell am broadcast --receiver-foreground \
  -a ai.arena.companion.DEBUG_SEED_ACCOUNT \
  -p ai.arena.companion \
  --es instance 111 --es nickname ArenaTest --es password ArenaTest123_

run-as ai.arena.companion ls -l files/instances/111/account.vault
# -rw------- ... files/instances/111/account.vault
# 76 files/instances/111/account.vault
```

## AuthFlow / LoginTaskStart 真机证据

启动 `MainActivity --es instance 111` 后点击“开始”，UI 连续观察到以下阶段：

1. `登录 · inspect`：正在检查 Arena 登录状态。
2. `登录 · mailbox`：已请求更改邮箱地址，正在等待新地址确认。
3. `登录 · createSubmitted`：已提交注册，等待确认邮件；Arena 页面显示邮箱 `suppusb1os@imxwe.com` 和昵称 `ArenaTest`。
4. `登录 · mail`：Arena 页面显示 “Verify your email address to continue”，并指向 `suppusb1os@imxwe.com`。
5. `登录 · return`：密码已提交，正在确认 Arena 主页面登录状态。
6. 随后 UI 进入 `第 1 轮 · confirm`，按钮从“停止登录”变为“暂停”，说明 `AuthFlow` 已达到 `phase == complete` 后退出登录 ticker，`LoginTaskStart.take(loginRunning=false, phase="complete")` 已一次性放行并创建 `RetryController`。

结论：**自动登录/注册 → 登录完成 → LoginTaskStart 放行自动化** 在真机上已跑通。

## 发送链路结果

- 修复前：`PageBridge.act("send")` 使用单纯 `el.click()`，真机页面停留在 `第 1 轮 · confirm / 已提交第 1 次，等待网页确认…`，草稿 `1+1=` 仍留在输入框，20 秒后暂停为“当前问题连续 20 秒无法确认”。
- 通过 CDP 复现：手动派发 pointer/mouse 事件序列可触发 Arena 的发送处理，证明移动端当前页需要真实 pointer/mouse 事件链。
- 修复后重新安装并点击“开始”：UI 在 `第 1 轮 · confirm` 阶段出现 Arena 站点提示：

```text
Too many requests. Please try again later.
Visit ID: 01a0bf92-c5ba-704e-8f11-5e17008b9f93
```

这说明发送按钮触发已进入站点提交路径，但站点返回 429/限流，未创建对话，`1+1=` 仍保留为草稿；没有生成回复，也没有本地 `归档` 文件。

## 证据文件

| 文件 | 内容 |
| --- | --- |
| `docs/evidence/android-auth-e2e-rate-limit-20260920.png` | 首次 E2E 后页面停在草稿/confirm 的截图。 |
| `docs/evidence/android-auth-e2e-rate-limit-20260920-window.xml` | 对应 UIAutomator XML。 |
| `docs/evidence/android-auth-e2e-rate-limit-20260920-cdp.json` | CDP 快照：`draft="1+1="`、`sendReady=true`、`conversation=false`。 |
| `docs/evidence/android-auth-e2e-after-pointerclick-20260920.png` | pointer click 修复后，Arena 显示 429 的最终截图。 |
| `docs/evidence/android-auth-e2e-after-pointerclick-20260920-window.xml` | 对应 UIAutomator XML。 |

## 验证结果

```text
JAVA_HOME=/d/programmingSoftware/java/jdk17 ./gradlew :core:test --rerun-tasks :app:assembleDebug --rerun-tasks
BUILD SUCCESSFUL in 27s
:core:test 165 tests completed
:app:assembleDebug 44 actionable tasks executed

get_diagnostics path=android
returned: 0
```

备注：该设备/ROM 的 `logcat --pid ai.arena.companion` 未稳定输出 app tag（多次只返回 HKS 块），因此真机证据以 UIAutomator dump、CDP snapshot、截图为准。

## 当前剩余阻塞

1. **未完成最终回复 / 归档闭环**：Arena 返回 `Too many requests`，未生成对话 URL / assistant 回复，因此无法验证归档、模型探针、重命名。
2. **账号设置 UI 自动填充不稳定**：手动坐标方式未成功保存 `account.vault`；本次用 debug-only receiver 种子账号。后续如需完全黑盒 UI 验证，应修复/改进设置页表单测试入口或使用更可靠的 UIAutomator 文本填充。
3. **限流时状态文案仍优先显示“当前问题无法确认”**：页面出现 429 后，`RetryController` 在 confirm 阶段先命中 prompt-confirm 超时，再处理 blocker；建议后续把 rate-limit/blocker 处理前置，给出更准确的“网站限流”状态。
4. **需待站点冷却或使用稳定既有账号重跑**：下一轮真机 E2E 应在 429 冷却后，或用已登录且未限流的真实账号，继续验证“发送成功 → 回复出现 → 模型探针 → 重命名/归档”。

---

# 第三十一批：对话区选择器按真实 DOM 重映射（B31）与会话重命名桥修复（B32）

日期：2026-09-21
性质：根因修复 + 离线回归基础设施。真机复核未做（本批无设备），见文末「验收状态」。
依据：`docs/mcp-android-prompt-confirm-timeout-20260921.md`（根因分析、arena.ai 真实 DOM 证据、§4 修复方案、§6 批次计划）。

## 背景

第三十批真机烟测停在「当前问题连续 20 秒无法确认，已暂停，不会自动重发」。根因文档证明：
`app/src/main/assets/PageBridge.js` 用 ChatGPT 风格的 `[data-message-author-role]` 系列选择器读对话区，
而 arena.ai 当前前端全站 JS 中不存在这些属性，于是 `promptConfirmed` / `conversation` / `response` /
`completionConfirmed` / `generationStamp` / `messageIdentity` 在真机上恒为空；阶段机（与 C# `RetryController.Tick.cs`
第 78-80 行逐句一致）按原语义在 20 秒后暂停。**阶段机不改**，只改页面桥，并补上桌面端一直有、安卓移植时丢掉的 jsdom 回归。

## 交付

| 文件 | 处理 |
| --- | --- |
| `android/app/src/main/assets/PageBridge.js` | 重写对话区读取（`version: 3`）。对话区 = `main [role="log"]`；消息 = `[data-agent-transcript-message][data-chat-message-id]`（只取最外层）；用户消息 = 含 `[data-user-message-layout]` 的消息，取最后一条；回答 = 其后最后一条非用户消息。`promptConfirmed`：用户消息（优先 `[data-user-message-body-row]`）内某节点的 NFC + 空白折叠文本 **等于提示词或以「提示词 + 空格」开头**，无角色标记时回退到对话区文本前缀；禁止子串匹配。`generating` = main 内可见且未禁用的 `Stop generating` 按钮；`activity` = generating 或回答范围内可见的 `[aria-busy]/[role=progressbar]/.animate-spin`（排除 `pre,code`）；`completionConfirmed` = 有回答 + 提示词已确认 + 无活动 + 回答内出现 `Copy` 类按钮（或 `data-state` 完成态）；`failed` 只看回答范围（无回答时看对话区）内的 `[role=alert]` / `[role=status]` / `data-state` 错误态，全局 alert 不再让本轮作废；`generationStamp` = 桌面端 `__arenaGenerationTracker`（发送 / 回车 / Regenerate / Retry 点击与生成上升沿自增的 revision）+ 用户消息数 + 两条消息的 `data-chat-message-id` + `responseSignature`；`messageIdentity` = 用户消息的 `data-chat-message-id`；`progressSignature` 覆盖用户消息之后的全部消息；`responseSignature` 生成中为空。`blocker` 的限流 / 人机验证判定改为只看 alert / status / dialog / toast 与 main 中对话区、输入框、代码块以外的文本，回答正文里的 "rate limit" / "请稍后" 不再触发暂停。`sendReady` 追加 `aria-disabled` 判定，新增 `act('stop')`，`attachmentNames` 按桌面端 `Remove <name>` 规则读取（B35 用）。输入框 / 发送 / New Chat / 侧栏展开 / 条款弹窗 / pointer 点击序列保持第二十八至三十批的真机校准结果不动。 |
| `android/app/src/main/assets/ModelRename.js` | 按桌面端 `assets/ModelRename.js` 逐句移植（`version: 3`），保留安卓 API `__ARENA_RENAME_BRIDGE__.act(action, value, target)` 与 `WebViewRenameExecutor.kt` 的字段约定。会话链接按与 `ConversationIdentity.created()` 同构的 `key()` 规范化后与目标精确匹配（不再用 `links[0]`）；菜单按钮 = 当前链接同级（或 shadcn `li[data-sidebar="menu-item"]` 内）标签严格为 `More options` 的按钮；菜单项 `[role=menuitem]`（或 `[role=menu]` 内按钮）标签严格为 `Rename`；重命名对话框标题按 `aria-labelledby` → 首个标题元素 → 整段文本匹配 `^Rename chat\b`，提交按钮 `Rename`、关闭按钮 `Cancel`；所有点击统一派发 `pointerdown → mousedown → pointerup → mouseup → click`（Radix 菜单靠 pointerdown 打开，第三十批证明移动页 `el.click()` 不触发）；输入框走原生 setter + `input`；保留 `<768px` 侧栏 Radix Sheet（`role=dialog[data-sidebar="sidebar"][data-mobile="true"]`）不算外来弹窗、其余弹窗 fail-closed 的桌面端语义；侧栏折叠时只点一次唯一的展开按钮并返回 `pending`。 |
| `android/core/src/main/resources/web/PageBridge.js` | 删除。它是一份已漂移的旧副本，`ProbeBridge.kt` 只从 `app/src/main/assets` 读脚本，任何代码都没有引用它。 |
| `android/app/src/test/js/fixture.cjs` | jsdom 夹具：补 `getBoundingClientRect` / `getClientRects` / `innerText` / `scrollIntoView` / `PointerEvent`，规则是「自身或祖先 hidden / display:none 即不可见」；视口按手机竖屏 412×915；jsdom 优先 `require('jsdom')`，未安装时回退复用 `reference/Arena模型助手-源码-fyb-0.1.0/tests/node_modules` 里的 26.1.0。 |
| `android/app/src/test/js/page-bridge.test.cjs` | 29 个用例，fixture 按根因文档 §3 的真实结构手写：空白新对话、草稿就绪、流式中、空壳助手消息、回答完成（Copy）且签名稳定、进度签名随内容变化、无 Stop 按钮的思考态、代码块内 spinner、回答内 alert / 用户消息下 alert 判 failed、对话区外 alert 不判 failed、多轮取最后一组、换行 / 全角空格 / NBSP 归一化、子串不算确认、附件名后缀、无角色标记的旧 DOM 回退、嵌套消息包装、限流提示进 blocker 而回答正文不进、人机验证弹窗、条款弹窗与 Agree、`act('send')` 的 pointer 序列与 revision 自增、生成上升沿、侧栏里的 Stop 不算生成、New Chat 唯一性、侧栏展开唯一性、附件 Remove 按钮、无 main 不崩。 |
| `android/app/src/test/js/rename-bridge.test.cjs` | 33 个用例：桌面端 `tests/rename-bridge.test.cjs` 全部 17 条逐条移植到安卓 API，另补 16 条：`state()` 快捷方式、`target=null` 取当前地址、只点当前会话的 More options 而不是第一条、shadcn menu-item 包装、`aria-label*="menu"` 类按钮不算、折叠侧栏只点一次展开并 pending、展开按钮不唯一拒绝、菜单项检测与点击、菜单项缺失 / 重复拒绝、已打开菜单阻止 openMenu 且 cleanup 用 Escape 关闭、`aria-labelledby` 识别对话框与原生 setter 填值、空 / 超长 / 非唯一输入拒绝、保存按钮点击一次且禁用拒绝、非重命名对话框不误判、hidden 元素忽略、未知动作与身份缺失报错。 |
| `android/app/src/test/js/run-all.cjs`、`package.json` | 顺序跑两个套件，任一失败退出码非 0；`npm test` 与 Gradle 共用。 |
| `android/app/build.gradle.kts` | 新增 `bridgeJsTest`（Exec）并挂到 `preBuild`：构建 APK 前自动跑 jsdom 回归；PATH 上找不到 node 时跳过并 warn，`-PnodeExecutable=` 指定解释器，`-PskipBridgeJsTest=true` 显式跳过。 |
| `android/README.md` | 状态段改为分项说明校准状态；新增「页面桥离线回归」一节。 |

## 关键语义与取舍

1. **只改页面桥，不改阶段机。** `RetryController.kt` 第 336-342 / 248-254 行与 C# 一致，保持不动。限流发生在提示词出现之前（第三十批的 429 情形）时，C# 与安卓都会先命中 20 秒「无法确认」再轮到 blocker，这是桌面端原有顺序，本批不重排（第三十批剩余阻塞第 3 条仍开着）。
2. **提示词确认改成"完整前缀"而不是子串。** 旧实现 `indexOf(prompt) >= 0` 会把 `1+1=` 匹配进任何包含它的文本；新实现要求用户消息内某节点的归一化文本等于提示词或以「提示词 + 空格」开头，动作条 sr-only 文本排在气泡前面时也能确认（用例覆盖）。
3. **`response` 的空壳问题。** 助手气泡刚挂载、只有头部标签时 `response` 可能为 true（与桌面端 `answer.innerText` 语义一致）；阶段机完成路径还要求 `!generating && !activity` 且 `responseSignature` 连续 10 秒不变，生成中签名恒为空，所以不会提前完成。没有把头部行按类名剔除，是因为站点头部无稳定属性，按启发式剔除反而可能把 `<div>2</div>` 这种短回答误删掉。
4. **两套可见性。** 可交互目标（输入框 / 发送 / New Chat）沿用真机校准的严格版 `visible()`（含 opacity）；对话区节点与完成证据按钮用桌面端语义的 `shown()`（不看 opacity），因为动作条常用 `opacity-0` + hover 显示。
5. **`conversation = 对话区文本非空`**（桌面端语义）而不是 `messages.length > 0`：角色标记再变也不会让 `fill` / `send` 的「必须是空白新对话」守卫失效。代价是若空白页也渲染了带文字的 `[role=log]`，`waitNew` 会 20 秒后暂停——这是真机 CDP 复核清单第 1 条。
6. **回归用例先在旧脚本上跑过一遍**：29 条里 21 条失败，包括「流式中 promptConfirmed 应为 true」——正是本次根因；说明这套用例能挡住同类回归。

## 验证结果

```text
# 沙箱（node 20 + jsdom 26.1.0）与 Windows 宿主（node 24 + reference jsdom 26.1.0）结果一致
node run-all.cjs
PageBridge regression passed: 29 checks
Rename bridge passed: 33 checks

cd android && JAVA_HOME=/d/programmingSoftware/java/jdk17 ./gradlew :core:test :app:assembleDebug
BUILD SUCCESSFUL in 56s
:core:test 165 tests, 0 failures, 0 errors
app/build/outputs/apk/debug/app-debug.apk  6569787 bytes  2026-09-21 19:57
  assets/PageBridge.js  21258 bytes（含 data-agent-transcript-message）
  assets/ModelRename.js 11891 bytes（含 More options）

./gradlew :app:bridgeJsTest
> Task :app:bridgeJsTest
PageBridge regression passed: 29 checks
Rename bridge passed: 33 checks
BUILD SUCCESSFUL in 6s

get_diagnostics path=android
returned: 0
```

## 验收状态与真机复核清单（B31 §4.3 第 2、3 条，待有设备时执行）

本批完成 B31 / B32 的代码与离线回归，**未完成真机验收**。安装 `app-debug.apk` 后按第二十八批 CDP 通道执行：

1. 空白 `/agent` 页：`JSON.stringify(__ARENA_PAGE_BRIDGE__.snapshot("1+1="))` 期望 `version` 为 3（`__ARENA_PAGE_BRIDGE__.version`）、`main=true`、`conversation=false`、`editor=true`、`newLinks=1`。若 `conversation=true`，记录 `document.querySelector('main [role="log"]').innerText`，按取舍第 5 条调整。
2. 手工发送「1+1=」后：流式期间 `promptConfirmed=true`、`generating=true`、`responseSignature=""`；结束后 `response=true`、`completionConfirmed=true`、`responseSignature!=""`、`messageIdentity` 等于 `document.querySelector('[data-agent-transcript-message]').dataset.chatMessageId`。若 `promptConfirmed=false`，导出用户消息 `outerHTML` 对照 `page-bridge.test.cjs` 的 `userMsg` fixture。
3. 侧栏：`__ARENA_RENAME_BRIDGE__.act('state','',null)` 期望 `linkCount=1`、`title` 为当前会话标题；`act('openMenu','',null)` 后 `state().renameMenu=true`；`act('menuRename')` 后 `renameDialog=true`；`act('cleanup')` 能关闭。
4. 阶段机 E2E：「开始」后 UI 依次出现 `第 1 轮 · confirm` → `observe（第 N 次：等待回答…）` → `回答已完成，正在读取本轮的模型名…` → `model` → `rename` → `collect`。若停在 `model`，进入 B33。
5. 证据落到 `docs/evidence/android-e2e-<date>-*.{png,xml,json}`，记入进度文档。

## 已知未覆盖

- 用户消息被站点折叠（长提示词 + "Show more"）时 `promptConfirmed` 会为 false；桌面端相同，默认提示词 `1+1=` 不受影响。
- 附件在用户消息中的渲染位置未知（B35）；当前只保证「气泡文本 = 提示词」或「提示词 + 空格 + 其他」两种形态。
- `thinking` 仅作诊断，依据是回答范围内标签以 Thinking / Thought / 思考 开头的按钮或 `[role=status]`。
- `WebViewArenaPage.parse()` 仍不解析 `attachmentNames` / `conversationAttachments`（B35 接线时一并处理）。

---

# 第三十二批：未保留模型网站归档移植（B34）、运行参数接线与入库整理（B35 部分）

- 日期：2026-09-21
- 性质：代码移植 + 离线回归 + 构建验证；**无真机**。B34 全部代码落地，B35 完成 git 收录 / `nul` 清理 / 附件字段解析，附件上传本身未做。
- 依据：`docs/mcp-android-prompt-confirm-timeout-20260921.md` §6 B34 / B35；桌面端 `WebPage.ModelArchive.cs`、`assets/ModelArchive.js`、`MainForm.ModelRetention.cs`。

## 背景

第三十一批之前，`RetryController.retentionPolicy` 一直是默认的 `KEEP_ALL`，`websiteArchive` 为 null：
设置页里勾选「要归档的模型」没有任何效果；即使策略生效，阶段机走到 `websiteArchive` 阶段也会因为
「网站归档不可用」直接暂停。轮次上限、无进展上限、模型名等待三个参数则写死为 0 / 300 / 150。
本批把这条链路补全，并把安卓源码收进 git。

## 交付

| 文件 | 变更 |
|---|---|
| `android/app/src/main/assets/ModelArchive.js` | 新增。桌面端 `assets/ModelArchive.js` 逐句移植：状态机 open → menu → sent → confirmSent，状态挂 `window.__arenaModelArchiveState` 并按 token 隔离；成功证据 = toast 文案或「当前行确实消失且稳定 1.5 秒」。差异：快照取自 `__ARENA_PAGE_BRIDGE__.snapshot()`；点击统一 pointer 序列；移动端 Radix Sheet 侧栏不算外来弹窗；不认 arena-demo.local。导出 `window.__ARENA_ARCHIVE_BRIDGE__ = {version: 1, step, reset, selectors}` 并保留 `window.__arenaModelArchive` 别名。 |
| `android/core/src/main/kotlin/ai/arena/companion/automation/WebsiteArchiver.kt` | 新增。对 `WebPage.ArchiveModelConversation`：同一目标复用一个 token，每 250 ms 一步、最多 120 步；`active()` 为假 / 页面离开 arena / 桥返回 error / 超时均以异常结束，绝不重试点击；步后暂停抛 `ArchivePausedException`。 |
| `android/core/src/main/kotlin/ai/arena/companion/data/ObservedModelNames.kt` | 新增。对桌面端 `model-observed-names.json`：每轮完成记录模型名，过滤规则复用 `ModelRetentionCatalog.withObserved`（空名 / 超长 / 控制字符 / 「未识别…」「演示模型…」不记），读失败视为空，原子写入。 |
| `android/core/src/main/kotlin/ai/arena/companion/data/TaskSettings.kt` | 新增 `roundLimit`（默认 0 = 不限）、`maximumNoProgressSeconds`（300）、`modelWaitSeconds`（150）；`normalized()` 在 load / save 时把越界值收回下限（0 / 60 / 30）。旧配置文件无这三个键时按默认值读取。 |
| `android/app/src/main/kotlin/ai/arena/companion/app/WebViewArchiveBridge.kt` | 新增。一步 = 一次 `evaluateJavascript("JSON.stringify(__ARENA_ARCHIVE_BRIDGE__.step(...))")`，解析为 `ArchiveStepResult`；超时返回 error 而不是 null。 |
| `android/app/src/main/kotlin/ai/arena/companion/app/MainActivity.kt` | `startAutomation()`：`retentionPolicy = 目录.policy(settings.excludedModels)`（目录 = 本地归档模型名 ∪ 观察缓存）、`websiteArchive = archiver.archive(url, prompt, stamp, active)`、`maximumNoProgressSeconds` / `modelWaitSeconds` 来自设置、`onRoundCompleted` 记录观察名、`start(prompt, settings.roundLimit)`。 |
| `android/app/src/main/kotlin/ai/arena/companion/app/ProbeBridge.kt` | document-start 注入追加 `ModelArchive.js`。 |
| `android/app/src/main/kotlin/ai/arena/companion/app/SettingsActivity.kt`、`res/layout/activity_settings.xml` | 新增三个输入框（轮次上限 / 无进展上限 / 等待模型名）；非整数或低于下限时整体不保存（与代理校验同一原则）；「要归档的模型」候选目录改为 归档 ∪ 观察缓存。 |
| `android/app/src/main/kotlin/ai/arena/companion/app/WebViewArenaPage.kt` | `parse()` 解析 `attachmentNames` / `conversationAttachments`（B35 前置）。 |
| `android/app/src/test/js/archive-bridge.test.cjs`、`run-all.cjs`、`package.json` | 新增归档桥离线回归 29 例并纳入 `npm test` / `:app:bridgeJsTest`。 |
| `android/core/src/test/kotlin/ai/arena/companion/{WebsiteArchiverTest,ObservedModelNamesTest,TaskSettingsTest}.kt` | 新增 8 + 4 + 2 例。 |
| `android/.gitignore`、`android/README.md` | `!**/data/` 放回被根 `.gitignore` 的 `data/` 规则误忽略的源码目录；README 补运行参数表、归档桥状态、入库注意。 |
| 仓库根 `nul` | 已删除（Windows 保留设备名，需 `\\?\` 路径删除）。 |

## 关键语义与取舍

1. **保留策略目录没有内置清单。** 桌面端有 `assets/model-catalog.json`，安卓端沿用第二十几批的决定：目录只来自
   观察到的名字。后果是「被勾选归档的模型」若既没有本地归档、也不在观察缓存里，策略会静默退回保留——
   这正是 `ModelRetentionPolicy.excludes` 的第 4 个条件（未知模型默认保留），所以补了 `model-observed-names.json`
   让被网站归档（因此不存本地）的模型名也留在目录里。
2. **网站归档失败一律暂停，不改用删除、不点 Undo。** `WebsiteArchiver` 与 `ModelArchive.js` 的每一条 error 文案与桌面端一致；
   `RetryController.archiveExcludedModel` 未改动。
3. **菜单归属判定保留桌面端的严格版本**：触发器必须带 `aria-expanded="true"`，菜单优先按 `aria-controls` 定位，
   找不到时只接受唯一一个可见 `[role="menu"]`。重命名桥（B32）没有这一层是因为它的后果可回退；归档虽可 Undo，但 Undo 不由我们点。
4. **成功证据**：toast 正则沿用桌面端；「当前行消失」证据要求原始链接脱离文档、无替身（隐藏的也不行）、New Chat 唯一可见、
   没有展开侧栏按钮、没有菜单 / 对话框 / progressbar，稳定 1.5 秒。手机侧栏若在归档后自动收起，这条证据不会成立，只能靠 toast。
5. **运行参数下限**：无进展 60 秒、模型名等待 30 秒，是阶段机能正常工作的最小值（阶段机内部本来就有 `max(60, …)`）；
   0 轮次 = 不限，与桌面端「收集后继续」勾选等价。Room 层的 `TaskSettingsEntity` 未加列（JSON 存储是唯一实际读写路径）。
6. **附件（B35）只做了字段解析**。上传需要 `WebChromeClient.onShowFileChooser` 把绑定文件的 URI 交给页面的 `<input type=file>`，
   并实现 `RequestPreparation.prepare()/check()`；没有真机无法验证，本批不做。

## 验证结果

```text
node run-all.cjs                              PageBridge 29 / Rename bridge 33 / Archive bridge 29 checks passed
./gradlew :core:test                          179 tests, 0 failures（第三十一批 165 → +14）
./gradlew :app:assembleDebug                  BUILD SUCCESSFUL；:app:bridgeJsTest 在 preBuild 执行并通过
APK                                           android/app/build/outputs/apk/debug/app-debug.apk（2026-09-21 20:18 起，含 assets/ModelArchive.js 14516 B）
git status --short --ignored android          仅 .gradle/ .kotlin/ build/ local.properties 被忽略
git commit 82a8eab4（main）                   android/ + docs/evidence/ + docs/mcp-android-*.md 共 130 个文件入库；未推送，未触碰其他已改动 / 已暂存文件
```

## 验收状态与真机复核清单

- [x] B34 代码：`retentionPolicy` 接线、`ModelArchive.js` + `websiteArchive` 移植、三个运行参数进设置页。
- [ ] B34 真机：勾选一个已观察到的模型 → 该模型回答完成后应出现「模型「…」未勾选保留，准备仅移入 Arena 网站归档」→
      侧栏 More options → Archive →（若有）确认框 → toast「Your previous chat history was archived」→ 状态「已确认移入网站归档，未保存本地」，
      且本地归档不新增记录、`websiteArchivedRounds` 加一。
- [ ] B34 真机：Archive 菜单项文案 / 确认框标题若与 `ARCHIVE` / `ARCHIVE_DIALOG` 正则不符，先用 CDP 抓 DOM 再改正则，不放宽为包含匹配。
- [x] B35：`android/`（含 `data/` 源码目录）与 `docs/mcp-android-*.md`、`docs/evidence/` 收进 git；根 `nul` 删除。
- [x] B35：附件上传（`RequestPreparation` + `onShowFileChooser`）——第三十三批完成代码，见下。

## 已知未覆盖

- 未观察到任何模型名前，设置页无法勾选归档模型（提示先跑一轮），这是有意为之，不自造清单。
- `ModelArchive.js` 的「当前行消失」证据在移动端可能永远不成立（侧栏 Sheet 收起后 New Chat 不可见），届时只有 toast 一条路。
- B33（模型阶段真机验证）仍需设备。

---

# 第三十三批：附件上传移植（B35 收尾）

- 日期：2026-09-21
- 性质：代码移植 + 离线回归 + 构建验证；**无真机**。B35 最后一项「附件随消息上传」代码落地，§6 计划表 B31–B35 至此全部有实现。
- 依据：`docs/mcp-android-prompt-confirm-timeout-20260921.md` §6 B35；桌面端 `src/AttachmentUpload.cs`、
  `assets/PageBridge.js`（`attachmentsReady`）、`RetryController.Tick.cs` L130-L136、`RetryController.RateLimit.cs` L88-L95、`MainForm.TaskSettings.cs` `PrepareTask`。

## 背景

第三十二批之后 `RetryController` 的 `preparation` 仍为 null：设置页绑定的附件只是落盘，阶段机从 `fill` 直接到 `send`，
`prepare` 分支和发送前 `check()` 从未被走到。桌面端的实现依赖 CDP `DOM.setFileInputFiles` 把文件直接塞进 `<input type=file>`；
安卓 WebView 没有这条路，唯一的交付口是 `WebChromeClient.onShowFileChooser`，而 Blink 只允许**用户激活**触发文件选择——
脚本里 `input.click()` 无效。本批据此设计了安卓版交付链路，其余语义与桌面端逐句对齐。

## 交付

| 文件 | 变更 |
|---|---|
| `android/app/src/main/assets/PageBridge.js` | version 3 → 4。新增 `attachmentsReady(names)`（对桌面端同名函数：`Remove <name>` 集合与绑定名严格相等、main 内无 progressbar / animate-spin）与 `attachmentEntry()`（对桌面端 `Stage` 的定位脚本：main 可见、对话区无文字、父级可见的 `input[type=file]` 恰好一个，打 `data-arena-bound-upload` 标记；额外给出可触摸入口的视口坐标 / visualViewport 偏移 / scale / dpr）。入口按 input 自身可见 → `label[for]` → 包裹 label → 同父容器唯一按钮 → main 内标签匹配 `ATTACH_LABEL` 的唯一按钮 依次解析，都不成立则 `trigger:false`。 |
| `android/core/src/main/kotlin/ai/arena/companion/automation/AttachmentUpload.kt` | 新增 `AttachmentEntry`、`AttachmentPage`（ready / entry / deliver 三个页面能力）与 `AttachmentUpload : RequestPreparation`。`configure` 三项全查并重置 `submitted`；`check` 在 Required 时先 `ensureArena`（只认 `https://arena.ai/agent` 与 `/agent/<uuid>`）；`prepare` = check → 未就绪且本轮未投递才 `stage()` 一次；`stage` 要求 `entry.count == 1` 且 `trigger`，`deliver` 返回 false 抛「附件入口已变化」。错误文案与 C# 一致。 |
| `android/core/src/main/kotlin/ai/arena/companion/automation/RetryController.kt` | `fill` 阶段：`preparation?.required == true` 时 `move("prepare")`，否则照旧 `move("send")`。这是本批对阶段机的唯一改动；桌面端在 `Configure` 时就已用 CDP 塞好文件，所以 L127 直接进 `send`，安卓的投递必须发生在草稿填好、发送之前。`prepare` / `send` / 限流重试里的既有附件分支未动。 |
| `android/app/src/main/kotlin/ai/arena/companion/app/WebViewAttachmentPage.kt` | 新增。`ready` / `entry` 各一次 evaluate；`deliver`：用 `FileProvider` 生成只读 `content://`，武装回调 → 主线程向 WebView 派发 `ACTION_DOWN`/`ACTION_UP`（CSS px → 减 visualViewport 偏移 → 乘 scale × dpr）→ 等 `onShowFileChooser` 最多 4 秒。回调里再核 URL 在 arena.ai/agent、单选 input 不接受多文件，不符交 null。未武装时回调返回 false。 |
| `android/app/src/main/kotlin/ai/arena/companion/app/MainActivity.kt` | `attachmentPage.install()`；`startAutomation` 前 `AttachmentUpload.configure(settings.attachments)`，校验失败 toast 并 `releaseSession()` 阻止启动（对 `PrepareTask`）；`RetryController(..., preparation = upload)`。 |
| `android/app/src/main/AndroidManifest.xml`、`res/xml/attachment_paths.xml` | 新增 `FileProvider`（`${applicationId}.attachments`，`exported=false`，`files-path .`）。 |
| `android/app/src/test/js/page-bridge.test.cjs` | 29 → 38 例：attachmentsReady 3 例（空清单 / 严格集合相等 / 进度条与 log 内 Remove 不算）、attachmentEntry 6 例（无 main / 有对话 / 无 input / 双 input 歧义不打标记 / 隐藏父级忽略 / label[for] / 同级唯一按钮 / 标签回退 / 绝不选 Send）。 |
| `android/core/src/test/kotlin/ai/arena/companion/{AttachmentUploadTest,RetryControllerTest}.kt` | 新增 6 + 5 例：无附件直通 send、有附件进 prepare 且就绪前绝不 send、prepare 60 秒暂停、send 前 check 失败暂停、stage 抛错 → 「操作已暂停：…」；AttachmentUpload 的 configure / 每轮一次投递 / 域名限制 / 入口与交付失败文案 / verify 失败不投递。 |
| `android/README.md` | 附件状态改为「已移植、真机未验证」，补「附件交付（B35）」步骤表。 |

## 关键语义与取舍

1. **交付方式是安卓唯一的实质差异。** 桌面端 `Configure` 时就把文件塞进 input，`prepare` 只是兜底；安卓必须在 `fill` 之后、
   `send` 之前由页面打开文件选择再回填，所以 `fill` 在有附件时转 `prepare`。没有附件（`required == false`）或未注入 `preparation`
   时，阶段序列与桌面端逐字相同，第三十一批之前的所有 `RetryControllerTest` 用例未改一处。
2. **真实触摸，不是 `click()`。** Blink 的文件选择需要 transient user activation；`dispatchTouchEvent` 走的是与用户手指相同的输入管线，
   页面收到的是可信事件。坐标换算 `((x - visualViewport.offsetLeft) * scale * devicePixelRatio)` 假设 WebView 以 1:1 显示，
   落点超出 `webView.width/height` 直接返回 false 不触摸。这一步真机上最可能出偏差，README 已标注。
3. **回调只在 4 秒武装窗口内有效，且只消费一次。** 窗口外 `onShowFileChooser` 返回 false（等于之前没有 WebChromeClient），
   避免「用户自己点了附件按钮，我们的文件被塞进去」。回调到来还要再核 URL 与单多选兼容——`FileChooserParams.mode` 不是
   `MODE_OPEN_MULTIPLE` 而绑定了多个文件时交 null 并按失败暂停，不会只传第一个。
4. **入口定位宁缺毋滥。** `attachmentEntry` 对 input 的要求与桌面端 `Stage` 相同（唯一 + 父级可见 + 空白新对话）；触发器五级回退里
   每一级都要求唯一命中，`ATTACH_LABEL` 只是最后一级，且排除 `[role=log]` 内按钮，绝不会落到 Send / Stop 上（有回归用例）。
   找不到触发器抛「附件入口无法触发」而不是猜。
5. **`ensureArena` 放行 `/agent/<uuid>`**（桌面端 `AbsolutePath.StartsWith("/agent/")` 同义）：限流重试时草稿在同一会话里恢复，
   `check()` 会在会话页被调用。
6. **`FileProvider` 路径 `files-path .`**：附件副本在 `<filesDir>/instances/<实例>/Attachments/<sha256>/<name>`，provider 不导出、
   URI 只随回调交给 WebView 进程内的 Blink，不授予外部应用。

## 验证结果

```text
node run-all.cjs                              PageBridge 38 / Rename bridge 33 / Archive bridge 29 checks passed
JAVA_HOME=jdk17 ./gradlew :core:test          190 tests, 0 failures（第三十二批 179 → +11）
JAVA_HOME=jdk17 ./gradlew :app:assembleDebug  BUILD SUCCESSFUL；:app:bridgeJsTest 在 preBuild 执行并通过
APK                                           android/app/build/outputs/apk/debug/app-debug.apk（2026-09-21 21:13，含 assets/PageBridge.js 25582 B、res/xml/attachment_paths.xml）
```

## 验收状态与真机复核清单

- [x] B35 代码：`AttachmentUpload` / `WebViewAttachmentPage` / `PageBridge.attachmentsReady + attachmentEntry` / `fill → prepare` 接线 / FileProvider。
- [ ] B35 真机：设置页绑定 1 个图片 → 开始 → 状态应依次为「正在检查页面」→（fill）→ prepare 期间页面弹出文件选择随即自动关闭 →
      输入区出现该文件缩略图与「Remove <name>」→ 「已提交第 1 次」。若卡在 prepare 60 秒后暂停「附件上传尚未确认」，
      先用 CDP 执行 `__ARENA_PAGE_BRIDGE__.attachmentEntry()` 看 `count` / `trigger` / `label` / 坐标，再决定是改入口规则还是坐标换算。
- [ ] B35 真机：绑定 2 个文件，确认 Arena 的 input 是 `multiple`（否则会按「只接受单个文件」暂停，这是预期行为）。
- [ ] B35 真机：手动点页面自己的附件按钮，确认弹出的是系统选择器而不是被我们的文件填充（武装窗口外回调必须返回 false）。
- [ ] B33 / B34 真机项沿用第三十一、三十二批清单。

## 已知未覆盖

- `attachmentEntry` 的触发器规则与坐标换算都没有在真机 DOM 上校准过；Arena 若把附件按钮做成 `[role=menuitem]` 或放在
  Radix Popover 里（点开才有 input），当前规则会得到 `count: 0, reason: 'no input'` 并暂停，需要按真机 DOM 补一级「先打开菜单」。
- 限流重试路径的附件分支（`RateLimit` L88-L95 对应代码）本批未加单测；逻辑未改，但 `retryPrepared` 与新的 `submitted`
  守卫叠加后，每次 cooldown 至多再投递一次。
- `WebViewAttachmentPage` 没有 instrumentation 测试（需要设备）。

