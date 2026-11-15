import { useEffect, useState } from 'react';

import { projectApi, type ProjectHealthSummary } from '../../../shared/api';

interface SeverityTone {
  dot: string;
  label: string;
  bg: string;
}

const SEVERITY_TONES: Record<string, SeverityTone> = {
  ok: { dot: 'bg-emerald-500', label: '一切正常', bg: 'bg-emerald-500/10' },
  warning: { dot: 'bg-amber-500', label: '需要关注', bg: 'bg-amber-500/10' },
  critical: { dot: 'bg-rose-500', label: '存在风险', bg: 'bg-rose-500/10' },
};

export interface HealthSummaryCardProps {
  projectId: string;
}

/** 项目健康摘要卡（M1, 2026-11-14）：打开概览时刷新并展示逾期告警。 */
export function HealthSummaryCard({ projectId }: HealthSummaryCardProps) {
  const [summary, setSummary] = useState<ProjectHealthSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setSummary(null);
    setError(null);
    projectApi
      .checkProjectHealth(projectId)
      .then((result) => {
        if (!cancelled) setSummary(result);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const tone = SEVERITY_TONES[summary?.severity ?? 'ok'] ?? SEVERITY_TONES.ok;

  return (
    <div
      data-testid="project-health-summary"
      className={`rounded-lg border border-white/10 ${tone.bg} p-4`}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${tone.dot}`} />
          <h3 className="text-sm font-medium text-slate-200">项目健康</h3>
        </div>
        <span className="text-xs text-slate-400">{tone.label}</span>
      </div>

      {error && <p className="mt-2 text-xs text-rose-400">健康检查失败：{error}</p>}

      {!error && summary && summary.severity !== 'ok' && summary.overdue.length > 0 && (
        <ul className="mt-3 space-y-1 text-xs text-slate-300">
          {summary.overdue.slice(0, 3).map((item) => (
            <li key={item.milestone_id} className="flex items-center justify-between">
              <span className="truncate">{item.title}</span>
              <span className="ml-2 shrink-0 text-rose-400">逾期 {item.days_overdue} 天</span>
            </li>
          ))}
          {summary.overdue.length > 3 && (
            <li className="text-slate-500">…还有 {summary.overdue.length - 3} 项</li>
          )}
        </ul>
      )}

      {!error && summary && summary.severity !== 'ok' && summary.overdue.length === 0 && (
        <p className="mt-2 text-xs text-slate-300">
          有 {summary.blocked_milestones} 个里程碑处于阻塞状态
        </p>
      )}

      {!error && summary && summary.severity === 'ok' && (
        <p className="mt-2 text-xs text-slate-400">所有里程碑进度正常</p>
      )}
    </div>
  );
}
