/**
 * 浏览器环境诊断 UI 区块（Phase E3）
 *
 * 渲染在 Settings > Network Tab 中，展示浏览器环境健康检查结果。
 * 调用后端 `/api/v1/diagnostic/browser-check` 端点（经 Electron IPC）。
 *
 * API 契约见 docs/plans/2026-09-17_multi-browser-support.md §4。
 */

import { useCallback, useEffect, useState } from 'react';

import { SettingRow } from '../../pages/settings/components';
import {
  fetchBrowserCheck,
  type BrowserCheckItem,
  type BrowserCheckResponse,
} from '../../shared/api/browserDiagnostics';
import { useI18n } from '../../shared/lib/i18n';

const STATUS_COLORS: Record<BrowserCheckItem['status'], string> = {
  pass: 'text-green-600',
  warn: 'text-yellow-600',
  fail: 'text-red-600',
  na: 'text-text-secondary',
};

const STATUS_DOT_COLORS: Record<BrowserCheckItem['status'], string> = {
  pass: 'bg-green-500',
  warn: 'bg-yellow-500',
  fail: 'bg-red-500',
  na: 'bg-border',
};

const BROWSER_LABELS: Record<string, string> = {
  chrome: 'Chrome / Edge',
  firefox: 'Firefox',
  none: '—',
};

export function BrowserEnvironmentSection() {
  const { t } = useI18n();
  const [data, setData] = useState<BrowserCheckResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const runCheck = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchBrowserCheck();
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    runCheck();
  }, [runCheck]);

  return (
    <SettingRow
      label={t('settings.network.browser_env')}
      desc={t('settings.network.browser_env.hint')}
    >
      <div className="flex flex-col gap-2 w-full min-w-0" data-testid="browser-env-section">
        {loading && !data && (
          <div className="text-xs text-text-secondary" data-testid="browser-env-loading">
            {t('settings.network.browser_env.loading')}
          </div>
        )}

        {error && !data && (
          <div className="text-xs text-error" data-testid="browser-env-error">
            {t('settings.network.browser_env.error')}
          </div>
        )}

        {data && (
          <>
            {/* 推荐浏览器 badge */}
            <div className="flex items-center gap-2 text-xs">
              <span className="text-text-secondary">
                {t('settings.network.browser_env.recommended')}:
              </span>
              <span
                className="px-2 py-0.5 rounded-radius-sm bg-bg-secondary text-text font-medium"
                data-testid="browser-env-recommended"
              >
                {BROWSER_LABELS[data.recommended_browser] ?? data.recommended_browser}
              </span>
            </div>

            {/* 检查项列表 */}
            <div className="flex flex-col gap-1" data-testid="browser-env-checks">
              {data.checks.map((check) => (
                <CheckRow key={check.id} check={check} />
              ))}
            </div>
          </>
        )}

        {/* 重新检测按钮 */}
        <button
          type="button"
          className="self-start px-3 py-1 text-xs border border-border rounded-radius-sm hover:bg-bg-secondary disabled:opacity-50"
          disabled={loading}
          onClick={runCheck}
          data-testid="browser-env-refresh"
        >
          {loading
            ? t('settings.network.browser_env.loading')
            : t('settings.network.browser_env.refresh')}
        </button>
      </div>
    </SettingRow>
  );
}

function CheckRow({ check }: { check: BrowserCheckItem }) {
  const { t } = useI18n();

  const statusLabel =
    t(`settings.network.browser_env.status.${check.status}` as Parameters<typeof t>[0]) ||
    check.status;

  return (
    <div
      className="flex items-start gap-2 text-xs py-1"
      data-testid={`browser-env-check-${check.id}`}
    >
      <span
        className={`mt-1 w-2 h-2 rounded-full flex-shrink-0 ${STATUS_DOT_COLORS[check.status]}`}
      />
      <div className="flex flex-col min-w-0">
        <div className="flex items-center gap-2">
          <span className={`font-medium ${STATUS_COLORS[check.status]}`}>{statusLabel}</span>
          <span className="text-text-secondary truncate">{check.detail}</span>
        </div>
        {check.fix_hint && check.status !== 'pass' && (
          <a
            href={check.fix_hint}
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary hover:underline text-xs mt-0.5"
            data-testid={`browser-env-fix-${check.id}`}
          >
            {t('settings.network.browser_env.fix')}: {check.fix_hint}
          </a>
        )}
      </div>
    </div>
  );
}
