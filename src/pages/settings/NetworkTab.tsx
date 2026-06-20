/**
 * Settings 页面 - 网络配置 Tab
 */

import type { EndpointsTabProps } from './components';
import { SettingRow } from './components';

export function NetworkTab({ settings, updateSettings }: EndpointsTabProps) {
  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">网络配置</h3>
        <SettingRow label="代理模式" desc="企业内部网络通常需要配置代理">
          <select
            value={settings.proxyMode}
            onChange={(e) =>
              updateSettings({ proxyMode: e.target.value as 'system' | 'custom' | 'direct' })
            }
            className="px-2 py-1 border border-border rounded-radius-sm text-xs font-mono bg-surface text-text"
          >
            <option value="system">系统代理</option>
            <option value="custom">自定义代理</option>
            <option value="direct">直连</option>
          </select>
        </SettingRow>
        <SettingRow label="代理地址" desc="HTTP 代理服务器地址">
          <input
            type="text"
            value={settings.proxyUrl}
            onChange={(e) => updateSettings({ proxyUrl: e.target.value })}
            className="px-2 py-1 border border-border rounded-radius-sm text-xs font-mono bg-surface text-text"
          />
        </SettingRow>
        <SettingRow label="TLS 版本" desc="Windows 7 最高支持 TLS 1.2">
          <select
            value={settings.tlsVersion}
            onChange={(e) => updateSettings({ tlsVersion: e.target.value as '1.2' | '1.3' })}
            className="px-2 py-1 border border-border rounded-radius-sm text-xs font-mono bg-surface text-text"
          >
            <option value="1.2">TLS 1.2</option>
            <option value="1.3">TLS 1.3</option>
          </select>
        </SettingRow>
      </section>
    </div>
  );
}
