# 编排计划前置 Round 3——preflight 可视化 + 设置旋钮透出

> 日期: 2026-09-19
> 前序: orch-plan-preflight Round 1（澄清门+侦察先行）/ Round 2（计划×编排打通），PR #1218
> 目标分支: feat/orch-plan-preflight（同分支延续）

## 背景

Round 1 登记的两个收尾项：
1. `orch_preflight` 事件已发但前端忽略——澄清/侦察窗口期（最长 ~7 分钟）
   用户只看到沉默，不知道系统在做什么；
2. `planPreflightEnabled / planScoutEnabled` 后端旋钮已落，设置页无入口
   ——round25/26 诊断过的"后端有闸门、用户找不到旋钮"。

## 批次 A：preflight 状态可视化

事件流：`{"state": "orch_preflight", "phase": "clarify"|"scout"}`（task_plan 之前）。

- `types.ts`：`AgentState` 联合 + `'orch_preflight'`；`AgentEvent` + `phase?`。
- `chatStreamStore.ts`：会话槽位 + `preflightPhase: 'clarify'|'scout'|null`
  （**独立于 taskBoard**——事件先于 task_plan 到达，此时板还不存在）；
  新 action `setPreflightPhase(sessionId, phase)`。
- `orchestrationEvents.ts`：`orch_preflight` → 写槽位；`task_plan` 初始化
  任务板时清空（进入确认/执行阶段）。
- `useChat.ts` `finishStream`：流结束兜底清空（拆解失败降级 single 时无
  task_plan，防止指示条跨 run 残留）。
- `Chat.tsx`：PlanCard 区块上方渲染指示条
  （`data-testid="orch-preflight-indicator"`）——"正在澄清需求…" /
  "正在侦察收集事实…"；仅在 `!taskBoard`（未拆解）时显示。

## 批次 B：设置旋钮透出

- `entities/setting/types.ts`：`OrchSettings` + `planPreflightEnabled/
  planScoutEnabled`（默认 true）+ `DEFAULT_ORCH_SETTINGS` 同步。
- `GeneralTab.tsx` 编排段：两个 `SettingRow`+`Toggle`（编排 section 顶部
  ——管线级开关排在数值旋钮前）。
- **后端 `data/settings_canonicalizer.py`**：`ALIASES` + `LEGAL_ORCH_KEYS`
  补两个键——round26 同款坑：缺白名单 → 编排段任一保存 400
  `invalid_settings_shape`（且前端静默吞错，设置永远无法持久化）。

## 验收

- `orchestrationEvents.test.ts`：orch_preflight 写槽位 / task_plan 清空。
- `GeneralTab.orch.test.tsx`：两个开关的部分更新契约
  （`updateSettings({ orch: { ...orch, key: v } })` 保留其余键）。
- `test_settings_canonicalizer.py`：新键过白名单 + snake 别名回翻。
- `tsc --noEmit` / eslint / 定向后端回归全绿。

## 非目标（继续登记）

- 计划 artifact 持久化 + 执行期逐步对照 + 验收失败定点返工（TaskPacket 激活）。
