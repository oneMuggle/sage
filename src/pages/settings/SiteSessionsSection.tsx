import { Globe, LogIn, ShieldCheck, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import {
  deleteSiteSession,
  fetchSiteLoginTemplates,
  fetchSiteSessions,
  isHttpUrl,
  isLoginInProgressError,
  startSiteLogin,
  waitForSiteLogin,
  type SiteLoginTemplate,
  type SiteSession,
} from '../../shared/api/webAccessClient';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';
import { confirmDialog } from '../../shared/ui/ConfirmDialog/confirmService';

import { CredentialsSection } from './NetworkCredentialsSection';

interface SiteSessionsSectionProps {
  /** 测试注入轮询间隔；线上保持 2s。 */
  pollIntervalMs?: number;
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function fill(template: string, vars: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (match, key: string) =>
    key in vars ? String(vars[key]) : match,
  );
}

function savedAgo(site: SiteSession, t: (key: TranslationKey) => string): string {
  if (!site.saved_at) return '';
  const hours = Math.max(1, Math.floor((Date.now() - site.saved_at) / 3600000));
  if (hours <= 1) return t('settings.network.sites.saved_just_now');
  return fill(t('settings.network.sites.saved_hours'), { hours });
}

/**
 * 「已登录的网站」——用户只面对登录动作，不接触 cookie/header 术语。
 *
 * 技术型开关与手动导入整体折叠进「高级：手动导入与诊断」，默认收起。
 */
export function SiteSessionsSection({ pollIntervalMs = 2000 }: SiteSessionsSectionProps) {
  const { t } = useI18n();
  const [sites, setSites] = useState<SiteSession[] | null>(null);
  const [templates, setTemplates] = useState<SiteLoginTemplate[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState('');
  const [url, setUrl] = useState('');
  const [busy, setBusy] = useState(false);

  const reload = (): void => {
    fetchSiteSessions()
      .then((list) => setSites(list))
      .catch(() => setSites([]));
  };

  useEffect(() => {
    reload();
    fetchSiteLoginTemplates()
      .then((list) => setTemplates(list))
      .catch(() => setTemplates([]));
  }, []);

  const chooseTemplate = (templateId: string): void => {
    setSelectedTemplate(templateId);
    const template = templates.find((item) => item.id === templateId);
    if (template) setUrl(template.login_url);
  };

  const runLogin = async (target: string): Promise<void> => {
    const trimmed = target.trim();
    if (!isHttpUrl(trimmed)) {
      toast.error(t('settings.network.sites.invalid_url'));
      return;
    }
    setBusy(true);
    try {
      const jobId = await startSiteLogin(trimmed);
      const job = await waitForSiteLogin(jobId, { intervalMs: pollIntervalMs });
      if (job.status !== 'success') {
        throw new Error(job.error || 'login_failed');
      }
      toast.success(t('settings.network.sites.success'));
      setUrl('');
      setSelectedTemplate('');
      reload();
    } catch (error) {
      toast.error(
        isLoginInProgressError(error)
          ? t('settings.network.sites.login_in_progress')
          : fill(t('settings.network.sites.failed'), { error: errorText(error) }),
      );
    } finally {
      setBusy(false);
    }
  };

  const disconnect = async (site: SiteSession): Promise<void> => {
    const confirmed = await confirmDialog({
      title: t('settings.network.sites.disconnect.confirm'),
      danger: true,
    });
    if (!confirmed) return;
    try {
      await deleteSiteSession(site.domain);
      reload();
    } catch (error) {
      toast.error(errorText(error));
    }
  };

  return (
    <section data-testid="site-sessions" data-settings-anchor="site_sessions">
      <h3 className="text-sm font-semibold text-text mb-3">{t('settings.network.sites')}</h3>
      <p className="text-xs text-muted mb-2">{t('settings.network.sites.hint')}</p>

      <div
        className="flex flex-wrap items-center gap-1.5 mb-3"
        data-testid="site-login-form"
      >
        <select
          data-testid="site-template-select"
          aria-label={t('settings.network.sites.template')}
          value={selectedTemplate}
          onChange={(event) => chooseTemplate(event.target.value)}
          className="px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text"
        >
          <option value="">{t('settings.network.sites.template.placeholder')}</option>
          {templates.map((template) => (
            <option key={template.id} value={template.id}>
              {template.display_name}
            </option>
          ))}
        </select>
        <input
          data-testid="site-url-input"
          aria-label={t('settings.network.sites.url_placeholder')}
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          placeholder={t('settings.network.sites.url_placeholder')}
          className="flex-1 min-w-48 px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
        />
        <button
          type="button"
          data-testid="site-login-btn"
          disabled={busy}
          onClick={() => void runLogin(url)}
          className="inline-flex items-center gap-1 px-2.5 py-1 text-xs border border-primary/40 bg-primary/10 text-primary rounded-radius-sm hover:bg-primary/20 disabled:opacity-50"
        >
          <LogIn className="w-3.5 h-3.5" />
          {t('settings.network.sites.login_button')}
        </button>
      </div>

      {busy && (
        <div className="text-xs text-text-secondary mb-2" data-testid="site-login-waiting">
          {t('settings.network.sites.waiting')}
        </div>
      )}

      {sites !== null && sites.length === 0 && (
        <div className="text-xs text-text-secondary" data-testid="site-sessions-empty">
          {t('settings.network.sites.empty')}
        </div>
      )}

      {sites !== null && sites.length > 0 && (
        <ul className="flex flex-col gap-1" data-testid="site-session-list">
          {sites.map((site) => (
            <li
              key={site.domain}
              data-testid={`site-row-${site.domain}`}
              className="flex items-center gap-2 text-xs px-2 py-1.5 border border-border rounded-radius-sm"
            >
              <Globe className="w-3.5 h-3.5 text-text-secondary shrink-0" />
              <span className="font-medium">{site.display_name}</span>
              <span className="text-text-secondary truncate max-w-40">
                {site.domain.replace(/^\./, '')}
              </span>
              <span
                className={
                  site.status === 'logged_in'
                    ? 'px-1.5 py-0.5 rounded bg-success/10 text-success'
                    : 'px-1.5 py-0.5 rounded bg-warning/10 text-warning'
                }
                data-testid={`site-status-${site.domain}`}
              >
                {t(
                  site.status === 'logged_in'
                    ? 'settings.network.sites.status.logged_in'
                    : 'settings.network.sites.status.expired',
                )}
              </span>
              {site.has_local_storage && (
                <span className="inline-flex items-center gap-1 text-text-secondary">
                  <ShieldCheck className="w-3 h-3" />
                  {t('settings.network.sites.storage')}
                </span>
              )}
              <span className="text-text-secondary">{savedAgo(site, t)}</span>
              <span className="ml-auto flex items-center gap-1">
                {site.kind === 'cookie' && (
                  <button
                    type="button"
                    data-testid={`site-relogin-${site.domain}`}
                    className="px-2 py-0.5 text-xs border border-border rounded-radius-sm hover:bg-bg-muted"
                    onClick={() => void runLogin(site.login_url)}
                  >
                    {t('settings.network.sites.relogin')}
                  </button>
                )}
                <button
                  type="button"
                  data-testid={`site-disconnect-${site.domain}`}
                  className="inline-flex items-center gap-1 px-2 py-0.5 text-xs border border-border rounded-radius-sm hover:bg-bg-muted"
                  onClick={() => void disconnect(site)}
                >
                  <Trash2 className="w-3 h-3" />
                  {t('settings.network.sites.disconnect')}
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}

      <details className="mt-3" data-testid="site-advanced">
        <summary className="text-xs text-text-secondary cursor-pointer select-none">
          {t('settings.network.advanced')}
        </summary>
        <p className="text-xs text-muted my-2">{t('settings.network.advanced.hint')}</p>
        <div data-settings-anchor="web_credentials">
          <CredentialsSection />
        </div>
      </details>
    </section>
  );
}
