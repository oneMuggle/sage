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
 *   成功后本地锁定（locallyLocked）+ onStart(items)。
 * - 取消语义随 locked：未派发 → onCancel()（仅前端清理）；
 *   已派发 → orchRunClient.cancelRun(runId) + onCancelled()。
 */
import { useState } from 'react';

import { orchRunClient } from '../shared/api/orchRunClient';
import type { TaskPlanItem } from '../shared/api/types';

interface PlanCardProps {
  runId: string;
  plan: TaskPlanItem[];
  locked: boolean; // 派发后转 true
  onCancel: () => void;
  onStart: (updatedPlan: TaskPlanItem[]) => void;
  onCancelled?: () => void; // C4：取消执行成功后的回调（前端清空 taskBoard）
}

export function PlanCard({
  runId,
  plan: initialPlan,
  locked,
  onCancel,
  onStart,
  onCancelled,
}: PlanCardProps) {
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

  const handleStart = async () => {
    try {
      await orchRunClient.updatePlan(runId, items);
    } catch {
      // 409（派发竞态）→ 保持编辑态，TaskBoard 首 status 事件会锁
      return;
    }
    setLocallyLocked(true);
    onStart(items);
  };

  const handleCancel = () => {
    if (effectiveLocked) {
      void orchRunClient.cancelRun(runId).then(() => onCancelled?.());
    } else {
      onCancel();
    }
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
