import { RefreshCw } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import {
  deleteSitePolicy,
  fetchBrowserUseConfig,
  fetchSitePolicies,
  setSitePolicy,
  updateBrowserUseConfig,
  type BrowserUseConfig,
  type SitePolicy,
} from '../../shared/api/browserControlClient';
import { fillTemplate } from '../../shared/lib/formatTemplate';
import { useI18n } from '../../shared/lib/i18n';
import { confirmDialog } from '../../shared/ui/ConfirmDialog/confirmService';

import { SettingRow, Toggle } from './components';

type PolicyMode = SitePolicy['mode'];

/** 后端缺省按开启处理：只有显式 false 才算关闭。 */
const DEFAULT_CONFIG: BrowserUseConfig = {
  default_visible: true,
  step_thumbnails: true,
};

function normalizeConfig(raw: unknown): BrowserUseConfig {
  const candidate = (raw ?? {}) as Partial<BrowserUseConfig>;
  return {
    default_visible: candidate.default_visible !== false,
    step_thumbnails: candidate.step_thumbnails !== false,
  };
}

function normalizeDomain(raw: string): string {
  return raw.trim().toLowerCase().replace(/\.+$/, '');
}

function toPolicy(raw: unknown): SitePolicy | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const candidate = raw as Partial<SitePolicy>;
  if (typeof candidate.domain !== 'string' || !candidate.domain) return null;
  return {
    domain: candidate.domain,
    mode: candidate.mode === 'block' ? 'block' : 'allow',
    updated_at: typeof candidate.updated_at === 'number' ? candidate.updated_at : 0,
  };
}

function toPolicyList(raw: unknown): SitePolicy[] | null {
  if (!Array.isArray(raw)) return null;
  return raw.map(toPolicy).filter((item): item is SitePolicy => item !== null);
}

function formatUpdatedAt(ts: number): string {
  const date = new Date(ts);
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString();
}

/**
 * 设置页「浏览器使用」（M4）。
 *
 * 控制受控浏览器的两个偏好开关（默认可见 / 步骤缩略图），并维护持久站点
 * 策略表（allow / block）。数据来自 browserControlClient，失败降级为提示，
 * 不阻塞设置页其余区块。
 */
export function BrowserUseSection() {
  const { t } = useI18n();
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [config, setConfig] = useState<BrowserUseConfig>(DEFAULT_CONFIG);
  const [savingField, setSavingField] = useState<keyof BrowserUseConfig | null>(null);
  const [policies, setPolicies] = useState<SitePolicy[]>([]);
  const [domain, setDomain] = useState('');
  const [mode, setMode] = useState<PolicyMode>('allow');
  const [policyBusy, setPolicyBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async (): Promise<void> => {
      const cfg = await fetchBrowserUseConfig().catch(() => null);
      const list = await fetchSitePolicies().catch(() => null);
      if (cancelled) return;
      if (cfg) setConfig(normalizeConfig(cfg));
      const parsed = toPolicyList(list);
      if (parsed) setPolicies(parsed);
      setLoadFailed(!cfg || !parsed);
      setLoading(false);
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleToggle = async (field: keyof BrowserUseConfig, value: boolean): Promise<void> => {
    if (savingField) return;
    const previous = config;
    setConfig({ ...config, [field]: value });
    setSavingField(field);
    try {
      const patch: Partial<BrowserUseConfig> =
        field === 'default_visible' ? { default_visible: value } : { step_thumbnails: value };
      const saved = await updateBrowserUseConfig(patch);
      setConfig(normalizeConfig(saved));
    } catch {
      setConfig(previous);
      toast.error(t('settings.network.browserUse.save_failed'));
    } finally {
      setSavingField(null);
    }
  };

  const refreshPolicies = async (): Promise<void> => {
    const parsed = toPolicyList(await fetchSitePolicies().catch(() => null));
    if (parsed) setPolicies(parsed);
  };

  const handleAddPolicy = async (): Promise<void> => {
    const normalized = normalizeDomain(domain);
    if (!normalized || policyBusy) return;
    setPolicyBusy(true);
    try {
      await setSitePolicy(normalized, mode);
      setDomain('');
      await refreshPolicies();
    } catch {
      toast.error(t('settings.network.browserUse.policies.save_failed'));
    } finally {
      setPolicyBusy(false);
    }
  };

  const handleDeletePolicy = async (target: string): Promise<void> => {
    const confirmed = await confirmDialog({
      title: t('settings.network.browserUse.policies.delete_title'),
      message: fillTemplate(t('settings.network.browserUse.policies.delete_message'), {
        domain: target,
      }),
      confirmLabel: t('common.delete'),
      danger: true,
    });
    if (!confirmed) return;
    setPolicyBusy(true);
    try {
      await deleteSitePolicy(target);
      setPolicies((prev) => prev.filter((item) => item.domain !== target));
    } catch {
      toast.error(t('settings.network.browserUse.policies.delete_failed'));
    } finally {
      setPolicyBusy(false);
    }
  };

  return (
    <section data-testid="browser-use-section">
      <h3 className="text-sm font-semibold text-text mb-3">
        {t('settings.network.browserUse.title')}
      </h3>
      <p className="text-xs text-muted mb-3">{t('settings.network.browserUse.hint')}</p>

      {loading ? (
        <div className="flex items-center gap-2 text-muted text-xs py-4">
          <RefreshCw className="w-4 h-4 animate-spin" />
          {t('settings.network.browserUse.loading')}
        </div>
      ) : (
        <>
          {loadFailed && (
            <div data-testid="browser-use-load-failed" className="mb-2 text-xs text-error">
              {t('settings.network.browserUse.load_failed')}
            </div>
          )}

          <SettingRow
            label={t('settings.network.browserUse.default_visible')}
            desc={t('settings.network.browserUse.default_visible.desc')}
          >
            <Toggle
              value={config.default_visible}
              disabled={savingField !== null}
              onChange={(value) => void handleToggle('default_visible', value)}
              testId="browser-use-default-visible"
            />
          </SettingRow>
          <SettingRow
            label={t('settings.network.browserUse.step_thumbnails')}
            desc={t('settings.network.browserUse.step_thumbnails.desc')}
          >
            <Toggle
              value={config.step_thumbnails}
              disabled={savingField !== null}
              onChange={(value) => void handleToggle('step_thumbnails', value)}
              testId="browser-use-step-thumbnails"
            />
          </SettingRow>

          <div className="mt-4" data-testid="site-policy-block">
            <div className="text-sm text-text">
              {t('settings.network.browserUse.policies.title')}
            </div>
            <p className="text-xs text-muted mt-0.5">
              {t('settings.network.browserUse.policies.hint')}
            </p>

            <div className="mt-2 flex items-center gap-2">
              <input
                data-testid="site-policy-domain"
                aria-label={t('settings.network.browserUse.policies.domain')}
                value={domain}
                onChange={(event) => setDomain(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') void handleAddPolicy();
                }}
                placeholder={t('settings.network.browserUse.policies.domain_placeholder')}
                className="flex-1 min-w-0 px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
              />
              <select
                data-testid="site-policy-mode"
                aria-label={t('settings.network.browserUse.policies.mode')}
                value={mode}
                onChange={(event) => setMode(event.target.value === 'block' ? 'block' : 'allow')}
                className="px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
              >
                <option value="allow">
                  {t('settings.network.browserUse.policies.mode.allow')}
                </option>
                <option value="block">
                  {t('settings.network.browserUse.policies.mode.block')}
                </option>
              </select>
              <button
                type="button"
                data-testid="site-policy-add"
                disabled={policyBusy || !normalizeDomain(domain)}
                onClick={() => void handleAddPolicy()}
                className="px-3 py-1 text-xs bg-primary text-text-inverse rounded-radius-sm hover:bg-primary-hover transition-colors disabled:opacity-40"
              >
                {t('settings.network.browserUse.policies.add')}
              </button>
            </div>

            {policies.length === 0 ? (
              <div
                data-testid="site-policy-empty"
                className="mt-2 px-3 py-4 text-xs text-muted bg-surface rounded-radius-sm"
              >
                {t('settings.network.browserUse.policies.empty')}
              </div>
            ) : (
              <table className="mt-2 w-full text-xs" data-testid="site-policy-table">
                <thead>
                  <tr className="text-left text-muted">
                    <th className="py-1 pr-2 font-normal">
                      {t('settings.network.browserUse.policies.domain')}
                    </th>
                    <th className="py-1 pr-2 font-normal">
                      {t('settings.network.browserUse.policies.mode')}
                    </th>
                    <th className="py-1 pr-2 font-normal">
                      {t('settings.network.browserUse.policies.updated_at')}
                    </th>
                    <th className="py-1 font-normal" aria-hidden="true" />
                  </tr>
                </thead>
                <tbody>
                  {policies.map((policy) => (
                    <tr
                      key={policy.domain}
                      data-testid={`site-policy-row-${policy.domain}`}
                      className="border-t border-border"
                    >
                      <td className="py-1 pr-2 font-mono text-text">{policy.domain}</td>
                      <td className="py-1 pr-2">
                        {t(`settings.network.browserUse.policies.mode.${policy.mode}`)}
                      </td>
                      <td className="py-1 pr-2 text-muted">{formatUpdatedAt(policy.updated_at)}</td>
                      <td className="py-1 text-right">
                        <button
                          type="button"
                          data-testid={`site-policy-delete-${policy.domain}`}
                          disabled={policyBusy}
                          onClick={() => void handleDeletePolicy(policy.domain)}
                          className="text-error hover:text-red-700 transition-colors disabled:opacity-40"
                        >
                          {t('settings.network.browserUse.policies.delete')}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </section>
  );
}
