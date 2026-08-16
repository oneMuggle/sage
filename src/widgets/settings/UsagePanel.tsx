/**
 * 用量/成本面板 (M6 生态扩展) — Settings 通用 Tab 底部区块。
 *
 * 数据源: GET /api/v1/usage (经 IPC usage_summary)。内存态统计,
 * 后端重启归零 — 面板明确是轻量概览, 不做持久化。
 */
import { useCallback, useEffect, useState } from 'react';

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

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setSummary(await fetchUsageSummary());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-2" data-testid="usage-panel">
      {error !== null && (
        <p className="text-xs text-red-500" data-testid="usage-error">
          {t('settings.usage.loadFailed')}: {error}
        </p>
      )}
      {summary !== null && (
        <>
          <div className="grid grid-cols-3 gap-2 text-xs">
            <div>
              <div className="text-text-muted">{t('settings.usage.requests')}</div>
              <div className="font-mono text-text" data-testid="usage-total-requests">
                {summary.totals.requests.toLocaleString()}
              </div>
            </div>
            <div>
              <div className="text-text-muted">{t('settings.usage.tokens')}</div>
              <div className="font-mono text-text" data-testid="usage-total-tokens">
                {formatTokens(summary.totals.prompt_tokens, summary.totals.completion_tokens)}
              </div>
            </div>
            <div>
              <div className="text-text-muted">{t('settings.usage.cost')}</div>
              <div className="font-mono text-text" data-testid="usage-total-cost">
                {formatCost(summary.totals.estimated_cost_usd)}
              </div>
            </div>
          </div>
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
                    <td className="pr-2">{formatTokens(entry.prompt_tokens, entry.completion_tokens)}</td>
                    <td>{formatCost(entry.estimated_cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="text-xs text-text-muted" data-testid="usage-today">
            {t('settings.usage.today')}: {summary.today.requests}
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
