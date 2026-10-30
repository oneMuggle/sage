/**
 * 「恢复默认设置」（从 GeneralTab 迁出，2026-10-28 设置页整理 P0）。
 *
 * app_settings blob + preferences KV 行为项全量回默认。破坏性操作走两步确认
 * （项目内惯例：面板内确认，不用 window.confirm）。实现见
 * storage.resetSettings / resetPreferencesToDefaults 的排除清单。
 */

import { useState } from 'react';

import { useSettings } from '../../features/manage-settings/useSettings';
import { useI18n } from '../../shared/lib/i18n';

import { SettingRow } from './components';

export function ResetDefaultsSection() {
  const { t } = useI18n();
  const { resetSettings } = useSettings();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<'done' | 'error' | null>(null);

  const handleConfirm = async (): Promise<void> => {
    setBusy(true);
    setMessage(null);
    try {
      await resetSettings();
      setMessage('done');
    } catch {
      setMessage('error');
    } finally {
      setBusy(false);
      setConfirming(false);
    }
  };

  if (!confirming) {
    return (
      <>
        <SettingRow
          anchor="reset_settings"
          label={t('settings.reset.label')}
          desc={t('settings.reset.desc')}
        >
          <button
            type="button"
            data-testid="settings-reset-button"
            onClick={() => {
              setMessage(null);
              setConfirming(true);
            }}
            className="px-3 py-1.5 text-xs border border-border rounded-radius-sm text-text hover:bg-bg-muted transition-colors"
          >
            {t('settings.reset.button')}
          </button>
        </SettingRow>
        {message === 'done' && (
          <div data-testid="settings-reset-done" className="text-xs text-success mt-1">
            {t('settings.reset.done')}
          </div>
        )}
        {message === 'error' && (
          <div data-testid="settings-reset-error" className="text-xs text-error mt-1">
            {t('settings.reset.error')}
          </div>
        )}
      </>
    );
  }

  return (
    <div
      data-testid="settings-reset-confirm"
      className="p-3 border border-border rounded-radius-sm bg-surface space-y-2"
    >
      <div className="text-sm text-text">{t('settings.reset.confirm_title')}</div>
      <p className="text-xs text-muted leading-relaxed">{t('settings.reset.confirm_desc')}</p>
      <div className="flex items-center gap-2">
        <button
          type="button"
          data-testid="settings-reset-confirm-yes"
          disabled={busy}
          onClick={() => {
            void handleConfirm();
          }}
          className="px-3 py-1 text-xs bg-error text-text-inverse rounded-radius-sm hover:opacity-90 disabled:opacity-50"
        >
          {busy ? t('settings.reset.resetting') : t('settings.reset.confirm')}
        </button>
        <button
          type="button"
          data-testid="settings-reset-confirm-no"
          disabled={busy}
          onClick={() => setConfirming(false)}
          className="px-3 py-1 text-xs border border-border rounded-radius-sm text-text hover:bg-bg-muted"
        >
          {t('settings.common.cancel')}
        </button>
      </div>
    </div>
  );
}
