import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { settingsClient } from '../../shared/api/settingsClient';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';
import { confirmDialog } from '../../shared/ui/ConfirmDialog/confirmService';

import { parseCookieHeader, type CookieImportItem } from './credentialCookieParser';
// ---------------------------------------------------------------------------
// Round 12：网站凭据（browser_cookies 档案 + web_access_config 开关）
// ---------------------------------------------------------------------------

/** 与后端 list_credentials 返回形态一致（脱敏后，无任何值） */
interface CredentialRecord {
  domain: string;
  kind: 'cookie' | 'header';
  cookie_names?: string[];
  header_names?: string[];
  expires_in_seconds: number | null;
  expired: boolean;
  encrypted: boolean;
  source_profile?: string;
}

interface WebAccessConfig {
  render_persistent: boolean;
  auto_refresh_credentials: boolean;
  render_pool_size?: number;
  tls_fingerprint?: boolean;
}

const DEFAULT_WEB_ACCESS_CONFIG: WebAccessConfig = {
  render_persistent: false,
  auto_refresh_credentials: false,
  render_pool_size: 2,
  tls_fingerprint: false,
};

const RENDER_POOL_SIZE_OPTIONS = [1, 2, 3, 4];

/** dev 走 Vite 代理；Electron 产物直连后端（与 mediaApi 同口径） */
function webAccessApiUrl(path: string): string {
  if (window.electronAPI) {
    return `http://127.0.0.1:8765${path}`;
  }
  return path;
}

/** 与后端 GET /api/v1/diagnostic/browser 返回形态一致（Round 14） */
interface BrowserHealth {
  browserFound: boolean;
  executable: string;
  chromeMajor: number | null;
  uaDeclaredMajor: number | null;
  warning: string;
}

/** 与后端 GET /api/v1/web-access/metrics 返回形态一致（Round 15/16） */
type HostMetrics = Record<
  string,
  { ok: number; fail: number; escalated: number; avg_elapsed_ms: number | null }
>;

/** R24/R25：快照中非 host 的全局键——渲染事件命中率 */
interface RenderEventMetrics {
  renders: number;
  channel_ok: number;
  event_status_hits: number;
}

export function CredentialsSection() {
  const { t } = useI18n();
  const [creds, setCreds] = useState<CredentialRecord[] | null>(null);
  const [config, setConfig] = useState<WebAccessConfig>(DEFAULT_WEB_ACCESS_CONFIG);
  const [browser, setBrowser] = useState<BrowserHealth | null>(null);
  const [metrics, setMetrics] = useState<HostMetrics | null>(null);
  const [headerDomain, setHeaderDomain] = useState('');
  const [headerName, setHeaderName] = useState('');
  const [headerValue, setHeaderValue] = useState('');
  const [cookieDomain, setCookieDomain] = useState('');
  const [cookieValue, setCookieValue] = useState('');
  const [cookieError, setCookieError] = useState<TranslationKey | null>(null);
  const [cookieSaving, setCookieSaving] = useState(false);
  const renderEvents = metrics?.render_events as unknown as RenderEventMetrics | undefined;

  const reload = (): void => {
    fetch(webAccessApiUrl('/api/v1/web-access/credentials'))
      .then((r) => (r.ok ? r.json() : { credentials: [] }))
      .then((data: { credentials?: CredentialRecord[] }) => setCreds(data.credentials ?? []))
      .catch(() => setCreds([]));
  };

  useEffect(() => {
    reload();
    fetch(webAccessApiUrl('/api/v1/diagnostic/browser'))
      .then((r) => (r.ok ? r.json() : null))
      .then((data: BrowserHealth | null) => setBrowser(data))
      .catch(() => setBrowser(null));
    fetch(webAccessApiUrl('/api/v1/web-access/metrics'))
      .then((r) => (r.ok ? r.json() : { metrics: {} }))
      .then((data: { metrics?: HostMetrics }) => setMetrics(data.metrics ?? {}))
      .catch(() => setMetrics({}));
    void settingsClient.getPreference('web_access_config').then((raw) => {
      if (!raw) return;
      try {
        const parsed = JSON.parse(raw) as Partial<WebAccessConfig>;
        setConfig({
          render_persistent: Boolean(parsed.render_persistent),
          auto_refresh_credentials: Boolean(parsed.auto_refresh_credentials),
        });
      } catch {
        /* keep defaults */
      }
    });
  }, []);

  const saveConfig = (next: WebAccessConfig): void => {
    setConfig(next);
    void settingsClient.setPreference('web_access_config', JSON.stringify(next), 'network');
    void fetch(webAccessApiUrl('/api/v1/web-access/config'), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(next),
    }).catch(() => undefined);
  };

  const refreshMetrics = (): void => {
    fetch(webAccessApiUrl('/api/v1/web-access/metrics'))
      .then((r) => (r.ok ? r.json() : { metrics: {} }))
      .then((data: { metrics?: HostMetrics }) => setMetrics(data.metrics ?? {}))
      .catch(() => setMetrics({}));
  };

  const resetMetrics = (): void => {
    void fetch(webAccessApiUrl('/api/v1/web-access/metrics/reset'), { method: 'PUT' })
      .then(() => setMetrics({}))
      .catch(() => undefined);
  };

  // P1-8: 用项目内 confirmDialog 服务取代 window.confirm。
  const removeCred = async (domain: string): Promise<void> => {
    const ok = await confirmDialog({
      title: t('settings.network.creds.confirm'),
      danger: true,
    });
    if (!ok) return;
    void fetch(webAccessApiUrl(`/api/v1/web-access/credentials/${encodeURIComponent(domain)}`), {
      method: 'DELETE',
    })
      .then(() => reload())
      .catch(() => undefined);
  };

  const addHeaderCred = (): void => {
    if (!headerDomain.trim() || !headerName.trim() || !headerValue.trim()) return;
    void fetch(webAccessApiUrl('/api/v1/web-access/credentials/header'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        domain: headerDomain.trim(),
        header_name: headerName.trim(),
        value: headerValue,
      }),
    })
      .then((r) => {
        if (r.ok) {
          setHeaderDomain('');
          setHeaderName('');
          setHeaderValue('');
          reload();
        } else {
          toast.error(t('settings.network.creds.add_header.invalid'));
        }
      })
      .catch(() => undefined);
  };

  const addCookieCred = async (): Promise<void> => {
    setCookieError(null);
    if (!cookieDomain.trim()) {
      setCookieError('settings.network.creds.add_cookie.invalid');
      return;
    }

    let cookies: CookieImportItem[];
    try {
      cookies = parseCookieHeader(cookieValue);
    } catch {
      setCookieError('settings.network.creds.add_cookie.invalid');
      return;
    }

    setCookieSaving(true);
    try {
      const response = await fetch(webAccessApiUrl('/api/v1/web-access/credentials/cookie'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ domain: cookieDomain.trim(), cookies }),
      });
      if (!response.ok) {
        setCookieError('settings.network.creds.add_cookie.failed');
        return;
      }
      setCookieDomain('');
      setCookieValue('');
      reload();
    } catch {
      setCookieError('settings.network.creds.add_cookie.failed');
    } finally {
      setCookieSaving(false);
    }
  };

  return (
    <section>
      <h3 className="text-sm font-semibold text-text mb-3">{t('settings.network.creds')}</h3>
      <p className="text-xs text-muted mb-2">{t('settings.network.creds.hint')}</p>
      <div className="flex flex-col gap-2 w-full" data-testid="web-credentials">
        <label className="flex items-start gap-2 text-xs" data-testid="cred-render-persistent-row">
          <input
            type="checkbox"
            className="mt-0.5"
            checked={config.render_persistent}
            onChange={(e) => saveConfig({ ...config, render_persistent: e.target.checked })}
          />
          <span>
            {t('settings.network.creds.render_persistent')}
            <span className="block text-text-secondary">
              {t('settings.network.creds.render_persistent.desc')}
            </span>
          </span>
        </label>
        <label className="flex items-start gap-2 text-xs" data-testid="cred-auto-refresh-row">
          <input
            type="checkbox"
            className="mt-0.5"
            checked={config.auto_refresh_credentials}
            onChange={(e) => saveConfig({ ...config, auto_refresh_credentials: e.target.checked })}
          />
          <span>
            {t('settings.network.creds.auto_refresh')}
            <span className="block text-text-secondary">
              {t('settings.network.creds.auto_refresh.desc')}
            </span>
          </span>
        </label>
        <label className="flex items-start gap-2 text-xs" data-testid="cred-pool-size-row">
          <span>
            {t('settings.network.creds.pool_size')}
            <span className="block text-text-secondary">
              {t('settings.network.creds.pool_size.desc')}
            </span>
          </span>
          <select
            data-testid="cred-pool-size-select"
            className="mt-0.5 border border-border rounded-radius-sm bg-bg text-text"
            value={config.render_pool_size ?? 2}
            onChange={(e) => saveConfig({ ...config, render_pool_size: Number(e.target.value) })}
          >
            {RENDER_POOL_SIZE_OPTIONS.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-start gap-2 text-xs" data-testid="cred-tls-fingerprint-row">
          <input
            type="checkbox"
            className="mt-0.5"
            checked={config.tls_fingerprint ?? false}
            onChange={(e) => saveConfig({ ...config, tls_fingerprint: e.target.checked })}
          />
          <span>
            {t('settings.network.creds.tls_fingerprint')}
            <span className="block text-text-secondary">
              {t('settings.network.creds.tls_fingerprint.desc')}
            </span>
          </span>
        </label>
        {browser && (
          <div className="text-xs text-text-secondary" data-testid="browser-health">
            {browser.browserFound
              ? `${t('settings.network.creds.browser')}: Chrome ${browser.chromeMajor ?? '?'}`
              : t('settings.network.creds.browser.missing')}
            {browser.warning && <span className="block text-error">{browser.warning}</span>}
          </div>
        )}
        {metrics !== null && Object.keys(metrics).length > 0 && (
          <div className="flex flex-col gap-1" data-testid="host-metrics">
            <div className="flex items-center gap-2 text-xs">
              <span>{t('settings.network.creds.metrics')}</span>
              <button
                type="button"
                data-testid="metrics-refresh-btn"
                className="px-2 py-0.5 text-xs border border-border rounded-radius-sm hover:bg-bg-secondary"
                onClick={refreshMetrics}
              >
                {t('settings.network.creds.metrics.refresh')}
              </button>
              <button
                type="button"
                data-testid="metrics-reset-btn"
                className="px-2 py-0.5 text-xs border border-border rounded-radius-sm hover:bg-bg-secondary"
                onClick={resetMetrics}
              >
                {t('settings.network.creds.metrics.reset')}
              </button>
            </div>
            {Object.entries(metrics)
              .filter(([host]) => host !== 'render_events')
              .map(([host, m]) => (
                <div
                  key={host}
                  data-testid={`metric-row-${host}`}
                  className="flex items-center gap-2 text-xs"
                >
                  <span className="font-medium">{host}</span>
                  <span className="text-text-secondary">
                    {t('settings.network.creds.metrics.ok')}: {m.ok}
                  </span>
                  <span className="text-text-secondary">
                    {t('settings.network.creds.metrics.fail')}: {m.fail}
                  </span>
                  {m.escalated > 0 && (
                    <span className="text-text-secondary">
                      {t('settings.network.creds.metrics.escalated')}: {m.escalated}
                    </span>
                  )}
                  {m.avg_elapsed_ms !== null && (
                    <span className="text-text-secondary">
                      {t('settings.network.creds.metrics.avg')}: {m.avg_elapsed_ms}ms
                    </span>
                  )}
                </div>
              ))}
            <div className="text-text-secondary text-xs">
              {t('settings.network.creds.metrics.hint')}
            </div>
          </div>
        )}
        {renderEvents && renderEvents.renders > 0 && (
          <div className="flex flex-col gap-1 text-xs" data-testid="render-events-metrics">
            <span>{t('settings.network.creds.metrics.render_events')}</span>
            <div className="flex items-center gap-2 text-text-secondary">
              <span>
                {t('settings.network.creds.metrics.render_events.renders')}: {renderEvents.renders}
              </span>
              <span>
                {t('settings.network.creds.metrics.render_events.channel')}:{' '}
                {renderEvents.channel_ok}
              </span>
              <span>
                {t('settings.network.creds.metrics.render_events.hits')}:{' '}
                {renderEvents.event_status_hits}
              </span>
            </div>
          </div>
        )}
        <div className="flex flex-col gap-1" data-testid="header-cred-form">
          <div className="text-xs">{t('settings.network.creds.add_header')}</div>
          <div className="flex gap-1">
            <input
              data-testid="header-domain-input"
              aria-label={t('settings.network.creds.add_header.domain')}
              value={headerDomain}
              onChange={(e) => setHeaderDomain(e.target.value)}
              placeholder={t('settings.network.creds.add_header.domain')}
              className="flex-1 px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
            />
            <input
              data-testid="header-name-input"
              aria-label={t('settings.network.creds.add_header.name')}
              value={headerName}
              onChange={(e) => setHeaderName(e.target.value)}
              placeholder={t('settings.network.creds.add_header.name')}
              className="flex-1 px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
            />
            <input
              data-testid="header-value-input"
              aria-label={t('settings.network.creds.add_header.value')}
              type="password"
              value={headerValue}
              onChange={(e) => setHeaderValue(e.target.value)}
              placeholder={t('settings.network.creds.add_header.value')}
              className="flex-1 px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
            />
            <button
              type="button"
              data-testid="header-save-btn"
              className="px-2 py-1 text-xs border border-border rounded-radius-sm hover:bg-bg-secondary"
              onClick={addHeaderCred}
            >
              {t('settings.network.creds.add_header.save')}
            </button>
          </div>
        </div>
        <form
          data-testid="cookie-cred-form"
          className="flex flex-col gap-1"
          onSubmit={(event) => {
            event.preventDefault();
            void addCookieCred();
          }}
        >
          <div className="text-xs">{t('settings.network.creds.add_cookie.label')}</div>
          <div className="flex gap-1">
            <input
              data-testid="cookie-domain-input"
              aria-label={t('settings.network.creds.add_cookie.domain')}
              value={cookieDomain}
              onChange={(e) => setCookieDomain(e.target.value)}
              placeholder={t('settings.network.creds.add_cookie.domain')}
              className="flex-1 px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
            />
            <textarea
              data-testid="cookie-value-input"
              aria-label={t('settings.network.creds.add_cookie.value')}
              value={cookieValue}
              onChange={(e) => setCookieValue(e.target.value)}
              placeholder={t('settings.network.creds.add_cookie.value')}
              rows={2}
              className="flex-1 px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
            />
            <button
              type="submit"
              data-testid="cookie-save-btn"
              disabled={cookieSaving}
              className="px-2 py-1 text-xs border border-border rounded-radius-sm hover:bg-bg-secondary disabled:opacity-50"
            >
              {t('settings.network.creds.add_cookie.save')}
            </button>
          </div>
          {cookieError && (
            <div data-testid="cookie-error" className="text-xs text-error">
              {t(cookieError)}
            </div>
          )}
        </form>
        {creds !== null && creds.length === 0 && (
          <div className="text-xs text-text-secondary" data-testid="creds-empty">
            {t('settings.network.creds.empty')}
          </div>
        )}
        {creds !== null && creds.length > 0 && (
          <div className="flex flex-col gap-1">
            {creds.map((c) => (
              <div
                key={c.domain}
                data-testid={`cred-row-${c.domain}`}
                className="flex items-center gap-2 text-xs"
              >
                <span className="font-medium">{c.domain}</span>
                <span className="text-text-secondary">{c.kind}</span>
                {!c.encrypted && (
                  <span className="text-error">{t('settings.network.creds.plaintext')}</span>
                )}
                {c.source_profile && (
                  <span className="text-text-secondary">
                    {t('settings.network.creds.profile')}: {c.source_profile}
                  </span>
                )}
                <span className="text-text-secondary">
                  {c.expired
                    ? t('settings.network.creds.expired')
                    : c.expires_in_seconds != null
                      ? `${Math.max(1, Math.floor(c.expires_in_seconds / 3600))}h`
                      : ''}
                </span>
                <button
                  type="button"
                  data-testid={`cred-delete-${c.domain}`}
                  className="ml-auto px-2 py-0.5 text-xs border border-border rounded-radius-sm hover:bg-bg-secondary"
                  onClick={() => removeCred(c.domain)}
                >
                  {t('settings.network.creds.delete')}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
