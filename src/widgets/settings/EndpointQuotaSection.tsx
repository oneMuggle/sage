/**
 * 端点限额进度区块 (P0-B 2026-09-18) — UsagePanel 底部。
 *
 * 数据源: GET /api/v1/usage/by-endpoint (usage_events 按 endpoint_id 聚合,
 * UTC 日 / UTC 月窗口) × settings.endpoints[*].quota。
 * 预警阈值: ≥80% 黄色"接近限额", ≥100% 红色"已超出限额"。
 */
import { useEffect, useState } from 'react';

import { formatTokens } from '../../entities/setting/contextPresets';
import type { EndpointQuota } from '../../entities/setting/types';
import { useSettings } from '../../features/manage-settings/useSettings';
import { fetchUsageByEndpoint, type UsageEndpointRow } from '../../shared/api/usageApi';

const WARN_RATIO = 0.8;

interface QuotaRow {
  endpointId: string | null;
  name: string;
  quota: EndpointQuota;
  row: UsageEndpointRow | null;
}

function buildRows(
  endpoints: { id: string; name: string; quota?: EndpointQuota }[],
  items: UsageEndpointRow[],
): QuotaRow[] {
  const byId = new Map<string, UsageEndpointRow>();
  const orphan: UsageEndpointRow[] = [];
  for (const item of items) {
    if (item.endpoint_id && endpoints.some((ep) => ep.id === item.endpoint_id)) {
      byId.set(item.endpoint_id, item);
    } else {
      orphan.push(item);
    }
  }
  const rows: QuotaRow[] = endpoints.map((ep) => ({
    endpointId: ep.id,
    name: ep.name || '(未命名端点)',
    quota: ep.quota ?? {},
    row: byId.get(ep.id) ?? null,
  }));
  const merged: UsageEndpointRow = {
    endpoint_id: null,
    total_requests: 0,
    total_tokens: 0,
    today_requests: 0,
    today_tokens: 0,
    month_requests: 0,
    month_tokens: 0,
    month_cost_usd: null,
  };
  for (const item of orphan) {
    merged.total_requests += item.total_requests;
    merged.total_tokens += item.total_tokens;
    merged.today_requests += item.today_requests;
    merged.today_tokens += item.today_tokens;
    merged.month_requests += item.month_requests;
    merged.month_tokens += item.month_tokens;
  }
  if (orphan.length > 0) {
    rows.push({ endpointId: null, name: '未归属端点', quota: {}, row: merged });
  }
  return rows;
}

function ratioColor(ratio: number): string {
  if (ratio >= 1) return 'bg-red-500';
  if (ratio >= WARN_RATIO) return 'bg-yellow-500';
  return 'bg-green-500';
}

function statusLabel(ratio: number): string | null {
  if (ratio >= 1) return '已超出限额';
  if (ratio >= WARN_RATIO) return '接近限额';
  return null;
}

function ProgressBar({
  used,
  limit,
  format,
}: {
  used: number;
  limit: number;
  format: (n: number) => string;
}) {
  const ratio = limit > 0 ? used / limit : 0;
  return (
    <div className="flex items-center gap-2 min-w-[220px]">
      <div className="flex-1 h-1.5 bg-bg-muted rounded-full overflow-hidden">
        <div
          className={`h-full ${ratioColor(ratio)}`}
          style={{ width: `${Math.min(ratio * 100, 100)}%` }}
        />
      </div>
      <span className="text-[11px] font-mono text-muted whitespace-nowrap">
        {format(used)} / {format(limit)}
      </span>
      {statusLabel(ratio) && (
        <span
          className={`text-[11px] whitespace-nowrap ${ratio >= 1 ? 'text-red-500' : 'text-yellow-600'}`}
        >
          {statusLabel(ratio)}
        </span>
      )}
    </div>
  );
}

export function EndpointQuotaSection({ refreshToken = 0 }: { refreshToken?: number }) {
  const { settings } = useSettings();
  const [items, setItems] = useState<UsageEndpointRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    fetchUsageByEndpoint()
      .then((d) => {
        if (!alive) return;
        setItems(d.items);
        setError(d.error ?? null);
      })
      .catch((err: unknown) => {
        if (!alive) return;
        setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      alive = false;
    };
  }, [refreshToken]);

  if (settings.endpoints.length === 0) return null;

  const rows = buildRows(settings.endpoints, items ?? []);

  return (
    <div className="space-y-2" data-testid="endpoint-quota-section">
      <h4 className="text-xs font-semibold text-text">按端点限额用量</h4>
      <p className="text-[11px] text-muted">
        日限额按 UTC 日、月预算按 UTC 月聚合; 达 80% 黄色预警、100% 红色超限。
      </p>
      {error && (
        <p className="text-xs text-red-500" data-testid="endpoint-quota-error">
          端点用量加载失败: {error}
        </p>
      )}
      <div className="space-y-2">
        {rows.map((r, i) => (
          <div
            key={r.endpointId ?? `orphan-${i}`}
            className="text-xs space-y-1"
            data-testid={r.endpointId ? `quota-row-${r.endpointId}` : 'quota-row-orphan'}
          >
            <div className="font-mono text-text">
              {r.name}
              {r.row && (
                <span className="text-muted ml-2">
                  今日 {r.row.today_requests} 次 · {r.row.today_tokens.toLocaleString()} tokens
                </span>
              )}
            </div>
            {r.quota.dailyTokens ? (
              <div className="flex items-center gap-1.5">
                <ProgressBar
                  used={r.row?.today_tokens ?? 0}
                  limit={r.quota.dailyTokens}
                  format={(n) => formatTokens(n)}
                />
                <span className="text-[11px] text-muted">tokens/日</span>
              </div>
            ) : null}
            {r.quota.monthlyBudgetUsd ? (
              r.row?.month_cost_usd == null ? (
                <span className="text-[11px] text-muted">
                  月预算 ${r.quota.monthlyBudgetUsd} — 本月成本未知
                </span>
              ) : (
                <ProgressBar
                  used={r.row.month_cost_usd}
                  limit={r.quota.monthlyBudgetUsd}
                  format={(n) => `$${n.toFixed(2)}`}
                />
              )
            ) : null}
            {!r.quota.dailyTokens && !r.quota.monthlyBudgetUsd && (
              <span className="text-[11px] text-muted/70">未设限额</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
