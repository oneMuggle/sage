# LLM 重试计时可视化 + "重试中"横幅状态修复

> 状态：M1/M2/M3 已实施 → **PR #2827 已提交**（CI 进行中）；M4 延后（独立 PR）
> 分支基线：`origin/release/win7`（c8dbaae31，含 #2815 重试预算可见性）
> 工作分支：`fix/llm-retry-timing-visibility`（commit eed51fd7d）
> PR：https://github.com/oneMuseum/sage/pull/2827
> 相关文档：`docs/technical/101-llm-error-classification-retry.md`

## 1. 背景与目标

### 1.1 触发问题

会话 `ce21ad04-8299-4787-81a9-efbb7a6941dd`（2026-11-03 08:48–08:59）中：

1. 用户发送"继续"后，**6 分 44 秒**才看到第一条回答，体感"重试时间很长"。
2. 思考内容（reasoning）已经出现在气泡里，横幅仍显示"重试中 (2/10)"。
3. 横幅只显示 attempt 计数与 2–4 秒退避倒计时，**在途等待最长 60 秒期间没有任何时间信息**，用户无法判断系统是否卡死、还要等多久。

### 1.2 日志证据（`data/logs/sage_20261103.log`）

| 时间                | 事件                                       | 说明                                    |
| ------------------- | ------------------------------------------ | --------------------------------------- |
| 08:48:45            | `POST /chat/stream` create                 | 用户发送"继续"                          |
| 08:49:08 → 08:49:52 | 小型 LLM 调用成功（148 tokens，44s）       | 上游本身很慢                            |
| 08:49:53 → 08:50:54 | 压缩摘要 LLM 调用失败 `LLM 请求失败(1/10)` | 代理 60s 静默超时；**该重试 UI 不可见** |
| 08:50:56 → 08:51:55 | 压缩重试成功（59s）                        | 08:51:55 压缩完成、用户消息落库         |
| 08:52:57            | 主流程 `LLM 流式请求失败(1/10)`            | ~60s 后失败，2s 退避                    |
| 08:54:01            | `LLM 流式请求失败(2/10)`                   | ~60s 后失败，4s 退避                    |
| ~08:55:29           | 第三次尝试成功                             | 首条回答落库（距发送 6m44s）            |
| 08:56:31            | 下一 Agent 步骤再次 `(1/10)`               | 重试跨步骤反复出现                      |

### 1.3 根因

**R1：每次失败前固定等满 60 秒代理静默超时，重试反而放大等待。**

- `backend/api/llm_proxy_routes.py` 的 `PROXY_TIMEOUT_SECONDS=60`，用户设置 `llmProxyTimeoutS=60`。
- 上游（`integrate.api.nvidia.com`，模型 `z-ai/glm-5.3-flash`）实测首字节 44–59s，与 60s 超时同量级：请求经常在"即将成功"时被掐断，重试只是再等一个 60s。
- 指数退避本身只有 2s/4s（`llmRetryBaseDelayS=2`），**不是耗时主因**。

**R2：重试总时长预算只约束退避，不约束在途请求。**

- `llm_client.py` 在退避前检查 `elapsed + delay > total_budget`，但在途请求最长仍可再跑满一个 `dynamic_timeout`（本次 86s）。
- 用户设置预算 180s，实际墙钟可达 180s + 一次完整超时 ≈ 240s。

**R3：attempt 在途期间没有事件，横幅静止且倒计时归零。**

- `retry` 事件只在失败后、退避前发送一次；倒计时 `useCountdown(info.delay, ...)` 2–4 秒后归零并隐藏。
- 之后新 attempt 在途、上游静默最长 60s，无任何 UI 事件（`heartbeat` 只在退避 sleep 中每 5s 发一次，且前端忽略、不清横幅）。
- 结果：横幅长时间静止显示"重试中 (2/10)"，看起来像卡住。

**R4：思考内容出现后横幅仍停留。**

- 主路径：`reasoning_delta` 经 `setStreamingMeta` 触发**延迟 3 秒**清除（`chatStreamStore.ts` 的设计），思考出现后横幅必然再停留最多 3s。
- 重接路径（`chatStreamRuntime.ts` 422–431 行）：`content_delta`/`reasoning_delta` 只 `replaceContent`/`replaceReasoning`，**不调用 `setStreamingMeta`** → `retryInfo` 不会被清除，切走再切回/渲染进程重载后横幅会一直残留到流结束（确定缺陷）。

**R5：上下文压缩的重试完全不可见。**

- `_maybe_auto_compact_session` 使用 `LLMClient.complete`，未接 `retry_callback`。
- 本次压缩段 08:49:53–08:51:55（约 2 分钟，占总等待 30%）在 UI 上只有"思考中"，用户没有任何解释。

### 1.4 参考主流产品做法

Claude Code（官方 Errors 文档，v2.1.198+）：

- 重试时 spinner 显示 `Retrying in Ns · attempt x/y`，并附错误类型标签。
- 流式请求 ≥20s 无数据时显示独立横幅：`Waiting for API response · will retry in … · check your network`，倒计时指向中断点；数据恢复或重试成功时横幅自动消失。
- 失败原因从第 3 次尝试起切换为具体原因（网络/TLS/限流）。

其他应用（如 frontman PR #762）：用服务端下发的 `retryAt` 时间戳驱动倒计时，避免客户端时钟漂移；错误横幅区分"倒计时中"与"重试进行中"。

### 1.5 目标

1. 横幅能回答四个问题：**现在在等什么（退避 vs 在途）、已等多久、还要等多久、预算还够几次**。
2. 思考/正文恢复时横幅立即消失；重接路径不再残留。
3. 180s 预算与 UI 承诺一致（墙钟不超过预算 + 可解释的余量）。
4. 压缩期间的重试可见。
5. 向后兼容：新增字段全部可选，旧前端可忽略；win7 py38 可用。

## 2. 涉及文件与模块

### 后端

- `backend/core/legacy/llm_client.py`：`RetryEvent` 扩展、新事件 `retry_attempt_started`、预算计入在途耗时、按剩余预算收紧单次超时。
- `backend/core/legacy/agent.py`：`_retry_info_from_event()` 透传新字段；转发新事件（流式与非流式回退两条路径共用同一构造函数，禁止内联重复构造）。
- `backend/api/chat_session_lifecycle.py`：`_maybe_auto_compact_session(..., retry_callback=None)`，接入压缩重试回调。
- `backend/api/legacy_routes.py`：producer 向压缩传入回调，转发 `compaction_status` 事件。
- `backend/api/llm_proxy_routes.py`：仅补充注释/文案（`llmProxyTimeoutS` 语义澄清），不改默认值。
- `backend/tests/unit/test_llm_retry.py`、`test_agent_retry_visibility.py`：新增断言。

### 前端

- `src/shared/api/types/chatAndEventTypes.ts`：`RetryInfo` 增 `elapsed_s?` / `attempt_timeout_s?`；新增 `retry_attempt_started` 事件类型与 `compaction_status`。
- `src/features/send-message/chatStreamStore.ts`：新增 `retryPhase`、`retryAttemptStartedAt`、清除策略调整。
- `src/features/send-message/chatStreamRuntime.ts`：重接路径在内容/推理到达时调用 `setStreamingMeta`（修复 R4）。
- `src/features/send-message/useChat.ts`：处理 `retry_attempt_started`、`compaction_status`。
- `src/widgets/chat/RetryBanner.tsx`：两阶段（退避/在途）渲染 + 已等待/剩余预算/单次上限。
- `src/shared/lib/useCountdown.ts`：新增 `useElapsed(startedAt)`（或同文件导出）。
- `src/shared/lib/i18n/retryBanner.ts`：中英文案新增。
- `src/widgets/chat/Message.tsx`：20s 无数据静默提示（可与 ThinkingShimmer 合并）。
- `src/widgets/session/SessionItem.tsx`：侧栏"重试中"徽章 tooltip 增加 attempt / 已等待。
- 测试：`RetryBanner.test.tsx`、`chatStreamStore` 相关测试、重接路径测试。

### 文档与门禁

- `docs/technical/101-llm-error-classification-retry.md`：协议与状态机更新。
- `architecture-baseline.json`：按本分支实测更新（win7 与 main 数值不同，禁止照抄）。
- `scripts/check_py38_compat.py` 通过。

## 3. 技术方案

### 3.1 后端事件协议

```python
@dataclass
class RetryEvent:
    attempt: int                      # 刚失败的尝试序号（1-based）
    max_attempts: int
    error_type: str
    error_message: str
    delay: float                      # 退避秒数
    elapsed_s: float = 0.0            # 自本请求首次尝试起累计耗时（含此前在途 + 退避）
    attempt_timeout_s: Optional[float] = None  # 下一次尝试的单次请求超时上限
    budget_total_s: Optional[float] = None
    budget_remaining_s: Optional[float] = None  # 退避结束后剩余预算

@dataclass
class RetryAttemptStartedEvent:
    attempt: int                      # 即将开始的尝试序号（= 失败次数 + 1）
    elapsed_s: float
    attempt_timeout_s: Optional[float]
    budget_remaining_s: Optional[float]
```

事件顺序（每个请求周期）：

```
attempt 1 失败
  → yield ("retry", RetryEvent(phase=backoff, delay=2s, elapsed_s, budget_remaining_s))
  → sleep(delay)，每 5s yield heartbeat
  → yield ("retry_attempt_started", RetryAttemptStartedEvent(attempt=2, elapsed_s, ...))
  → attempt 2 在途（最长 attempt_timeout_s）
  → 成功首条 reasoning/content delta 即视为恢复（前端清除横幅）
```

`attempt_timeout_s` 取值：

```python
attempt_timeout = dynamic_timeout
if total_budget > 0:
    remaining = total_budget - (_retry_now() - stream_started)
    if remaining <= _LLM_RETRY_MIN_ATTEMPT_S:   # 新增常量，默认 5s
        raise _retry_budget_exhausted_error(...)
    attempt_timeout = max(_LLM_RETRY_MIN_ATTEMPT_S, min(dynamic_timeout, remaining))
```

- 预算计入在途耗时：`elapsed_s` 用同一 `stream_started` 起点，在 attempt 结束后自然包含在途时长。
- 这样 `180s` 预算成为真实墙钟上限（误差 ≤ `_LLM_RETRY_MIN_ATTEMPT_S`）。
- 保留 `_retry_now()` 采样方式，避免破坏 `test_llm_retry.py` 的 fake clock。

### 3.2 前端状态机

`StreamingState` 新增：

```ts
retryPhase?: 'backoff' | 'in_flight' | null;
retryAttemptStartedAt?: number | null;   // 本地 Date.now()，收到 retry_attempt_started 时写入
retryFirstFailedAt?: number | null;      // 首次失败时间，用于"已累计等待"
```

横幅两阶段文案：

| 阶段                                         | 文案示例                                                              |
| -------------------------------------------- | --------------------------------------------------------------------- |
| backoff                                      | `将在 4 秒后重试（第 2/10 次失败）· 本次已等 66 秒 · 剩余预算 112 秒` |
| in_flight（未超时）                          | `正在重试（第 3/10 次尝试）· 已等待 23 秒 · 单次上限 86 秒`           |
| in_flight（超过 attempt_timeout_s 仍未返回） | `已超过 86 秒，仍在等待上游响应 · 可点击停止`                         |

- 倒计时归零不是阶段切换依据；阶段由 `retry_attempt_started` 事件驱动（无该事件时前端以 `countdown === 0` 兜底推断）。
- 预算进度条：`budget_remaining_s / budget_total_s`，仅在预算启用时显示。
- **清除策略**：首个 `reasoning_delta` / `content_delta` 到达时立即清除（≤500ms 淡出），不再延迟 3 秒；若希望保留"发生过重试"的记忆，在消息元数据里记录并在气泡底部显示一行可忽略的"已自动重试 N 次后恢复"（可选，M3 再做）。
- `retry_attempt_started` 通过 BroadcastQueue 重放时需幂等：以 `(attempt, streamId)` 去重。

### 3.3 20 秒无数据静默提示（对标 Claude Code）

- 前端在流式期间维护 `lastEventAt`（任何事件刷新，含 heartbeat）。
- 超过 20s 无事件时显示弱提示：`等待上游响应 · 已等待 Ns`；数据恢复自动消失。
- 与 RetryBanner 不叠加：重试 in-flight 阶段由 RetryBanner 承担同类信息。

### 3.4 压缩可见性

- `_maybe_auto_compact_session` 增加可选 `retry_callback`，透传给内部 `LLMClient.complete` 所用的 `LLMClient`。
- producer 在压缩前后推送：
  - `compaction_status { phase: 'started' }`
  - `compaction_status { phase: 'retry', retry_info: {..., source: 'compaction'} }`
  - `compaction_status { phase: 'done', removed, after }`（与既有 `compact_triggered` 合并）
- 前端把 `source: 'compaction'` 的 retry_info 渲染为独立状态行：`正在压缩上下文… 重试中（1/10，已等 61 秒）`，不占用当前消息气泡的 RetryBanner。

### 3.5 设置页与文案

- `BasicTab` 的"LLM 代理超时"描述明确：**上游静默/首字超时**；提示"若日志频繁出现'上游长时间未返回任何数据'且间隔≈该值，说明上游延迟已接近超时，优先调大该值或更换模型，而不是增加重试次数"。
- 在重试设置区域显示估算：`按当前超时与预算，最多可重试约 ⌊预算 / 单次超时⌋ 次`（前端计算，仅提示）。
- i18n 新增 key（zh/en）：`chat.retry.backoff_in`、`chat.retry.in_flight`、`chat.retry.waited`、`chat.retry.attempt_timeout`、`chat.retry.budget_remaining`（已有）、`chat.retry.quiet_wait`、`chat.retry.compaction`。

## 4. 实施步骤

### M1：前端缺陷修复（不依赖后端协议）— ✅ 已完成

- [x] `chatStreamRuntime.ts` 重接路径：`reasoning_delta` / `reasoning` / `reasoning_final` / `content_delta` 到达时同步 `setStreamingMeta({state})`，触发 retryInfo 清除。
- [x] `chatStreamStore.ts`：首个 delta 到达时立即清除 retryInfo（替换 3s 延迟；保留 `retryInfoClearedAt` 供诊断使用）。
- [x] 更新既有单测：chatStreamStore.test.ts / Message.retry.test.tsx / useChat.streamingAndGates.test.ts 三处"3 秒延迟"断言改为"立即清空"。
- [x] 前端全量测试 + tsc + eslint + prettier。（1263/1266 pass；1 failure 为 Office.tabs 基线问题，与本次改动无关）

### M2：后端事件与预算 — ✅ 已完成（前一轮会话）

- [x] `RetryEvent` 增字段（`elapsed_s` / `attempt_timeout_s` / `phase` / `source`）；新增 `RetryAttemptStartedEvent` 与发送点。
- [x] 预算计入在途耗时；按剩余预算收紧单次超时。
- [x] `agent.py` 透传字段并转发新事件。
- [x] `test_llm_retry.py` / `test_agent_retry_visibility.py` 新增断言，26/26 绿。
- [x] py38 兼容。

### M3：横幅重构 — ✅ 已完成

- [x] `RetryInfo` 类型新增 `phase?` / `elapsed_s?` / `attempt_timeout_s?` / `source?`（chatAndEventTypes.ts）。
- [x] `RetryBanner` 两阶段渲染（backoff/in_flight）+ `Loader2` 图标 + `useElapsed` 计数器 + 单次上限字段 + source 前缀。
- [x] `formatRetryBannerSummary` / `formatRetryBannerJson` 增 `phase` 等字段。
- [x] i18n zh/en 新增 6 个 key（backoff_hint / in_flight_hint / elapsed / attempt_elapsed / attempt_timeout / source.compaction）。
- [x] `useElapsed` hook（useCountdown.ts）新增导出。
- [x] RetryBanner.test.tsx 新增 4 个测试覆盖双阶段渲染。
- [ ] `Message.tsx` 20s 无数据提示 — **延后**（独立 PR，不在本次范围）。
- [ ] `SessionItem.tsx` tooltip 增加 attempt/已等待 — **延后**（现有 tooltip 两阶段通用）。

### M4：压缩可见性 + 设置文案 + 文档 — ⏸ 延后到独立 PR

- [ ] `_maybe_auto_compact_session` 回调；producer 转发 `compaction_status`。
- [ ] 前端压缩状态行。
- [ ] `BasicTab` 描述与估算提示。
- [ ] 更新 `docs/technical/101-llm-error-classification-retry.md`；更新 `architecture-baseline.json`（本分支实测）。
- [ ] `scripts/mock_stall_upstream.py`：模拟 60s 静默上游，做端到端手工验收。

## 5. 测试与验收

### 自动化

- 后端：新增事件字段/顺序/预算语义单测；现有 `test_llm_retry.py` 16 例保持绿。
- 前端：RetryBanner 阶段切换、倒计时归零不切阶段、retry_attempt_started 切阶段、首个 delta 立即清除、重接路径清除、预算条渲染。
- 门禁：`tsc`（main + electron）、eslint、prettier、architecture-check、py38 compat。

### 手工验收（对照本次会话时间线）

1. 用 mock stall 上游制造 60s 静默 → 横幅先显示"4 秒后重试"，随后切换"正在重试 · 已等待 Ns · 单次上限 60s"，倒计时/计时连续可见。
2. 第 3 次尝试返回 reasoning → 横幅立即消失（≤1s），思考内容正常显示。
3. 切走再切回会话（重接）→ 思考/正文到达后横幅不残留。
4. 预算耗尽 → 错误信息给出已等待时长、预算值与可操作建议。
5. 压缩期间重试 → 出现"正在压缩上下文… 重试中"状态行。

## 6. 风险评估与依赖

| 风险                                 | 影响 | 缓解                                                                             |
| ------------------------------------ | ---- | -------------------------------------------------------------------------------- |
| 预算收紧改变现有行为（可能更早停止） | 中   | `_LLM_RETRY_MIN_ATTEMPT_S` 默认 5s；发布说明中标注；测试锁定                     |
| fake clock 采样假设被破坏            | 中   | 沿用 `_retry_now()` 单点采样；先跑 `test_llm_retry.py` / `test_generation_stats` |
| 重接重放导致事件重复                 | 低   | `(attempt, streamId)` 幂等去重                                                   |
| 横幅信息过载                         | 低   | 两行紧凑布局 + 预算条；窄宽度下折叠次要信息                                      |
| win7 py38 语法/依赖                  | 低   | `Optional` / dataclass 默认值；`check_py38_compat.py`                            |
| 架构行数棘轮                         | 低   | 按本分支实测更新 baseline；prettier 折行导致的 +1 行优先压回单行                 |
| 本地分支落后 origin 2 提交           | 低   | 实施前先同步 `origin/release/win7`（a028a06a3 / 5203f7467）                      |

## 7. 双分支同步

- 本计划先落 `release/win7`（当前分支），功能完成后 cherry-pick 到 `main`；协议字段为可选，天然兼容。
- 依赖 #2815 已引入的 `budget_total_s` / `budget_remaining_s`，两个分支均已具备。
- `architecture-baseline.json` 必须分别实测（内存 `sage-win7-sync-per-branch-numbers.md`）。
