# 架构演进与多账号/会话聚合体系设计 (mcp-account-session-aggregation.md)

日期：2026-09-20
基线：基于 docs/mcp-android-implementation-progress.md 及 reference/ArenCard 实现

---

## 1. 核心概念与实体关系重构

### 1.1 从「实例 (Instance)」到「账号 (Account)」的语义迁移
- **原有概念**：此前架构中称作「实例」，但本质上每个运行上下文严格绑定 arena.ai 的一个注册账号（邮箱 + 密码 + 登录 Session/Cookie）。
- **重命名原则**：
  - 领域模型、存储表结构及用户界面全面统一为 **Account（账号）**。
  - 账号实体核心属性：
    - `id`: 唯一标识 (UUID / 邮箱前缀)
    - `email` & `password`: 凭据（Android 端放 Keystore/EncryptedSharedPreferences，后端安全存储）
    - `dailyCredits`: 当日总额度/剩余额度 (`creditsRemaining`)
    - `usedCreditsToday`: 当日已用额度
    - `lastQuotaRefreshTime`: 最近额度刷新时间
    - `status`: `NORMAL`（正常）、`EXHAUSTED`（额度耗尽）、`RISK_CONTROL`（触发风控/图片验证）、`RATE_LIMITED`（429 退避中）
    - `backoffUntil`: 429 阶梯退避截止时间戳

### 1.2 会话（Conversation / Chat Session）与账号的归属关系
- **多对一模型**：一个账号下拥有多个会话，但一个会话严格归属于创建它的特定账号。
- **用户视角**：
  - 用户关心的是**每一个具体的对话**（例如抽中 `gpt-5-fable` 或 `claude-3-7-sonnet` 的高质量会话），而不是底层哪个账号资产。
  - 系统需向用户暴露一个**统一的全局会话聚合中心**，跨账号聚合、检索、展示所有会话，并支持一键无缝唤起/打开目标对话。

---

## 2. 关键探查项目与全生命周期状态机

### 2.1 账户额度探测 (Quota & Billing Probe)
- **探测时机**：
  1. 账号初始化/注册成功后立刻探查。
  2. 每天零点跨日重置时刷新。
  3. 每次发起新对话轮数前后自适应校验。
- **接口协议依据**（参考 `reference/ArenCard/arena_core.py`）：
  - `GET https://arena.ai/api/billing/balance`
  - 返回字段：`creditsRemaining`、`creditsUsed` 等。
- **策略**：当 `creditsRemaining <= 0` 时，标记账号状态为 `EXHAUSTED`，并自动从可用账号池中切换到下一个可用账号。

### 2.2 每一轮对话的模型动态检测 (Per-Turn Model Detection)
- **业务痛点**：Arena 在经过不定的交互轮数后可能悄然降级或切换 underlying 模型，因此**不仅建会话时要探查，每一轮对话都必须探查**。
- **探测链路依据**（参考 `reference/ArenCard/arena_draw.py`）：
  1. 获取会话 Trigger Token：`POST https://arena.ai/api/chat/trigger-token`，入参 `{"sessionId": sid}`。
  2. 订阅 Realtime Out 流：`GET https://arena.ai/ai-proxy/realtime/v1/sessions/<sid>/out` (SSE)，读取帧内 `records[].headers` 中的 `public-access-token`。
  3. 解码 Access Token 提取 `scopes` 中的 `run_id`（`read:runs:<run_id>`）。
  4. 查询 Run Events：`GET https://api.trigger.dev/api/v1/runs/<run_id>/events`，解析 `ai.streamText.doStream` 事件中的 `tabler-cube` 图标文本（即官方真实模型名）及 span 属性中的内部配置名（如 `gpt-6-astra-low`）。
  5. **轮次记录**：记录 `conversation_turns` 表，保存 `turn_index`, `model_name`, `provider`, `internal_tier`, `reasoning_tokens`, `timestamp`。

### 2.3 异常与风控处理矩阵 (Risk Control & Anomaly Handling)
- **429 限流退避 (Rate Limiting)**：
  - 区别 Cloudflare 挑战（出口 IP 彻底被阻断）与 Arena 业务 429。
  - 参考 `ArenCard` 的 `GATE_LADDER` 阶梯退避机制与账号独立门闸（一号一把闸，互不影响；若遇到出口 IP 被挡则联动动态代理触发切 IP）。
- **图片验证码 / 深度人机验证 (Captcha / Cloudflare Turnstile)**：
  - 遇到前端阻断/图形验证码时，标记账号为 `NEED_MANUAL_VERIFY` 或 `CAPTCHA_BLOCKED`。
  - 自动从调度池剔除，并在 UI 弹窗通知用户接入（或通过宿主 WebView 手工通过后恢复）。
- **多账号无缝轮换 (Account Pool Rotation)**：
  - 调度器维护 `AccountPool`，支持策略：优先额度充足 -> 处于非退避状态 -> 最近最少使用 (LRU)。

---

## 3. 全局会话聚合页面 (Unified Conversations Hub) 设计

### 3.1 页面核心价值
- 打破「账号隔离」对用户使用造成的碎片化体验。
- 用户无需关心当前会话背后是哪个账号，只需在聚合页根据**模型名称、会话主题、创建时间、最近更新轮数**进行筛选与搜索。

### 3.2 聚合卡片信息展示规范
每张会话卡片展示：
1. **会话标题**：自动抓取或通过 `PATCH /api/history/agentic/<id>` 重命名的模型标签（如 `[Fable-5] 算法优化研讨`）。
2. **当前模型真实标签**：显示最新一轮探查到的确定模型（带提供商徽标及推理档位，例如 OpenAI / Anthropic / xAI）。
3. **模型演变履历**：标注该会话是否发生过跨模型迁移（如 `Claude-3.7-Thinking -> Claude-3.5-Haiku`）。
4. **归属账号简标**：显示小角标（例如 `user123@dbwot.com` 的脱敏前缀），方便排查异常。
5. **快捷操作**：
   - **一键直达**：点击直接拉起对应会话窗口（注入对应账号凭据，直达 `/agent/<id>`）。
   - **快速改名/置顶/归档/删除**。

---

## 4. 参考 ArenCard 实现要点提炼与借鉴

在 `reference/ArenCard` 中，核心能力已被验证并封装成协议化实现，具备极高的参考价值：
1. **免浏览器快速注册 (`arena_core.py`)**：
   - 依赖 10minutemail.one catch-all 邮箱与纯 HTTP 6步协议，支持动态代理轮换。
2. **纯协议抽卡与精准模型捕获 (`arena_draw.py`)**：
   - 绕开前端 DOM 解析，直击底层 SSE 流和 `Trigger.dev` 事件接口，获取百分之百准确的真实底层模型名与 reasoning token 开销。
3. **细粒度账号隔离限速门闸 (`gate_status` & `_throttle_lock`)**：
   - 全局最小请求间隔 + 账号单体退避阶梯，有效隔离账号间影响。
4. **会话状态更新闭环**：
   - 抽中后调用 `PATCH /api/history/agentic/{id}` 自动写入模型标题，未命中则通过 `POST /api/chat/{id}/archive` 归档或 `DELETE` 清理。

---

## 5. 后续研发落地任务清单 (Todos)

- [ ] **数据模型与存储改造**：重构 SQLite / Room 实体定义，将 `Instance` 升级为 `Account`，新增 `AccountQuotas`、`ConversationMeta` 与 `TurnModelHistory` 表。
- [ ] **协议探查引擎移植**：将 `ArenCard` 的 `balance` 接口与 `Trigger.dev` 模型解析逻辑集成至当前服务层。
- [ ] **每轮交互探针拦截器**：在用户交互流或请求发送钩子中挂载探查动作，完成实时模型校验与变更通知。
- [ ] **聚合工作台 UI 构建**：实现跨账号会话聚合列表、标签筛选器与一键切换会话的路由调度。
