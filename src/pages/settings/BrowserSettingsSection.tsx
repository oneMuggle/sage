import { Check, Globe, RefreshCw } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import {
  fetchBrowserList,
  setBrowserPath,
  type DiscoveredBrowser,
} from '../../shared/api/browserSettingsClient';
import { useI18n } from '../../shared/lib/i18n';

/**
 * 浏览器选择设置。
 *
 * 展示系统发现的 Chromium 系浏览器列表，允许用户指定首选浏览器。
 * browser_login 工具会使用用户选择的浏览器进行登录操作。
 */
export function BrowserSettingsSection() {
  const { t } = useI18n();
  const [browsers, setBrowsers] = useState<DiscoveredBrowser[]>([]);
  const [userConfigured, setUserConfigured] = useState<string | null>(null);
  const [embeddedAvailable, setEmbeddedAvailable] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);

  const load = async (): Promise<void> => {
    try {
      const result = await fetchBrowserList();
      setBrowsers(result.browsers);
      setUserConfigured(result.userConfigured);
      setEmbeddedAvailable(result.embeddedAvailable);
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const handleSelect = async (path: string): Promise<void> => {
    setSaving(path);
    try {
      const result = await setBrowserPath(path);
      if (result.success) {
        setUserConfigured(path || null);
        toast.success(t('settings.network.browser.saved'));
      } else {
        toast.error(result.error || t('settings.network.browser.save_failed'));
      }
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setSaving(null);
    }
  };

  const handleReset = async (): Promise<void> => {
    await handleSelect('');
  };

  const isSelected = (path: string): boolean => {
    if (userConfigured) return userConfigured === path;
    return browsers.find((b) => b.isDefault)?.path === path;
  };

  if (loading) {
    return (
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">
          {t('settings.network.browser.title')}
        </h3>
        <div className="flex items-center gap-2 text-muted text-xs py-4">
          <RefreshCw className="w-4 h-4 animate-spin" />
          {t('settings.network.browser.loading')}
        </div>
      </section>
    );
  }

  return (
    <section>
      <h3 className="text-sm font-semibold text-text mb-3">
        {t('settings.network.browser.title')}
      </h3>
      <p className="text-xs text-muted mb-3">{t('settings.network.browser.hint')}</p>

      {browsers.length === 0 && !embeddedAvailable ? (
        <div className="px-3 py-4 text-xs text-muted bg-surface rounded-radius-sm">
          {t('settings.network.browser.none_found')}
        </div>
      ) : (
        <div className="space-y-2">
          {browsers.map((browser) => {
            const selected = isSelected(browser.path);
            const isSaving = saving === browser.path;

            return (
              <button
                key={browser.path}
                type="button"
                disabled={isSaving}
                onClick={() => handleSelect(browser.path)}
                className={`w-full flex items-center gap-3 px-3 py-2 rounded-radius-sm border transition-colors text-left ${
                  selected
                    ? 'border-primary bg-primary/5'
                    : 'border-border bg-surface hover:border-primary/50'
                } ${isSaving ? 'opacity-50 cursor-wait' : 'cursor-pointer'}`}
              >
                <Globe className="w-4 h-4 text-muted shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-text flex items-center gap-2">
                    {browser.name}
                    {browser.version && (
                      <span className="text-xs text-muted">v{browser.version}</span>
                    )}
                    {browser.isDefault && !userConfigured && (
                      <span className="text-xs text-primary">
                        ({t('settings.network.browser.system_default')})
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-muted font-mono truncate">{browser.path}</div>
                </div>
                {selected && <Check className="w-4 h-4 text-primary shrink-0" />}
                {isSaving && <RefreshCw className="w-4 h-4 animate-spin text-muted shrink-0" />}
              </button>
            );
          })}
        </div>
      )}

      {userConfigured && (
        <button
          type="button"
          onClick={handleReset}
          disabled={saving !== null}
          className="mt-3 text-xs text-muted hover:text-text transition-colors"
        >
          {t('settings.network.browser.reset')}
        </button>
      )}
    </section>
  );
}
