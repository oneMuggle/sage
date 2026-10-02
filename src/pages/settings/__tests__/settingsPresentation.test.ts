import { describe, expect, it, vi } from 'vitest';

import { settingsGroups, focusSettingsEntry } from '../settingsPresentation';
describe('settings presentation', () => {
  it('groups known tabs without creating unsupported platform tabs', () => {
    const groups = settingsGroups(['basic', 'models', 'network', 'usage-stats'], 'en');
    expect(groups).toHaveLength(4);
    expect(groups.flatMap((group) => group.keys)).toEqual([
      'basic',
      'models',
      'network',
      'usage-stats',
    ]);
  });
  it('focuses an actual labelled row and does not pretend a missing row exists', () => {
    const container = document.createElement('div');
    const row = document.createElement('div');
    row.dataset.settingLabel = 'Theme';
    row.tabIndex = -1;
    row.scrollIntoView = vi.fn();
    container.append(row);
    document.body.append(container);
    const entry = {
      key: 'theme',
      tab: 'basic' as const,
      label: '主题',
      labelEn: 'Theme',
      keywords: '',
    };
    expect(focusSettingsEntry(container, entry)).toBe(true);
    expect(document.activeElement).toBe(row);
    expect(focusSettingsEntry(container, { ...entry, label: 'Missing', labelEn: 'Missing' })).toBe(
      false,
    );
    container.remove();
  });
});
