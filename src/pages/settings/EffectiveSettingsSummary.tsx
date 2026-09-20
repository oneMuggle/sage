import { useEffect, useState } from 'react';

import { useSettings } from '../../features/manage-settings/useSettings';
import { settingsClient } from '../../shared/api/settingsClient';

export function EffectiveSettingsSummary(): JSX.Element {
  const { settings } = useSettings();
  const [networkMode, setNetworkMode] = useState('online');
  const [permissionMode, setPermissionMode] = useState('workspace_write');

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      const [networkRaw, permission] = await Promise.all([
        settingsClient.getPreference('network_policy'),
        settingsClient.getPreference('permission_mode'),
      ]);
      if (!mounted) return;
      if (permission) setPermissionMode(permission);
      if (networkRaw) {
        try {
          const parsed = JSON.parse(networkRaw) as { mode?: string };
          setNetworkMode(parsed.mode ?? 'online');
        } catch {
          setNetworkMode('online');
        }
      }
    };
    void load();
    const onChanged = (event: Event) => {
      const key = (event as CustomEvent<{ key?: string }>).detail?.key;
      if (key === 'network_policy' || key === 'permission_mode') void load();
    };
    window.addEventListener('sage:setting-changed', onChanged);
    return () => {
      mounted = false;
      window.removeEventListener('sage:setting-changed', onChanged);
    };
  }, []);

  const selectedChatModel = settings.modelSelections.chatModel.modelId ?? '未选择';
  const context = settings.autoContext ? '自动' : `${settings.maxContext} tokens`;

  return (
    <section
      data-testid="effective-settings-summary"
      className="mb-6 border border-border rounded-radius-sm bg-surface px-4 py-3"
    >
      <h3 className="text-sm font-semibold text-text mb-2">当前有效配置</h3>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-muted md:grid-cols-5">
        <span>模型：{selectedChatModel}</span>
        <span>上下文：{context}</span>
        <span>网络：{networkMode}</span>
        <span>权限：{permissionMode}</span>
        <span>流式：{settings.streaming ? '开启' : '关闭'}</span>
      </div>
    </section>
  );
}
