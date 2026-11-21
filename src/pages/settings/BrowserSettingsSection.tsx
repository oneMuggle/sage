import { Check, Globe, RefreshCw } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import {
  fetchBrowserConfig,
  fetchBrowserList,
  setBrowserConfig as saveBrowserConfig,
  setBrowserPath,
  type BrowserConfig,
  type DiscoveredBrowser,
} from '../../shared/api/browserSettingsClient';
import { useI18n } from '../../shared/lib/i18n';

/** 与后端 EMBEDDED_EXECUTABLE 一致：内置浏览器选项在 browser_path 中的哨兵值 */
const EMBEDDED_PATH = '(embedded)';

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
  const [error, setError] = useState<string | null>(null);
  // 2026-11-20: 浏览器会话配置（P0/P3）
  const [browserConfig, setBrowserConfig] = useState<BrowserConfig>({
    maxSessions: 4,
    lruEvict: false,
  });
  const [savingConfig, setSavingConfig] = useState(false);

  const load = async (): Promise<void> => {
    setLoading(true);
    setError(null);
    try {
      const [result, config] = await Promise.all([fetchBrowserList(), fetchBrowserConfig()]);
      setBrowsers(result.browsers);
      setUserConfigured(result.userConfigured);
      setEmbeddedAvailable(result.embeddedAvailable);
      setBrowserConfig(config);
    } catch (cause) {
      // 加载失败 ≠ 未发现浏览器：空态只用于「后端明确返回空」。
      setError(cause instanceof Error ? cause.message : String(cause));
      toast.error(t('settings.network.browser.load_failed'));
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

  // P0/P3: 保存并发上限 / LRU 回收开关
  const handleSaveConfig = async (patch: Partial<BrowserConfig>): Promise<void> => {
    setSavingConfig(true);
    try {
      const next = await saveBrowserConfig(patch);
      setBrowserConfig(next);
      toast.success(t('settings.network.browser.config_saved'));
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setSavingConfig(false);
    }
  };

  const isSelected = (path: string): boolean => {
    if (path === EMBEDDED_PATH) {
      return userConfigured === EMBEDDED_PATH || (!userConfigured && embeddedAvailable);
    }
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

      {error ? (
        <div
          data-testid="browser-load-error"
          className="px-3 py-4 text-xs bg-surface rounded-radius-sm"
        >
          <div className="text-text">{t('settings.network.browser.load_failed')}</div>
          <div className="text-muted mt-1 break-all font-mono">{error}</div>
          <button
            type="button"
            data-testid="browser-retry"
            onClick={() => void load()}
            className="mt-2 px-3 py-1 text-xs bg-primary text-text-inverse rounded-radius-sm hover:bg-primary-hover transition-colors"
          >
            {t('settings.network.browser.retry')}
          </button>
        </div>
      ) : browsers.length === 0 && !embeddedAvailable ? (
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
          {embeddedAvailable && (
            <button
              type="button"
              data-testid="embedded-browser-option"
              disabled={saving === EMBEDDED_PATH}
              onClick={() => handleSelect(EMBEDDED_PATH)}
              className={`w-full flex items-center gap-3 px-3 py-2 rounded-radius-sm border transition-colors text-left ${
                isSelected(EMBEDDED_PATH)
                  ? 'border-primary bg-primary/5'
                  : 'border-border bg-surface hover:border-primary/50'
              } ${saving === EMBEDDED_PATH ? 'opacity-50 cursor-wait' : 'cursor-pointer'}`}
            >
              <Globe className="w-4 h-4 text-muted shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="text-sm text-text flex items-center gap-2">
                  {t('settings.network.browser.embedded')}
                  {!userConfigured && (
                    <span className="text-xs text-primary">
                      ({t('settings.network.browser.system_default')})
                    </span>
                  )}
                </div>
                <div className="text-xs text-muted">
                  {t('settings.network.browser.embedded_hint')}
                </div>
              </div>
              {isSelected(EMBEDDED_PATH) && <Check className="w-4 h-4 text-primary shrink-0" />}
              {saving === EMBEDDED_PATH && (
                <RefreshCw className="w-4 h-4 animate-spin text-muted shrink-0" />
              )}
            </button>
          )}
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

      {/* P0: 并发实例上限 */}
      <div className="mt-6 pt-4 border-t border-border">
        <div className="flex items-center justify-between mb-2">
          <h4 className="text-sm font-medium text-text">
            {t('settings.network.browser.max_sessions')}
          </h4>
          <span className="text-sm font-mono text-text">{browserConfig.maxSessions}</span>
        </div>
        <p className="text-xs text-muted mb-3">{t('settings.network.browser.max_sessions_hint')}</p>
        <input
          type="range"
          min={2}
          max={8}
          step={1}
          value={browserConfig.maxSessions}
          disabled={savingConfig}
          onChange={(e) => void handleSaveConfig({ maxSessions: Number(e.target.value) })}
          className="w-full accent-primary disabled:opacity-50"
          data-testid="browser-max-sessions-slider"
        />
        <div className="flex justify-between text-xs text-muted mt-1">
          <span>{t('settings.network.browser.max_sessions_low')}</span>
          <span>{t('settings.network.browser.max_sessions_rec')}</span>
          <span>{t('settings.network.browser.max_sessions_high')}</span>
        </div>
      </div>

      {/* P3: LRU 自动回收开关 */}
      <div className="mt-4 flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="text-sm text-text">{t('settings.network.browser.lru_evict')}</div>
          <p className="text-xs text-muted mt-1">{t('settings.network.browser.lru_evict_hint')}</p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={browserConfig.lruEvict}
          disabled={savingConfig}
          onClick={() => void handleSaveConfig({ lruEvict: !browserConfig.lruEvict })}
          className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors disabled:opacity-50 ${
            browserConfig.lruEvict ? 'bg-primary' : 'bg-surface border border-border'
          }`}
          data-testid="browser-lru-evict-toggle"
        >
          <span
            className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
              browserConfig.lruEvict ? 'translate-x-4' : 'translate-x-1'
            }`}
          />
        </button>
      </div>
    </section>
  );
}
