import type { SettingsSearchEntry, SettingsTabKey } from './settingsSearchIndex';

const GROUPS = [
  { id: 'basic', zh: '基础与外观', en: 'Basics and appearance', keys: ['basic'] },
  { id: 'models', zh: '模型与服务', en: 'Models and services', keys: ['endpoints', 'models'] },
  {
    id: 'knowledge',
    zh: '记忆与资料',
    en: 'Memory and sources',
    keys: ['memory-knowledge', 'memory', 'zotero'],
  },
  {
    id: 'tools',
    zh: '工具与安全',
    en: 'Tools and safety',
    keys: ['tools-connections', 'mcp', 'orchestration', 'evolution'],
  },
  {
    id: 'network',
    zh: '网络与远程',
    en: 'Network and remote',
    keys: ['network', 'remote-workspaces'],
  },
  {
    id: 'diagnostics',
    zh: '诊断、用量与更新',
    en: 'Diagnostics, usage and updates',
    keys: ['runtime', 'usage-stats', 'updates', 'providers'],
  },
] as const;

export function settingsGroups(available: readonly SettingsTabKey[], locale = 'zh') {
  return GROUPS.map((group) => ({
    id: group.id,
    label: locale === 'en' ? group.en : group.zh,
    keys: available.filter((key) => (group.keys as readonly string[]).includes(key)),
  })).filter((group) => group.keys.length > 0);
}

/** Stable row metadata, not an unverified coordinate or a whole-page text match. */
export function focusSettingsEntry(container: HTMLElement, entry: SettingsSearchEntry): boolean {
  const labels = [entry.label, entry.labelEn].map((label) => label.toLocaleLowerCase());
  const row = Array.from(container.querySelectorAll<HTMLElement>('[data-setting-label]')).find(
    (element) => {
      const label = element.dataset.settingLabel?.toLocaleLowerCase() ?? '';
      return labels.some((candidate) => label === candidate || label.startsWith(candidate + ' '));
    },
  );
  if (!row) return false;
  row.scrollIntoView?.({ block: 'center', behavior: 'smooth' });
  row.focus({ preventScroll: true });
  return true;
}
