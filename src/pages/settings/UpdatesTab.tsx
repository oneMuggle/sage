import { useEffect, useState } from 'react';

import type { UpdateChannel, UpdateConfig, UpdateStrategy } from '../../../electron/updateConfig';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';

import { SettingRow } from './components';

const STRATEGIES: readonly UpdateStrategy[] = ['manual', 'auto-download', 'auto-install'];
const CHANNELS: readonly UpdateChannel[] = ['stable', 'beta', 'alpha'];

const strategyLabelKeys: Record<UpdateStrategy, TranslationKey> = {
  manual: 'updates.strategy.manual',
  'auto-download': 'updates.strategy.autoDownload',
  'auto-install': 'updates.strategy.autoInstall',
};

const strategyDescriptionKeys: Record<UpdateStrategy, TranslationKey> = {
  manual: 'updates.strategy.manual.desc',
  'auto-download': 'updates.strategy.autoDownload.desc',
  'auto-install': 'updates.strategy.autoInstall.desc',
};

const channelLabelKeys: Record<UpdateChannel, TranslationKey> = {
  stable: 'updates.channel.stable',
  beta: 'updates.channel.beta',
  alpha: 'updates.channel.alpha',
};

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function UpdatesTab() {
  const { t } = useI18n();
  const [config, setConfig] = useState<UpdateConfig | null>(null);
  const [checking, setChecking] = useState(false);
  const [checkResult, setCheckResult] = useState<{
    available: boolean;
    version?: string;
    error?: boolean;
  } | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const loadConfig = async (): Promise<void> => {
      try {
        const loadedConfig = await window.electronAPI?.updates.getConfig();
        if (!cancelled && loadedConfig) setConfig(loadedConfig);
      } catch (error: unknown) {
        if (!cancelled) setConfigError(getErrorMessage(error));
      }
    };
    void loadConfig();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleStrategyChange = async (strategy: UpdateStrategy): Promise<void> => {
    try {
      await window.electronAPI?.updates.setStrategy(strategy);
      setConfig((previous) => (previous ? { ...previous, updateStrategy: strategy } : null));
    } catch (error: unknown) {
      setConfigError(getErrorMessage(error));
    }
  };

  const handleChannelChange = async (channel: UpdateChannel): Promise<void> => {
    try {
      await window.electronAPI?.updates.setChannel(channel);
      setConfig((previous) => (previous ? { ...previous, channel } : null));
    } catch (error: unknown) {
      setConfigError(getErrorMessage(error));
    }
  };

  const handleCheckNow = async (): Promise<void> => {
    setChecking(true);
    setCheckResult(null);
    try {
      const result = await window.electronAPI?.updates.check();
      setCheckResult({
        available: result?.updateAvailable ?? false,
        version: result?.version,
      });
    } catch {
      setCheckResult({ available: false, error: true });
    } finally {
      setChecking(false);
    }
  };

  return (
    <div className="space-y-6" data-testid="updates-tab">
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">{t('updates.strategy')}</h3>
        <fieldset className="space-y-2">
          <legend className="sr-only">{t('updates.strategy')}</legend>
          {STRATEGIES.map((strategy) => (
            <label
              key={strategy}
              className="flex items-start gap-3 p-3 border border-border rounded-radius-sm cursor-pointer hover:bg-bg-muted"
            >
              <input
                type="radio"
                name="update-strategy"
                value={strategy}
                checked={config?.updateStrategy === strategy}
                disabled={config === null}
                onChange={() => void handleStrategyChange(strategy)}
                className="mt-0.5"
              />
              <span>
                <span className="block text-sm text-text">{t(strategyLabelKeys[strategy])}</span>
                <span className="block text-xs text-muted mt-0.5">
                  {t(strategyDescriptionKeys[strategy])}
                </span>
              </span>
            </label>
          ))}
        </fieldset>
      </section>

      <section>
        <SettingRow label={t('updates.channel')}>
          <select
            data-testid="updates-channel-select"
            aria-label={t('updates.channel')}
            value={config?.channel ?? ''}
            disabled={config === null}
            onChange={(event) => void handleChannelChange(event.target.value as UpdateChannel)}
            className="px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
          >
            <option value="" disabled>
              {t('common.loading')}
            </option>
            {CHANNELS.map((channel) => (
              <option key={channel} value={channel}>
                {t(channelLabelKeys[channel])}
              </option>
            ))}
          </select>
        </SettingRow>
      </section>

      <section>
        <h3 className="text-sm font-semibold text-text mb-3">{t('updates.checkNow')}</h3>
        <button
          type="button"
          data-testid="updates-check-button"
          disabled={checking}
          onClick={() => void handleCheckNow()}
          className="px-3 py-1.5 text-xs border border-border rounded-radius-sm text-text hover:bg-bg-muted disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {checking ? t('updates.checking') : t('updates.checkNow')}
        </button>
        {configError && (
          <p className="text-xs text-error mt-2" role="alert">
            {configError}
          </p>
        )}
        {checkResult?.error && (
          <p className="text-xs text-error mt-2" role="alert">
            {t('updates.checkFailed')}
          </p>
        )}
        {checkResult && !checkResult.error && checkResult.available && checkResult.version && (
          <p className="text-xs text-success mt-2" role="status">
            {t('updates.available').replace('{version}', checkResult.version)}
          </p>
        )}
        {checkResult && !checkResult.error && !checkResult.available && (
          <p className="text-xs text-muted mt-2" role="status">
            {t('updates.upToDate')}
          </p>
        )}
      </section>
    </div>
  );
}
