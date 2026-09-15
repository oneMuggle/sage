# 前端网关设置卡 Round 20 实施计划

> 日期: 2026-09-11 · 分支: `feat/gateway-settings-ui` · 基于 main @ 38576040
> 来源: 「剩余已知差距」#4（consolidation/pin 管理面前端未接入）的网关部分
> Win7 对齐: 全部为**新功能**，不 cherry-pick 到 release/win7（31-win7-lts.md §2）。

## 背景

Round 19 的网关配置端点（GET/PUT /gateway/telegram/config）目前只能
API 调用。本批接入 Settings 页：新增「消息网关」卡片——token/白名单/
启用开关的查看与保存 + 运行状态与绑定列表（status/binds 端点）。

## 批次任务

### A. `src/shared/api/gatewayApi.ts`（新）

- `gatewayApi.getConfig/updateConfig/status/listBinds/unbind`，
  全部走 `backendRequest`（Electron relay，浏览器 fallback fail-closed）

### B. `src/widgets/settings/GatewayCard.tsx`（新）

- 配置态：bot token（写入口令式输入，读回显示打码值）、白名单
  （逗号分隔输入）、启用开关、保存按钮（PUT → restart_required 提示）
- 状态行：source（env/settings/none）/ running / 绑定数
- 绑定列表：chat_id + 解绑按钮（DELETE，确认后执行）

### C. 接入

- `GeneralTab.tsx` 挂 `<GatewayCard />`（「连接」分区）

### D. 测试

- `src/widgets/settings/__tests__/GatewayCard.test.tsx`（jsdom +
  mock backendRequest）：读回打码渲染 / 保存调用 PUT 载荷 / 解绑确认
