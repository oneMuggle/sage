import { clsx } from 'clsx';

import { DEFAULT_FAILOVER_SETTINGS, type FailoverSettings } from '../../../entities/setting/types';
import { useI18n } from '../../../shared/lib/i18n';
import type { EndpointsTabProps } from '../components';

const MIN_PROBE_INTERVAL_MS = 30_000;
const MIN_COOLDOWN_MS = 5_000;

/**
 * 2026-11-26: 端点故障转移设置块。
 *
 * 总开关默认关闭；开启后当前端点失败会自动切到下一个 priority 端点。
 * 数值输入在失焦/输入时即时落盘（与设置页其余字段一致），越界值夹紧到
 * 后端校验范围，避免保存 400。
 */
export function EndpointFailoverSection({ settings, updateSettings }: EndpointsTabProps) {
  const { t } = useI18n();
  const value: FailoverSettings = settings.failover ?? DEFAULT_FAILOVER_SETTINGS;
  const patch = (partial: Partial<FailoverSettings>) =>
    updateSettings({ failover: { ...value, ...partial } });

  const inputCls =
    'w-20 px-2 py-1 border border-border rounded-radius-sm text-xs font-mono bg-surface text-text disabled:opacity-50';

  return (
    <div
      data-testid="endpoint-failover-section"
      className="p-4 border rounded-radius-sm bg-surface space-y-3"
    >
      <label className="flex items-center gap-2 text-sm font-medium text-text">
        <input
          type="checkbox"
          data-testid="failover-enabled"
          checked={value.enabled}
          onChange={(e) => patch({ enabled: e.target.checked })}
        />
        {t('settings.endpoints.failover.section')}
      </label>
      <div className="flex flex-wrap items-center gap-4 text-xs text-muted">
        <label className="flex items-center gap-1">
          {t('settings.endpoints.failover.probe_interval')}
          <input
            type="number"
            min={0.5}
            step={0.5}
            disabled={!value.enabled}
            data-testid="failover-probe-interval"
            value={value.probeIntervalMs / 60_000}
            onChange={(e) => {
              const minutes = Number(e.target.value);
              patch({
                probeIntervalMs: Math.max(
                  MIN_PROBE_INTERVAL_MS,
                  Math.round(minutes * 60_000) || MIN_PROBE_INTERVAL_MS,
                ),
              });
            }}
            className={inputCls}
          />
        </label>
        <label className="flex items-center gap-1">
          {t('settings.endpoints.failover.cooldown')}
          <input
            type="number"
            min={5}
            step={5}
            disabled={!value.enabled}
            data-testid="failover-cooldown"
            value={value.cooldownMs / 1000}
            onChange={(e) => {
              const seconds = Number(e.target.value);
              patch({
                cooldownMs: Math.max(
                  MIN_COOLDOWN_MS,
                  Math.round(seconds * 1000) || MIN_COOLDOWN_MS,
                ),
              });
            }}
            className={inputCls}
          />
        </label>
        <label className="flex items-center gap-1">
          {t('settings.endpoints.failover.threshold')}
          <input
            type="number"
            min={1}
            max={10}
            disabled={!value.enabled}
            data-testid="failover-threshold"
            value={value.consecutiveFailThreshold}
            onChange={(e) =>
              patch({
                consecutiveFailThreshold: Math.max(
                  1,
                  Math.min(10, Math.round(Number(e.target.value)) || 1),
                ),
              })
            }
            className={clsx(inputCls, 'w-14')}
          />
        </label>
      </div>
      <p className="text-ui-xs text-muted/70">{t('settings.endpoints.failover.hint')}</p>
    </div>
  );
}
