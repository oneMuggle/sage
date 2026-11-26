import { clsx } from 'clsx';
import { useState } from 'react';

import {
  TOKEN_UNITS,
  TOKEN_UNIT_MULTIPLIERS,
  deriveTokenInput,
  type TokenUnit,
} from '../../../entities/setting/contextPresets';
import type { EndpointQuota } from '../../../entities/setting/types';
import type { ProbeResult } from '../../../features/manage-endpoints/api';
import { useI18n, type TranslationKey } from '../../../shared/lib/i18n';

/**
 * 2026-11-26: 从 EndpointsTab 拆出的端点编辑器组件。
 *
 * 拆出原因：EndpointsTab 接近 800 行守卫上限，故障转移 UI（优先级排序 +
 * 健康状态）需要新增行数；这两个纯展示/编辑组件无状态耦合，适合独立放。
 */

/**
 * Render probe status and metadata below the endpoint info.
 *
 * Displays:
 * - status badge (success / unsupported / error)
 * - metadata (native context, architecture, quantization) when available
 * - error message when probe failed
 */
export function ProbeStatusDisplay({ result }: { result: ProbeResult }) {
  const { t } = useI18n();
  const statusConfig: Record<
    ProbeResult['status'],
    { labelKey: TranslationKey; color: string; bg: string }
  > = {
    success: {
      labelKey: 'settings.endpoints.probe_status.success',
      color: 'text-green-600',
      bg: 'bg-green-50',
    },
    unsupported: {
      labelKey: 'settings.endpoints.probe_status.unsupported',
      color: 'text-yellow-600',
      bg: 'bg-yellow-50',
    },
    error: {
      labelKey: 'settings.endpoints.probe_status.error',
      color: 'text-red-600',
      bg: 'bg-red-50',
    },
  };

  const config = statusConfig[result.status];

  return (
    <div className={clsx('mt-2 px-2 py-1.5 rounded-radius-sm text-ui-xs', config.bg)}>
      <span className={clsx('font-medium', config.color)}>{t(config.labelKey)}</span>
      {result.adapter !== 'unknown' && (
        <span className="text-muted ml-2">
          {t('settings.endpoints.result.adapter')}: {result.adapter}
        </span>
      )}
      {result.status === 'success' && result.data && (
        <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-1 text-muted">
          {result.data.native != null && (
            <span>
              {t('settings.endpoints.result.context_native')}: {result.data.native.toLocaleString()}
            </span>
          )}
          {result.data.service != null && (
            <span>
              {t('settings.endpoints.result.context_service')}:{' '}
              {result.data.service.toLocaleString()}
            </span>
          )}
          {result.data.architecture && (
            <span>
              {t('settings.endpoints.result.architecture')}: {result.data.architecture}
            </span>
          )}
          {result.data.quantization && (
            <span>
              {t('settings.endpoints.result.quantization')}: {result.data.quantization}
            </span>
          )}
        </div>
      )}
      {result.status === 'error' && result.error && (
        <div className="mt-0.5 text-red-500">{result.error}</div>
      )}
      {result.status === 'unsupported' && result.error && (
        <div className="mt-0.5 text-yellow-600">{result.error}</div>
      )}
    </div>
  );
}

/**
 * P0-B (2026-09-18): 端点限额编辑区 — 日 token 限额 (数值 + tokens/K/M 单位)
 * 与月预算 (USD)。留空 = 不限额; 仅驱动用量面板的进度与预警, 不做请求侧熔断。
 */
export function QuotaEditor({
  quota,
  onChange,
}: {
  quota: EndpointQuota;
  onChange: (q: EndpointQuota) => void;
}) {
  const { t } = useI18n();
  const derive = (n: number | undefined) => (n ? deriveTokenInput(n) : null);
  const [tokensText, setTokensText] = useState(() => derive(quota.dailyTokens)?.text ?? '');
  const [tokenUnit, setTokenUnit] = useState<TokenUnit>(
    () => derive(quota.dailyTokens)?.unit ?? 'K',
  );
  const [budgetText, setBudgetText] = useState(() =>
    quota.monthlyBudgetUsd ? String(quota.monthlyBudgetUsd) : '',
  );

  const commit = (next: { text: string; unit: TokenUnit; budget: string }) => {
    const tokens = Number(next.text) * TOKEN_UNIT_MULTIPLIERS[next.unit];
    const budget = Number(next.budget);
    onChange({
      ...(Number.isFinite(tokens) && tokens > 0 ? { dailyTokens: Math.round(tokens) } : {}),
      ...(Number.isFinite(budget) && budget > 0 ? { monthlyBudgetUsd: budget } : {}),
    });
  };

  const inputCls =
    'px-2 py-1 border border-border rounded-radius-sm text-xs font-mono bg-surface text-text';

  return (
    <div
      className="pt-3 border-t border-dashed border-border space-y-2"
      data-testid="endpoint-quota-editor"
    >
      <label className="text-xs text-muted block">{t('settings.endpoints.quota.section')}</label>
      <div className="flex items-center gap-2">
        <span className="text-xs text-muted w-20">
          {t('settings.endpoints.quota.daily_tokens')}
        </span>
        <input
          type="number"
          min={0}
          aria-label={t('settings.endpoints.quota.aria_daily_tokens')}
          value={tokensText}
          placeholder={t('settings.endpoints.quota.unlimited')}
          onChange={(e) => {
            setTokensText(e.target.value);
            commit({ text: e.target.value, unit: tokenUnit, budget: budgetText });
          }}
          className={`${inputCls} w-24`}
        />
        <select
          aria-label={t('settings.endpoints.quota.aria_daily_unit')}
          value={tokenUnit}
          onChange={(e) => {
            const unit = e.target.value as TokenUnit;
            setTokenUnit(unit);
            commit({ text: tokensText, unit, budget: budgetText });
          }}
          className={inputCls}
        >
          {TOKEN_UNITS.map((u) => (
            <option key={u.value} value={u.value}>
              {u.label}
            </option>
          ))}
        </select>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-xs text-muted w-20">
          {t('settings.endpoints.quota.monthly_budget')}
        </span>
        <input
          type="number"
          min={0}
          step={0.5}
          aria-label={t('settings.endpoints.quota.aria_budget')}
          value={budgetText}
          placeholder={t('settings.endpoints.quota.unlimited')}
          onChange={(e) => {
            setBudgetText(e.target.value);
            commit({ text: tokensText, unit: tokenUnit, budget: e.target.value });
          }}
          className={`${inputCls} w-24`}
        />
      </div>
    </div>
  );
}
