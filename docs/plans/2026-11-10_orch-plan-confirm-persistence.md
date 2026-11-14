# 编排计划确认状态持久化

> 修复：会话切换后编排计划回退到「待确认」状态（开始执行/取消按钮重现、goal 可编辑）

## 背景与目标

### 问题现象

用户在编排会话中确认了计划（点击「开始执行」），切换到其他会话后再切回，
计划卡片又显示「开始执行」/「取消」按钮，goal 行可编辑。

### 根因

1. **`PlanCard.locallyLocked` 是组件局部 state**（`PlanCard.tsx:119`），
   卸载后丢失。
2. **`PlanApprovalBar` 传 `locked={false}` 硬编码**（`PlanApprovalBar.tsx:344`），
   没有从 store 读取持久锁定信号。
3. **`task_plan` 事件重放重建 board 但 `dispatchedAt == null`**
   （`orchestrationEvents.ts:87-106`），`PlanApprovalBar` 在
   `!dispatchedAt` 时渲染 PlanCard。
4. **`reattachActiveStream` 调 `startStream` 清空 board**
   （`chatStreamRuntime.ts:418`），`useChatStickyScroll` restore 因 effect
   排序被跳过（`useChatStickyScroll.ts:119` early return）。
5. **后端 `confirmRun` 不写库**（`orch_routes.py:454-490`），确认状态仅存
   于内存 `asyncio.Event`，重启丢失。`OrchRunDetail` 不返回
   `confirmed_at`/`dispatched_at`。

### 目标

- 确认状态持久化到 SQLite（`confirmed_at` 列），重启/切换不丢失
- API 返回真实 `confirmed_at` + `dispatched_at`，前端据此恢复锁定态
- `PlanApprovalBar` 动态计算 `locked`，不依赖组件局部 state
- `reattachActiveStream` 不再无意义清空已有 board
- 双分支（main + release/win7）对齐

## 涉及的文件与模块

### 后端

| 文件 | 改动 |
|------|------|
| `backend/data/database.py` | `orch_runs` 新增 `confirmed_at` 列（ALTER TABLE） |
| `backend/data/orch_run_repo.py` | `OrchRun` dataclass 新增字段；`upsert`/`get`/`list`/`list_by_session` 同步；新增 `mark_confirmed()` |
| `backend/api/orch_routes.py` | `OrchRunDetail` 返回 `confirmed_at` + `dispatched_at`；`confirm_run` 写库 |

### 前端

| 文件 | 改动 |
|------|------|
| `src/shared/api/orchRunClient.ts` | `OrchRunDetail` 接口新增 `confirmed_at` + `dispatched_at` |
| `src/features/send-message/chatStreamStore.ts` | `TaskBoardState` 新增 `confirmedAt` |
| `src/features/send-message/orchestrationEvents.ts` | `restoreRunToBoard` 映射真实 `confirmedAt`；`task_plan` handler 保留 `confirmedAt` |
| `src/features/send-message/chatStreamRuntime.ts` | `reattachActiveStream` 保留已有 board |
| `src/pages/chat/PlanApprovalBar.tsx` | `locked` prop 动态计算 |
| `src/pages/chat/useChatStickyScroll.ts` | restore 映射 `confirmedAt` |

## 实施步骤

- [ ] M1: 后端 DB 迁移 — `orch_runs` 加 `confirmed_at` 列
- [ ] M2: 后端 repo — `OrchRun` 加字段 + `mark_confirmed()` + 所有 SELECT 映射
- [ ] M3: 后端 API — `OrchRunDetail` 加 `confirmed_at`/`dispatched_at` + `confirm_run` 写库
- [ ] M4: 前端 type — `orchRunClient.OrchRunDetail` 加字段
- [ ] M5: 前端 store — `TaskBoardState` 加 `confirmedAt`
- [ ] M6: 前端 restore — `restoreRunToBoard` 映射真实 `confirmedAt`/`dispatchedAt`
- [ ] M7: 前端 reattach — 保留已有 board（不清空）
- [ ] M8: 前端 PlanApprovalBar — 动态 `locked` prop
- [ ] M9: 测试 — 更新/补充相关测试
- [ ] M10: 移植到 release/win7

## 风险评估

- **ALTER TABLE 幂等**：用 `PRAGMA table_info` + `if "confirmed_at" not in cols` 守卫，
  与 `original_request` / `revision` 同模式。worktree 共用同一 `data/sage.db`，双进程
  竞争需 try/except 兜底（已有惯例）。
- **`confirmed_at` 与 `dispatched_at` 语义区分**：`confirmed_at` = 用户确认时间，
  `dispatched_at` = 首个 task_status 到达时间。两者可能相差数秒。
  `PlanApprovalBar` 用 `confirmedAt ?? dispatchedAt` 做锁定信号。
- **`reattachActiveStream` 保留 board**：不再调 `startStream` 清空 taskBoard，
  改为选择性重置（streaming 相关字段重置，taskBoard 保留）。
  需确认不影响 `startStream` 的其他语义（streaming state 必须重置）。
- **release/win7 pydantic v1**：`OrchRunDetail` 改动需检查 pydantic v1 兼容性
  （`model_config` → `Config` class 差异已有项目惯例）。

## 依赖

- 无外部依赖，纯内部改动
