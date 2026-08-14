// src/components/PlanCardList.tsx
/**
 * P1-5 历史编排记录列表（Wave 2 2026-08-14）—— 展示已持久化的
 * orch_runs（run_id + status + created_at）,每行提供"恢复"按钮,
 * resume 后把新 run_id + 重建 plan 交还给调用方（onResume）。
 */
import { useEffect, useState } from 'react';

import { orchRunClient, type OrchRunSummary } from '../shared/api/orchRunClient';
import type { TaskPlanItem } from '../shared/api/types';

interface PlanCardListProps {
  onResume: (newRunId: string, plan: TaskPlanItem[]) => void;
}

export function PlanCardList({ onResume }: PlanCardListProps) {
  const [runs, setRuns] = useState<OrchRunSummary[]>([]);

  useEffect(() => {
    orchRunClient.listRuns().then(setRuns);
  }, []);

  const handleResume = async (runId: string) => {
    const resp = await orchRunClient.resumeRun(runId);
    onResume(resp.new_run_id, resp.plan);
  };

  return (
    <div className="border rounded p-3 bg-bg-hover" data-testid="plan-card-list">
      <h3 className="text-sm font-semibold mb-2">历史编排记录</h3>
      {runs.length === 0 ? (
        <div className="text-xs text-text-tertiary">暂无历史</div>
      ) : (
        <ul>
          {runs.map((r) => (
            <li
              key={r.run_id}
              className="flex justify-between items-center py-1 border-b"
              data-testid={`plan-history-row-${r.run_id}`}
            >
              <div className="text-xs">
                <div>{r.run_id}</div>
                <div className="text-text-tertiary">
                  {r.status} · {new Date(r.created_at).toLocaleString()}
                </div>
              </div>
              <button
                onClick={() => handleResume(r.run_id)}
                className="text-xs px-2 py-1 border rounded"
                data-testid={`plan-resume-${r.run_id}`}
              >
                恢复
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
