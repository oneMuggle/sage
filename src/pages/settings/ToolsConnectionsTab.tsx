/**
 * Settings 页面 - 权限与工具 Tab
 *
 * 包含权限模式、Hooks、网关、降级模型等设置。
 * 从原 GeneralTab 拆分而来（2026-09-19 设置治理 Phase 2）。
 */

import { useEffect, useState } from 'react';

import { PreferenceSaveStatus } from '../../features/manage-settings/PreferenceSaveStatus';
import { useConfirmedPreference } from '../../features/manage-settings/useConfirmedPreference';
import { permissionApi } from '../../shared/api/permissionApi';
import { useI18n } from '../../shared/lib/i18n';
import { GatewaySection } from '../../widgets/settings/GatewaySection';
import { HooksCard } from '../../widgets/settings/HooksCard';

import { PermissionRulesManager } from './PermissionRulesManager';
import { SettingRow, Toggle } from './components';

export const PERMISSION_MODES = ['read_only', 'workspace_write', 'prompt', 'full_access'] as const;
export type PermissionMode = (typeof PERMISSION_MODES)[number];

export function PermissionModeSelector() {
  const { t } = useI18n();
  const preference = useConfirmedPreference<PermissionMode>({
    key: 'permission_mode',
    initial: 'workspace_write',
    category: 'permissions',
    parse: (value) => {
      if (value === null) return 'workspace_write';
      if (!(PERMISSION_MODES as readonly string[]).includes(value)) throw new Error('Invalid mode');
      return value as PermissionMode;
    },
    serialize: (value) => value,
  });
  return (
    <>
      <SettingRow
        anchor="permission_mode"
        label={t('settings.permission.mode')}
        desc={t(`settings.permission.mode.${preference.value}.desc`)}
      >
        <select
          data-testid="permission-mode-select"
          aria-label={t('settings.permission.mode')}
          value={preference.value}
          disabled={!preference.loaded || preference.status === 'saving'}
          onChange={(event) => preference.update(event.target.value as PermissionMode)}
          className="px-2 py-1 text-ui-sm border border-border rounded bg-surface text-text"
        >
          {PERMISSION_MODES.map((mode) => (
            <option key={mode} value={mode}>
              {t(`settings.permission.mode.${mode}`)}
            </option>
          ))}
        </select>
      </SettingRow>
      <PreferenceSaveStatus {...preference} />
      <p className="text-xs text-muted mt-2">{t('settings.permission.rules_hint')}</p>
      <TrustEscalationSection />
    </>
  );
}

/**
 * P2-5 渐进式授权。
 *
 * 连续 N 次手动批准某工具后，之后的常规调用自动放行 —— 对标 Claude Code /
 * Codex 的 progressive delegation。默认关闭：未经用户显式同意的自动放行
 * 是 PHILOSOPHY 明令禁止的黑盒决策。
 *
 * 两条如实告知（不夸大承诺）：
 * - 只对**常规操作**生效。破坏性/可疑命令、写工作区外、无法静态评估风险的
 *   工具（skill/repl）永远保留人工审批。
 * - 自动放行的决策会落审计台账（answered_by='trust'），事后可区分「你点的」
 *   与「系统放行的」。
 */
function TrustEscalationSection(): JSX.Element {
  const { t } = useI18n();
  const [enabled, setEnabled] = useState(false);
  const [threshold, setThreshold] = useState(3);
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [consecutive, setConsecutive] = useState<Record<string, number>>({});

  useEffect(() => {
    let mounted = true;
    permissionApi
      .getTrustPolicy()
      .then((state) => {
        if (!mounted) return;
        setEnabled(state.enabled);
        setThreshold(state.threshold);
        setConsecutive(state.consecutive);
      })
      .catch((e: unknown) => {
        if (mounted)
          setError(e instanceof Error ? e.message : t('settings.tools.trust.load_failed'));
      })
      .finally(() => {
        if (mounted) setLoaded(true);
      });
    return () => {
      mounted = false;
    };
  }, [t]);

  const persist = (nextEnabled: boolean, nextThreshold: number) => {
    setSaving(true);
    setError(null);
    permissionApi
      .setTrustPolicy(nextEnabled, nextThreshold)
      .then((state) => {
        setEnabled(state.enabled);
        setThreshold(state.threshold);
        return permissionApi.getTrustPolicy();
      })
      .then((state) => setConsecutive(state.consecutive))
      .catch((e: unknown) => {
        // 写失败必须回滚 UI 状态 —— 开关显示「开」但后端没开是最坏的撒谎
        setError(e instanceof Error ? e.message : t('settings.tools.trust.save_failed'));
        permissionApi
          .getTrustPolicy()
          .then((state) => {
            setEnabled(state.enabled);
            setThreshold(state.threshold);
          })
          .catch(() => {
            /* 读取也失败时保持当前显示，由错误提示说明 */
          });
      })
      .finally(() => setSaving(false));
  };

  const trustEntries = Object.entries(consecutive).filter(([, n]) => n > 0);

  return (
    <div className="mt-4 border-t border-border pt-3" data-testid="trust-escalation-section">
      <SettingRow
        anchor="trust_escalation"
        label={t('settings.tools.trust.label')}
        desc={t('settings.tools.trust.desc').replace('{threshold}', String(threshold))}
      >
        <Toggle
          value={enabled}
          onChange={(v) => {
            setEnabled(v);
            persist(v, threshold);
          }}
          testId="trust-escalation-toggle"
        />
      </SettingRow>
      {enabled ? (
        <SettingRow
          label={t('settings.tools.trust.threshold_label')}
          desc={t('settings.tools.trust.threshold_desc')}
        >
          <input
            type="number"
            min={1}
            max={20}
            data-testid="trust-escalation-threshold"
            value={threshold}
            disabled={saving || !loaded}
            onChange={(e) => {
              const v = Math.max(1, Math.min(20, Number(e.target.value) || 1));
              setThreshold(v);
            }}
            onBlur={() => persist(enabled, threshold)}
            className="w-20 px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
          />
        </SettingRow>
      ) : null}
      {error ? (
        <p role="alert" className="text-xs text-error mt-1">
          {error}
        </p>
      ) : null}
      {enabled && trustEntries.length > 0 ? (
        <div className="mt-2" data-testid="trust-escalation-trust-list">
          <p className="text-xs text-muted">{t('settings.tools.trust.list_heading')}</p>
          <ul className="mt-1 flex flex-wrap gap-1.5">
            {trustEntries.map(([key, n]) => {
              const tool = key.split('|').slice(1).join('|') || key;
              return (
                <li
                  key={key}
                  className="rounded border border-border px-1.5 py-0.5 text-ui-2xs text-text-secondary"
                >
                  {tool} · {n}
                  {n >= threshold ? ` · ${t('settings.tools.trust.threshold_reached')}` : ''}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

/**
 * D-1 (round5 批次 D): 主模型重试耗尽后的降级模型——preferences KV
 * fallback_model。留空 = 不降级。producer 在构建 llm_config 时读取。
 *
 * 批次 A2：改用显式回执写入（useConfirmedPreference）——保存失败/超时不再被
 * 当成成功，界面显示“保存中 / 已确认 / 未确认”。
 */
function FallbackModelInput(): JSX.Element {
  const { t } = useI18n();
  const preference = useConfirmedPreference({
    key: 'fallback_model',
    initial: '',
    optimistic: true,
    parse: (value) => value ?? '',
    serialize: (value: string) => value.trim(),
  });
  return (
    <>
      <SettingRow
        anchor="fallback_model"
        label={t('settings.tools.fallback.label')}
        desc={t('settings.tools.fallback.desc')}
      >
        <input
          type="text"
          data-testid="settings-fallback-model-input"
          disabled={!preference.loaded}
          value={preference.value}
          onChange={(event) => preference.update(event.target.value)}
          placeholder={t('settings.tools.fallback.placeholder')}
          className="w-44 text-xs border border-border rounded-radius-sm px-2 py-1 bg-surface text-text font-mono"
        />
      </SettingRow>
      <PreferenceSaveStatus {...preference} />
    </>
  );
}

export function ToolsConnectionsTab() {
  const { t } = useI18n();
  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-ui-base font-semibold text-text mb-3">
          {t('settings.section.permission')}
        </h3>
        <PermissionModeSelector />
        <PermissionRulesManager />
      </section>
      <section>
        <h3 className="text-ui-base font-semibold text-text mb-3">
          {t('settings.tools.section.fallback_model')}
        </h3>
        <FallbackModelInput />
      </section>
      <section>
        <h3 className="text-ui-base font-semibold text-text mb-3">
          {t('settings.tools.section.hooks')}
        </h3>
        <HooksCard />
      </section>
      <GatewaySection />
    </div>
  );
}
