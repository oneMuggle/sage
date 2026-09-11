# 网关命令完善 + 使用文档 Round 12 实施计划

> 日期: 2026-09-11 · 分支: `feat/gateway-commands-docs` · 基于 main @ dba8d1f5
> 来源: hermes-agent 对标（网关命令面收口）
> Win7 对齐: 全部为**新功能**，不 cherry-pick 到 release/win7（31-win7-lts.md §2）。

## 批次任务

### A. `backend/gateway/telegram.py` 命令补全

- `/reset` — 解绑当前 chat 的会话并新建（长对话治理；配合 Round 11
  token 预算，重置即全新上下文）
- `/help` — 网关命令总览
- 未知 `/xxx` 命令 → 提示 `/help`（不再落入 LLM 对话产生困惑回答）

### B. 文档

- `docs/technical/32-telegram-gateway.md`（新）：启用步骤（环境变量）、
  白名单、命令表、审批转发说明、安全边界（默认关闭/非沙箱声明）
- `README.md` 核心功能表追加「消息网关（Telegram）」行

### C. 测试

- 命令测试追加 `/reset`（绑定变更 + 消息进新会话）、`/help`、未知命令

## 验收

- [ ] 测试全绿；ruff 干净；CI 绿
