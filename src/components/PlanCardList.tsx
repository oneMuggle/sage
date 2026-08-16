// src/components/PlanCardList.tsx
/**
 * P1-5 历史编排记录列表（Wave 2 2026-08-14）—— 展示已持久化的
 * orch_runs（run_id + status + created_at）,每行提供"恢复"按钮。
 *
 * Wave 3 C5 (2026-08-15) —— 恢复流委托:
 * onResume 只交 runId 给上层 useChat.resumeOrchestration
 *（内部完成 resumeRun → sendMessage(original_request, plan_override)，
 *  恢复原始请求逐字），组件不再内部调 resumeRun。
 */
import { useEffect, useState } from 'react';

import { orchRunClient, type OrchRunSummary } from '../shared/api/orchRunClient';

interface PlanCardListProps {
  // Wave 3 C5: onResume 只交 runId 给 useChat.resumeOrchestration
  //（内部完成 resumeRun → sendMessage(original_request, plan_override)）。
  onResume: (runId: string) => void;
}

export function PlanCardList({ onResume }: PlanCardListProps) {
  const [runs, setRuns] = useState<OrchRunSummary[]>([]);

  useEffect(() => {
    orchRunClient.listRuns().then(setRuns);
  }, []);

  const handleResume = (runId: string) => onResume(runId);

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
