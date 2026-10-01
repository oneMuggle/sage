/** Safety-sensitive preferences use explicit backend acknowledgements. */
import { PreferenceSaveStatus } from '../../features/manage-settings/PreferenceSaveStatus';
import { useConfirmedPreference } from '../../features/manage-settings/useConfirmedPreference';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';
import { GatewayCard } from '../../widgets/settings/GatewayCard';
import { HooksCard } from '../../widgets/settings/HooksCard';

import { SettingRow } from './components';

export const PERMISSION_MODES = ['read_only', 'workspace_write', 'prompt', 'full_access'] as const;
export type PermissionMode = (typeof PERMISSION_MODES)[number];

function PermissionModeSelector() {
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
        label={t('settings.permission.mode')}
        desc={t(`settings.permission.mode.${preference.value}.desc` as TranslationKey)}
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
              {t(`settings.permission.mode.${mode}` as TranslationKey)}
            </option>
          ))}
        </select>
      </SettingRow>
      <PreferenceSaveStatus {...preference} />
    </>
  );
}

function FallbackModelInput() {
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
        label="降级模型 (fallback)"
        desc="主模型重试耗尽后切换；留空不降级。只有保存确认后生效。"
      >
        <input
          type="text"
          data-testid="settings-fallback-model-input"
          disabled={!preference.loaded}
          value={preference.value}
          onChange={(event) => preference.update(event.target.value)}
          placeholder="例如 gpt-4o-mini"
          className="w-44 text-ui-sm border border-border rounded px-2 py-1 bg-surface text-text font-mono"
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
      </section>
      <section>
        <h3 className="text-ui-base font-semibold text-text mb-3">模型降级</h3>
        <FallbackModelInput />
      </section>
      <section>
        <h3 className="text-ui-base font-semibold text-text mb-3">钩子 (Hooks)</h3>
        <HooksCard />
      </section>
      <section>
        <h3 className="text-ui-base font-semibold text-text mb-3">诊断</h3>
        <GatewayCard platform="telegram" />
        <GatewayCard platform="discord" />
        <GatewayCard platform="slack" />
      </section>
    </div>
  );
}
