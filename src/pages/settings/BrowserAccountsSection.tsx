import { Globe, Plus, Shuffle, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import {
  createBrowserAccount,
  deleteBrowserAccount,
  fetchBrowserAccounts,
  switchBrowserAccount,
  type BrowserAccount,
} from '../../shared/api/webAccessClient';
import { useI18n } from '../../shared/lib/i18n';
import { confirmDialog } from '../../shared/ui/ConfirmDialog/confirmService';

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function fill(template: string, vars: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (match, key: string) =>
    key in vars ? String(vars[key]) : match,
  );
}

/**
 * 「浏览器账号」——同一网站多账号的池管理与热切换。
 *
 * 账号凭据由后端 credential vault 按 domain::account_id 隔离；切换走
 * Cookie State Swap（快照当前 → 清空 → 注入目标 → 刷新），不串号。
 */
export function BrowserAccountsSection() {
  const { t } = useI18n();
  const [accounts, setAccounts] = useState<BrowserAccount[] | null>(null);
  const [label, setLabel] = useState('');
  const [domain, setDomain] = useState('');
  const [creating, setCreating] = useState(false);
  const [switching, setSwitching] = useState('');

  const reload = (): void => {
    fetchBrowserAccounts()
      .then((list) => setAccounts(list))
      .catch(() => setAccounts([]));
  };

  useEffect(() => {
    reload();
  }, []);

  const create = async (): Promise<void> => {
    const trimmedLabel = label.trim();
    const trimmedDomain = domain.trim().replace(/^\./, '');
    if (!trimmedLabel || !trimmedDomain) {
      toast.error(t('settings.network.accounts.name_placeholder'));
      return;
    }
    setCreating(true);
    try {
      await createBrowserAccount({ label: trimmedLabel, domain: trimmedDomain });
      toast.success(fill(t('settings.network.accounts.created'), { label: trimmedLabel }));
      setLabel('');
      setDomain('');
      reload();
    } catch (error) {
      toast.error(errorText(error));
    } finally {
      setCreating(false);
    }
  };

  const switchTo = async (account: BrowserAccount): Promise<void> => {
    setSwitching(account.id);
    try {
      const result = await switchBrowserAccount(account.id);
      toast.success(
        result.message ||
          fill(t('settings.network.accounts.switch_success'), { label: account.label }),
      );
    } catch (error) {
      toast.error(fill(t('settings.network.accounts.switch_failed'), { error: errorText(error) }));
    } finally {
      setSwitching('');
    }
  };

  const remove = async (account: BrowserAccount): Promise<void> => {
    const confirmed = await confirmDialog({
      title: t('settings.network.accounts.delete.confirm'),
      danger: true,
    });
    if (!confirmed) return;
    try {
      await deleteBrowserAccount(account.id);
      toast.success(t('settings.network.accounts.deleted'));
      reload();
    } catch (error) {
      toast.error(errorText(error));
    }
  };

  const grouped = (accounts ?? []).reduce<Record<string, BrowserAccount[]>>((acc, account) => {
    (acc[account.domain] ??= []).push(account);
    return acc;
  }, {});

  return (
    <section data-testid="browser-accounts">
      <h3 className="text-sm font-semibold text-text mb-3">{t('settings.network.accounts')}</h3>
      <p className="text-xs text-muted mb-2">{t('settings.network.accounts.hint')}</p>

      <div className="flex flex-wrap items-center gap-1.5 mb-3" data-testid="account-create-form">
        <input
          data-testid="account-name-input"
          aria-label={t('settings.network.accounts.name_placeholder')}
          value={label}
          onChange={(event) => setLabel(event.target.value)}
          placeholder={t('settings.network.accounts.name_placeholder')}
          className="w-44 px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
        />
        <input
          data-testid="account-domain-input"
          aria-label={t('settings.network.accounts.domain_placeholder')}
          value={domain}
          onChange={(event) => setDomain(event.target.value)}
          placeholder={t('settings.network.accounts.domain_placeholder')}
          className="flex-1 min-w-40 px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
        />
        <button
          type="button"
          data-testid="account-create-btn"
          disabled={creating}
          onClick={() => void create()}
          className="inline-flex items-center gap-1 px-2.5 py-1 text-xs border border-primary/40 bg-primary/10 text-primary rounded-radius-sm hover:bg-primary/20 disabled:opacity-50"
        >
          <Plus className="w-3.5 h-3.5" />
          {t('settings.network.accounts.create')}
        </button>
      </div>

      {accounts !== null && accounts.length === 0 && (
        <div className="text-xs text-text-secondary" data-testid="browser-accounts-empty">
          {t('settings.network.accounts.empty')}
        </div>
      )}

      {accounts !== null && accounts.length > 0 && (
        <div className="flex flex-col gap-2" data-testid="browser-account-groups">
          {Object.entries(grouped).map(([groupDomain, groupAccounts]) => (
            <div key={groupDomain} data-testid={`account-group-${groupDomain}`}>
              <div className="flex items-center gap-1.5 text-xs text-text-secondary mb-1">
                <Globe className="w-3.5 h-3.5" />
                <span className="font-medium">{groupDomain.replace(/^\./, '')}</span>
              </div>
              <ul className="flex flex-col gap-1">
                {groupAccounts.map((account) => (
                  <li
                    key={account.id}
                    data-testid={`account-row-${account.id}`}
                    className="flex items-center gap-2 text-xs px-2 py-1.5 border border-border rounded-radius-sm"
                  >
                    {account.color && (
                      <span
                        className="w-2.5 h-2.5 rounded-full shrink-0"
                        style={{ backgroundColor: account.color }}
                        aria-hidden
                      />
                    )}
                    <span className="font-medium">{account.label}</span>
                    {account.is_default && (
                      <span className="px-1.5 py-0.5 rounded bg-bg-muted text-text-secondary">
                        {t('settings.network.accounts.default_badge')}
                      </span>
                    )}
                    {account.notes && (
                      <span className="text-text-secondary truncate max-w-40">{account.notes}</span>
                    )}
                    <span className="ml-auto flex items-center gap-1">
                      <button
                        type="button"
                        data-testid={`account-switch-${account.id}`}
                        disabled={switching === account.id}
                        className="inline-flex items-center gap-1 px-2 py-0.5 text-xs border border-border rounded-radius-sm hover:bg-bg-muted disabled:opacity-50"
                        onClick={() => void switchTo(account)}
                      >
                        <Shuffle className="w-3 h-3" />
                        {t(
                          switching === account.id
                            ? 'settings.network.accounts.switching'
                            : 'settings.network.accounts.switch',
                        )}
                      </button>
                      <button
                        type="button"
                        data-testid={`account-delete-${account.id}`}
                        className="inline-flex items-center gap-1 px-2 py-0.5 text-xs border border-border rounded-radius-sm hover:bg-bg-muted"
                        onClick={() => void remove(account)}
                      >
                        <Trash2 className="w-3 h-3" />
                        {t('settings.network.accounts.delete')}
                      </button>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
