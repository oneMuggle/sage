// src/components/PlanCard.tsx
/**
 * P1-5 计划卡（Wave 2 2026-08-14）—— 编排计划可交互编辑。
 *
 * 在首次派发前展示 task_plan 内容：每行 = agent 徽标 + goal textarea
 * （可编辑）+ 删除按钮（≥1 行守卫）。头部"开始执行"派发后转锁定
 * （disabled，后端 update_plan 同步返回 409）。
 *
 * Wave 3 C4 (2026-08-15) —— 交互接线：
 * - 开始执行：内部先 orchRunClient.updatePlan(runId, items) 落库，
 *   成功后本地锁定（locallyLocked）。派发由后端 conductor 工具调用驱动，
 *   前端无需额外回调（M4 2026-08-15：onStart 链已收口删除）。
 * - 取消（C4+H1, 2026-08-15）：任意阶段都委托上层 onCancel()，
 *   由 Chat.handleCancelRun 统一调 cancelRun（未派发时后端置
 *   cancelled + dispatcher.cancel() 阻止自动派发，避免空转烧 token）
 *   + 清空 taskBoard；取消失败也照常清理（.catch 兜底）。
 *
 * 编排计划卡片 UX (2026-10-26) —— 三项优化：
 * 1. reasoning 折叠展示：LLM 的规划思路默认收起，用户想看再展开
 *    （原来的界面只给干巴巴的任务清单，看不到决策过程）。
 * 2. 乐观折叠：点"开始执行"成功即折叠成一行摘要，不必等首个
 *    task_status 事件才消失 —— 修复"卡片霸占会话区底部"的问题。
 *    用户仍可手动展开回看（派发后后端 409 锁编辑，纯只读）。
 * 3. 自然语言修订：锁定前可用一句话让 LLM 改计划（走后端
 *    plan-items 修订通道），不必在"开始执行 / 取消"之间二选一。
 *    修订以本地 items（含未提交的 textarea 编辑）为基线，且与"开始执行"
 *    互斥 —— 两者是同一个 plan_json 的竞争写者。
 */
import { useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';

import type { InvokeError } from '../shared/api/desktopInvoke';
import { orchRunClient } from '../shared/api/orchRunClient';
import type { TaskPlanItem } from '../shared/api/types';

interface PlanCardProps {
  runId: string;
  plan: TaskPlanItem[];
  locked: boolean; // 派发后转 true
  onCancel: () => void; // C4+H1：任意阶段取消 → 委托上层统一 cancelRun + 清空 taskBoard
  // Fix #3 (2026-09-06): 需要用户显式确认才开始执行。
  // true → handleStart 调 updatePlan + confirmRun（唤醒 producer 启动 conductor）。
  // false → 仅调 updatePlan（旧行为，依赖 conductor 自动 dispatch）。
  needConfirm?: boolean;
  // 编排计划卡片 UX (2026-10-26): LLM 规划思路（折叠展示）。
  reasoning?: string;
  // 编排计划卡片 UX (2026-10-26): 自然语言修订 —— 上层负责 plan-items
  // 修订调用 + updatePlan 落库 + store 回写；这里只透出用户输入的一句话。
  // currentItems 传本组件的本地 items（含用户未提交的 textarea 编辑），
  // 不能用 store 里的 taskBoard.plan —— 后者在用户点"开始执行"落库前
  // 一直是原始计划，拿它当修订基线会把用户的 goal 编辑静默冲掉。
  onRevise?: (instruction: string, currentItems: TaskPlanItem[]) => Promise<void>;
  revising?: boolean;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatPlanCardMarkdown(
  runId: string,
  plan: TaskPlanItem[],
  locked: boolean,
  needConfirm?: boolean,
): string {
  const lines = [
    `# 编排计划 (${runId || '—'})`,
    `- 状态: ${locked ? '已锁定' : '待编辑'}`,
    `- 需确认: ${needConfirm ? '是' : '否'}`,
    `- 计划项数: ${plan.length}`,
  ];
  for (const item of plan) {
    lines.push(`- **${item.task_id}** [${item.agent_id}]: ${item.goal}`);
  }
  return lines.join('\n');
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatPlanCardJson(
  runId: string,
  plan: TaskPlanItem[],
  locked: boolean,
  needConfirm?: boolean,
): string {
  return JSON.stringify(
    {
      runId,
      locked,
      needConfirm: Boolean(needConfirm),
      count: plan.length,
      items: plan.map((it) => ({
        task_id: it.task_id,
        agent_id: it.agent_id,
        goal: it.goal,
      })),
    },
    null,
    2,
  );
}

export function PlanCard({
  runId,
  plan: initialPlan,
  locked,
  onCancel,
  needConfirm = false,
  reasoning,
  onRevise,
  revising = false,
}: PlanCardProps) {
  const [items, setItems] = useState(initialPlan);
  // 编排计划卡片 UX (2026-10-26): 修订结果经上层写回 store → 新 plan 数组
  // 引用到达本组件，同步进本地 items（useState 初始值不会跟随 prop 变化）。
  // 确认窗口内 initialPlan 换引用只有一种来源 = 修订结果回写：
  // orchestrationEvents 的 task_plan 分支对同一 run 的重复事件（NDJSON
  // 重放）不再重建任务板，所以重放不会走到这里覆盖用户编辑。
  useEffect(() => {
    setItems(initialPlan);
  }, [initialPlan]);
  // C4：开始执行落库成功后的本地锁定（后端首 status 事件到达前防重复点击）。
  const [locallyLocked, setLocallyLocked] = useState(false);
  const effectiveLocked = locked || locallyLocked;
  // 编排计划卡片 UX (2026-10-26): 乐观折叠 + 规划思路/修订输入开关。
  const [collapsed, setCollapsed] = useState(false);
  const [showReasoning, setShowReasoning] = useState(false);
  const [instruction, setInstruction] = useState('');

  const updateGoal = (idx: number, goal: string) => {
    setItems(items.map((it, i) => (i === idx ? { ...it, goal } : it)));
  };

  const removeItem = (idx: number) => {
    if (items.length <= 1) return; // ≥1 行守卫
    setItems(items.filter((_, i) => i !== idx));
  };

  // §13.7 C4 (2026-08-15): ref 同步守卫 —— await 前置位，双击第二击被拦截
  // （React 状态更新异步，locallyLocked 在成功后 set 拦不住双击）。
  const startingRef = useRef(false);
  const handleStart = async () => {
    if (startingRef.current) return;
    // 修订是一次 5-30s 的 LLM 往返，期间不允许开始执行 —— 否则
    // updatePlan（旧计划）与修订落库竞态，conductor 可能执行旧计划而界面
    // 显示新计划（静默分叉）。
    if (revising) return;
    startingRef.current = true;
    try {
      await orchRunClient.updatePlan(runId, items);
      // Fix #3 (2026-09-06): needConfirm 模式下,updatePlan 后调 confirmRun
      // 唤醒后端 producer（producer 在 task_plan 后暂停等待用户确认）。
      if (needConfirm) {
        await orchRunClient.confirmRun(runId);
      }
    } catch (err) {
      startingRef.current = false; // 失败后允许重试
      // 409（派发竞态）→ 静默保持编辑态，TaskBoard 首 status 事件会锁。
      if ((err as InvokeError).status_code === 409) return;
      toast.error(`计划保存失败：${err instanceof Error ? err.message : String(err)}`);
      return;
    }
    setLocallyLocked(true);
    // 乐观折叠：确认成功即收起，任务板头部/进度区接管执行可视化，
    // 不再让计划卡继续霸占会话区（问题 2）。
    setCollapsed(true);
  };

  // C4+H1 (2026-08-15): 任意阶段（未派发/已锁定）取消都委托上层 onCancel ——
  // Chat.handleCancelRun 统一调 cancelRun（阻止后端自动派发）+ 清空 taskBoard。
  const handleCancel = () => {
    onCancel();
  };

  // 编排计划卡片 UX (2026-10-26): 一句话修订（问题 3）。失败不折叠、
  // 不清空输入，用户可改写法重试。currentItems 传本地 items —— 用户在
  // textarea 里改过但还没点"开始执行"的 goal 必须作为修订基线，否则
  // 后端"未提及任务原样保留"会把旧 goal 还原回来。
  const handleRevise = async () => {
    const text = instruction.trim();
    if (!text || !onRevise) return;
    // 开始执行已在飞行中 → 拒绝修订，别和落库竞态。
    if (startingRef.current) {
      toast.error('正在开始执行，请稍候再调整计划');
      return;
    }
    try {
      await onRevise(text, items);
      setInstruction('');
    } catch (err) {
      toast.error(`计划修订失败：${err instanceof Error ? err.message : String(err)}`);
    }
  };

  /* v8 ignore start */

  /* v8 ignore stop */

  // 编排计划卡片 UX (2026-10-26): 乐观折叠 —— 点"开始执行"成功即收起成
  // 一行摘要，把会话区底部还给任务板/进度条；用户仍可展开回看（派发后
  // 后端 409 锁编辑，展开态为纯只读）。
  if (collapsed) {
    return (
      <div
        className="border rounded p-2 bg-bg-hover flex items-center justify-between"
        data-testid="plan-card-collapsed"
      >
        <span className="text-xs text-text-secondary">编排计划已开始执行（{items.length} 项）</span>
        <button
          onClick={() => setCollapsed(false)}
          data-testid="plan-expand"
          className="px-2 py-1 text-xs border rounded"
        >
          展开计划
        </button>
      </div>
    );
  }

  return (
    <div className="border rounded p-3 bg-bg-hover" data-testid="plan-card">
      <div className="flex justify-between mb-2">
        <h3 className="text-sm font-semibold">编排计划（{items.length} 项）</h3>
        <div className="flex gap-2">
          <button
            disabled={effectiveLocked || revising}
            onClick={() => void handleStart()}
            data-testid="plan-start"
            className="px-2 py-1 text-xs border rounded bg-primary/10 text-primary"
          >
            {effectiveLocked ? '已开始执行（计划锁定）' : '开始执行'}
          </button>
          <button
            onClick={handleCancel}
            data-testid="plan-cancel"
            className="px-2 py-1 text-xs border rounded"
          >
            {effectiveLocked ? '取消执行' : '取消'}
          </button>
        </div>
      </div>

      {/* 编排计划卡片 UX (2026-10-26): 规划思路（问题 1）—— 默认收起，
          用户想看 LLM 为什么这样拆解再展开，不占首屏视觉重心。 */}
      {reasoning && reasoning.trim() && (
        <div className="mb-2">
          <button
            onClick={() => setShowReasoning((v) => !v)}
            data-testid="plan-reasoning-toggle"
            className="text-xs text-text-secondary hover:text-text-primary"
          >
            {showReasoning ? '▾ 隐藏规划思路' : '▸ 查看 LLM 规划思路'}
          </button>
          {showReasoning && (
            <pre
              className="mt-1 text-xs whitespace-pre-wrap p-2 border rounded bg-bg-primary text-text-secondary"
              data-testid="plan-reasoning"
            >
              {reasoning}
            </pre>
          )}
        </div>
      )}

      {items.map((item, idx) => (
        <div
          key={item.task_id}
          className="flex gap-2 items-start mb-1"
          data-testid={`plan-row-${item.task_id}`}
        >
          <span className="px-1 rounded bg-primary/10 text-primary">{item.agent_id}</span>
          <textarea
            value={item.goal}
            disabled={effectiveLocked}
            onChange={(e) => updateGoal(idx, e.target.value)}
            className="flex-1 text-xs p-1 border rounded"
            data-testid={`plan-goal-${item.task_id}`}
          />
          <button
            disabled={effectiveLocked || items.length <= 1}
            onClick={() => removeItem(idx)}
            data-testid={`plan-remove-${item.task_id}`}
            className="px-1 border rounded"
          >
            ×
          </button>
        </div>
      ))}

      {/* 编排计划卡片 UX (2026-10-26): 自然语言修订（问题 3）—— 锁定前
          可用一句话让 LLM 改计划；派发后后端 409 锁计划，按钮随之隐藏。 */}
      {!effectiveLocked && onRevise && (
        <div className="mt-2 pt-2 border-t" data-testid="plan-revise">
          <textarea
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            placeholder="用一句话说明要怎么改，例如：把调研拆成中英两篇、写作步骤加一个摘要"
            className="w-full text-xs p-1 border rounded"
            rows={2}
            data-testid="plan-revise-input"
          />
          <button
            disabled={revising || !instruction.trim()}
            onClick={() => void handleRevise()}
            data-testid="plan-revise-submit"
            className="mt-1 px-2 py-1 text-xs border rounded bg-primary/10 text-primary"
          >
            {revising ? 'LLM 正在调整…' : '按这句话调整计划'}
          </button>
        </div>
      )}
    </div>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditPlanCardGovernance(
  state: {
    stepCount?: number;
    completedCount?: number;
  } = {},
): {
  module: 'src/components/PlanCard.tsx';
  phase: 'P152';
  stepCount: number;
  completedCount: number;
  healthy: boolean;
} {
  const stepCount =
    typeof state.stepCount === 'number' && Number.isFinite(state.stepCount)
      ? Math.max(0, Math.trunc(state.stepCount))
      : 3;
  const completedCount =
    typeof state.completedCount === 'number' && Number.isFinite(state.completedCount)
      ? Math.max(0, Math.min(stepCount, Math.trunc(state.completedCount)))
      : 1;
  return {
    module: 'src/components/PlanCard.tsx',
    phase: 'P152',
    stepCount,
    completedCount,
    healthy: stepCount >= 1 && completedCount <= stepCount,
  };
}
