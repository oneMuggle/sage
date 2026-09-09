/**
 * 用量/成本面板 (M6 生态扩展) — Settings 通用 Tab 底部区块。
 *
 * 数据源: GET /api/v1/usage (经 IPC usage_summary)。内存态统计,
 * 后端重启归零 — 面板明确是轻量概览, 不做持久化。
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import { fetchUsageSummary, UsageSummary } from '../../shared/api/usageApi';
import { useI18n } from '../../shared/lib/i18n';

function formatCost(cost: number | null): string {
  return cost === null ? '—' : `$${cost.toFixed(4)}`;
}

function formatTokens(promptTokens: number, completionTokens: number): string {
  return `${(promptTokens + completionTokens).toLocaleString()}`;
}

export function UsagePanel() {
  const { t } = useI18n();
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  // L8 PR-A (2026-09-09): range tab state — 与后端 usage_routes pattern 对齐,
  // today 优先看当日重活, total 看累计。PR-B (7d/30d) 在此处扩展。
  const [range, setRange] = useState<'today' | 'total'>('today');
  // 卸载守卫: load 的异步 continuation 可能在组件卸载（含测试环境拆除）
  // 之后才 resolve,此刻 setState 会抛 unhandled rejection
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchUsageSummary(range);
      if (!mountedRef.current) return;
      setSummary(data);
    } catch (err) {
      if (!mountedRef.current) return;
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, [range]);

  useEffect(() => {
    void load();
  }, [load]);

  // L8 PR-A (2026-09-09): 选 range 时显示对应 bucket 的数字。
  // cache_hit_rate 在 today/total 下语义不同——today 是当日命中率,
  // total 是自启动以来累计命中率。两个都展示便于用户对比当日效率。
  const activeBucket = summary ? (range === 'today' ? summary.today : summary.totals) : null;

  return (
    <div className="space-y-2" data-testid="usage-panel">
      {error !== null && (
        <p className="text-xs text-red-500" data-testid="usage-error">
          {t('settings.usage.loadFailed')}: {error}
        </p>
      )}
      {summary !== null && (
        <>
          {/* L8 PR-A: 时间范围 Tab — 两段按钮切换 today / total */}
          <div className="flex gap-1 text-xs" data-testid="usage-range-tabs" role="tablist">
            {(['today', 'total'] as const).map((r) => (
              <button
                key={r}
                type="button"
                role="tab"
                aria-selected={range === r}
                data-testid={`usage-range-${r}`}
                onClick={() => setRange(r)}
                className={`px-2 py-1 border border-border rounded-radius-sm transition-colors ${
                  range === r ? 'bg-bg-muted text-text' : 'text-text-muted hover:text-text'
                }`}
              >
                {t(`settings.usage.range.${r}`)}
              </button>
            ))}
          </div>
          {activeBucket !== null && (
            <div className="grid grid-cols-3 gap-2 text-xs">
              <div>
                <div className="text-text-muted">{t('settings.usage.requests')}</div>
                <div className="font-mono text-text" data-testid="usage-total-requests">
                  {activeBucket.requests.toLocaleString()}
                </div>
              </div>
              <div>
                <div className="text-text-muted">{t('settings.usage.tokens')}</div>
                <div className="font-mono text-text" data-testid="usage-total-tokens">
                  {formatTokens(activeBucket.prompt_tokens, activeBucket.completion_tokens)}
                </div>
              </div>
              <div>
                <div className="text-text-muted">{t('settings.usage.cost')}</div>
                <div className="font-mono text-text" data-testid="usage-total-cost">
                  {formatCost(activeBucket.estimated_cost_usd)}
                </div>
              </div>
            </div>
          )}
          {/* L8 PR-A: cache 命中率 + 拆分明细行 — read 与 creation 分开展示
              让用户区分"命中缓存省了多少"和"为了缓存新写了多少" */}
          {activeBucket !== null && (
            <div className="grid grid-cols-3 gap-2 text-xs" data-testid="usage-cache-row">
              <div>
                <div className="text-text-muted">{t('settings.usage.cacheRead')}</div>
                <div className="font-mono text-text" data-testid="usage-cache-read">
                  {activeBucket.cache_read_tokens.toLocaleString()}
                </div>
              </div>
              <div>
                <div className="text-text-muted">{t('settings.usage.cacheCreation')}</div>
                <div className="font-mono text-text" data-testid="usage-cache-creation">
                  {activeBucket.cache_creation_tokens.toLocaleString()}
                </div>
              </div>
              <div>
                <div className="text-text-muted">{t('settings.usage.cacheHitRate')}</div>
                <div className="font-mono text-text" data-testid="usage-cache-hit-rate">
                  {(summary.cache_hit_rate * 100).toFixed(1)}%
                </div>
              </div>
            </div>
          )}
          {summary.by_model.length > 0 && (
            <table className="w-full text-xs" data-testid="usage-by-model">
              <thead>
                <tr className="text-text-muted text-left">
                  <th className="font-normal pr-2">{t('settings.usage.model')}</th>
                  <th className="font-normal pr-2">{t('settings.usage.requests')}</th>
                  <th className="font-normal pr-2">{t('settings.usage.tokens')}</th>
                  <th className="font-normal">{t('settings.usage.cost')}</th>
                </tr>
              </thead>
              <tbody>
                {summary.by_model.map((entry) => (
                  <tr key={entry.model} className="border-t border-border">
                    <td className="font-mono pr-2 py-0.5">{entry.model}</td>
                    <td className="pr-2">{entry.requests}</td>
                    <td className="pr-2">
                      {formatTokens(entry.prompt_tokens, entry.completion_tokens)}
                    </td>
                    <td>{formatCost(entry.estimated_cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="text-xs text-text-muted" data-testid="usage-today">
            {t(`settings.usage.range.${range}`)}: {activeBucket?.requests ?? 0}
          </div>
        </>
      )}
      <button
        type="button"
        data-testid="usage-refresh"
        onClick={() => void load()}
        disabled={loading}
        className="px-3 py-1.5 text-xs border border-border rounded-radius-sm text-text hover:bg-bg-muted transition-colors disabled:opacity-50"
      >
        {t('settings.usage.refresh')}
      </button>
    </div>
  );
}
