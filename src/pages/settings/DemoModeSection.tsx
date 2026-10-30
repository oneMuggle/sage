/**
 * 演示模式开关（从 GeneralTab 迁出，2026-10-28 设置页整理 P0）。
 *
 * 用户开启后，renderer 立即通过 IPC 写 `<userData>/sage-demo-mode.json`；
 * 下次启动 main 进程读取该文件决定是否跳过 Python 后端 spawn。当前会话不会
 * 立即生效，需重启应用。「跳过后端」在下次启动 Electron 时生效；页面数据
 * 切换即时生效。
 */

import { useState } from 'react';

import { useSettings } from '../../features/manage-settings/useSettings';
import { getDemoModeOverride, setDemoModeOverride } from '../../shared/api/demoRuntime';
import { useI18n } from '../../shared/lib/i18n';

import { SettingRow, Toggle } from './components';

export function DemoModeSection() {
  const { t } = useI18n();
  const { settings, updateSettings } = useSettings();
  const [persisting, setPersisting] = useState(false);
  const [persistError, setPersistError] = useState<string | null>(null);

  const handleToggle = async (next: boolean): Promise<void> => {
    setPersistError(null);
    setPersisting(true);
    const wasDemoProcess = getDemoModeOverride() === true;
    try {
      await updateSettings({ demoMode: next });
      const result = await window.electronAPI?.setDemoMode?.(next);
      if (result && result.ok === false) {
        throw new Error(t('settings.demo.save_failed'));
      }
      if (!wasDemoProcess) setDemoModeOverride(next);
    } catch (err) {
      setPersistError(err instanceof Error ? err.message : t('settings.demo.save_failed'));
      try {
        await updateSettings({ demoMode: !next });
        setDemoModeOverride(wasDemoProcess);
      } catch {
        // Keep the visible error when rollback persistence also fails.
      }
    } finally {
      setPersisting(false);
    }
  };

  return (
    <div data-testid="demo-mode-section">
      <SettingRow anchor="demoMode" label={t('settings.demo.label')} desc={t('settings.demo.desc')}>
        <Toggle
          value={settings.demoMode}
          disabled={persisting}
          onChange={(v) => {
            void handleToggle(v);
          }}
        />
      </SettingRow>
      {persisting && <div className="text-xs text-muted mt-1">{t('settings.demo.saving')}</div>}
      {persistError && (
        <div className="text-xs text-error mt-1" data-testid="demo-mode-error">
          {t('settings.demo.save_failed_with_error').replace('{error}', persistError)}
        </div>
      )}
      <p className="text-ui-xs text-muted mt-2 leading-relaxed">{t('settings.demo.note')}</p>
    </div>
  );
}
