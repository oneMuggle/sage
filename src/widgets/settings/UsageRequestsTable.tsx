/**
 * 请求明细表 (L8 PR-B, 2026-09-09) — M6 用量/成本面板的二级面板。
 *
 * 与 UsagePanel 顶部汇总解耦, 独立加载 usage_events 行 (按 created_at DESC 分页)。
 * 后端: GET /api/v1/usage/requests?limit=&offset=&session_id= (走 IPC usage_list_requests)。
 *
 * 设计要点:
 * - 父子各自维护 loading/error, 互不阻塞 — 汇总失败时明细仍可看, 反之亦然
 * - 分页用 offset/limit 游标, 不依赖 page 号 (后端返回 total 即可算 pageInfo)
 * - 空态文案分两档: items.length===0 → "暂无请求记录"; error → "请求明细加载失败: ..."
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import { fetchUsageRequests, UsageRequestRow } from '../../shared/api/usageApi';
import { useI18n } from '../../shared/lib/i18n';

const PAGE_SIZE = 20;

function formatCost(cost: number | null): string {
  return cost === null ? '—' : `$${cost.toFixed(4)}`;
}

function formatTokens(prompt: number, completion: number): string {
  return (prompt + completion).toLocaleString();
}

function formatTime(iso: string, ms: number): string {
  if (iso) return iso.replace('T', ' ').replace('Z', '');
  if (ms > 0) {
    try {
      return new Date(ms).toISOString().replace('T', ' ').replace('Z', '');
    } catch {
      return '—';
    }
  }
  return '—';
}

export function UsageRequestsTable() {
  const { t } = useI18n();
  const [items, setItems] = useState<UsageRequestRow[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const load = useCallback(async (nextOffset: number) => {
    setLoading(true);
    setError(null);
    try {
      const page = await fetchUsageRequests({ limit: PAGE_SIZE, offset: nextOffset });
      if (!mountedRef.current) return;
      setItems(page.items ?? []);
      setTotal(typeof page.total === 'number' ? page.total : 0);
      setOffset(nextOffset);
    } catch (err) {
      if (!mountedRef.current) return;
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(0);
  }, [load]);

  const end = Math.min(offset + items.length, total);
  const hasPrev = offset > 0;
  const hasNext = offset + items.length < total;

  return (
    <div className="space-y-2 pt-2 border-t border-border" data-testid="usage-requests-table">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-medium text-text">{t('settings.usage.requestsTable.title')}</h4>
        <button
          type="button"
          data-testid="usage-requests-refresh"
          onClick={() => void load(offset)}
          disabled={loading}
          className="px-2 py-0.5 text-xs border border-border rounded-radius-sm text-text hover:bg-bg-muted transition-colors disabled:opacity-50"
        >
          {t('settings.usage.refresh')}
        </button>
      </div>
      {error !== null && (
        <p className="text-xs text-red-500" data-testid="usage-requests-error">
          {t('settings.usage.requestsTable.loadFailed')}: {error}
        </p>
      )}
      {!error && items.length === 0 && !loading && (
        <p className="text-xs text-text-muted" data-testid="usage-requests-empty">
          {t('settings.usage.requestsTable.empty')}
        </p>
      )}
      {items.length > 0 && (
        <table className="w-full text-xs" data-testid="usage-requests-rows">
          <thead>
            <tr className="text-text-muted text-left">
              <th className="font-normal pr-2">{t('settings.usage.requestsTable.col.time')}</th>
              <th className="font-normal pr-2">{t('settings.usage.requestsTable.col.model')}</th>
              <th className="font-normal pr-2 text-right">
                {t('settings.usage.requestsTable.col.tokens')}
              </th>
              <th className="font-normal pr-2 text-right">
                {t('settings.usage.requestsTable.col.cacheRead')}
              </th>
              <th className="font-normal pr-2 text-right">
                {t('settings.usage.requestsTable.col.cacheCreation')}
              </th>
              <th className="font-normal text-right">
                {t('settings.usage.requestsTable.col.cost')}
              </th>
            </tr>
          </thead>
          <tbody>
            {items.map((row) => (
              <tr key={row.id} className="border-t border-border">
                <td className="font-mono pr-2 py-0.5 whitespace-nowrap">
                  {formatTime(row.created_at_iso, row.created_at_ms)}
                </td>
                <td className="font-mono pr-2 py-0.5">{row.model || '—'}</td>
                <td className="pr-2 py-0.5 text-right">
                  {formatTokens(row.prompt_tokens, row.completion_tokens)}
                </td>
                <td className="pr-2 py-0.5 text-right">{row.cache_read_tokens.toLocaleString()}</td>
                <td className="pr-2 py-0.5 text-right">
                  {row.cache_creation_tokens.toLocaleString()}
                </td>
                <td className="py-0.5 text-right">{formatCost(row.estimated_cost_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="flex items-center justify-between text-xs">
        <span className="text-text-muted" data-testid="usage-requests-pageinfo">
          {total > 0
            ? t('settings.usage.requestsTable.pageInfo')
                .replace('{offset}', String(offset + 1))
                .replace('{end}', String(end))
                .replace('{total}', String(total))
            : ''}
        </span>
        <div className="flex gap-1">
          <button
            type="button"
            data-testid="usage-requests-prev"
            disabled={!hasPrev || loading}
            onClick={() => void load(Math.max(0, offset - PAGE_SIZE))}
            className="px-2 py-0.5 border border-border rounded-radius-sm text-text hover:bg-bg-muted transition-colors disabled:opacity-50"
          >
            {t('settings.usage.requestsTable.prevPage')}
          </button>
          <button
            type="button"
            data-testid="usage-requests-next"
            disabled={!hasNext || loading}
            onClick={() => void load(offset + PAGE_SIZE)}
            className="px-2 py-0.5 border border-border rounded-radius-sm text-text hover:bg-bg-muted transition-colors disabled:opacity-50"
          >
            {t('settings.usage.requestsTable.nextPage')}
          </button>
        </div>
      </div>
    </div>
  );
}
