# Sage Arena：账号体系重构、逐轮模型动态探查与聚合会话工作台方案

> 日期：2026-09-20
> 关联文件：
> - [docs/mcp-android-implementation-progress.md](docs/mcp-android-implementation-progress.md)（安卓版 27 批进度基线）
> - [docs/mcp-android-implementation-plan.md](docs/mcp-android-implementation-plan.md)（安卓实施总方案）
> - [docs/mcp-aren-card-port-plan.md](docs/mcp-aren-card-port-plan.md)（ArenCard 协议移植规划）
> - [reference/ArenCard](reference/ArenCard)（参考实现源码）

---

## 1. 背景与核心认知转变

在既有移动端与伴侣端（Android Companion）的初步实现中，承袭了桌面端以宿主进程为边界的「实例（Instance）」抽象（如 `InstanceManager`、`InstancePickerActivity`、`ActiveInstanceGate`）。

然而，经过深入业务分析与实践对照，既有模型存在显著的心智割裂与场景错位：
1. **实体的本质是账号而非虚机**：所谓“独立实例”，其本质在 Arena.ai 网站端就是一个个独立的**注册账号（Account / Session Profile）**。以“实例”命名不仅晦涩，而且掩盖了其账号凭据、每日限额、代理绑定与风控状态的生命周期。
2. **账号受额度与风控强约束**：每个 Arena 账号存在每日额度限制（默认约 15000 credits/天）、频次限制（429）、IP 风险控制（Cloudflare 挑战）以及人机验证拦截。单个账号无法满足持续高强度使用，必须由多账号池进行轮转与备援。
3. **模型具备对话级与轮次级不确定性**：Arena 会话在创建时分配模型，但**在多轮长对话中，后台可能因为负载、安全策略或动态路由发生无感知的模型漂移（Model Drift）**。仅做首次检测会导致张冠李戴，必须逐轮检测。
4. **用户价值的核心是“会话”本身**：对于真实使用者而言，底层挂载的是哪一个临时账号毫无价值，用户真正关心的是**“我与某个特定模型（如 Fable-5 / GPT-6）开展的对话，以及如何立即打开并继续聊下去”**。

因此，系统架构必须完成一次根本性的升级：**全链路废除“实例”概念，端到端确立以“账号（Account）为供给支撑、以会话（Conversation）为消费核心”的全新双层架构。**

---

## 2. 核心架构重构：从“实例”到“账号与会话”

### 2.1 术语全面对齐

| 原有术语（废弃） | 新规范术语（采用） | 业务本质与职责说明 |
|---|---|---|
| `Instance`（实例） | **`Account`（账号）** | 承载 Arena.ai 的用户身份（邮箱、密码、User ID、JWT、Cookies）、绑定出口 IP、额度与风控状态。 |
| `InstanceManager` | **`AccountPoolManager`** | 统一管理所有账号的持久化、凭据加解密、状态流转（可用/冷却/耗尽/失效）与自动轮换调度。 |
| `InstancePickerActivity` | **`AccountManagerActivity`** | 账号管理中心：查看账号池、导入/批量注册、监控额度、绑定代理 IP。 |
| `ActiveInstanceGate` | **`ActiveAccountGate`** | 单设备/单代理并发控制闸门，协调活动账号排队与互斥。 |
| `GalleryActivity`（单实例孤立归档） | **`ConversationHubActivity`（聚合会话工作台）** | **全局跨账号会话中心**：聚合呈现所有账号名下的所有会话，支持按模型筛选与一键免密跳转。 |

### 2.2 实体关系模型

```
┌────────────────────────────────────────────────────────┐
│                   Account（账号实体）                   │
│ - id / email / password_hash / user_id                 │
│ - credits_remaining (每日额度探查)                      │
│ - bound_proxy (绑定出口 IP / sid)                      │
│ - status (Available / Cooling / Depleted / NeedVerify) │
│ - profile_path (本地隔离 Cookie / WebView 数据目录)     │
└──────────────────────────┬─────────────────────────────┘
                           │ 1 (拥有)
                           │
                           ▼ N (多会话)
┌────────────────────────────────────────────────────────┐
│                Conversation（会话实体）                │
│ - id (sid) / url / title / account_id                  │
│ - created_at / last_active_at                          │
│ - current_model (最新生效模型)                          │
│ - model_history (逐轮模型演进轨迹列表)                   │
│ - reasoning_level / tokens_usage                       │
│ - state (active / archived / deleted)                  │
└────────────────────────────────────────────────────────┘
```

---

## 3. 核心探查机制设计

### 3.1 账户当前额度探查（Account Quota Probing）

* **探查端点**：`GET https://arena.ai/api/billing/balance`（请求头需携带对应账号的 Session Cookie/JWT 及 `Referer: https://arena.ai/`）。
* **数据结构**：返回 JSON `{ "creditsRemaining": 15000, "totalCredits": 15000, ... }`。
* **探查时机与策略**：
  1. **登录/启动初始探查**：账号登入激活或加入账号池时，主动获取基线额度；
  2. **对话完成轻量级回写**：每一轮对话完成（生成 response）后，异步拉取最新 balance，精确计算本轮消耗；
  3. **定时与手动刷新**：账号管理看板支持下拉刷新与周期性健康探测（结合防抖 4 次 × 3s 退避重试）；
  4. **额度预警与熔断**：当 `creditsRemaining <= 阈值`（如 100 credits）时，状态自动翻转为 `DepletedToday`，触发自动切号。

### 3.2 每一个会话对应的模型探查

* **双通道探测架构**：
  1. **协议层直接截获（推荐高精度通道）**：
     * 会话交互时，获取 Trigger.dev 令牌：`POST /api/chat/trigger-token`；
     * 订阅 SSE 流：`GET /ai-proxy/realtime/v1/sessions/{sid}/out`，提取每一轮最新的 `public-access-token`；
     * 查询运行详情：`GET https://api.trigger.dev/api/v1/runs/{runId}/events`，提取 `ai.streamText.doStream` 中包含的模型名；
     * 正则深挖内部配置与档位：从原始 JSON 提取 `"modelName"\s*:\s*"([^"]{2,80})"`（如 `gpt-6-astra-low`、`fable-5.1-high`）；
     * 提取推理深度：从 `token.usage.recorded` span 读取 `reasoningTokens`。
  2. **移动端 WebView 注入探针（无感轻量通道）**：
     * 利用 `arena-model-probe.inject.js` 在 `DOCUMENT_START` 劫持网页端 `fetch` 与 `EventSource`；
     * 将抓取到的内部模型事件注入 `window.__arenaProbe`；
     * 客户端调用 `WebViewProbeReader` 执行单次原子 JavaScript 读取快照。

### 3.3 关键突破：多轮对话的模型动态漂移检测（Round-by-Round Detection）

* **为什么必须逐轮检测**：
  * 在 Arena.ai 的运行体系中，模型分配并非终身绑定。在多轮交互中，由于平台服务端动态负载均衡、安全上下文重评估或多 Agent 协同切换，**同一会话在第 1 轮由 Model A 应答，在第 3 轮可能被悄然切换为 Model B**。
  * 若仅在首次发消息时做一次检测，会话元数据将在后续轮次发生“认知偏差”。
* **逐轮检测工作流**：
  1. **触发锚点**：监听每次用户发送输入 -> 接收流式回答完成（`generationStamp` 稳定）；
  2. **增量探查**：每次稳定后，重新执行模型解析链路，取得本轮的 `{ round_id, model, internal, reasoning, timestamp }`；
  3. **演化记录（Model Drift Track）**：
     * 追加写入 `model_history` 数组；
     * 校验 `new_model != current_model`：若发生漂移，标记 `model_drifted = true`；
  4. **感知同步**：
     * 在会话详情与聚合工作台实时展示模型演变日志（如：`第 1~2 轮: gpt-5.6-luna → 第 3 轮: claude-3-7-sonnet`）；
     * 自动更新会话标题后缀（如开启命中重命名，自动补齐最新阶段名）。

---

## 4. 多账号管理与多维风控应对方案

面对大规模、多会话的实际使用，账号必须具备抵御风控、自愈与自动轮替的能力。

| 风险/异常类型 | 识别特征 | 自动化处置策略 | 账号状态变化 |
|---|---|---|---|
| **普通限流（429 JSON）** | HTTP 429 且响应体为正常 JSON 限流提示 | 账号级独立阶梯退避：15s → 30s → 60s → 90s，互不干扰；240s 无异常自动降级。 | 维持 `Cooling`，退避结束后自愈 |
| **严重限流 / 换 IP 阈值** | 429 退避累计到达 60s 档位 | 中止本轮，自动从代理池提取新代理更换绑定（旧代理拉黑 30 分钟），退避计数清零。 | `Rebinding` → `Available` |
| **Cloudflare 拦截** | HTTP 429/403 包含 `Just a moment...` 或 `cf-chl` | 判定出口 IP 已被封锁，等待完全无效；**立即**更换出口代理 IP，旧 IP 强拉黑 180s。 | `Rebinding`（立即换 IP） |
| **reCAPTCHA 拒绝** | HTTP 403 `{"error":"recaptcha validation failed"}` | token 浏览器环境评分低；累计达 10 次后，单独重启 token 出口/更换 token 浏览器代理。 | 账号不变，token 引擎刷新 |
| **强人机图片验证** | 页面弹出 Turnstile 复选框、滑动拼图或图片点选 | 纯协议无法自愈，**立即暂停自动化任务**并发出系统通知；唤起前端交互式 WebView 供人工完成；通过后 `epoch++` 原位继续。 | `NeedVerification`（挂起） |
| **额度耗尽（Quota Exhausted）** | `creditsRemaining < 100` 或扣费失败 402 | 记录当天重置时间（次日 00:00 UTC）；触发**自动换号机制**，从池中调度下一健康账号接管。 | `DepletedToday`（次日自动恢复） |
| **凭据彻底失效** | 密码错误、账号被封禁（HTTP 401/403 鉴权失败） | 隔离账号，标记为失效，弹出告警通知，从轮转可用池中移除。 | `Invalid` |

---

## 5. 以用户为中心的“会话聚合工作台”（Unified Conversation Hub）

### 5.1 页面设计理念
用户使用 AI 工具的核心诉求是**直接与高质量模型对话**，而非记忆账号。因此，聚合工作台作为应用默认主入口，提供跨账号的全局会话中枢。

### 5.2 核心功能矩阵

1. **跨账号全局统一卡片列表**：
   * 破除“按实例分目录”的割裂结构，全局展示全部历史与当前活跃会话；
   * 每张会话卡片呈现：
     * **会话标题**（如：`claude-fable-5.1-high·r1840`）；
     * **当前最新生效模型 Badge**（附带供应商 Logo、档位、是否有模型漂移提示）；
     * **所属账号标签**（脱敏邮箱如 `u89a***@dbwot.com`，附带该账号当前剩余额度 `13,500`）；
     * **轮次与活跃时间**（如：`5 轮对话 · 10 分钟前`）。
2. **多维筛选与聚合切片**：
   * **按模型筛选**：顶部横向 Chips 自动汇聚（`全部`、`GPT-6/Luna`、`Claude/Fable`、`Sonnet`、`未识别`）；
   * **按账号筛选**：支持下钻查看某个指定账号名下的会话集；
   * **按状态筛选**：活跃会话 / 已归档 / 已命中保留。
3. **一键免密秒级唤起（Fast Launch）**：
   * 点击任意会话卡片：
     1. 系统解析该会话归属的 `account_id`；
     2. 检查该账号隔离沙箱（`ProfileManager` 中的 Cookies/Storage）；
     3. 自动将 WebView 绑定至对应账号沙箱环境；
     4. 瞬间加载 `https://arena.ai/agent/{sessionId}`；
     5. 用户直接进入聊天打字界面，无需任何手动登出/登入操作。

---

## 6. reference\ArenCard 现网实现机制剖析与对照

为了确保新方案架构完备且具备工业级鲁棒性，特对参考实现 `reference/ArenCard` 的核心模块进行源码级深度对照：

### 6.1 模块结构与实现亮点

| 能力模块 | ArenCard 源码实现 | 关键技术机制（优势分析） |
|---|---|---|
| **额度查询** | `arena_core.py:385-401` `get_balance()` | `GET /api/billing/balance`，提取 `creditsRemaining`；内置 4 次 × 3s 退避重试防偶发抖动。 |
| **纯协议建会话** | `arena_draw.py:400-429` `create_chat()` | 纯 HTTP POST `/nextjs-api/stream/create-chat`，规避笨重的浏览器渲染；请求头伪装 Chrome 131 指纹。 |
| **模型精细化提取** | `arena_draw.py:575-605` `parse_models()` | 订阅 Trigger.dev SSE 输出流拿到 `runId`，从 `events` 解析官方模型，并在原始 JSON 正则深挖内部配置名。 |
| **推理深度分析** | `arena_draw.py:265-275` & `737-761` `read_usage()` | 从 `token.usage.recorded` span 读取 `reasoningTokens`，支持按“是否具备推理”作为保留条件。 |
| **代理与 429 治理** | `arena_draw.py:54-73` & `proxy_relay.py` | 账号级独立限速门闸；阶梯累计触发自动换 IP；自建本地 CONNECT 中继清除有害 Host 头。 |
| **账号池汇总** | `arena_register.py:1057-1073` `_model_summary()` | 账号管理页汇总每个账号历史抽到的所有模型，按优先级（Fable5/Astra > 其他）排序展示。 |

### 6.2 ArenCard 的局限性与本方案的超越点

| 维度 | reference\ArenCard 局限性 | 本方案的升级超越设计 |
|---|---|---|
| **会话生命周期** | **单次抽卡即焚**：仅发送一次 `1+1=` 探明模型后即终止（命中改名保留，未命中直接删除或归档）。 | **完整多轮对话支持**：支持持续互动与长会话管理，将会话视为持久的核心数字资产。 |
| **模型漂移检测** | **无多轮检测**：仅检测首轮模型，完全不具备多轮对话中识别模型漂移的能力。 | **逐轮闭环探查**：每一轮应答稳定后均执行增量探测，记录模型演化链，提示漂移风险。 |
| **用户使用场景** | **仅为“制号/抽卡机”**：界面为纯配置表单，抽到好模型后用户必须在外部浏览器手动登录该号查找会话。 | **一体化“会话聚合工作台”**：内置全局聚合看板，一键点击直切对应账号 Profile 打开对话，无缝使用。 |
| **验证码处理** | **遭遇图片验证即阻塞或崩溃**：仅能退避重试，无人工干预通道。 | **人机协作挂起态**：遇到强验证码时状态机优雅挂起，通知用户在 WebView 中人工辅助完成，随后原位续跑。 |

---

## 7. 落地实施阶段规划

1. **阶段 1：术语与数据层重构（Account & ModelHistory）**
   * 将 `InstanceManager` 重命名并重构为 `AccountPoolManager`；
   * 扩充 `ArchiveEntry` / Room `ConversationEntity`，加入 `accountId`、`accountEmail`、`currentModel`、`modelHistory`（JSON 数组）及 `creditsRemaining` 字段。
2. **阶段 2：额度探查与逐轮模型探针集成**
   * 落地 `AccountBalanceClient`（对接 `/api/billing/balance`）；
   * 扩展 `WebViewProbeReader` 与 `ConversationRenamer`，在每个对话 round 结束后触发增量双读校验与历史追加。
3. **阶段 3：多账号风控状态机与自动轮转**
   * 移植 ArenCard 的 429 阶梯退避、Cloudflare 挑战识别与自动重绑 IP 逻辑；
   * 实现额度耗尽自动标记与账号切换调度器。
4. **阶段 4：会话聚合工作台 UI（ConversationHubActivity）**
   * 开发全局跨账号会话看板，支持模型 Chips 分组、关键词检索；
   * 打通“点击条目 → `ProfileManager` 切号 → 启动 `MainActivity` WebView 直达会话 URL”的一键交互链路。
