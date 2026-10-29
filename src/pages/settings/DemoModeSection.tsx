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

import { SettingRow, Toggle } from './components';

export function DemoModeSection() {
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
        throw new Error('无法保存演示模式设置');
      }
      if (!wasDemoProcess) setDemoModeOverride(next);
    } catch (err) {
      setPersistError(err instanceof Error ? err.message : '无法保存演示模式设置');
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
      <SettingRow
        anchor="demoMode"
        label="演示模式"
        desc="开启后下次启动跳过后端，各功能页面展示内置示例数据"
      >
        <Toggle
          value={settings.demoMode}
          disabled={persisting}
          onChange={(v) => {
            void handleToggle(v);
          }}
        />
      </SettingRow>
      {persisting && <div className="text-xs text-muted mt-1">正在保存…</div>}
      {persistError && (
        <div className="text-xs text-error mt-1" data-testid="demo-mode-error">
          保存失败：{persistError}
        </div>
      )}
      <p className="text-ui-xs text-muted mt-2 leading-relaxed">
        注意：「跳过后端」在下次启动 Electron 时生效；页面数据切换即时生效。
      </p>
    </div>
  );
}
