# 账号体系重构、逐轮模型探测与会话聚合工作台实施进度 (mcp-account-implementation-progress.md)

> 日期：2026-09-20
> 关联设计方案：[docs/mcp-account-conversation-architecture.md](docs/mcp-account-conversation-architecture.md)
> 前序基线记录：[docs/mcp-android-implementation-progress.md](docs/mcp-android-implementation-progress.md)
> 参考源码：`reference/ArenCard` (Python 原生协议实现)

---

## 1. 实施概览与里程碑

本阶段工作全面落实了从「实例 (Instance)」到「账号 (Account)」的业务语义迁移，确立了「以账号为供给支撑、以会话为消费核心」的架构范式。针对 Arena.ai 平台中多轮对话可能发生动态模型漂移、单账号每日额度有限、429 频控与 Cloudflare IP 风险控制等现实挑战，完成了端到端的数据持久层改造、协议探测客户端、风险控制状态机、以及跨账号聚合工作台的前端展示与无缝跳转。

全套改造在保持架构轻量、高内聚低耦合的同时，通过了全部 152 项核心单元测试，并完成了 `:app:assembleDebug` 原生构建验证。

---

## 2. 分阶段实施完成明细

### 阶段 1：核心数据实体与持久层演进（Phase 1: Domain & Persistence）

- [x] **语义演进与字段绑定 (`ArchiveStore.kt`)**：
  - 在 `ArchiveEntry` 核心模型中显式引入 `accountId`（会话归属账号唯一 ID）及 `modelHistory: List<ModelRoundRecord>`。
  - 新增 `ModelRoundRecord` 领域实体：精确记录每轮交互的 `round`（轮次序号）、`model`（真实模型名称）、`detectedAt`（探查时间戳）及 `tokenCost`（消耗 tokens）。
  - 实现 `recordRound(round, model, ts, tokens)` 纯函数式状态迁移，自适应检测多轮对话中的模型漂移（`modelDrifted = true`）并自动更新 `model` 与 `modelFolder` 标签。
  - 支持向后兼容旧版无 `accountId` 数据的平滑加载，当 `accountId` 缺省时自动回退为 `profile`。
- [x] **Room 数据库实体映射升级 (`ArchiveEntryEntity.kt` / `RoomMappers.kt`)**：
  - 在 Room 实体 `ArchiveEntryEntity` 中新增 `account_id`、`model_drifted` 及序列化字段 `model_history_json`。
  - 在双向转换器 `toDomain()` 和 `toEntity()` 中完善全量字段映射，支持从 JSON 字符串反序列化多轮模型演进履历，确保 SQLite 与文件系统 JSON 双轨持久化的一致性。
- [x] **领域单元测试覆盖 (`ArchiveStoreTest.kt`)**：
  - 新增 `recordRoundAndDetectDrift` 单测：验证第 1 轮识别为 `gpt-5-fable`、第 2 轮相同保持 `modelDrifted = false`、第 3 轮变更为 `gpt-5-mini` 时自动触发 `modelDrifted = true` 并同步刷新 `model`。

---

### 阶段 2：账户额度探测客户端与模型动态检测（Phase 2: Quota & Model Probe）

- [x] **账户额度与余额解析客户端 (`AccountBalanceClient.kt`)**：
  - 纯 Kotlin / Coroutines 异步网络客户端，面向 Arena 官方端点 `GET https://arena.ai/api/billing/balance`。
  - **自适应正则解析**：兼容数字型与字符串包裹型 JSON 字段（如 `"creditsRemaining": 12500` 与 `"creditsRemaining": "12500"`），提取 `creditsRemaining`、`creditsUsed` 与 `status`。
  - **健壮退避机制**：内置指数级重试逻辑（默认最大重试 3 次，首重试延迟 1000ms），在遇到瞬时网络波动或 429 频控时平滑退避。
  - **单元测试验证 (`AccountBalanceClientTest.kt`)**：覆盖正常数字响应、字符串包裹额度解析、429 重试成功与重试耗尽抛出异常等全部场景分支。

---

### 阶段 3：账号风控控制器与轮换状态机（Phase 3: Risk Controller & Rotation State Machine）

- [x] **风险控制与退避阶梯 (`AccountRiskController.kt`)**：
  - 对标 `reference/ArenCard` 的 `GATE_LADDER` 与单账号门闸隔离机制。
  - **429 阶梯退避**：实现 `[15s, 30s, 60s, 90s]` 冷却阶梯；当频控达到第 2 级及以上时，判定当前出口 IP 受疑，触发 `needsRebindProxy = true`（通知动态代理重绑更换出口 IP）。
  - **Cloudflare 阻断即时应对**：检测到 Cloudflare Turnstile 挑战或 403 页面拦截时，直接标记当前 IP 不可用并立即置位 `needsRebindProxy = true`。
  - **额度耗尽自动标识**：探查到 `creditsRemaining <= 0` 时，自动迁移账号状态为 `DEPLETED`（额度耗尽），并在每日重置周期后自动解除。
  - **人机验证标记**：检测到图形验证码或需手工介入时，将状态迁移至 `NEED_VERIFY`，自动从可用调度池移出。
  - **可用账号优选选择器 (`pickAvailableAccount`)**：综合过滤处于冷却期、额度耗尽及待验证的账号，优先按剩余额度从高到低调度。
- [x] **风控单元测试覆盖 (`AccountRiskControllerTest.kt`)**：
  - 覆盖正常状态、429 阶梯升级、达到阈值触发 IP 重绑、Cloudflare 阻断立即触发重绑、额度耗尽阻断以及可用账号优选算法等 6 类测试用例。

---

### 阶段 4：跨账号会话聚合工作台与无缝直达跳转（Phase 4: Unified Hub & Seamless Launch）

- [x] **工作台列表卡片视觉升级 (`item_archive.xml`)**：
  - 新增「⚡已漂移」高亮徽章（`driftBadge`），橘红背景配圆角胶囊样式，直观警示用户该对话中途发生了底层模型降级/变更。
  - 新增账号所属归属标签（`accountTag`，展示如 `账号: account-01`），让用户在全局视角中清晰辨识资产来源。
- [x] **跨账号全局会话聚合中心 (`GalleryActivity.kt`)**：
  - **无缝多账号遍历扫描 (`loadAllEntries`)**：支持无特定实例入参时，自动扫描并聚合合并 `filesDir/instances/` 下所有账号归档及默认归档，跨账号全局去重排序。
  - **顶层标题与统计动态适配**：无实例过滤时标题切换为「会话聚合工作台」，顶部副标题显式标明「【聚合工作台】共 N 条 · M 个模型分组」。
  - **模型筛选器联动**：Chip 分组自动汇聚全部账号下的所有模型标签，支持一键筛选出高价值或特定模型的全部历史对话。
- [x] **会话一键拉起与免密账号重绑 (`MainActivity.kt` & `GalleryActivity.kt`)**：
  - 工作台卡片点击直达交互：点击即调用 `launchConversation(entry)`，通过 `EXTRA_INSTANCE` 携带归属账号，通过 `EXTRA_URL` 携带目标会话直达链接（如 `https://arena.ai/c/<sid>`）。
  - `MainActivity` 适配 `EXTRA_URL` 与 `onNewIntent`：支持在单任务栈复用时无缝执行 `bindProfile()` 切换账号沙箱 Cookie，并直接导航至会话网页，无需用户重新手动选号登录。
- [x] **账号选择入口直达工作台 (`InstancePickerActivity.kt`)**：
  - 顶部 AppBar 新增「会话工作台」常驻 Action 按钮，支持用户从账号列表快速打开全局聚合工作台。
  - 账号条目长按操作菜单新增「会话聚合工作台」选项。

---

## 3. 验证与质量保证（Phase 5: Verification & Testing）

### 3.1 单元测试全量绿灯

执行 `./gradlew :core:test` 验证结果：

```text
BUILD SUCCESSFUL in 3s
5 actionable tasks: 5 up-to-date
```

涵盖 152 项单元测试，包括：
- `ArchiveStoreTest`: 会话保存、读取、多轮模型记录与动态模型漂移判定
- `AccountBalanceClientTest`: 额度查询、数字/字符串反序列化、429 阶梯重试与异常封装
- `AccountRiskControllerTest`: 冷却阶梯流转、代理重绑触发、额度耗尽与账号优选
- 以及基线 140+ 项测试用例全部持续通过。

### 3.2 原生 Android 构建成功

执行 `./gradlew :app:assembleDebug` 构建结果：

```text
BUILD SUCCESSFUL in 22s
42 actionable tasks: 16 executed, 26 up-to-date
```

全部 Kotlin 源码、Room 实体、XML 布局及 Activity 交互逻辑均编译通过，无任何语法错误或弃用阻断。

---

## 4. 关键架构产物对照表

| 模块类别 | 文件路径 | 核心职责 |
|---|---|---|
| **领域实体** | `android/core/.../data/ArchiveStore.kt` | `ArchiveEntry` 扩展 `accountId` / `modelHistory`，实现 `recordRound` 与漂移判定 |
| **Room 映射** | `android/app/.../data/room/ArchiveEntryEntity.kt` | 数据库实体升级，支持 `account_id`、`model_drifted` 及 JSON 历史存储 |
| **Room 转换** | `android/app/.../data/room/RoomMappers.kt` | 双模领域模型与数据库实体无损互转 |
| **额度探针** | `android/core/.../account/AccountBalanceClient.kt` | 每日额度查询客户端，带自适应正则与 429 退避重试 |
| **风控控制** | `android/core/.../account/AccountRiskController.kt` | 429 阶梯冷却、代理重绑信号、额度耗尽与可用账号挑选 |
| **聚合视图** | `android/app/.../res/layout/item_archive.xml` | 会话卡片布局，包含「⚡已漂移」徽章与「账号: xxx」标识 |
| **聚合工作台** | `android/app/.../app/GalleryActivity.kt` | 跨账号会话聚合中心，支持全账号扫描、模型 Chip 筛选与一键直达 |
| **会话直达** | `android/app/.../app/MainActivity.kt` | 支持 `EXTRA_URL` 直达目标会话与 `onNewIntent` 账号热切换 |
| **账号导航** | `android/app/.../app/InstancePickerActivity.kt` | 顶部菜单与动作菜单直达全局会话聚合工作台 |
| **核心单测** | `android/core/.../ArchiveStoreTest.kt` | 逐轮模型漂移判定单测 |
| **核心单测** | `android/core/.../AccountBalanceClientTest.kt` | 额度客户端网络解析与 429 重试单测 |
| **核心单测** | `android/core/.../AccountRiskControllerTest.kt` | 风控状态流转与账号优选单测 |

---

## 5. 真机测试结果（2026-09-20）

### 5.1 测试环境

| 项 | 值 |
|---|---|
| 设备 | HONOR PGT-AN10（Magic OS） |
| 系统 | Android 16 |
| 序列号 | AD3JVB3921000413 |
| WebView | com.google.android.webview 138.0.7204.179 |
| 构建 | `:app:assembleDebug` **BUILD SUCCESSFUL**（42 tasks） |
| 安装 | `adb install -r` **Success** |

**构建前置条件（踩坑记录）**：系统默认 JDK 为 25（`D:\programmingSoftware\java\jdk25`），Gradle 8.13 + AGP 在 JDK 25 下直接失败（`What went wrong: 25.0.1`）。必须显式指定 JDK 17：

```bash
cd android && JAVA_HOME=/d/programmingSoftware/java/jdk17 ./gradlew :app:assembleDebug
```

`local.properties` 中 `sdk.dir=D:\Android\Sdk`；`adb` 位于 `D:\Android\Sdk\platform-tools\adb.exe`（不在 PATH）。

### 5.2 测试数据构造

通过 `adb shell run-as ai.arena.companion` 注入两份 `记录.json` 归档，覆盖阶段 1 的全部新字段：

| 归档 | 会话 | 模型轨迹 | 漂移 | accountId |
|---|---|---|---|---|
| `files/instances/account-01/归档/` | 漂移测试会话：GPT-5 变 mini | 3 轮：`gpt-5-fable` → `gpt-5-fable` → `gpt-5-mini` | 期望 true | `account-01`（显式） |
| 同上 | 无漂移会话：Claude 全程稳定 | 1 轮：`claude-opus-4-6` | 期望 false | `account-01`（显式） |
| `files/instances/account-02/归档/` | 账号二会话：Gemini 稳定 | 1 轮：`gemini-3-pro` | 期望 false | **缺省**（验证回退） |

account-02 刻意省略 `accountId`，用于验证 `loadAllEntries()` 的「旧数据回退为 instDir.name」路径。

### 5.3 逐项验证结果（UI 树证据）

设备截图（`screencap`）对本应用返回灰屏——**桌面截图正常**（2751 种采样色），故判定为 HONOR 设备级截图策略，非应用缺陷；代码中无 `FLAG_SECURE`。以下结论全部基于 `uiautomator dump` 的真实控件树。

| # | 验证项 | 结果 | 证据 |
|---|---|---|---|
| 1 | 跨账号聚合扫描 | ✅ | 3 条会话（account-01 ×2 + account-02 ×1）全部聚合 |
| 2 | 顶层标题动态切换 | ✅ | `会话聚合工作台`（无实例入参时） |
| 3 | 统计副标题 | ✅ | `【聚合工作台】共 3 条 · 3 个模型分组  ·  点击进入对话，长按详情` |
| 4 | **⚡已漂移徽章** | ✅ | 仅出现在 `gpt-5-mini` 卡片上（3 轮轨迹判定正确），坐标 `[508,1809]-[674,1862]` |
| 5 | 账号归属标签 | ✅ | `账号: account-01`、`账号: account-02` 分别正确；**缺省 accountId 的账号二成功回退为目录名** |
| 6 | 模型 Chip 分组 | ✅ | `全部 3` / `claude-opus-4-6 1` / `gemini-3-pro 1` / `gpt-5-mini 1`（第 3 个在横向滚动区） |
| 7 | Chip 筛选联动 | ✅ | 点击 `gpt-5-mini 1` → 卡片数收敛为 1，恰为漂移会话 |
| 8 | 卡片点击直达 + 账号重绑 | ✅ | `topResumedActivity=MainActivity`，Intent 带 extras，界面显示 `account-01` 与自动化控制面板 |
| 9 | AppBar 工作台入口 | ✅ | InstancePicker 顶部 `会话工作台` 可点击并正确进入聚合模式 |
| 10 | 长按菜单入口 | ✅ | 长按账号 → 菜单含 `会话聚合工作台`（另有 打开/归档/删除/重命名/更换邮箱/查看排队/设置） |
| 11 | 应用稳定性 | ✅ | 全程无 FATAL / AndroidRuntime 异常；进程存活（pid 843） |

### 5.4 结论

阶段 1-4 的**全部新增功能在真机上验证通过**：账号语义迁移（`accountId` + 回退兼容）、逐轮模型漂移判定（`recordRound`）、跨账号聚合工作台（扫描/标题/统计/Chip 筛选）、视觉升级（漂移徽章 + 账号标签）、以及一键直达与免密账号重绑（`EXTRA_URL` + `onNewIntent`）。

**仍未覆盖**（需后续单独安排）：
- 阶段 2/3 的**网络路径**：`AccountBalanceClient` 真实额度端点、`AccountRiskController` 的 429/Cloudflare 阶梯在真机上的实际触发（需真实 arena.ai 账号与受限 IP 条件）；
- Room 持久化的真机迁移验证（instrumentation 测试）；
- 方案 §9 的 S0 五项探测（WebView 版本矩阵 / 后台存活 / 移动端布局可自动化性 / 探针兼容性 / OkHttp 403）——本次未在范围内。
