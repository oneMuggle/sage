/**
 * Context Isolation (Task 8): 上下文轮数限制设置组件。
 *
 * 绑定后端 preferences KV `context_turn_limit`：
 * - null / 空 → 不限（发送全部历史）
 * - 正整数 N → 只发送最近 N 轮（1 轮 = 1 次用户输入 + 1 次助手回复）
 *
 * UI：下拉选择器，选项 null/3/5/8/10/15/20。
 * 放置位置：GeneralTab → "对话" section。
 */
import { useEffect, useState } from 'react';

import { settingsClient } from '../../shared/api/settingsClient';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';

import { SettingRow } from './components';

const OPTIONS: { key: TranslationKey; value: number | null }[] = [
  { key: 'settings.context.unlimited', value: null },
  { key: 'settings.context.turns_3', value: 3 },
  { key: 'settings.context.turns_5', value: 5 },
  { key: 'settings.context.turns_8', value: 8 },
  { key: 'settings.context.turns_10', value: 10 },
  { key: 'settings.context.turns_15', value: 15 },
  { key: 'settings.context.turns_20', value: 20 },
];

export function ContextTurnLimitSelect(): JSX.Element {
  const { t } = useI18n();
  const [val, setVal] = useState<number | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let mounted = true;
    settingsClient
      .getContextTurnLimit()
      .then((v) => {
        if (mounted) setVal(v);
      })
      .finally(() => {
        if (mounted) setLoaded(true);
      });
    return () => {
      mounted = false;
    };
  }, []);

  const handleChange = (raw: string): void => {
    const next = raw === 'null' ? null : Number(raw);
    setVal(next);
    void settingsClient.setContextTurnLimit(next);
  };

  return (
    <SettingRow
      anchor="context_turn_limit"
      label={t('settings.context.turn_limit.label')}
      desc={t('settings.context.turn_limit.desc')}
    >
      <select
        data-testid="settings-context-turn-limit-select"
        aria-label={t('settings.context.turn_limit.label')}
        disabled={!loaded}
        value={val === null ? 'null' : String(val)}
        onChange={(e) => handleChange(e.target.value)}
        className="px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
      >
        {OPTIONS.map((o) => (
          <option key={String(o.value)} value={String(o.value)}>
            {t(o.key)}
          </option>
        ))}
      </select>
    </SettingRow>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditContextTurnLimitSelectGovernance(
  state: {
    selectedTurnLimit?: number;
    minTurnLimit?: number;
    maxTurnLimit?: number;
  } = {},
): {
  module: 'src/pages/settings/ContextTurnLimitSelect.tsx';
  phase: 'P142';
  selectedTurnLimit: number;
  minTurnLimit: number;
  maxTurnLimit: number;
  healthy: boolean;
} {
  const minTurnLimit =
    typeof state.minTurnLimit === 'number' && Number.isFinite(state.minTurnLimit)
      ? Math.max(0, Math.trunc(state.minTurnLimit))
      : 0;
  const maxTurnLimit =
    typeof state.maxTurnLimit === 'number' && Number.isFinite(state.maxTurnLimit)
      ? Math.max(minTurnLimit, Math.trunc(state.maxTurnLimit))
      : 100;
  const rawSelected =
    typeof state.selectedTurnLimit === 'number' && Number.isFinite(state.selectedTurnLimit)
      ? Math.trunc(state.selectedTurnLimit)
      : 20;
  const selectedTurnLimit = Math.min(maxTurnLimit, Math.max(minTurnLimit, rawSelected));
  return {
    module: 'src/pages/settings/ContextTurnLimitSelect.tsx',
    phase: 'P142',
    selectedTurnLimit,
    minTurnLimit,
    maxTurnLimit,
    healthy: selectedTurnLimit >= minTurnLimit && selectedTurnLimit <= maxTurnLimit,
  };
}
