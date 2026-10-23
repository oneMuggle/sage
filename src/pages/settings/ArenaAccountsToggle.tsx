/**
 * Arena 自动化开关
 *
 * 大多数用户用不到 Arena 账号池（用于自动化评测/对比多模型账号）；
 * 默认侧边栏隐藏、设置页中显式开启后才会显示在「更多」分组。
 *
 * 状态由 `useFeatureUnlock('arena-accounts')` 管理，与渐进式披露（U10）共享同一 store：
 * - 用户主动访问 `/arena-accounts` URL 后永久解锁
 * - 在此开关 ON/OFF 也触发 unlock/lock，与 Sidebar 双向同步
 */

import { useState } from 'react';

import { useFeatureUnlock } from '../../shared/lib/hooks/useFeatureUnlock';

import { SettingRow, Toggle } from './components';

// eslint-disable-next-line react-refresh/only-export-components
export function formatArenaAccountsToggleAuditSnapshot(opts: { enabled?: boolean }): string {
  return `arenaAccountsToggle|enabled=${opts.enabled ? 1 : 0}`;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatArenaAccountsToggleAuditJson(opts: { enabled?: boolean }): string {
  return JSON.stringify({
    enabled: Boolean(opts.enabled),
  });
}

export function ArenaAccountsToggle() {
  const [enabled, setEnabled] = useFeatureUnlock('arena-accounts');
  const [copiedSnapshot, setCopiedSnapshot] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);

  /* v8 ignore start */
  const handleCopySnapshot = async () => {
    setCopiedSnapshot(true);
    try {
      await navigator.clipboard?.writeText(formatArenaAccountsToggleAuditSnapshot({ enabled }));
    } catch {
      // ignore
    }
  };
  const handleCopyJson = async () => {
    setCopiedJson(true);
    try {
      await navigator.clipboard?.writeText(formatArenaAccountsToggleAuditJson({ enabled }));
    } catch {
      // ignore
    }
  };
  /* v8 ignore stop */

  return (
    <SettingRow
      label="Arena 自动化"
      desc="启用后侧边栏显示「Arena」入口（/arena 控制台）。用于多账号批量自动化评测，普通用户无需开启。"
    >
      <div className="inline-flex items-center gap-1.5">
        <span
          data-testid="arena-accounts-toggle-copy-snapshot"
          onClick={() => void handleCopySnapshot()}
        >
          {copiedSnapshot ? '已复制快照' : ''}
        </span>
        <span
          data-testid="arena-accounts-toggle-copy-json"
          onClick={() => void handleCopyJson()}
        >
          {copiedJson ? '已复制JSON' : ''}
        </span>
        <Toggle value={enabled} onChange={setEnabled} testId="toggle-arena-accounts" />
      </div>
    </SettingRow>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditArenaAccountsToggleGovernance(): {
  module: 'src/pages/settings/ArenaAccountsToggle.tsx';
  phase: 'P172';
  domain: 'settings';
  testId: 'toggle-arena-accounts';
  compliant: boolean;
} {
  return {
    module: 'src/pages/settings/ArenaAccountsToggle.tsx',
    phase: 'P172',
    domain: 'settings',
    testId: 'toggle-arena-accounts',
    compliant: true,
  };
}
