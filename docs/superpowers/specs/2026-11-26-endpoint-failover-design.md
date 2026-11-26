# 端点优先级故障转移（Endpoint Priority Failover）设计

> **Date**: 2026-11-26（修订自 2026-11-14 Draft）
> **Status**: Approved（用户确认功能范围与四项关键决策）
> **Author**: Claude + User

## 背景

Sage 支持配置多个 LLM 端点，但同一时刻只使用一个（`modelSelections.chatModel`）。
该端点出现 5xx / 超时 / 网络错误时，用户只能手动切换。现有机制里：

- 同端点内已有 `fallback_model` 降级（重试耗尽后换模型，每实例一次）；
- 流式有"首字后不重试"契约（`llm_client.py` 的 `nothing_yielded` 判定）；
- 端点失败只有前端提示（`endpointStatus.ts`），没有自动切换。

本次新增：按优先级组织的端点链，请求失败时自动切换到下一个优先级端点，并提供端点健康监控与被动/主动恢复（failback）。

## 目标

1. **自动故障转移**：当前端点重试耗尽或认证失败时，自动切到下一优先级端点，同一轮请求内完成。
2. **完整健康监控**：记录端点健康状态；失败端点冷却；后台轻量探测恢复；新请求自动回到优先级更高的健康端点（failback）。
3. **用户可见**：设置页显示端点优先级与健康状态；聊天中显示"已切换到备用端点"提示。
4. **零影响**：故障转移默认关闭；关闭时行为与现状完全一致。

## 非目标

- 负载均衡 / 预算路由（预留未来策略位，但本期不实现）。
- 跨会话协调（每个请求独立构链）。
- 多端点并发请求（hedging）。
- 非聊天链路（标题生成、记忆抽取、utility 客户端）的端点转移——本期仅聊天链路。

## 已确认决策

| 决策点 | 选择 |
|---|---|
| 功能范围 | 完整健康监控（被动信号 + 后台探测 + failback） |
| 触发时机 | 可重试错误（429/5xx/超时/网络）重试耗尽后切换；401/403 认证错误不重试直接切换；**流式已出首字后不切换**（仅上报失败供后续请求规避） |
| 优先级配置 | `EndpointConfig.priority`（1 最高）+ 设置页上移/下移按钮 + 故障转移总开关（默认关闭） |
| 切换后模型 | 目标端点有同名模型则沿用；否则用该端点配置的默认模型，再否则第一个发现的模型；都无则跳过该端点 |

## 架构

```
设置页（EndpointsTab）                聊天（SSE / RetryBanner）
   │ priority / failover 开关              ▲ failover 事件（retry_info.kind=failover）
   ▼                                      │
app_settings.failover + endpoints[].priority
   │                                      │
llm_factory.load_llm_config_for_chat()    │
   │ 构链：主端点 → 其余按 priority 升序     │
   ▼                                      │
LLMConfig.endpoint_chain: [EndpointHop]   │
   ▼                                      │
LLMClient.chat() / chat_stream_events() ──┘
   │ 每跳内跑现有重试循环；耗尽/认证错误 → 下一跳
   ▼
EndpointHealthRegistry（内存状态机）
   ▲ 被动上报（每次尝试成功/失败）
   │
EndpointProbeService（lifespan 后台任务）
   定时探测 degraded/failed 端点 → 成功则恢复健康
```

### 1. 数据模型

**EndpointConfig 新增字段**（前后端 + canonicalizer 同步）：

```ts
priority: number   // 1 = 最高优先级；缺省/非法视为「未排序」，排在已排序端点之后
```

**AppSettings 新增 `failover` 段**（顶层键，默认值）：

```ts
interface FailoverSettings {
  enabled: boolean;                 // 默认 false
  probeIntervalMs: number;          // 失败端点探测间隔，默认 300000（5 分钟），最小 30000
  cooldownMs: number;               // 失败端点冷却期，默认 60000（1 分钟），最小 5000
  consecutiveFailThreshold: number; // 连续失败判定 failed 的阈值，默认 2，范围 1–10
}
```

后端白名单：

- `LEGAL_TOP_KEYS` += `failover`
- `LEGAL_ENDPOINT_KEYS` += `priority`
- 新增 `LEGAL_FAILOVER_KEYS = {enabled, probeIntervalMs, cooldownMs, consecutiveFailThreshold}`
- 值校验：priority 正整数（可选）；failover 各字段范围校验，非法值拒收（400）。

前端同步：`src/entities/setting/types.ts`、`storage.ts` 的 `TOP_KEYS` / `ENDPOINT_KEYS`
白名单、`DEFAULT_SETTINGS`、`sanitizeForBackend`。契约测试
`backend/tests/contract/test_settings_schema_parity.py` 同步更新。

### 2. 健康状态机（`backend/services/endpoint_health.py`）

内存注册表，不持久化（重启后视为全健康，由探测/被动信号重建）：

```python
EndpointStatus = Literal["healthy", "degraded", "failed"]

@dataclass
class EndpointHealthState:
    endpoint_id: str
    status: EndpointStatus = "healthy"
    consecutive_failures: int = 0
    last_failure_at: float | None = None
    last_success_at: float | None = None
    last_failure_reason: str | None = None
    failover_count: int = 0
```

规则：

- `record_success(endpoint_id)` → `healthy`，清零连续失败、清空原因。
- `record_failure(endpoint_id, reason)` → 连续失败 +1；达到 `consecutive_fail_threshold` → `failed`；否则（有失败未达阈值）→ `degraded`。
- `record_failover(endpoint_id)` → `failover_count` +1（统计用）。
- `is_available(endpoint_id)`：`healthy`/`degraded` → True；`failed` → 仅当距 `last_failure_at` 已超过 `cooldown_s` 时 True（冷却期满允许被动重试，即被动 failback）。
- `snapshot()` → 供 API/UI 读取的纯数据 dict。

配置（阈值/冷却）由注册表在构链与探测时通过 `configure(threshold, cooldown_s)` 更新，读取 `app_settings.failover`；任何读取失败回退默认，不抛错。

单例访问：`get_health_registry()`；测试提供 `reset_health_registry()`。

### 3. 端点链构建（`backend/orchestration/llm_factory.py`）

`load_llm_config_for_chat()` 在 failover 开启时附加 `endpoint_chain`：

- 候选端点：协议受支持、`baseUrl` 非空、满足协议鉴权契约（与现有
  `_endpoint_has_required_api_key` 同口径）。
- 排序：
  1. 当前显式解析出的端点（会话覆盖/profile/全局选择所在端点）排第一；
  2. 其余按 `priority` 升序（缺省 priority 视为极大值，保持原数组顺序稳定）；
  3. 冷却期内的 `failed` 端点整体后移（仅在无可用端点时兜底），冷却期满恢复原位。
- 每跳模型：
  1. 端点 `discoveredModels` 含当前模型 → 沿用当前模型；
  2. 否则 `endpoint.modelId`；
  3. 否则 `discoveredModels[0].id`；
  4. 都没有 → 跳过该端点。
- 每跳携带：`endpoint_id / endpoint_name / base_url / api_key / provider /
  model / fallback_model / reasoning_effort / thinking_budget`。
  - `fallback_model`：仅主跳沿用全局降级模型（保持现有语义，每实例一次）。
  - reasoning 参数：取端点的 `reasoningEffort` / `thinkingBudget`。
- failover 关闭或只有一条有效端点 → 不写入 `endpoint_chain`（行为与现状一致）。

### 4. LLMClient 集成（`backend/core/legacy/llm_client.py`）

新增：

```python
@dataclass(frozen=True)
class EndpointHop: ...

@dataclass
class FailoverEvent:
    from_endpoint: str | None
    from_endpoint_name: str | None
    to_endpoint: str | None
    to_endpoint_name: str | None
    reason: str          # error_type value
    hop_index: int
    total_hops: int
```

`LLMConfig` 增加 `endpoint_chain: List[EndpointHop] = []`。无链时 `_failover_hops()`
返回仅由 config 构造的单跳（含 `fallback_model`），完全保持现状。

**每跳请求通道**：新增 `_get_client_for_hop(hop)`。主跳复用现有 `_get_client()`
（测试对其打桩的语义不变）；其余跳按 hop 的 `base_url/api_key` 构建独立
`httpx.AsyncClient` 并缓存，`close()` 一并关闭。代理模式下 hop 的上游 URL 通过
`X-LLM-Provider-Url` 传递，鉴权头使用 hop 的 api_key。

**非流式 `chat()`**：外层 hop 循环包住现有重试循环：

- 每跳内：现有 `max_attempts` 重试 → `fallback_model` 降级（仅主跳）→ 仍失败则进入下一跳；
- 触发下一跳的条件：错误类型 ∈ 可重试集合（重试耗尽），或
  `AUTH_FAILED` / 401 / 403（认证类，不重试直接跳）；
- 每跳成功 → `record_success`；跳走 → `record_failure` + `record_failover`；
- 切换时通过新可选回调 `failover_callback` 上报 `FailoverEvent`；全部跳失败
  → 抛最后一个错误（错误信息注明"已尝试 N 个端点"）；
- usage tracking 使用实际成功跳的 `endpoint_id`。

**流式 `chat_stream_events()`**：

- 仅 `nothing_yielded`（无 content/reasoning 增量）时允许跨跳；已出首字后失败
  → 上报失败并原样抛出（保持现有"首字后不可重放"契约）；
- 跨跳前重置聚合器/内容缓冲（与现有 `fallback_model` 同口径）；
- 通过 `("failover", FailoverEvent)` 事件下发切换信息；
- 首字前失败且链耗尽 → 抛最后错误，由 agent 层回退非流式（现有行为）。

**事件透传**：`agent.run_loop` 消费 `("failover", ...)`，映射为
`AgentEvent(state=AgentState.RETRY, retry_info={... kind: "failover" ...})`；
SSE 层无需新状态。前端 `RetryInfo` 增加可选字段：
`kind?: 'retry' | 'failover'`、`from_endpoint`、`to_endpoint`、
`from_endpoint_name`、`to_endpoint_name`。`RetryBanner` 在
`kind === 'failover'` 时渲染"已自动切换到端点 X（原因：…）"，不显示倒计时/尝试点。

**与 `fallback_model` 的顺序**：主跳内：主模型重试耗尽 → fallback 模型重试 →
仍失败 → 下一端点。非主跳不再触发 `fallback_model`（目标端点的降级模型语义不明确，
YAGNI）。

### 5. 健康探测（`backend/services/endpoint_probe.py`）

- FastAPI lifespan 启动后台任务 `run_endpoint_probe_loop()`，shutdown 取消。
- 每轮读取 `failover` 配置；未启用 → 休眠。
- 仅探测 `degraded` / `failed` 端点（健康端点零开销）。
- 探测请求：`GET {baseUrl}/models`（`openai-compatible` / `anthropic` / `gemini`），
  Ollama 用 `GET {baseUrl}/api/tags`；超时 5 秒；不消耗 token。
- 结果判定：
  - 2xx → `record_success`；
  - 401 / 5xx / 超时 / 连接失败 → `record_failure(reason="probe")`；
  - 403 / 404 / 405 → **视为可达**（模型列表权限或路径不支持，不代表聊天不可用），
    记录 debug 日志，不改状态。
- 休眠时长 = `probeIntervalMs`，按 ≤30s 分片，便于及时响应 shutdown。

### 6. API 与 UI

**后端 API**：`GET /api/v1/endpoints/health`

```json
{ "endpoints": [ { "endpointId": "...", "status": "healthy|degraded|failed",
  "consecutiveFailures": 0, "lastFailureAt": null, "lastSuccessAt": null,
  "lastFailureReason": null, "failoverCount": 0 } ] }
```

- 读取当前 settings 的端点 id 列表 + 健康注册表快照；未记录的端点返回 healthy。
- 鉴权：走现有 LocalAuthMiddleware（非公开路由）。

**设置页（EndpointsTab）**：

- 每行显示 `P{n}` 优先级徽章与健康状态点（health API 轮询，15s 一次，页签卸载即停）。
- 上移/下移按钮：交换相邻端点的 `priority` 并重排整个列表为 1..N，保存。
- 故障转移设置块（端点列表上方）：
  - 开关 `failover.enabled`；
  - 三个数值输入：探测间隔（分钟，UI 换算 ms）、冷却期（秒）、失败阈值，
    带范围校验；关闭时输入禁用。
- i18n：新增 zh/en 文案键。

**聊天界面**：`RetryBanner` 支持 failover 形态（见 §4 事件透传）。

### 7. 错误处理与风险

| 风险 | 处置 |
|---|---|
| 流式跨跳内容重复 | 严格 `nothing_yielded` 判定；跨跳前重置全部流式累积器 |
| 认证错误静默切走、用户不知 key 配错 | failover 事件始终展示；全部跳失败时错误信息包含各端点失败原因摘要 |
| 探测 403/404 误判端点坏死 | 403/404/405 视为可达，不改状态 |
| 冷却期内主端点无法被使用 | 冷却期满 `is_available` 返回 True（被动重试）；探测成功提前恢复 |
| py38 / release/win7 兼容 | 不使用 `match`、PEP 604 联合类型、`X | Y` 注解等；测试文件保留 `# ruff: noqa: UP006, UP007, UP035, UP045` 头 |
| 单端点用户 | failover 默认关闭；关闭时 `endpoint_chain` 不注入，零行为变化 |
| 设置保存 400（白名单漂移） | canonicalizer + settings_models + 前端白名单 + 契约测试四处同步更新 |

### 8. 测试策略（≥80% 覆盖新增代码）

- 后端单测：
  - 健康状态机：healthy→degraded→failed、成功恢复、冷却期可用性、阈值/冷却配置、快照；
  - 链构建：priority 排序、主端点置顶、同名模型解析、默认模型回退、无模型跳过、
    冷却端点后移、failover 关闭不构链；
  - LLMClient 非流式：429 耗尽→下一跳成功、401 直接跳、多跳全失败抛最后错误、
    fallback_model 仍在主跳生效、usage 归属正确跳、failover 回调事件；
  - LLMClient 流式：首字前跨跳并重置状态、首字后不跨跳、failover 事件、
    fallback_model 与跨跳的顺序；
  - 探测服务：成功/失败/403 可达判定、disabled 时不探测、任务取消；
  - canonicalizer：priority 与 failover 白名单（合法/非法）；
  - health API 契约。
- 前端测试：类型默认值、上移/下移逻辑、sanitizeForBackend 保留新字段、
  RetryBanner failover 渲染。
- 回归：现有 `test_llm_client_fallback.py`、`test_llm_retry.py`、
  `test_retry_resilience.py`、settings 契约测试全绿。

### 9. 交付与同步

- 分支：`feat/endpoint-failover-priority`（worktree）。
- main 完成后 cherry-pick 到 `release/win7` 并做 py38 适配。
- 功能合并后删除旧 `feat/endpoint-failover` 分支与 worktree（另行确认）。
