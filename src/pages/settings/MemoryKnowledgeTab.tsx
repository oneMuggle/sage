/** Keep backend confirmation separate from memory/safety input drafts. */
import { useState } from 'react';

import { PreferenceSaveStatus } from '../../features/manage-settings/PreferenceSaveStatus';
import { useConfirmedPreference } from '../../features/manage-settings/useConfirmedPreference';
import { useSettings } from '../../features/manage-settings/useSettings';
import { useI18n } from '../../shared/lib/i18n';
import { productMessages } from '../../shared/lib/productMessages';

import { ContextTurnLimitSelect } from './ContextTurnLimitSelect';
import { SettingRow, Toggle } from './components';

function AutoCheckpointCard() {
  const preference = useConfirmedPreference({
    key: 'auto_checkpoint',
    initial: true,
    parse: (value) => value !== '0',
    serialize: (value: boolean) => (value ? '1' : '0'),
  });
  return (
    <section data-testid="auto-checkpoint-section">
      <h3 className="text-ui-base font-semibold text-text mb-3">安全网</h3>
      <SettingRow label="发送前自动快照" desc="保存确认后生效；为工作区创建可回滚的检查点。">
        {preference.loaded ? (
          <Toggle
            value={preference.value}
            onChange={(value) => {
              if (preference.status !== 'saving') preference.update(value);
            }}
          />
        ) : (
          <span className="text-ui-sm text-muted">…</span>
        )}
      </SettingRow>
      <PreferenceSaveStatus {...preference} />
    </section>
  );
}

function SpendLimitInput() {
  const preference = useConfirmedPreference({
    key: 'spend_limit_usd',
    initial: '',
    category: 'general',
    optimistic: true,
    parse: (value) => value ?? '',
    serialize: (value: string) => (value === '' ? '0' : value),
  });
  return (
    <>
      <SettingRow
        label="每日花费限额 (USD)"
        desc="按估算成本拦截请求；0 或留空不限，保存确认后生效。"
      >
        <input
          type="number"
          step="0.5"
          min="0"
          disabled={!preference.loaded}
          data-testid="settings-spend-limit-input"
          value={preference.value}
          onChange={(event) => {
            const value = event.target.value;
            if (value === '' || (Number.isFinite(Number(value)) && Number(value) >= 0))
              preference.update(value);
          }}
          placeholder="0"
          className="w-24 text-ui-sm border border-border rounded px-2 py-1 bg-surface text-text"
        />
      </SettingRow>
      <PreferenceSaveStatus {...preference} />
    </>
  );
}

export function MemoryKnowledgeTab() {
  const { settings, updateSettingsStrict } = useSettings();
  const { locale } = useI18n();
  const [saving, setSaving] = useState(false);
  const [unconfirmed, setUnconfirmed] = useState(false);
  const saveMemory = async (partial: Parameters<typeof updateSettingsStrict>[0]) => {
    if (saving) return;
    setSaving(true);
    setUnconfirmed(false);
    try {
      await updateSettingsStrict(partial);
    } catch {
      setUnconfirmed(true);
    } finally {
      setSaving(false);
    }
  };
  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-ui-base font-semibold text-text mb-3">记忆管理</h3>
        <SettingRow label="自动记忆提取" desc="只在保存确认后改变长期记忆提取策略。">
          <Toggle
            value={settings.autoMemory}
            onChange={(value) => {
              void saveMemory({ autoMemory: value });
            }}
          />
        </SettingRow>
        <SettingRow label="确认后再删除记忆" desc="删除记忆前弹出确认对话框。">
          <Toggle
            value={settings.confirmDelete}
            onChange={(value) => {
              void saveMemory({ confirmDelete: value });
            }}
          />
        </SettingRow>
        {saving && (
          <p role="status" className="text-ui-sm text-muted">
            {productMessages(locale).saving}
          </p>
        )}
        {unconfirmed && (
          <p role="alert" className="text-ui-sm text-error">
            {productMessages(locale).saveFailed}
          </p>
        )}
        <ContextTurnLimitSelect />
      </section>
      <AutoCheckpointCard />
      <section>
        <h3 className="text-ui-base font-semibold text-text mb-3">用量控制</h3>
        <SpendLimitInput />
        <p className="text-ui-sm text-muted mt-2">详细用量可在主界面查看。</p>
      </section>
    </div>
  );
}
