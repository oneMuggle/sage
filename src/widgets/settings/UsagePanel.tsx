/**
 * 用量/成本面板 (M6 生态扩展) — Settings 通用 Tab 底部区块。
 *
 * 数据源: GET /api/v1/usage (经 IPC usage_summary)。内存态统计,
 * 后端重启归零 — 面板明确是轻量概览, 不做持久化。
 *
 * L8 PR-C (2026-09-09): 集成 UsageTrendChart (自绘 SVG) + CSV 导出按钮。
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import {
  fetchUsageCsvExport,
  fetchUsageSummary,
  fetchUsageTrend,
  UsageRange,
  UsageSummary,
  UsageTrend,
} from '../../shared/api/usageApi';
import { useI18n } from '../../shared/lib/i18n';
import { UsageRequestsTable } from './UsageRequestsTable';
import { UsageTrendChart } from './UsageTrendChart';

function formatCost(cost: number | null): string {
  return cost === null ? '—' : `$${cost.toFixed(4)}`;
}

function formatTokens(promptTokens: number, completionTokens: number): string {
  return `${(promptTokens + completionTokens).toLocaleString()}`;
}

/** L8 PR-C: 浏览器侧把 CSV 字符串触发为下载 */
function triggerCsvDownload(csv: string, filename: string): void {
  // ﻿ 是 UTF-8 BOM, Excel/Sheets 识别 UTF-8 的标志
  const blob = new Blob(['﻿', csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.style.display = 'none';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function UsagePanel() {
  const { t } = useI18n();
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  // L8 PR-A/PR-B: range tab state — 与后端 usage_routes pattern 对齐,
  // today 看当日, 7d/30d 看预聚合, total 看累计。
  const [range, setRange] = useState<UsageRange>('today');
  // L8 PR-C: trend 数据独立 state, 与 summary 解耦 (任一失败不影响对方)。
  const [trend, setTrend] = useState<UsageTrend | null>(null);
  const [trendLoading, setTrendLoading] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
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

  // L8 PR-C: trend 跟随 range 重拉 — 总线请求, 失败静默 (chart 自带空态)
  const loadTrend = useCallback(async () => {
    setTrendLoading(true);
    try {
      const data = await fetchUsageTrend({ range });
      if (!mountedRef.current) return;
      setTrend(data);
    } catch {
      // trend 失败不刷 summary 的 error; chart 显示空态即可
      if (!mountedRef.current) return;
      setTrend({ range, bucket: range === 'today' ? 'hour' : 'day', series: [] });
    } finally {
      if (mountedRef.current) setTrendLoading(false);
    }
  }, [range]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void loadTrend();
  }, [loadTrend]);

  const onExportCsv = useCallback(async () => {
    setExportError(null);
    try {
      const csv = await fetchUsageCsvExport({ range });
      if (!mountedRef.current) return;
      const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
      triggerCsvDownload(csv, `sage-usage-${range}-${stamp}.csv`);
    } catch (err) {
      if (!mountedRef.current) return;
      setExportError(err instanceof Error ? err.message : String(err));
    }
  }, [range]);

  // L8 PR-A/PR-B: today 模式显示 today bucket; 7d/30d/total 模式显示 totals (DB 聚合)
  const activeBucket =
    summary !== null ? (range === 'today' ? summary.today : summary.totals) : null;

  return (
    <div className="space-y-3" data-testid="usage-panel">
      {error !== null && (
        <p className="text-xs text-red-500" data-testid="usage-error">
          {t('settings.usage.loadFailed')}: {error}
        </p>
      )}
      {summary !== null && (
        <>
          {/* 时间范围 Tab — today / 7d / 30d / total */}
          <div className="flex gap-1 text-xs" data-testid="usage-range-tabs" role="tablist">
            {(['today', '7d', '30d', 'total'] as const).map((r) => (
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
        </>
      )}
      <div className="flex gap-2 items-center">
        <button
          type="button"
          data-testid="usage-refresh"
          onClick={() => void load()}
          disabled={loading}
          className="px-3 py-1.5 text-xs border border-border rounded-radius-sm text-text hover:bg-bg-muted transition-colors disabled:opacity-50"
        >
          {t('settings.usage.refresh')}
        </button>
        {/* L8 PR-C: CSV 导出 — 浏览器侧 Blob 下载 */}
        <button
          type="button"
          data-testid="usage-export-csv"
          onClick={() => void onExportCsv()}
          className="px-3 py-1.5 text-xs border border-border rounded-radius-sm text-text hover:bg-bg-muted transition-colors"
        >
          {t('settings.usage.exportCsv')}
        </button>
      </div>
      {exportError !== null && (
        <p className="text-xs text-red-500" data-testid="usage-export-error">
          {t('settings.usage.trend.loadFailed')}: {exportError}
        </p>
      )}
      {/* L8 PR-C: 趋势图 (双线 SVG, 跟随 range 重拉) */}
      <UsageTrendChart trend={trend} loading={trendLoading} />
      {/* L8 PR-B: 单次请求明细表 (与 summary 解耦, 独立加载) */}
      <UsageRequestsTable />
    </div>
  );
}
