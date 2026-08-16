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
 */
import { useRef, useState } from 'react';
import { toast } from 'sonner';

import type { InvokeError } from '../shared/api/desktopInvoke';
import { orchRunClient } from '../shared/api/orchRunClient';
import type { TaskPlanItem } from '../shared/api/types';

interface PlanCardProps {
  runId: string;
  plan: TaskPlanItem[];
  locked: boolean; // 派发后转 true
  onCancel: () => void; // C4+H1：任意阶段取消 → 委托上层统一 cancelRun + 清空 taskBoard
}

export function PlanCard({ runId, plan: initialPlan, locked, onCancel }: PlanCardProps) {
  const [items, setItems] = useState(initialPlan);
  // C4：开始执行落库成功后的本地锁定（后端首 status 事件到达前防重复点击）。
  const [locallyLocked, setLocallyLocked] = useState(false);
  const effectiveLocked = locked || locallyLocked;

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
    startingRef.current = true;
    try {
      await orchRunClient.updatePlan(runId, items);
    } catch (err) {
      startingRef.current = false; // 失败后允许重试
      // 409（派发竞态）→ 静默保持编辑态，TaskBoard 首 status 事件会锁。
      if ((err as InvokeError).status_code === 409) return;
      toast.error(`计划保存失败：${err instanceof Error ? err.message : String(err)}`);
      return;
    }
    setLocallyLocked(true);
  };

  // C4+H1 (2026-08-15): 任意阶段（未派发/已锁定）取消都委托上层 onCancel ——
  // Chat.handleCancelRun 统一调 cancelRun（阻止后端自动派发）+ 清空 taskBoard。
  const handleCancel = () => {
    onCancel();
  };

  return (
    <div className="border rounded p-3 bg-bg-hover" data-testid="plan-card">
      <div className="flex justify-between mb-2">
        <h3 className="text-sm font-semibold">编排计划（{items.length} 项）</h3>
        <div className="flex gap-2">
          <button
            disabled={effectiveLocked}
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
    </div>
  );
}
