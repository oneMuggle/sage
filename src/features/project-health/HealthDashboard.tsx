import { HeartPulse, RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  projectApi,
  type ProjectHealthSummary,
  type ProjectsHealthCheckResult,
} from '../../shared/api';
import {
  SEVERITY_ORDER,
  SEVERITY_TOKENS,
  type HealthSeverity,
} from '../../shared/lib/healthSeverity';
import { Button } from '../../shared/ui/Button';

type Filter = 'all' | HealthSeverity;

const FILTERS: Array<{ value: Filter; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'critical', label: SEVERITY_TOKENS.critical.label },
  { value: 'warning', label: SEVERITY_TOKENS.warning.label },
  { value: 'ok', label: SEVERITY_TOKENS.ok.label },
];

function StatCard({ severity, count }: { severity: HealthSeverity; count: number }) {
  const token = SEVERITY_TOKENS[severity];
  const Icon = token.Icon;
  return (
    <div
      data-testid={`health-dashboard-stat-${severity}`}
      className={`flex items-center gap-2.5 rounded-lg border ${token.border} ${token.softBg} px-3 py-2.5`}
    >
      <Icon className={`h-4 w-4 shrink-0 ${token.text}`} aria-hidden="true" />
      <div className="min-w-0">
        <div className={`text-lg font-semibold leading-none tabular-nums ${token.text}`}>
          {count}
        </div>
        <div className="mt-1 text-ui-2xs text-text-muted">{token.label}</div>
      </div>
    </div>
  );
}

function HealthRow({ summary }: { summary: ProjectHealthSummary }) {
  const token = SEVERITY_TOKENS[summary.severity];
  const overdueCount = summary.overdue.length;
  return (
    <li
      data-testid={`health-dashboard-row-${summary.project_id}`}
      className="flex items-center justify-between gap-3 rounded-md border border-transparent px-3 py-2 transition-colors hover:border-border hover:bg-bg-hover"
    >
      <div className="flex min-w-0 items-center gap-2">
        <span className={`h-2 w-2 shrink-0 rounded-full ${token.dot}`} aria-hidden="true" />
        <span className="truncate text-xs font-medium text-text">{summary.project_name}</span>
        {summary.project_stage && (
          <span className="shrink-0 rounded bg-bg-muted px-1.5 py-0.5 text-ui-2xs text-text-muted">
            {summary.project_stage}
          </span>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2 text-ui-2xs text-text-muted">
        <span className="tabular-nums">
          {summary.completed_milestones}/{summary.total_milestones} 里程碑
        </span>
        {overdueCount > 0 ? (
          <span
            className={`inline-flex items-center rounded-full px-2 py-0.5 font-medium ${SEVERITY_TOKENS.critical.badge}`}
          >
            逾期 {overdueCount} 项
          </span>
        ) : (
          <span className={token.text}>{token.stateLabel}</span>
        )}
      </div>
    </li>
  );
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

  const groups = useMemo(() => {
    const visible =
      filter === 'all' ? summaries : summaries.filter((summary) => summary.severity === filter);
    return SEVERITY_ORDER.map((severity) => ({
      severity,
      items: visible.filter((summary) => summary.severity === severity),
    })).filter((group) => group.items.length > 0);
  }, [summaries, filter]);

  const visibleCount = groups.reduce((sum, group) => sum + group.items.length, 0);
  const counts = result?.severities ?? { critical: 0, warning: 0, ok: 0 };

  return (
    <section
      data-testid="project-health-dashboard"
      className="mb-4 rounded-xl border border-border bg-ui-card p-4"
      aria-label="项目健康看板"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <HeartPulse className="h-4 w-4 text-primary" aria-hidden="true" />
          <h2 className="text-sm font-semibold text-text">项目健康</h2>
        </div>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => void refresh()}
          disabled={loading}
          data-testid="health-dashboard-refresh"
        >
          <RefreshCw className={`mr-1 h-3 w-3 ${loading ? 'animate-spin' : ''}`} />
          {loading ? '检查中…' : '重新检查'}
        </Button>
      </div>

      <p className="sr-only">
        风险 {counts.critical} · 关注 {counts.warning} · 正常 {counts.ok}
      </p>

      <div className="mt-3 grid grid-cols-3 gap-2">
        {SEVERITY_ORDER.map((severity) => (
          <StatCard key={severity} severity={severity} count={counts[severity]} />
        ))}
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
                ? 'bg-primary text-text-inverse'
                : 'bg-bg-muted text-text-muted hover:text-text'
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>

      {error && (
        <p className="mt-3 text-xs text-rose-500" data-testid="health-dashboard-error">
          健康检查失败：{error}
        </p>
      )}

      {!error && loading && summaries.length === 0 && (
        <div className="mt-3 space-y-1.5" data-testid="health-dashboard-loading">
          <p className="sr-only">正在检查项目健康状态…</p>
          {[0, 1, 2].map((index) => (
            <div key={index} className="h-9 animate-pulse rounded-md bg-bg-muted/60" />
          ))}
        </div>
      )}

      {!error && !loading && summaries.length === 0 && (
        <p className="mt-3 text-xs text-text-muted" data-testid="health-dashboard-empty">
          暂无活跃项目需要检查。
        </p>
      )}

      {!error && visibleCount > 0 && (
        <ul className="mt-3 space-y-1.5" data-testid="health-dashboard-list">
          {groups.map((group) => {
            const token = SEVERITY_TOKENS[group.severity];
            const showGroupHeader = filter === 'all' && groups.length > 1;
            return (
              <li key={group.severity} className="list-none">
                {showGroupHeader && (
                  <div
                    data-testid={`health-dashboard-group-${group.severity}`}
                    className={`mb-1.5 flex items-center gap-1.5 text-ui-2xs font-medium ${token.text}`}
                  >
                    <span className={`h-1.5 w-1.5 rounded-full ${token.dot}`} aria-hidden="true" />
                    {token.label}
                    <span className="text-text-muted">({group.items.length})</span>
                  </div>
                )}
                <ul className="space-y-1">
                  {group.items.map((summary) => (
                    <HealthRow key={summary.project_id} summary={summary} />
                  ))}
                </ul>
              </li>
            );
          })}
        </ul>
      )}

      {!error && !loading && summaries.length > 0 && visibleCount === 0 && (
        <p className="mt-3 text-xs text-text-muted" data-testid="health-dashboard-none">
          没有符合该风险等级的项目。
        </p>
      )}
    </section>
  );
}
