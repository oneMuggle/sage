import { useEffect, useState } from 'react';

import type { UpdateChannel, UpdateConfig, UpdateStrategy } from '../../../electron/updateConfig';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';

import { AdvancedSection, ApplyModeBadge, SettingRow } from './components';

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
    errorMessage?: string;
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

  const handleConfigPatch = async (patch: Partial<UpdateConfig>): Promise<void> => {
    try {
      const next = await window.electronAPI?.updates.setConfigPatch(patch);
      if (next) setConfig(next);
    } catch (error: unknown) {
      setConfigError(getErrorMessage(error));
    }
  };

  const handleCheckNow = async (): Promise<void> => {
    setChecking(true);
    setCheckResult(null);
    try {
      const result = await window.electronAPI?.updates.check();
      if (result?.error) {
        // 主进程返回了检查失败原因 (如网络不可达 / 源配置错误) — 展示而非静默当作"无更新"
        setCheckResult({
          available: false,
          error: true,
          errorMessage: result.error,
        });
        return;
      }
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
        <div className="mt-2">
          <ApplyModeBadge mode="immediate" />
        </div>
      </section>

      <AdvancedSection
        title="高级更新设置"
        description="这些设置会立即保存并由更新管理器使用；更新服务器必须是 HTTPS。"
      >
        <div className="space-y-1">
          <SettingRow label="回滚窗口（天）" desc="安装后允许自动回滚的时间窗口">
            <input
              type="number"
              min={1}
              max={30}
              data-testid="updates-rollback-window"
              value={config?.rollbackWindowDays ?? ''}
              disabled={config === null}
              onChange={(event) =>
                void handleConfigPatch({ rollbackWindowDays: Number(event.target.value) })
              }
              className="w-24 px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text"
            />
          </SettingRow>
          <SettingRow label="自动回滚触发次数" desc="启动失败多少次后自动回滚">
            <input
              type="number"
              min={1}
              max={10}
              data-testid="updates-rollback-threshold"
              value={config?.autoRollbackThreshold ?? ''}
              disabled={config === null}
              onChange={(event) =>
                void handleConfigPatch({ autoRollbackThreshold: Number(event.target.value) })
              }
              className="w-24 px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text"
            />
          </SettingRow>
          <SettingRow label="自动检查周期（小时）">
            <input
              type="number"
              min={1}
              max={168}
              data-testid="updates-check-interval"
              value={config?.checkIntervalHours ?? ''}
              disabled={config === null}
              onChange={(event) =>
                void handleConfigPatch({ checkIntervalHours: Number(event.target.value) })
              }
              className="w-24 px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text"
            />
          </SettingRow>
          <SettingRow label="更新服务器地址" desc="必须使用 HTTPS，且不能包含用户名、密码或路径">
            <input
              type="url"
              data-testid="updates-server-url"
              value={config?.updateServerUrl ?? ''}
              disabled={config === null}
              onChange={(event) =>
                void handleConfigPatch({ updateServerUrl: event.target.value.trim() })
              }
              className="w-64 px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text font-mono"
            />
          </SettingRow>
          <SettingRow label="启用更新遥测" desc="发送更新相关遥测数据">
            <input
              type="checkbox"
              data-testid="updates-telemetry"
              checked={config?.enableTelemetry ?? false}
              disabled={config === null}
              onChange={(event) =>
                void handleConfigPatch({ enableTelemetry: event.target.checked })
              }
            />
          </SettingRow>
          <SettingRow label="缓存保留天数">
            <input
              type="number"
              min={1}
              max={365}
              data-testid="updates-cache-retention"
              value={config?.cacheRetentionDays ?? ''}
              disabled={config === null}
              onChange={(event) =>
                void handleConfigPatch({ cacheRetentionDays: Number(event.target.value) })
              }
              className="w-24 px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text"
            />
          </SettingRow>
        </div>
      </AdvancedSection>

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
            {checkResult.errorMessage
              ? `${t('updates.checkFailed')}: ${checkResult.errorMessage}`
              : t('updates.checkFailed')}
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
