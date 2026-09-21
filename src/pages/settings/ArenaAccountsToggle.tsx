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

import { useFeatureUnlock } from '../../shared/lib/hooks/useFeatureUnlock';

import { SettingRow, Toggle } from './components';

export function ArenaAccountsToggle() {
  const [enabled, setEnabled] = useFeatureUnlock('arena-accounts');

  return (
    <SettingRow
      label="Arena 自动化"
      desc="启用后侧边栏显示「Arena 账号」入口。用于多账号批量自动化评测，普通用户无需开启。"
    >
      <Toggle
        value={enabled}
        onChange={setEnabled}
        testId="toggle-arena-accounts"
      />
    </SettingRow>
  );
}
