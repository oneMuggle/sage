# 网关会话上下文预算 Round 11 实施计划（对标 hermes-agent）

> 日期: 2026-09-11 · 分支: `feat/gateway-context-budget` · 基于 origin/main @ 70fb1287
> 来源: hermes-agent 对标分析（长会话上下文治理）
> Win7 对齐: 全部为**新功能**，不 cherry-pick 到 release/win7（31-win7-lts.md §2）。

## 背景

Telegram 网关的对话历史按「最近 20 条」截断（`_MAX_HISTORY`）——20 条
超长消息（如贴入的日志）即可撑爆上下文。hermes 按 token 预算治理历史。
本批给网关对话加 **token 预算截断**（ oldest-first，保留最近消息 + 早期
省略提示），复用 `core/legacy/context_first_aid.estimate_messages_tokens`
既有估算器（单一事实来源）。

## 批次任务

### A. `backend/gateway/telegram.py`

- `_history_budget_messages(history, budget_tokens) -> (kept, omitted_count)`：
  从最新往回累积 token，超出预算即停（至少保留最近 2 条）；
  omitted>0 时在历史头部插入一条 system 说明（「早期 N 条已省略」）
- 预算 env `SAGE_GW_HISTORY_TOKEN_BUDGET`（默认 4000）
- 预算 ≤0 时保持旧行为（仅条数上限）

### B. 测试

- `backend/tests/unit/test_telegram_approvals.py` 追加或新建
  `test_gateway_history_budget.py`：短历史不动 / 长历史截断 + 省略提示 /
  预算关闭

## 验收

- [ ] 新测试全绿 + 网关存量测试不回归
- [ ] ruff 干净；CI 覆盖率 ≥80% 绿
