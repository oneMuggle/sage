import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  projectApi,
  type ProjectHealthSummary,
  type ProjectsHealthCheckResult,
} from '../../shared/api';
import { Button } from '../../shared/ui/Button';

type Severity = 'ok' | 'warning' | 'critical';
type Filter = 'all' | Severity;

const SEVERITY_DOT: Record<Severity, string> = {
  ok: 'bg-emerald-500',
  warning: 'bg-amber-500',
  critical: 'bg-rose-500',
};

const SEVERITY_LABEL: Record<Severity, string> = {
  ok: '正常',
  warning: '关注',
  critical: '风险',
};

const FILTERS: Array<{ value: Filter; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'critical', label: '风险' },
  { value: 'warning', label: '关注' },
  { value: 'ok', label: '正常' },
];

function severityOf(summary: ProjectHealthSummary): Severity {
  return summary.severity;
}

/** 全局项目健康看板（M3, 2026-11-14）：一次拉取全部活跃项目并支持按风险等级筛选。 */
export function HealthDashboard() {
  const [result, setResult] = useState<ProjectsHealthCheckResult | null>(null);
  const [filter, setFilter] = useState<Filter>('all');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await projectApi.listProjectsHealth();
      setResult(next);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const summaries = useMemo(() => result?.summaries ?? [], [result]);

  const visible = useMemo(
    () => (filter === 'all' ? summaries : summaries.filter((s) => severityOf(s) === filter)),
    [summaries, filter],
  );

  const counts = result?.severities ?? { critical: 0, warning: 0, ok: 0 };

  return (
    <section
      data-testid="project-health-dashboard"
      className="mb-4 rounded-lg border border-white/10 bg-white/5 p-4"
      aria-label="项目健康看板"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-3">
          <h2 className="text-sm font-medium text-slate-200">项目健康</h2>
          <span className="text-xs text-slate-400">
            风险 {counts.critical} · 关注 {counts.warning} · 正常 {counts.ok}
          </span>
        </div>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => void refresh()}
          disabled={loading}
          data-testid="health-dashboard-refresh"
        >
          {loading ? '检查中…' : '重新检查'}
        </Button>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {FILTERS.map((item) => (
          <button
            key={item.value}
            type="button"
            data-testid={`health-dashboard-filter-${item.value}`}
            aria-pressed={filter === item.value}
            onClick={() => setFilter(item.value)}
            className={`rounded-full px-2.5 py-1 text-xs transition-colors ${
              filter === item.value
                ? 'bg-primary text-primary-foreground'
                : 'bg-white/5 text-slate-300 hover:text-slate-100'
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>

      {error && (
        <p className="mt-3 text-xs text-rose-400" data-testid="health-dashboard-error">
          健康检查失败：{error}
        </p>
      )}

      {!error && loading && summaries.length === 0 && (
        <p className="mt-3 text-xs text-slate-400">正在检查项目健康状态…</p>
      )}

      {!error && !loading && summaries.length === 0 && (
        <p className="mt-3 text-xs text-slate-400" data-testid="health-dashboard-empty">
          暂无活跃项目需要检查。
        </p>
      )}

      {!error && visible.length > 0 && (
        <ul className="mt-3 space-y-1.5" data-testid="health-dashboard-list">
          {visible.map((summary) => (
            <li
              key={summary.project_id}
              data-testid={`health-dashboard-row-${summary.project_id}`}
              className="flex items-center justify-between gap-3 rounded-md bg-black/10 px-3 py-2"
            >
              <div className="flex min-w-0 items-center gap-2">
                <span
                  className={`h-2 w-2 shrink-0 rounded-full ${SEVERITY_DOT[summary.severity]}`}
                />
                <span className="truncate text-xs text-slate-200">{summary.project_name}</span>
                {summary.project_stage && (
                  <span className="shrink-0 text-xs text-slate-500">{summary.project_stage}</span>
                )}
              </div>
              <div className="flex shrink-0 items-center gap-3 text-xs text-slate-400">
                <span>
                  {summary.completed_milestones}/{summary.total_milestones} 里程碑
                </span>
                {summary.overdue.length > 0 ? (
                  <span className="text-rose-400">逾期 {summary.overdue.length} 项</span>
                ) : (
                  <span>{SEVERITY_LABEL[summary.severity]}</span>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {!error && !loading && summaries.length > 0 && visible.length === 0 && (
        <p className="mt-3 text-xs text-slate-400" data-testid="health-dashboard-none">
          没有符合该风险等级的项目。
        </p>
      )}
    </section>
  );
}
