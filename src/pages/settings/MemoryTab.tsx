/**
 * Settings 页面 - 记忆管理 Tab
 */

import type { EndpointsTabProps } from './components';
import { SettingRow, Toggle } from './components';

export function MemoryTab({ settings, updateSettings }: EndpointsTabProps) {
  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">记忆管理</h3>
        <SettingRow label="本地存储路径" desc="记忆数据在本地文件系统中的存储位置">
          <input
            type="text"
            value="%APPDATA%\\Sage\\memory.db"
            readOnly
            className="px-2 py-1 border border-border rounded-radius-sm text-xs font-mono bg-bg-muted text-text-secondary"
          />
        </SettingRow>
        <SettingRow label="同步到内部服务器" desc="联网时将记忆增量同步到企业内部服务器">
          <Toggle value={settings.autoMemory} onChange={(v) => updateSettings({ autoMemory: v })} />
        </SettingRow>
      </section>
    </div>
  );
}
