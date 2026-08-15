# §13.7 编排计划卡延后项收尾设计

> 承接 Wave 3（PR #318 `0b559d20` / #321 `ec816754`）§13.7 已知限制列表。
> 本次设计覆盖全部 3 个延后项，全部为前端收尾，单 PR 交付。
> 分支基线：main @ `ec816754`。日期：2026-08-15。

## 1. 背景与目标

Wave 3 计划卡前端接线（#318）交付后，§13.7 记录了 3 个已知限制：

| 延后项 | 现状缺口 | 目标 |
|---|---|---|
| **C4 双击竞态** | `handleStart` 连点两次可能双 `updatePlan`（本地锁定在 await 后） | 同步防重入，单次落库 |
| **handleStart 静默吞错** | `catch { return; }` 吞掉所有错误；网络/500 无用户反馈 | 区分 409 与其他错误，非 409 给 toast |
| **original_request NULL 兜底** | 旧库 NULL 行 resume 时 `?? ''` 发空消息给 LLM | 占位文案继续 + toast 提示 |

后端无需改动：`update_plan` 已有 `dispatched_at` 检查（第二次落库返回 409），
双击竞态后端已幂等安全，本波只消前端重复发送。

---

## 2. ① C4 双击竞态（`src/components/PlanCard.tsx`）

**根因**：`locallyLocked` 状态在 `await updatePlan` 成功后 set。React 状态更新
异步，双击时第二次点击在重渲染禁用按钮前进入 `handleStart` → 双 `updatePlan`。

**方案**：`useRef` 同步守卫（ref 在 await 前立即置位）：

```tsx
const startingRef = useRef(false);
const handleStart = async () => {
  if (startingRef.current) return;   // 同步防重入
  startingRef.current = true;
  try {
    await orchRunClient.updatePlan(runId, items);
  } catch (err) {
    startingRef.current = false;     // 失败后允许重试
    return handleStartError(err);    // §3 的 409 区分
  }
  setLocallyLocked(true);
};
```

- ref 在 `await` 前置位 → 双击第二击被同步拦截，不依赖重渲染。
- catch 中复位 ref → 落库失败（409 或网络/500）后用户可重试。
- `locallyLocked` state 仍保留在成功后设置（视觉锁定）。

## 3. ② handleStart 静默吞错（跨 3 层）

**根因**：`catch { return; }` 吞掉所有错误；且错误链上 409 无结构化标识
（`electron/invoke.ts` 把 HTTP 错误转成通用 `Error`，main 进程 `sage:invoke`
再 `new Error(msg)` 重包装，自定义属性过不了 Electron 21 IPC，message 可靠）。

**方案**（用户决策：增强 invoke 错误结构）：

| 层 | 改动 | 作用 |
|---|---|---|
| `electron/invoke.ts` | `invokeBackend` 非 OK 响应时在 Error 上附加 `status_code`（`res.status` 权威来源） | 进程内契约 + 单测断言 |
| `src/shared/api/desktopInvoke.ts`（renderer 唯一漏斗） | catch 拒绝，message 匹配 `/→ (\d+):/` 附加 `status_code`（已有时优先保留） | **真正穿过 IPC 的落点**，全局一劳永逸 |
| `src/components/PlanCard.tsx` | `err.status_code === 409` → 静默保持编辑态；否则 `toast.error('计划保存失败：' + message)` | 用户反馈 + 可重试 |

**409 语义**：派发竞态下后端已把计划锁定，保持编辑态是刻意的 —— TaskBoard
首 status 事件会把视图锁为任务树。409 不 toast（非用户错误）。

## 4. ③ original_request NULL 兜底（`src/features/send-message/useChat.ts`）

**现状**：`resumeOrchestration` 用 `resp.original_request ?? ''`，空串被
`sendMessage` 当正常消息 → 空 user 气泡 + 空 prompt 发给 LLM
（`ChatRequest.message` 无非空校验）。

**方案**（用户决策：占位文案继续 + 提示）：

```ts
const content = resp.original_request ?? '（旧记录无原始请求，已从计划恢复）';
if (!resp.original_request) toast.info('该记录缺少原始请求，已从计划恢复执行');
await sendMessage(content, undefined, undefined, 'force_multi', {
  planOverride: resp.plan,
  runId: resp.new_run_id,
});
```

`useChat.ts` 新增 `import { toast } from 'sonner'`（依赖已存在，Chat.tsx 在用）。

---

## 5. 涉及文件

**源文件（4）**：

| 文件 | 改动 |
|---|---|
| `src/components/PlanCard.tsx` | ref 守卫 + 409 区分 + toast |
| `src/shared/api/desktopInvoke.ts` | message → status_code 附加 |
| `electron/invoke.ts` | 抛错附加 status_code 字段 |
| `src/features/send-message/useChat.ts` | NULL 兜底 + sonner toast |

**测试（4）**：

| 测试文件 | 覆盖 |
|---|---|
| `src/widgets/chat/__tests__/PlanCard.test.tsx` | 双击单次落库 / 409 静默保持编辑态 / 非 409 toast + 可重试 |
| `src/shared/api/__tests__/desktop.test.ts` | message 解析出 status_code |
| `electron/__tests__/invoke.test.ts` | 非 OK 响应抛错带 status_code |
| `src/features/send-message/__tests__/useChat.resume.test.ts` | NULL → 占位文案 + toast |

## 6. 错误处理与测试策略

- **非 409 失败**：toast 提示 + ref 复位 → 用户可重试。
- **409**：静默，保持编辑态（TaskBoard 事件流会锁）。
- **NULL original_request**：占位文案作为 user 消息 + toast.info 提示。
- 前端 vitest 覆盖 3 项全场景；后端无改动，回归跑一遍确认不破坏。

## 7. 不在范围内

- ❌ 后端 update_plan 幂等增强（已安全）
- ❌ C4 之外的编排功能新增
- ❌ 进度可视化已知局限（§9.3 / §11.7 另行治理）
