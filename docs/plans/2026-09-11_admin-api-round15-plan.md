# 管理面收口 Round 15 实施计划

> 日期: 2026-09-11 · 分支: `feat/admin-api-round15` · 基于 main @ 62a92f8f
> Win7 对齐: 全部为**新功能**，不 cherry-pick 到 release/win7（31-win7-lts.md §2）。

## 背景

Round 5/9 的巡检建议、Round 6/10 的网关绑定，管理操作面有两处缺口：
1. archive 类建议只能手敲 archive 接口逐个执行——补「采纳」端点；
2. 网关 chat↔session 绑定无查看/解绑入口——补绑定管理 API。

## 批次任务

### A. 建议采纳（`backend/api/legacy_routes.py`）

- `POST /skills/consolidation/accept`：body
  `{skill_names: [...], pinned 自动跳过}` → 逐个走
  `lifecycle.set_archived(True)`（自动进审计台账）；pinned 技能跳过并在
  响应 `skipped_pinned` 报告。merge/revise 类建议不走此端点（已有草稿面）。

### B. 网关绑定管理（`backend/api/gateway_routes.py`）

- `GET /gateway/telegram/binds` — 列出绑定（chat_id/session_id/created_at）
- `DELETE /gateway/telegram/binds/{chat_id}` — 解绑（下次消息重新建会话）

### C. 测试

- `backend/tests/unit/test_consolidation_accept.py`
- `backend/tests/unit/test_gateway_binds.py`
