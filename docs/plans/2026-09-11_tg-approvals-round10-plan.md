# Telegram 审批转发 Round 10 实施计划（对标 hermes-agent gateway）

> 日期: 2026-09-11 · 分支: `feat/telegram-approval-forward` · 基于 main @ c02255df
> 来源: hermes-agent 对标分析（网关实用性关键一步：远程审批）
> Win7 对齐: 全部为**新功能**，不 cherry-pick 到 release/win7（31-win7-lts.md §2）。

## 背景

Round 6 网关支持了远程对话。无人值守场景的最后一环是**远程审批**：
agent 请求执行危险操作时，审批请求转发到 Telegram，用户 `/approve`/`/deny`
远程裁决——复用既有 `ApprovalGate`（M1 权限闸口）与 Round 6 网关基建，
不新增任何权限面。

## 方案（纯轮询，零闸口改动）

### A. `backend/gateway/telegram.py` 扩展

- `poll_once` 每 tick 调 `_forward_new_approvals()`：`gate.pending()`
  中未转发过的请求格式化后发到白名单 chats（request_id 全量去重）
- 命令处理（白名单内、不进 LLM 对话）：
  - `/pending` — 列出挂起审批（短 id + 工具 + 风险）
  - `/approve <短id>` / `/deny <短id>` — 短 id（request_id 前 8 位）
    前缀匹配 → `gate.answer()`；未知/已处理显式提示
  - `/status` — 网关统计

### B. 测试

- `backend/tests/unit/test_telegram_approvals.py`：转发去重、approve/deny
  命令解析 gate、未知短 id、pending 列表、命令不进 LLM 对话
