# LLM 重试预算/次数可见性与设置保存失败提示

> 日期：2026-11-02
> 分支：`fix/llm-retry-budget-visibility`（main → cherry-pick 到 release/win7）

## 背景与目标

用户反馈：在 win7 最新安装包中把「重试次数」设为 10，遇到 429 时却只重试了 3 次。

根因（上一轮已诊断确认）：

1. 参数确实生效 —— 后端读到了 `max_attempts=10`、`total_budget=180`。
2. 真正截断重试的是 **总时长预算**：上游 `Retry-After` 约 60 秒，单次等待被
   `llmRetryMaxDelayS`（默认 60）封顶，180 秒预算 ÷ 60 秒 ≈ 3 次后
   `elapsed + delay > budget` 命中，循环停止。
3. 但 UI 完全看不出「预算截断」这回事：
   - 设置页「最大重试次数」的语义实际是「总尝试次数（含首次）」，文案误导；
   - 预算与次数的「先到先停」关系没有说明；
   - 重试横幅只显示 `(attempt/max)`，不显示剩余预算；
   - 最终错误消息虽然带「总时长预算，已停止」后缀，但缺少可操作提示。
4. 另有两个独立缺陷：
   - 429 分类未回传 `status_code=429`（401 有回传），下游无法按状态码区分限流；
   - 设置 PUT 失败被 `saveSettings` 静默吞掉（仅 console.warn），用户会看到
     UI 显示新值、重启后却回到旧值。

目标：

- P0：让「预算 vs 次数」的交互在设置页、重试横幅、最终错误消息三处可见。
- P1：修正「最大重试次数」的文案语义（尝试次数含首次，10 = 9 次重试）。
- P1：429 错误回传 `status_code=429`。
- P1：设置写入后端失败时给出用户可见提示（节流，避免连点刷屏）。

## 涉及文件与模块

### 后端

| 文件 | 改动 |
| --- | --- |
| `backend/core/legacy/llm_client.py` | `RetryEvent` 增加 `budget_total_s` / `budget_remaining_s`；两条重试循环（`chat` / `chat_stream_events`）填充预算字段；预算耗尽错误消息加入 `attempt/max` 与可操作提示；429 分类补 `status_code=429` |
| `backend/core/legacy/agent.py` | `retry` 事件转换时透传新的预算字段 |
| `backend/tests/unit/test_llm_retry.py` | 新增 429 status_code 测试、预算事件字段测试；强化预算停止消息断言 |

### 前端

| 文件 | 改动 |
| --- | --- |
| `src/shared/api/types/chatAndEventTypes.ts` | `RetryInfo` 增加可选 `budget_total_s` / `budget_remaining_s` |
| `src/widgets/chat/RetryBanner.tsx` | 有剩余预算时显示「剩余预算 N 秒」 |
| `src/shared/lib/i18n/retryBanner.ts` | 新增 `chat.retry.budget_remaining`（zh/en） |
| `src/shared/lib/i18n/locales/{zh,en}/settingsUi.ts` | 修正重试次数/预算/最大退避文案；新增保存失败提示 key |
| `src/shared/lib/i18n/index.tsx` | 新增 `translateStatic(key)`，供非组件代码（store）取当前 locale 文案 |
| `src/entities/setting/storage.ts` | `saveSettings` 改用 `setSettingsStrict` 并返回是否成功（后端确认语义） |
| `src/features/manage-settings/settingsStore.ts` | `updateSettings` 在保存失败时 toast（5 秒节流） |

### 测试

- 后端：`backend/tests/unit/test_llm_retry.py`
- 前端：
  - `src/entities/setting/__tests__/storage.test.ts`（保存成功/失败返回值）
  - `src/features/manage-settings/__tests__/settingsStore.saveFailure.test.ts`（新增，toast + 节流）
  - `src/widgets/chat/__tests__/RetryBanner.test.tsx`（预算剩余渲染）
  - `src/shared/lib/i18n/__tests__/index.test.tsx`（`translateStatic`）

## 技术方案

### 1. 预算事件的字段设计

`RetryEvent` 新增两个可选字段（默认 `None`，向后兼容）：

```python
budget_total_s: Optional[float] = None      # 0 或未配置时为 None
budget_remaining_s: Optional[float] = None  # 本次等待后剩余预算，>= 0
```

计算口径（两条循环一致）：

```python
budget_remaining = None
if total_budget > 0:
    budget_remaining = max(0.0, total_budget - ((_retry_now() - retry_started) + delay))
```

agent 转 `AgentEvent(retry_info=...)` 时一并透传；前端 `RetryInfo` 同名字段，
`RetryBanner` 在 `budget_remaining_s != null` 时渲染 `剩余预算 N 秒`。

### 2. 预算耗尽消息

两条循环统一为：

```
{原始消息}（已尝试 {attempt}/{max_attempts} 次后停止：本次重试还需等待 {delay:.0f}s，
加上此前累计等待将超过 {total_budget:.0f}s 总时长预算。可在「设置 → 基础 → LLM 重试」
调大总时长预算或降低最大退避）
```

保留「预算」字样以兼容既有断言；新增断言覆盖次数与可操作提示。

### 3. 文案语义

- `settings.basic.retry_max_label`：`最大尝试次数（含首次请求）` / `Max attempts (incl. first request)`
- `retry_max_desc`：说明 10 = 最多请求 10 次（重试 9 次），且会被预算先到先停。
- `retry_total_budget_desc`：用「Retry-After 60s + 预算 180s ≈ 3 次」的示例说明截断。
- `max_delay.desc`：说明 Retry-After 与指数退避都受该上限约束。

存储键名 `llmRetryMaxAttempts` 不变，避免迁移。

### 4. 设置保存失败可见化

- `saveSettings(partial): Promise<boolean>` —— 改用 `setSettingsStrict`
  （只有后端确认才算成功；超时/失败返回 `false` 并 `console.warn`）。
- 唯一调用方 `settingsStore.updateSettings`：`false` 时
  `toast.error(translateStatic('settings.save_failed_sync'))`，同一失败
  5 秒内只提示一次。
- `translateStatic` 读取 `localStorage['sage.locale']`，与 Provider 持久化一致；
  无 Provider 的 store 代码也能拿到正确语言的文案。
- `updateSettingsStrict` 路径不变（继续抛错给调用方）。

## 实施步骤

- [x] 步骤 1：编写计划文档（本文件）
- [x] 步骤 2：后端 RED —— 新增/强化 `test_llm_retry.py` 断言（429 status_code、预算事件字段、预算停止消息）
- [x] 步骤 3：后端 GREEN —— `llm_client.py` + `agent.py` 实现
- [x] 步骤 4：前端 RED —— storage/settingsStore/RetryBanner/i18n 测试
- [x] 步骤 5：前端 GREEN —— 类型、i18n、storage、store、RetryBanner 实现
- [x] 步骤 6：本地验证（pytest 目标文件、vitest 目标文件、tsc、ruff、prettier）
- [x] 步骤 7：代码审查（CI 门禁 + 本地多轮验证覆盖：pytest/vitest/tsc/ruff/prettier/eslint/arch）
- [x] 步骤 8：提交 + PR 到 main（PR #2812；首次 CI 因陈旧测试断言红灯，已修）
- [x] 步骤 9：cherry-pick 到 release/win7（py3.8 验证 16/16 / 实测 baseline 更新 / PR #2815）
- [ ] 步骤 10：归档计划（并入技术手册/记忆索引后删除本文件）— 待双 PR 合并后执行

## 风险评估与依赖

- **行为兼容**：`saveSettings` 从「静默失败」改为「返回 false + toast」，不改变
  乐观 UI 与 localStorage 缓存策略；后端不可用时会多一次 toast，但被节流。
- **事件协议兼容**：预算字段为可选，前端旧版本收到新事件会忽略；后端旧版本
  不发送时前端不渲染预算，行为不变。
- **测试影响面**：`saveSettings` 改用 strict 后，mock `settingsClient` 的测试
  若走到真实 store 需补 `setSettingsStrict`；已确认 BasicTab 等页面测试 mock 了
  `useSettings`，不走 store。
- **win7 适配**：改动均为纯逻辑/文案，py3.8 语法兼容（沿用 `Optional` 注解与
  现有 `from __future__ import annotations`）；无 pydantic 依赖变化。
- **不包含**：前端默认 `llmRetryMaxDelayS=30` 与后端默认 15 的不一致（P2，
  用户未批准），本轮不动。
