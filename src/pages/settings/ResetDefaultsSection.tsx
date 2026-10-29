/**
 * 「恢复默认设置」（从 GeneralTab 迁出，2026-10-28 设置页整理 P0）。
 *
 * app_settings blob + preferences KV 行为项全量回默认。破坏性操作走两步确认
 * （项目内惯例：面板内确认，不用 window.confirm）。实现见
 * storage.resetSettings / resetPreferencesToDefaults 的排除清单。
 */

import { useState } from 'react';

import { useSettings } from '../../features/manage-settings/useSettings';

import { SettingRow } from './components';

export function ResetDefaultsSection() {
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
          label="恢复默认设置"
          desc="将外观 / 模型上下文 / 编排 / 权限模式 / 网络 / 钩子 / 花费限额等全部设置项恢复默认"
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
            恢复默认设置
          </button>
        </SettingRow>
        {message === 'done' && (
          <div data-testid="settings-reset-done" className="text-xs text-success mt-1">
            已恢复默认设置
          </div>
        )}
        {message === 'error' && (
          <div data-testid="settings-reset-error" className="text-xs text-error mt-1">
            恢复失败，请重试
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
      <div className="text-sm text-text">确认恢复所有设置为默认值？</div>
      <p className="text-xs text-muted leading-relaxed">
        端点与模型选择、界面外观、权限模式、网络 / 代理 / 搜索、钩子、花费限额都会回到默认。
        已保存的站点登录凭据、工具审批规则与当前会话不受影响。部分面板需切换标签页后刷新。
      </p>
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
          {busy ? '恢复中…' : '确认恢复'}
        </button>
        <button
          type="button"
          data-testid="settings-reset-confirm-no"
          disabled={busy}
          onClick={() => setConfirming(false)}
          className="px-3 py-1 text-xs border border-border rounded-radius-sm text-text hover:bg-bg-muted"
        >
          取消
        </button>
      </div>
    </div>
  );
}
