/**
 * Settings 页面 - 通用设置 Tab
 */

import { useSettings } from '../../features/manage-settings/useSettings';

import { ThemeSelector } from './ThemeSelector';
import { SettingRow, Toggle } from './components';

export function GeneralTab({ resetSettings }: { resetSettings: () => void }) {
  const { settings, updateSettings } = useSettings();

  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">主题</h3>
        <ThemeSelector />
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">外观</h3>
        <SettingRow label="紧凑模式" desc="减少间距，在同一屏幕内显示更多内容">
          <Toggle
            value={settings.compactMode}
            onChange={(v) => updateSettings({ compactMode: v })}
          />
        </SettingRow>
        <SettingRow label="流式输出" desc="逐字显示 AI 回复，而非等待全部生成完成">
          <Toggle value={settings.streaming} onChange={(v) => updateSettings({ streaming: v })} />
        </SettingRow>
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">对话</h3>
        <SettingRow label="自动记忆提取" desc="对话中自动识别并保存关键信息到记忆库">
          <Toggle value={settings.autoMemory} onChange={(v) => updateSettings({ autoMemory: v })} />
        </SettingRow>
        <SettingRow label="确认后再删除记忆" desc="删除记忆前弹出确认对话框">
          <Toggle
            value={settings.confirmDelete}
            onChange={(v) => updateSettings({ confirmDelete: v })}
          />
        </SettingRow>
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">数据</h3>
        <button
          onClick={resetSettings}
          className="px-3 py-1.5 text-xs border border-border rounded-radius-sm text-text hover:bg-bg-muted transition-colors"
        >
          恢复默认设置
        </button>
      </section>
    </div>
  );
}
