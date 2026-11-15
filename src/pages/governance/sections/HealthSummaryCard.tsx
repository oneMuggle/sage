import { AlertTriangle, CheckCircle2 } from 'lucide-react';
import { useEffect, useState } from 'react';

import { projectApi, type ProjectHealthSummary } from '../../../shared/api';
import { SEVERITY_TOKENS } from '../../../shared/lib/healthSeverity';
import { Progress } from '../../../shared/ui/Progress';

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

  const tone = SEVERITY_TOKENS[summary?.severity ?? 'ok'];
  const ToneIcon = tone.Icon;
  const progress =
    summary && summary.total_milestones > 0
      ? Math.round((summary.completed_milestones / summary.total_milestones) * 100)
      : null;

  return (
    <div
      data-testid="project-health-summary"
      className={`rounded-xl border ${tone.border} ${tone.softBg} p-4`}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ToneIcon className={`h-4 w-4 ${summary ? tone.text : 'text-text-muted'}`} />
          <h3 className="text-sm font-semibold text-text">项目健康</h3>
        </div>
        <span className={`text-xs font-medium ${summary ? tone.text : 'text-text-muted'}`}>
          {summary ? tone.stateLabel : '检查中…'}
        </span>
      </div>

      {progress !== null && (
        <div className="mt-3">
          <div className="mb-1 flex items-center justify-between text-ui-2xs text-text-muted">
            <span>里程碑进度</span>
            <span className="tabular-nums">
              {summary?.completed_milestones}/{summary?.total_milestones} · {progress}%
            </span>
          </div>
          <Progress value={progress} />
        </div>
      )}

      {error && <p className="mt-2 text-xs text-rose-500">健康检查失败：{error}</p>}

      {!error && summary && summary.severity !== 'ok' && summary.overdue.length > 0 && (
        <ul className="mt-3 space-y-1.5 text-xs text-text">
          {summary.overdue.slice(0, 3).map((item) => (
            <li key={item.milestone_id} className="flex items-center justify-between gap-2">
              <span className="truncate">{item.title}</span>
              <span
                className={`ml-2 shrink-0 rounded-full px-2 py-0.5 text-ui-2xs font-medium ${SEVERITY_TOKENS.critical.badge}`}
              >
                逾期 {item.days_overdue} 天
              </span>
            </li>
          ))}
          {summary.overdue.length > 3 && (
            <li className="text-ui-2xs text-text-muted">…还有 {summary.overdue.length - 3} 项</li>
          )}
        </ul>
      )}

      {!error && summary && summary.severity !== 'ok' && summary.overdue.length === 0 && (
        <p className="mt-2 flex items-center gap-1.5 text-xs text-text">
          <AlertTriangle className={`h-3.5 w-3.5 shrink-0 ${tone.text}`} aria-hidden="true" />有{' '}
          {summary.blocked_milestones} 个里程碑处于阻塞状态
        </p>
      )}

      {!error && summary && summary.severity === 'ok' && (
        <p className="mt-2 flex items-center gap-1.5 text-xs text-text-muted">
          <CheckCircle2 className={`h-3.5 w-3.5 shrink-0 ${tone.text}`} aria-hidden="true" />
          所有里程碑进度正常
        </p>
      )}
    </div>
  );
}
